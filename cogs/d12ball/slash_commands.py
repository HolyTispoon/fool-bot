"""
Every slash command, the three subgroups they hang off, and the
startup sweep that files finished games away.
"""

import asyncio
import discord
import re
from typing import Optional

from discord import app_commands
from discord.ext import commands
from d12ball.components import (
    MatchPeriod,
    MatchState,
    PlayerRole,
    RuleRefusal,
    TeamSide,
    Zone,
)
from d12ball.game import (
    AIOpponent,
    D12BallGame,
    GameMode,
    GameStatus,
    team_display_name,
)
from d12ball import stats, tutorial
from d12ball.flow import gates
from d12ball.rules_doc import (
    LIVING_RULES_PATH,
    RulesDocument,
    chunk_for_discord,
    load_rules_document,
)
from gamesaves.d12ball.storage import save_games
from gamesaves.d12ball.hub import get_hub, set_hub
from cogs.d12ball_helpers import (
    BENCH_DESTINATIONS,
    HUB_ROLES,
    LOGGER,
    PBD_GAMES_CATEGORY_NAME,
    add_full_image_button,
    add_full_image_button_to_response,
    build_game_channel_name,
    build_hub_message,
    build_hub_roles_message,
    build_lobby_message,
    find_guild_role,
    hub_role_by_key,
    load_d12_emoji,
    load_d12_button_emoji,
    destination_display_name,
    filter_choices,
    format_ai_name,
    format_team_side_label,
    get_or_create_category,
    may_act_for_coach,
    may_act_in_game,
    parse_space_value,
    resolve_adjustable_value,
    space_choices,
    space_label,
)
from cogs.d12ball_views import (
    HubRolesView,
    LobbyView,
    NewGameHubView,
    TeamSelectionView,
)



# The highest the clock may be set to by hand. The clock itself has no
# ceiling -- it runs for as long as a last possession does -- so this is
# not a rule, only what two digits hold: everything that prints the
# clock does so as `{:02d}`, and `/d12ball time 100` would be the one
# state the scoreboard cannot draw.
MAX_DEBUG_CLOCK = 99


class CommandsMixin:
    """
    Every slash command, the three subgroups they hang off, and the
    startup sweep that files finished games away.
    """

    ball_group = app_commands.Group(
        name="ball",
        description="Move the ball and manage possession, speed.",
    )
    meeple_group = app_commands.Group(
        name="meeple",
        description="Move meeples on the board.",
    )

    stats_group = app_commands.Group(
        name="stats",
        description="What has actually been played -- this game, or all of them.",
    )

    # The scopes a coach may ask for, in the order they are offered.
    # `this_game` is first because it is the one with an obvious
    # answer in a game channel; the other three are the split the
    # author asked for and the only one that means anything -- see
    # `stats.game_category`.
    STATS_SCOPE_CHOICES = [
        app_commands.Choice(name="This game", value=stats.SCOPE_THIS_GAME),
        app_commands.Choice(name="Games against Dinky", value=stats.SCOPE_DINKY),
        app_commands.Choice(name="Test games", value=stats.SCOPE_TEST),
        app_commands.Choice(
            name="Games between two players", value=stats.SCOPE_HUMAN,
        ),
        app_commands.Choice(name="Every game", value=stats.SCOPE_ALL),
    ]

    def stats_matches(
        self,
        interaction: discord.Interaction,
        scope: str,
    ) -> Optional[tuple[list[tuple[D12BallGame, MatchState]], int, str]]:
        """
        Every game the scope covers in **this server**, with its match
        -- plus how many of them had nothing recorded, and a heading.

        **Scoped to the guild, always.** `self.games` is every game the
        bot knows about on every server it is in, and one server's
        players have no business reading another's. There is no option
        to widen it: a cross-server total is not a statistic anybody
        asked for and is a disclosure nobody consented to.

        A game whose match fails to load is skipped rather than
        raising. A saved game older than a rename can refuse to build
        (see the legacy-migration gotcha in docs/design/gotchas.md), and a report
        that dies on one bad record is worse than one that counts the
        other forty and says how many it could not read.
        """
        if scope == stats.SCOPE_THIS_GAME:
            game, match = self.match_for_channel(interaction.channel_id)
            if game is None:
                return None
            return [(game, match)], 0, self.stats_game_heading(game, match)

        in_scope = [
            game
            for game in stats.games_in_scope(self.games.values(), scope)
            if game.guild_id == interaction.guild_id
        ]
        pairs: list[tuple[D12BallGame, MatchState]] = []
        unreadable = 0
        for game in in_scope:
            if game.match_state is None:
                continue
            try:
                pairs.append((game, self.engine.load_match_state(game)))
            except (ValueError, KeyError) as error:
                unreadable += 1
                LOGGER.info(
                    "Leaving game %s out of the statistics: %s",
                    game.game_id,
                    error,
                )

        empty = sum(1 for _, match in pairs if not match.events) + (
            len(in_scope) - len(pairs)
        )
        heading = "\n".join(
            stats.format_scope_heading(scope, len(in_scope), empty)
        )
        return pairs, empty, heading

    def stats_game_heading(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> str:
        """The one-line "which game is this" a per-game report opens with."""
        status = {
            GameStatus.SETUP: "in setup",
            GameStatus.IN_PROGRESS: "in progress",
            GameStatus.FINISHED: (
                "abandoned" if game.abandoned else "finished"
            ),
        }[game.status]
        board = match.scoreboard
        return (
            f"**PBD{game.game_number}** -- "
            f"{team_display_name(match.home.team)} "
            f"{board.home_score}:{board.visiting_score} "
            f"{team_display_name(match.visiting.team)} "
            f"({status}, {board.period.value.replace('_', ' ')} "
            f"minute {board.time:02d})"
        )

    @staticmethod
    def stats_thread_name(heading: str) -> str:
        """A thread name off the report's first heading line, markdown
        stripped and cut to Discord's 100 characters."""
        first = re.sub(r"[*_`~#]", "", heading.splitlines()[0]).strip()
        return first[:100] or "D12 Ball stats"

    async def open_stats_thread(
        self,
        interaction: discord.Interaction,
        heading: str,
        share: bool,
    ) -> Optional[discord.Thread]:
        """
        The thread a report's tables go in, or `None` when they should
        go back to the caller as followups instead.

        **Not sharing puts the whole report in a thread of its own.**
        A report is several messages of wide code block, and a coach
        asking about maneuver usage mid-game is not asking to fill the
        channel both sides are playing in -- but the ephemeral dump
        this replaced was worse: it was gone on the next restart, and
        neither the other coach nor a scrollback could ever see it. A
        thread keeps it out of the channel's history, hands every
        coach a durable copy, and lands those sends in a rate-limit
        bucket of its own (see "Discord's rate limits"). The thread is
        started with no parent message, so the channel gets nothing
        but the thread; the caller is pointed at it ephemerally.

        `None` -- meaning "just use followups" -- covers sharing
        (straight into the channel), a command already run inside a
        thread (threads do not nest), and a thread that could not be
        opened for want of the Create Public Threads permission.
        """
        channel = interaction.channel
        if share or channel is None or isinstance(channel, discord.Thread):
            return None
        try:
            thread = await channel.create_thread(
                name=self.stats_thread_name(heading),
                type=discord.ChannelType.public_thread,
                auto_archive_duration=1440,
            )
        except discord.HTTPException as error:
            LOGGER.error(
                "Could not open a stats thread in #%s, posting to you "
                "instead: %s",
                getattr(channel, "name", interaction.channel_id),
                error,
            )
            return None
        await interaction.followup.send(
            f"Your D12 Ball stats are in {thread.mention}.", ephemeral=True,
        )
        return thread

    async def send_stats(
        self,
        interaction: discord.Interaction,
        heading: str,
        blocks: list[list[str]],
        share: bool,
    ) -> None:
        """
        Post a report: the heading as text, each table in its own code
        fence.

        **One message per table, not one per report.** Discord's 2000
        characters would hold most of these together, but a fence with
        two tables in it scrolls as one block on a phone -- and a
        report that outgrows the limit would then fail rather than
        arriving in pieces. None of these sends is a channel message
        edit, so none competes for that bucket (see "Discord's rate
        limits").
        """
        thread = await self.open_stats_thread(interaction, heading, share)
        if thread is not None:
            await thread.send(heading)
        else:
            await interaction.followup.send(heading, ephemeral=not share)
        for block in blocks:
            if not block:
                continue
            payload = "```\n" + "\n".join(block) + "\n```"
            if thread is not None:
                await thread.send(payload)
            else:
                await interaction.followup.send(payload, ephemeral=not share)

    @stats_group.command(
        name="game",
        description="What has happened in this channel's game.",
    )
    @app_commands.describe(
        share="Post it straight into the channel instead of a thread of its own.",
    )
    @app_commands.guild_only()
    async def stats_game(
        self,
        interaction: discord.Interaction,
        share: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=not share)
        found = self.stats_matches(interaction, stats.SCOPE_THIS_GAME)
        if found is None:
            await interaction.followup.send(
                "There is no D12 Ball game in this channel to report on.",
                ephemeral=True,
            )
            return

        pairs, _, heading = found
        matches = [match for _, match in pairs]
        maneuvers = stats.collect_maneuvers(matches)
        if not maneuvers.turns:
            await interaction.followup.send(
                f"{heading}\n\nNothing has been played yet -- or this "
                "game was already under way before the bot started "
                "keeping a record of what happens in it.",
                ephemeral=not share,
            )
            return

        conditions = stats.collect_conditions(matches)
        await self.send_stats(
            interaction,
            heading,
            [
                stats.format_turn_actions(maneuvers),
                stats.format_maneuver_usage(maneuvers, self.maneuver_catalog),
                stats.format_maneuver_cost(maneuvers, self.maneuver_catalog),
                stats.format_shots(stats.collect_shots(matches)),
                stats.format_conditions(conditions),
                stats.format_players(conditions, self.stats_player_name),
            ],
            share,
        )

    @stats_group.command(
        name="maneuvers",
        description="Which maneuvers get played, and which of them win.",
    )
    @app_commands.describe(
        scope="Which games to count.",
        share="Post it straight into the channel instead of a thread of its own.",
    )
    @app_commands.choices(scope=STATS_SCOPE_CHOICES)
    @app_commands.guild_only()
    async def stats_maneuvers(
        self,
        interaction: discord.Interaction,
        scope: Optional[app_commands.Choice[str]] = None,
        share: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=not share)
        await self.post_scoped_stats(
            interaction,
            scope,
            share,
            lambda maneuvers, matches, pairs: [
                stats.format_turn_actions(maneuvers),
                stats.format_maneuver_usage(maneuvers, self.maneuver_catalog),
                stats.format_maneuver_cost(maneuvers, self.maneuver_catalog),
            ],
        )

    @stats_group.command(
        name="matchups",
        description="Which maneuver has met which, and how often.",
    )
    @app_commands.describe(
        scope="Which games to count.",
        share="Post it straight into the channel instead of a thread of its own.",
    )
    @app_commands.choices(scope=STATS_SCOPE_CHOICES)
    @app_commands.guild_only()
    async def stats_matchups(
        self,
        interaction: discord.Interaction,
        scope: Optional[app_commands.Choice[str]] = None,
        share: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=not share)
        await self.post_scoped_stats(
            interaction,
            scope,
            share,
            lambda maneuvers, matches, pairs: [
                stats.format_matchups(maneuvers, self.maneuver_catalog),
            ],
        )

    @stats_group.command(
        name="overview",
        description="Games, goals and results.",
    )
    @app_commands.describe(
        scope="Which games to count.",
        share="Post it straight into the channel instead of a thread of its own.",
    )
    @app_commands.choices(scope=STATS_SCOPE_CHOICES)
    @app_commands.guild_only()
    async def stats_overview(
        self,
        interaction: discord.Interaction,
        scope: Optional[app_commands.Choice[str]] = None,
        share: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=not share)
        await self.post_scoped_stats(
            interaction,
            scope,
            share,
            lambda maneuvers, matches, pairs: [
                stats.format_overview(stats.collect_overview(pairs)),
                stats.format_shots(stats.collect_shots(matches)),
            ],
        )

    @stats_group.command(
        name="players",
        description="Goals, injuries and exhaustion by player.",
    )
    @app_commands.describe(
        scope="Which games to count.",
        share="Post it straight into the channel instead of a thread of its own.",
    )
    @app_commands.choices(scope=STATS_SCOPE_CHOICES)
    @app_commands.guild_only()
    async def stats_players(
        self,
        interaction: discord.Interaction,
        scope: Optional[app_commands.Choice[str]] = None,
        share: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=not share)

        def blocks(maneuvers, matches, pairs):
            conditions = stats.collect_conditions(matches)
            return [
                stats.format_players(
                    conditions, self.stats_player_name, limit=15,
                ),
                stats.format_roles(conditions, self.player_catalog),
                stats.format_conditions(conditions),
            ]

        await self.post_scoped_stats(interaction, scope, share, blocks)

    def stats_player_name(self, player_id: str) -> str:
        """
        A card's name for a statistics table.

        Deliberately **no team emoji and no role bracket**, unlike
        `player_label` and every other place the bot names somebody:
        these tables are read across games, and the same person can
        appear in them under either of their two rosters (see "One
        player, both sides" in docs/design/teams-and-players.md). A colour that changed
        between rows of one table would be saying something untrue
        about the player.

        `player_by_id` resolves a visiting side's suffixed card id to
        the same person, which is what makes one row rather than two.
        """
        try:
            return self.player_catalog.player_by_id(player_id).name
        except ValueError:
            return player_id

    async def post_scoped_stats(
        self,
        interaction: discord.Interaction,
        scope: Optional[app_commands.Choice[str]],
        share: bool,
        blocks,
    ) -> None:
        """
        The body every scoped stats command shares: resolve the scope,
        fold the matches, and post whichever tables the command asked
        for.

        `blocks` is handed the folded maneuver report, the matches and
        the game/match pairs, because the five commands need different
        subsets of the three and folding them all for every command
        would walk every saved game four times over for tables nobody
        asked for.
        """
        chosen = scope.value if scope is not None else stats.SCOPE_ALL
        found = self.stats_matches(interaction, chosen)
        if found is None:
            await interaction.followup.send(
                "There is no D12 Ball game in this channel to report on.",
                ephemeral=True,
            )
            return

        pairs, _, heading = found
        matches = [match for _, match in pairs]
        maneuvers = stats.collect_maneuvers(matches)
        if not pairs:
            await interaction.followup.send(
                f"{heading}\n\nThere is nothing to report yet.",
                ephemeral=not share,
            )
            return

        await self.send_stats(
            interaction, heading, blocks(maneuvers, matches, pairs), share,
        )



    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # Games whose channel Discord says does not exist. Collected and
        # dropped after the sweep rather than during it, so the save
        # happens once and the dict is not mutated while it is walked.
        deleted_channels: list[str] = []

        for game in self.games.values():
            if game.status != GameStatus.FINISHED:
                continue

            if game.channel_id is None:
                # A game that was never played on Discord -- the web
                # frontend's -- has no channel to file away.
                continue

            # A saved game can outlive the thing it points at: channels
            # get deleted by hand, and the bot gets removed from
            # servers. Neither is anyone's to fix, and both would
            # otherwise repeat their error on every reconnect, so they
            # stay on the console.
            if self.bot.get_guild(game.guild_id) is None:
                # Kept, not dropped. An unavailable guild is also how a
                # Discord outage looks from here, and the games would be
                # gone for good.
                LOGGER.info(
                    "Not archiving finished D12 Ball game %s: the bot is "
                    "not in its server any more.",
                    game.game_id,
                )
                continue

            try:
                channel = await self.fetch_game_channel(game)
            except discord.NotFound:
                LOGGER.info(
                    "Dropping finished D12 Ball game %s: its channel no "
                    "longer exists.",
                    game.game_id,
                )
                deleted_channels.append(game.game_id)
                continue
            except (ValueError, discord.HTTPException) as error:
                LOGGER.error(
                    "Could not archive finished D12 Ball game %s: %s",
                    game.game_id,
                    error,
                )
                continue

            try:
                await self.move_channel_to_archive(channel)
            except (ValueError, discord.Forbidden, discord.HTTPException) as error:
                # An error rather than a warning: a finished game whose
                # channel stays in the games category is a permission
                # problem that needs someone to fix it, and nothing else
                # reports it.
                LOGGER.error(
                    "Could not archive finished D12 Ball game %s: %s",
                    game.game_id,
                    error,
                )

        if deleted_channels:
            for game_id in deleted_channels:
                del self.games[game_id]
            save_games(self.games)

    def create_game_refusal(
        self,
        interaction: discord.Interaction,
        p1: Optional[discord.Member],
        p2: Optional[discord.Member],
        test_game: bool,
        tutorial: bool,
    ) -> Optional[str]:
        """
        Why this /d12ball create_game cannot be run at all, or None.

        Asked before the two coaches are worked out, since none of
        these depend on who they turn out to be.
        """
        if interaction.guild is None:
            return "This command can only be used inside a server."

        if not isinstance(interaction.user, discord.Member):
            return "I could not identify the person creating the game."

        if test_game and (p1 is not None or p2 is not None):
            return (
                "A test game cannot specify p1 or p2; you control both sides."
            )

        # The tutorial is a scripted warm-up against Dinky and nothing
        # else -- see d12ball/tutorial.py. Its five beats set a position
        # a side at a time and rail one coach onto one card, neither of
        # which means anything with a second human in the game or with
        # one person holding both sides' menus. Refused rather than
        # quietly ignored: a coach who asked for a tutorial and got an
        # ordinary game would have no way to tell.
        if tutorial and (p1 is not None or p2 is not None or test_game):
            return (
                "A tutorial game is played against Dinky on your own, so "
                "it cannot take p1, p2 or test_game."
            )

        return None

    def resolve_game_players(
        self,
        interaction: discord.Interaction,
        p1: Optional[discord.Member],
        p2: Optional[discord.Member],
        test_game: bool,
    ) -> tuple[Optional[discord.Member], Optional[discord.Member]]:
        """
        Which members are Player 1 and Player 2.

        Naming nobody means a solo game against Dinky; naming one
        person means them against whoever ran the command; naming two
        sets up a game between other people. A test game is one person
        on both sides.
        """
        if test_game:
            return interaction.user, interaction.user

        if p1 is not None and p2 is not None:
            return p1, p2

        # One named opponent, or none at all -- either way the caller
        # takes Player 1 and whoever they named (if anyone) takes 2.
        return interaction.user, p1 if p1 is not None else p2

    def player_pair_refusal(
        self,
        player_1: Optional[discord.Member],
        player_2: Optional[discord.Member],
        test_game: bool,
    ) -> Optional[str]:
        """
        Why this pair of coaches cannot play each other, or None.
        A test game is exempt from the last of them, being one person
        deliberately holding both sides.
        """
        if player_1 is None:
            return "Player 1 could not be identified."

        if player_1.bot:
            return "Player 1 cannot be a bot."

        if player_2 is not None and player_2.bot:
            return "Player 2 cannot be a bot."

        if (
            not test_game
            and player_2 is not None
            and player_1.id == player_2.id
        ):
            return "Player 1 and Player 2 must be different people."

        return None

    @app_commands.command(
        name="create_game",
        description="Create a new D12 Ball game.",
    )
    @app_commands.describe(
        p1="Player 1. Leave blank to make yourself Player 1.",
        p2="Player 2. Leave blank to play against the AI.",
        game_name=(
            "A fun name for this game, used in the channel name. Leave "
            "blank to name it after the players."
        ),
        test_game=(
            "Create a test game where you control Player 1 and Player 2."
        ),
        tutorial=(
            "Play a guided warm-up against Dinky before the real game "
            "starts. Best for a first game."
        ),
    )
    @app_commands.guild_only()
    async def create_game(
        self,
        interaction: discord.Interaction,
        p1: Optional[discord.Member] = None,
        p2: Optional[discord.Member] = None,
        game_name: Optional[app_commands.Range[str, 1, 80]] = None,
        test_game: bool = False,
        tutorial: bool = False,
    ) -> None:
        refusal = self.create_game_refusal(
            interaction, p1, p2, test_game, tutorial,
        )
        if refusal is not None:
            await interaction.response.send_message(refusal, ephemeral=True)
            return

        player_1, player_2 = self.resolve_game_players(
            interaction, p1, p2, test_game,
        )

        refusal = self.player_pair_refusal(player_1, player_2, test_game)
        if refusal is not None:
            await interaction.response.send_message(refusal, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            game = await self.open_new_game(
                interaction.guild,
                player_1,
                player_2,
                test_game=test_game,
                created_by=interaction.user,
                game_name=game_name,
                tutorial=tutorial,
            )
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        await interaction.followup.send(
            f"Game created: <#{game.channel_id}>",
            ephemeral=True,
        )

    def game_channel_overwrites(
        self,
        guild: discord.Guild,
        player_1: discord.Member,
        player_2: Optional[discord.Member],
        bot_member: discord.Member,
    ) -> dict:
        """
        Who can see a game's channel: its coaches and the bot, and
        nobody else. The bot also needs Manage Channels, since
        archiving a finished game moves the channel between categories.
        """
        def player_access() -> discord.PermissionOverwrite:
            # A fresh object per coach rather than one shared between
            # them: an overwrite is handed to discord.py, and two
            # entries in this dict should not be able to become the
            # same object by accident.
            return discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
            ),
            player_1: player_access(),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
            ),
        }

        if player_2 is not None:
            overwrites[player_2] = player_access()

        return overwrites

    def lobby_channel_overwrites(
        self,
        guild: discord.Guild,
        bot_member: discord.Member,
    ) -> dict:
        """
        A lobby channel is open to the whole server -- `@everyone` can
        see it and talk in it -- so anyone can look in and decide to
        join or observe. `lobby_start` swaps this for
        `game_channel_overwrites` plus the observers once the game
        begins.
        """
        return {
            guild.default_role: discord.PermissionOverwrite(
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

    def game_channel_lockdown_overwrites(
        self,
        game: D12BallGame,
        guild: discord.Guild,
        bot_member: discord.Member,
    ) -> dict:
        """
        The overwrites `lobby_start` writes over the open lobby ones:
        `@everyone` loses sight of the channel, the two players get full
        access, and everyone who asked to observe gets read-only access.

        Targets are `discord.Object`s rather than resolved members --
        `TextChannel.edit(overwrites=...)` accepts them, and an
        observer may not be in the member cache.
        """
        overwrites: dict = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
            ),
        }

        player_ids = {game.player_1_id}
        if game.player_2_id is not None:
            player_ids.add(game.player_2_id)

        for player_id in player_ids:
            overwrites[discord.Object(id=player_id, type=discord.Member)] = (
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )
            )

        for observer_id in game.observer_ids:
            if observer_id in player_ids:
                continue
            overwrites[discord.Object(id=observer_id, type=discord.Member)] = (
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=False,
                    read_message_history=True,
                )
            )

        return overwrites

    async def create_private_game_channel(
        self,
        guild: discord.Guild,
        channel_name: str,
        overwrites: dict,
        bot_member: discord.Member,
        created_by: Optional[discord.abc.User],
    ) -> discord.TextChannel:
        """
        Make the channel a game is played in, under the PBD Games
        category, and confirm the bot came out of it able to manage
        what it just created.

        Every failure is a ValueError carrying the text to show whoever
        asked for the game -- see open_new_game.
        """
        try:
            category = await get_or_create_category(
                guild,
                PBD_GAMES_CATEGORY_NAME,
                "Create the category for active PBD games.",
            )
            game_channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                category=category,
                reason=(
                    f"D12 Ball game created by {created_by}"
                    if created_by is not None
                    else "D12 Ball game created."
                ),
            )

        except discord.Forbidden:
            raise ValueError(
                "I do not have permission to create the PBD Games category "
                "or its game channels."
            )

        except discord.HTTPException as error:
            raise ValueError(
                f"Discord could not create the channel: {error}"
            )

        try:
            await game_channel.set_permissions(
                bot_member,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                reason="Ensure the bot can manage its private game channel.",
            )
        except (discord.Forbidden, discord.HTTPException) as error:
            bot_permissions = game_channel.permissions_for(bot_member)

            if (
                not bot_permissions.view_channel
                or not bot_permissions.manage_channels
            ):
                raise ValueError(
                    "The private channel was created, but I could not add "
                    f"myself with permission to manage it: {error}"
                )

        bot_permissions = game_channel.permissions_for(bot_member)
        if (
            not bot_permissions.view_channel
            or not bot_permissions.manage_channels
        ):
            raise ValueError(
                "The private channel was created, but Discord did not grant "
                "me View Channel and Manage Channels permissions."
            )

        return game_channel

    async def post_game_setup_message(
        self,
        game_channel: discord.TextChannel,
        game: D12BallGame,
    ) -> int:
        """
        The first message in a game's channel: the team picker, and the
        line above it that the channel keeps for the rest of the game.

        This message is **not** the one the board ends up on -- the
        coin flip re-points `game.message_id` at the home/visiting
        choice it posts, which is what every later board is written to.
        See "Discord's rate limits" in docs/design/rate-limits.md.
        """
        view = TeamSelectionView(
            cog=self,
            game_id=game.game_id,
        )

        message_text = (
            "Start playing in this channel.\n\n"
            f"{view.build_team_message(game)}"
        )

        try:
            game_message = await game_channel.send(
                message_text,
                view=view,
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )

        except discord.HTTPException as error:
            raise ValueError(
                f"The channel was created, but I could not send "
                f"the game message: {error}"
            )

        return game_message.id

    async def open_new_game(
        self,
        guild: discord.Guild,
        player_1: discord.Member,
        player_2: Optional[discord.Member],
        test_game: bool = False,
        created_by: Optional[discord.abc.User] = None,
        mode: GameMode = GameMode.BASIC,
        board_size: int = 7,
        ai_opponent: Optional[AIOpponent] = None,
        game_name: Optional[str] = None,
        tutorial: bool = False,
    ) -> D12BallGame:
        """
        Create the private channel for a game, save the game record,
        and post its setup message. Shared by /d12ball create_game and
        the full-time rematch button, which is why everything that can
        go wrong is raised as a ValueError carrying the text to show
        the person who asked for the game rather than replying itself.

        The settings arguments exist for the rematch, which carries the
        finished game's configuration over; a fresh game takes the
        defaults and settles them in setup.
        """
        game_number = self.service.next_game_number(guild.id)
        resolved_ai_opponent = (
            None if player_2 else ai_opponent or AIOpponent.DINKY
        )
        player_1_name = "Player 1" if test_game else player_1.display_name
        player_2_name = (
            "Player 2"
            if test_game
            else player_2.display_name if player_2 else None
        )
        channel_name = build_game_channel_name(
            game_number,
            player_1_name,
            player_2_name or format_ai_name(resolved_ai_opponent),
            # A tutorial names its own channel unless the coach named
            # it, so the one game in the category whose opening is
            # scripted says so from the channel list. It goes through
            # `game_name` rather than being appended to the pattern,
            # because the number's position in the name is what
            # CHANNEL_NAME_PATTERN reads back -- see "Game channels".
            game_name=game_name or ("tutorial" if tutorial else None),
        )

        bot_member = guild.me

        if bot_member is None:
            raise ValueError("I could not find my server account.")

        game_channel = await self.create_private_game_channel(
            guild,
            channel_name,
            self.game_channel_overwrites(
                guild, player_1, player_2, bot_member,
            ),
            bot_member,
            created_by,
        )

        # The record is the service's to make (step 8 of
        # docs/architecture-migration.md); what the channel is called
        # and where it is are this frontend's, passed in.
        game = self.service.create_game(
            guild_id=guild.id,
            channel_id=game_channel.id,
            game_number=game_number,
            player_1_id=player_1.id,
            player_2_id=player_2.id if player_2 else None,
            player_1_name=player_1_name,
            player_2_name=player_2_name,
            test_game=test_game,
            game_name=game_name,
            mode=mode,
            board_size=board_size,
            ai_opponent=resolved_ai_opponent,
            tutorial=tutorial,
        )

        try:
            game.message_id = await self.post_game_setup_message(
                game_channel, game,
            )
        except ValueError:
            # The record was only ever made so the view could build
            # its message off it; with nothing posted there is no game.
            self.service.discard_game(game.game_id)
            raise

        self.service.save()
        return game

    # -- The game-creation hub and the lobby --------------------------
    #
    # The friendly front door: a locked channel with one button that
    # opens a private lobby, where players join and pick settings before
    # anyone commits to a game. `/d12ball create_game` stays for test,
    # tutorial and explicitly-paired games. See "The game-creation hub
    # and the lobby" in docs/design/hub-and-lobby.md.

    @app_commands.command(
        name="setup_hub",
        description=(
            "Post (or repair) the 'want to play?' and roles messages in "
            "this channel and lock it."
        ),
    )
    @app_commands.guild_only()
    async def setup_hub(self, interaction: discord.Interaction) -> None:
        """
        Register the current channel as this server's game-creation
        hub: lock it so only the bot can post, then send or edit its two
        messages -- the games message carrying the D12 Ball button, and
        the roles message carrying a toggle button per `HUB_ROLES`
        entry.

        Re-runnable -- run it again to move the hub to another channel
        or to put either message back if it was deleted. The roles
        themselves are not created here: the reply names any the server
        is missing, and the button for one answers with the same until
        somebody makes it.
        """
        permissions = getattr(interaction.user, "guild_permissions", None)
        if permissions is None or not permissions.manage_channels:
            await interaction.response.send_message(
                "Only someone who can manage channels can set up the hub.",
                ephemeral=True,
            )
            return

        channel = interaction.channel
        guild = interaction.guild
        if not isinstance(channel, discord.TextChannel) or guild is None:
            await interaction.response.send_message(
                "Run this in a normal text channel.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await channel.set_permissions(
                guild.default_role,
                send_messages=False,
                reason="Lock the D12 Ball game-creation hub channel.",
            )
            if guild.me is not None:
                await channel.set_permissions(
                    guild.me,
                    view_channel=True,
                    send_messages=True,
                    reason="Keep the bot able to post in the hub channel.",
                )
        except discord.HTTPException as error:
            await interaction.followup.send(
                f"I could not lock this channel: {error}",
                ephemeral=True,
            )
            return

        # Re-fetch both d12 emoji here so an upload through the Developer
        # Portal takes effect on the next `setup_hub` without a restart.
        self.d12_emoji = await load_d12_emoji(self.bot)
        self.d12_button_emoji = await load_d12_button_emoji(self.bot)
        hub_message = build_hub_message(self.d12_emoji)

        existing = get_hub(guild.id)
        if existing is None or existing["channel_id"] != channel.id:
            existing = {}

        # The games message first, then the roles message under it. Each
        # is edited in place when the recorded one is still there and
        # sent afresh otherwise, so a deleted roles message comes back
        # under a games message that is left alone.
        try:
            message = await self.post_or_edit_hub_message(
                channel,
                existing.get("message_id"),
                hub_message,
                NewGameHubView(self),
            )
        except discord.HTTPException as error:
            await interaction.followup.send(
                f"I could not post the hub message: {error}",
                ephemeral=True,
            )
            return

        try:
            roles_message = await self.post_or_edit_hub_message(
                channel,
                existing.get("roles_message_id"),
                build_hub_roles_message(),
                HubRolesView(self),
            )
        except discord.HTTPException as error:
            # The games message landed, so record it: a hub with a live
            # D12 Ball button and no roles message is the pre-roles hub,
            # which is better than one nothing is re-armed against.
            self.hubs[guild.id] = set_hub(guild.id, channel.id, message.id)
            await interaction.followup.send(
                f"I could not post the roles message: {error}",
                ephemeral=True,
            )
            return

        self.hubs[guild.id] = set_hub(
            guild.id, channel.id, message.id, roles_message.id,
        )

        missing_roles = [
            hub_role.role_name for hub_role in HUB_ROLES
            if find_guild_role(guild, hub_role) is None
        ]
        report = (
            "This channel is now the D12 Ball game-creation hub. It is "
            "locked, and its two messages are live."
        )
        if missing_roles:
            report += (
                "\n\nThe server has no role named "
                + ", ".join(f"**{name}**" for name in missing_roles)
                + " -- that button will say so until somebody creates "
                "the role. Its name is what I look it up by."
            )
        await interaction.followup.send(report, ephemeral=True)

    async def post_or_edit_hub_message(
        self,
        channel: discord.TextChannel,
        message_id: Optional[int],
        content: str,
        view: discord.ui.View,
    ) -> discord.Message:
        """
        Edit the hub message `message_id` names into `content` and
        `view`, or send a fresh one when there is no id or the message
        it names is gone. Raises `discord.HTTPException` from the send
        or edit; a failed *fetch* is just "send a new one".
        """
        if message_id is not None:
            try:
                message = await channel.fetch_message(message_id)
            except discord.HTTPException:
                message = None
            if message is not None:
                await message.edit(content=content, view=view)
                return message
        return await channel.send(content, view=view)

    async def toggle_hub_role(
        self, interaction: discord.Interaction, key: str,
    ) -> None:
        """
        A click on the roles message: give the member the role the
        button names, or take it off them if they already have it, and
        say which ephemerally. Nothing here touches a game or a save.
        """
        hub_role = hub_role_by_key(key)
        if hub_role is None:
            # A button from a table entry that has since been removed.
            await interaction.response.send_message(
                "That role is no longer on offer.", ephemeral=True,
            )
            return

        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "This button only works inside the server.", ephemeral=True,
            )
            return

        role = find_guild_role(guild, hub_role)
        if role is None:
            await interaction.response.send_message(
                f"This server has no role named **{hub_role.role_name}** "
                "yet -- ask an admin to create it.",
                ephemeral=True,
            )
            return

        try:
            if member.get_role(role.id) is not None:
                await member.remove_roles(
                    role, reason="Removed via the D12 Ball hub.",
                )
                reply = f"Took **{role.name}** off you."
            else:
                await member.add_roles(
                    role, reason="Added via the D12 Ball hub.",
                )
                reply = f"You now have **{role.name}**."
        except discord.Forbidden:
            # Manage Roles missing, or the role sits above the bot's own.
            reply = (
                f"I'm not allowed to give out **{role.name}**. It needs "
                "to sit below my own role, and I need Manage Roles."
            )
        except discord.HTTPException as error:
            reply = f"Discord refused to change your roles: {error}"

        await interaction.response.send_message(reply, ephemeral=True)

    async def open_lobby(self, interaction: discord.Interaction) -> None:
        """
        Make a private lobby channel for whoever clicked the hub button
        and post its LobbyView. The channel is reused as the game
        channel once Start Game is pressed -- see `lobby_start`.
        """
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This only works inside a server.",
                ephemeral=True,
            )
            return

        bot_member = guild.me
        if bot_member is None:
            await interaction.response.send_message(
                "I could not find my server account.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        creator = interaction.user
        game_number = self.service.next_game_number(guild.id)

        try:
            channel = await self.create_private_game_channel(
                guild,
                f"d12ball-pbd{game_number}-lobby",
                # A lobby is visible to the whole server -- anyone can
                # look in and decide to join or observe. `lobby_start`
                # locks it down to the two players (plus observers) once
                # the game begins.
                self.lobby_channel_overwrites(guild, bot_member),
                bot_member,
                creator,
            )
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        game = self.service.create_game(
            guild_id=guild.id,
            channel_id=channel.id,
            game_number=game_number,
            player_1_id=creator.id,
            player_1_name=creator.display_name,
            in_lobby=True,
        )

        try:
            message = await channel.send(
                build_lobby_message(game, self.d12_emoji),
                view=LobbyView(self, game.game_id),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as error:
            self.service.discard_game(game.game_id)
            await interaction.followup.send(
                f"The lobby channel was created, but I could not post its "
                f"message: {error}",
                ephemeral=True,
            )
            return

        game.message_id = message.id
        self.service.save()

        await interaction.followup.send(
            f"Your lobby is ready: <#{channel.id}>",
            ephemeral=True,
        )

    async def _refresh_lobby(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        # The record has already been changed and saved by the service
        # by the time this redraws the message, as it is for every
        # click past the lobby (docs/design/game-service.md).
        await interaction.response.edit_message(
            content=build_lobby_message(game, self.d12_emoji),
            view=LobbyView(self, game.game_id),
            # The message lists players and observers by mention; an
            # edit that adds one must not ping them.
            allowed_mentions=discord.AllowedMentions.none(),
        )

    # Join, Observe and Leave are about the clicker themselves, which
    # is why none of the three is gated: the record refuses whoever
    # may not do what they asked (`D12BallGame.lobby_join` and its
    # neighbours), and the sentence it refuses with is the reply.

    async def lobby_join(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        user = interaction.user
        try:
            self.service.lobby_join(
                game.game_id, user.id, getattr(user, "display_name", None),
            )
        except RuleRefusal as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await self._refresh_lobby(interaction, game)

    async def lobby_observe(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        try:
            self.service.lobby_observe(game.game_id, interaction.user.id)
        except RuleRefusal as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await self._refresh_lobby(interaction, game)

    async def lobby_leave(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        try:
            self.service.lobby_leave(game.game_id, interaction.user.id)
        except RuleRefusal as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await self._refresh_lobby(interaction, game)

    async def lobby_start(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        if not may_act_in_game(interaction.user, game):
            await interaction.response.send_message(
                "Only a player in this lobby can start the game.",
                ephemeral=True,
            )
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "I could not find the lobby channel.", ephemeral=True,
            )
            return

        # Who takes the other side is the record's to settle
        # (`D12BallGame.start_lobby`); the service saves it before the
        # team picker is put up, since the picker is built off it.
        try:
            self.service.start_lobby(game.game_id)
        except RuleRefusal as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        try:
            new_message_id = await self.post_game_setup_message(channel, game)
        except ValueError as error:
            # Nothing to pick teams on: the lobby's own message is what
            # the channel still shows, so the record goes back to being
            # the lobby it was.
            self.service.reopen_lobby(game.game_id)
            await interaction.response.send_message(
                f"I could not start the game: {error}", ephemeral=True,
            )
            return

        # Lock the channel down now that it is a real game -- until now
        # it was open to the whole server. The two players get full
        # access; anyone who pressed Observe keeps read-only access. Done
        # in the same `channel.edit` as the rename (the one deliberate
        # channel rename in the codebase -- see "Game channels"), so it
        # is one request, best-effort: a failure leaves an open channel,
        # not a broken game.
        bot_member = channel.guild.me
        if game.game_name:
            # A name the players gave the game -- the same thing
            # `/d12ball create_game game_name:` does.
            channel_name = build_game_channel_name(
                game.game_number, "", "", game_name=game.game_name,
            )
        elif game.test_game:
            channel_name = build_game_channel_name(
                game.game_number, "", "",
                game_name=f"{game.player_1_name or 'player'} test game",
            )
        elif game.tutorial:
            channel_name = build_game_channel_name(
                game.game_number, "", "",
                game_name=f"{game.player_1_name or 'player'} tutorial",
            )
        else:
            player_2_label = (
                game.player_2_name
                if game.player_2_id is not None
                else format_ai_name(game.ai_opponent)
            )
            channel_name = build_game_channel_name(
                game.game_number,
                game.player_1_name or "player-1",
                player_2_label or "player-2",
            )
        try:
            edit_kwargs = dict(
                name=channel_name,
                reason="D12 Ball: lobby started, becoming the game channel.",
            )
            if bot_member is not None:
                edit_kwargs["overwrites"] = self.game_channel_lockdown_overwrites(
                    game, channel.guild, bot_member,
                )
            await channel.edit(**edit_kwargs)
        except discord.HTTPException as error:
            LOGGER.warning(
                "Could not rename/lock lobby channel for game %s: %s",
                game.game_id, error,
            )

        try:
            await interaction.response.edit_message(
                content=(
                    "**Game starting** -- pick your teams in the message "
                    "below."
                ),
                view=None,
            )
        except discord.HTTPException:
            pass

        game.message_id = new_message_id
        self.service.save()

    async def start_rematch(
        self,
        game: D12BallGame,
        requested_by: Optional[discord.abc.User] = None,
    ) -> D12BallGame:
        """
        Open a rematch of a finished game -- the same two players (or
        the same AI opponent) and the same settings, in a new channel
        -- and archive the finished game's own channel on the way out.

        The new game id is remembered on the finished game so a second
        click on its rematch button finds the rematch instead of
        opening another one.
        """
        guild = self.bot.get_guild(game.guild_id)
        if guild is None:
            raise ValueError("The server for this game is not available.")

        try:
            player_1 = guild.get_member(
                game.player_1_id
            ) or await guild.fetch_member(game.player_1_id)
        except discord.HTTPException:
            raise ValueError(
                "Player 1 is no longer a member of this server."
            )

        player_2 = player_1 if game.test_game else None
        if game.player_2_id is not None and not game.test_game:
            try:
                player_2 = guild.get_member(
                    game.player_2_id
                ) or await guild.fetch_member(game.player_2_id)
            except discord.HTTPException:
                raise ValueError(
                    "Player 2 is no longer a member of this server."
                )

        rematch = await self.open_new_game(
            guild,
            player_1,
            player_2,
            test_game=game.test_game,
            created_by=requested_by,
            mode=game.mode,
            board_size=game.board_size,
            ai_opponent=game.ai_opponent,
            game_name=game.game_name,
        )

        game.rematch_game_id = rematch.game_id
        save_games(self.games)

        # Last, so a rematch is never lost to a channel the bot turns
        # out not to be allowed to move.
        await self.archive_game_channel(game)
        return rematch

    @app_commands.command(
        name="show_game",
        description="Post a fresh snapshot of the full board.",
    )
    @app_commands.guild_only()
    async def show_game(
        self,
        interaction: discord.Interaction,
    ) -> None:
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "There is no D12 Ball match in progress in this channel.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        snapshot = await interaction.followup.send(
            file=await self.build_match_file(game),
            wait=True,
        )
        await add_full_image_button(snapshot)

    @app_commands.command(
        name="team_roster",
        description=(
            "List a team's players, positions, exhaustion, and conditions."
        ),
    )
    @app_commands.describe(
        all_teams="Show both teams' rosters instead of just your own.",
        abilities="Include each player's role ability.",
    )
    @app_commands.guild_only()
    async def team_roster(
        self,
        interaction: discord.Interaction,
        all_teams: bool = False,
        abilities: bool = False,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        setups = self.engine.roster_setups_for_user(
            game, match, interaction.user.id, all_teams=all_teams,
        )
        if setups is None:
            await interaction.followup.send(
                "You are not one of the players in this game. Use "
                "all_teams:true to see both rosters.",
                ephemeral=True,
            )
            return

        for setup in setups:
            await interaction.followup.send(
                self.build_team_roster_section(
                    game, match, setup, show_abilities=abilities,
                )
            )

    @app_commands.command(
        name="maneuver_reference",
        description="Post the maneuver reference image showing the defeat cycle.",
    )
    @app_commands.guild_only()
    async def maneuver_reference(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.send_message(
            file=self.build_maneuver_reference_file(
                self.reference_tier(
                    self.game_for_channel(interaction.channel_id)
                )
            ),
        )
        await add_full_image_button_to_response(interaction)

    @app_commands.command(
        name="role_abilities",
        description="List each role's ability.",
    )
    @app_commands.guild_only()
    async def role_abilities(
        self,
        interaction: discord.Interaction,
    ) -> None:
        lines = [
            f"**{role.value.title()}** — "
            f"{self.player_catalog.role_profiles[role].ability}"
            for role in PlayerRole
        ]
        await interaction.response.send_message("\n".join(lines))

    async def load_rules(
        self,
        interaction: discord.Interaction,
    ) -> Optional[RulesDocument]:
        """The living rules, or None once the coach has been told why not.

        The document ships with the checkout, so a deployment without it
        is a broken deployment and worth an ERROR -- see "Logging and the
        #logs channel" in docs/design/logging.md. Both commands ask before they answer
        the interaction, so the refusal is the response itself.
        """
        try:
            return await asyncio.to_thread(load_rules_document)
        except OSError as error:
            LOGGER.error(
                "Could not read the living rules at %s: %s",
                LIVING_RULES_PATH,
                error,
            )
            await interaction.response.send_message(
                "The rules document is missing from this bot's checkout, "
                "so there is nothing to post.",
                ephemeral=True,
            )
            return None

    @app_commands.command(
        name="rules_full",
        description="Post the complete rules of D12 Ball in a thread.",
    )
    @app_commands.guild_only()
    async def rules_full(
        self,
        interaction: discord.Interaction,
    ) -> None:
        document = await self.load_rules(interaction)
        if document is None:
            return

        chunks = chunk_for_discord(document.text)
        channel = interaction.channel

        # The whole ruleset is around forty messages, so it goes in a
        # thread: it stays out of the channel's history, and a thread
        # has its own id, so those sends are a rate-limit bucket of
        # their own rather than the game channel's -- see "Discord's
        # rate limits" in docs/design/rate-limits.md. A command run inside a thread
        # already has one, and threads do not nest.
        if isinstance(channel, discord.Thread):
            await interaction.response.send_message(
                f"Posting the full rules ({len(chunks)} messages)."
            )
            destination: discord.abc.Messageable = channel
        else:
            await interaction.response.send_message(
                f"**{document.title}** -- the full rules, in the thread "
                "below."
            )
            anchor = await interaction.original_response()
            try:
                destination = await anchor.create_thread(
                    name="D12 Ball rules",
                    auto_archive_duration=1440,
                )
            except discord.HTTPException as error:
                LOGGER.error(
                    "Could not open a rules thread in #%s: %s",
                    getattr(channel, "name", interaction.channel_id),
                    error,
                )
                await interaction.followup.send(
                    "I could not open a thread here. Give me the "
                    "Create Public Threads permission, or run this in a "
                    "channel where I have it.",
                    ephemeral=True,
                )
                return

        for chunk in chunks:
            await destination.send(chunk)

    @app_commands.command(
        name="rules_search",
        description="Post one section of the D12 Ball rules.",
    )
    @app_commands.describe(
        section="Which part of the rules to post.",
    )
    @app_commands.guild_only()
    async def rules_search(
        self,
        interaction: discord.Interaction,
        section: str,
    ) -> None:
        document = await self.load_rules(interaction)
        if document is None:
            return

        # Discord lets a coach submit what they typed instead of a
        # choice, so words that were never offered still have to be
        # answered -- with the section when they can only mean one, and
        # with the headings that mention them otherwise.
        found = document.best_match(section)
        if found is None:
            matches = document.search(section, limit=5)
            suggestions = "\n".join(f"- {match.label}" for match in matches)
            await interaction.response.send_message(
                f"No one rules section matches “{section}”."
                + (f"\n\nDid you mean:\n{suggestions}" if matches else ""),
                ephemeral=True,
            )
            return

        # The section is the answer, so the first chunk is the response
        # itself rather than a deferral followed by one.
        first, *rest = chunk_for_discord(found.text)
        await interaction.response.send_message(first)
        for chunk in rest:
            await interaction.followup.send(chunk)

    @rules_search.autocomplete("section")
    async def rules_search_section_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        try:
            document = await asyncio.to_thread(load_rules_document)
        except OSError:
            return []
        return [
            app_commands.Choice(name=match.label[:100], value=match.slug)
            for match in document.search(current)
        ]

    @app_commands.command(
        name="offensive_choice",
        description=(
            "(Re-)post the ball-handler and shoot/maneuver choice for "
            "the team in possession."
        ),
    )
    @app_commands.guild_only()
    async def offensive_choice(
        self,
        interaction: discord.Interaction,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        # A turn that is merely waiting -- on a challenge, a shot, an
        # owed roll -- wants its prompt back, not throwing away; what it
        # waits on is the model's to name (`RulesEngine.turn_in_progress`).
        # A turn that is genuinely wedged wants `resume force:true`.
        waiting = self.engine.turn_in_progress(match)
        if waiting is not None:
            await interaction.followup.send(
                f"This turn is still waiting on {waiting}. Use "
                "`/d12ball resume` to put its prompt back up, or "
                "`/d12ball resume force:true` to abandon the turn and "
                "start the offensive choice over.",
                ephemeral=True,
            )
            return

        # Otherwise start the turn fresh: `GameService.reset_turn`
        # clears the stale choice, re-derives the ball handler from the
        # board and asks the offense again -- refused where the
        # position is not a turn at all (setup, halftime, the shootout,
        # a time out), which a plain resume walks on instead.
        try:
            result = self.rendered(game, self.service.reset_turn(game.game_id))
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        if result.refused:
            await interaction.followup.send(
                f"{result.refusal} Use `/d12ball resume` to put its "
                "prompt back up.",
                ephemeral=True,
            )
            return
        await self.present(interaction, game, result)

    def may_administer_game(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> bool:
        """
        Whether this person may run a recovery command on this game:
        either of its two players, or a game helper.

        This is `may_act_in_game` under the name the recovery commands
        already called it, kept because that is what they read as. It
        was the first gate in the codebase to let somebody act on a game
        they are not in, and the rest of the flow now answers the same
        question the same way -- see "Who may act on a game" in
        docs/design/permissions.md. **Don't re-inline the permission check here**: two
        readings of one rule is how the lobby came to refuse a helper a
        setting while letting them abandon the game outright.
        """
        return may_act_in_game(interaction.user, game)

    @app_commands.command(
        name="skip_tutorial",
        description="End the guided warm-up and play the rest for real.",
    )
    @app_commands.guild_only()
    async def skip_tutorial(self, interaction: discord.Interaction) -> None:
        """
        Turn the rails off where they stand.

        Clearing `tutorial_step` is the whole of it: every rail asks
        `game.in_tutorial` and every one of them answers "no rail" once
        it is None, so nothing has to be undone. The board, the clock
        and the score are left exactly as the warm-up left them --
        skipping is leaving a lesson, not rewinding the game, and the
        position a beat set is a legal one either way.

        Gated on `may_act_for_coach`: the coach being taught, or a game
        helper. It used to be the coach alone, on the reasoning that a
        tutorial is one human against Dinky and nobody else's business
        -- which is right about who it *matters* to and wrong about who
        is standing next to them. The person who turned the tutorial on
        in the lobby for a new player is the one they will ask to turn
        it off again.
        """
        game = self.game_for_channel(interaction.channel_id)

        if game is None:
            await interaction.response.send_message(
                "This channel does not have a D12 Ball game in it.",
                ephemeral=True,
            )
            return

        if not may_act_for_coach(interaction.user, game.player_1_id):
            await interaction.response.send_message(
                "Only the coach being taught can end the tutorial.",
                ephemeral=True,
            )
            return

        if not game.in_tutorial:
            await interaction.response.send_message(
                "This game is not in the tutorial."
                if not game.tutorial
                else "The tutorial has already finished.",
                ephemeral=True,
            )
            return

        game.tutorial_step = None
        game.tutorial_staged = False
        # A coach who opted out is not taught the Coaching Choice
        # either, whenever the game next offers them one.
        game.tutorial_coaching_explained = True
        save_games(self.games)

        await interaction.response.send_message(tutorial.SKIPPED)

        # A note held behind Continue is a click the game is waiting
        # on, and the coach has just said they are not reading it:
        # what it was holding up runs now, as the click would have run
        # it (`d12ball.flow.gates.continue_step`).
        if game.tutorial_gate and game.match_state is not None:
            match = self.engine.load_match_state(game)
            await self.dispatch_step_result(
                interaction,
                game,
                match,
                gates.continue_step(self.engine, game, match),
            )

    @app_commands.command(
        name="resume",
        description=(
            "Unstick a game: re-post whatever prompt it is waiting on."
        ),
    )
    @app_commands.describe(
        force=(
            "Throw the current turn away and start the offensive choice "
            "over. Use only when resuming normally doesn't help."
        ),
    )
    @app_commands.guild_only()
    async def resume(
        self,
        interaction: discord.Interaction,
        force: bool = False,
    ) -> None:
        """
        Recover a game whose live prompt is gone.

        A restart re-arms exactly one message per game -- the one in
        `turn_message_id` -- so a game can come back with no working
        button anywhere: the prompt was deleted once both sides picked
        (`close_maneuver_prompt`), or the process died before the
        prompt it was about to send was recorded, or it died in the
        middle of a cascade whose next step was the bot's own. See
        `GameService.resume`.

        Plain resume changes nothing about the match; it only puts the
        question back. `force` is the escape hatch for state that is
        genuinely inconsistent -- it clears the turn and asks the
        offense to choose again.
        """
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        if not self.may_administer_game(interaction, game):
            await interaction.followup.send(
                "Only a player in this game, or someone who can manage "
                "channels, can resume it.",
                ephemeral=True,
            )
            return

        if game.status == GameStatus.FINISHED:
            await interaction.followup.send(
                "This game has already finished, so there is nothing to "
                "resume.",
                ephemeral=True,
            )
            return

        if force:
            # Which positions `force` may not clear is the model's
            # (`RulesEngine.turn_reset_refusal`): setup, halftime, a
            # time out and the shootout are real positions in the game
            # rather than a turn gone wrong, and a plain resume walks
            # them on.
            try:
                result = self.rendered(
                    game, self.service.reset_turn(game.game_id),
                )
            except ValueError as error:
                await interaction.followup.send(str(error), ephemeral=True)
                return
            if result.refused:
                await interaction.followup.send(
                    f"{result.refusal} Run `/d12ball resume` without "
                    "`force`.",
                    ephemeral=True,
                )
                return

            await self.present(interaction, game, result)
            await interaction.followup.send(
                "Turn cleared and the offensive choice re-posted.",
                ephemeral=True,
            )
            return

        try:
            waiting_on = await self.resume_game(interaction, game)
        except ValueError as error:
            # Every step this hands off to validates the state it
            # loads, so a match that no longer hangs together says so
            # here rather than half-resuming.
            await interaction.followup.send(
                f"I could not resume this game: {error}\n"
                "`/d12ball resume force:true` will clear the turn and "
                "start the offensive choice over.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"Resumed — the game was waiting on {waiting_on}.",
            ephemeral=True,
        )

    @app_commands.command(
        name="abandon_game",
        description=(
            "End this channel's game without a result and archive it."
        ),
    )
    @app_commands.describe(
        confirm='Type "confirm" to abandon this game.',
    )
    @app_commands.guild_only()
    async def abandon_game(
        self,
        interaction: discord.Interaction,
        confirm: str,
    ) -> None:
        """
        End one stuck game, rather than every unfinished game at once,
        which is all `/debug reset_channels` can do.

        The channel is archived, not deleted: it is the record of what
        happened, deleting one is the tightest rate limit Discord has
        (see "Discord's rate limits" in docs/design/rate-limits.md), and the saved game
        is what keeps its PBD number from being handed out twice.
        """
        await interaction.response.defer(ephemeral=True)

        game = self.game_for_channel(interaction.channel_id)
        if game is None:
            await interaction.followup.send(
                "There is no D12 Ball game in this channel.",
                ephemeral=True,
            )
            return

        if not self.may_administer_game(interaction, game):
            await interaction.followup.send(
                "Only a player in this game, or someone who can manage "
                "channels, can abandon it.",
                ephemeral=True,
            )
            return

        if game.status == GameStatus.FINISHED:
            await interaction.followup.send(
                "This game has already finished.",
                ephemeral=True,
            )
            return

        if confirm != "confirm":
            await interaction.followup.send(
                'Abandon cancelled. Type "confirm" in the confirm field '
                "to end this game without a result and move its channel "
                "to the PBD archive. The channel and everything in it "
                "are kept.",
                ephemeral=True,
            )
            return

        try:
            await self.abandon_and_archive_game(game, interaction.user)
        except (ValueError, discord.Forbidden, discord.HTTPException) as error:
            # An error rather than a warning: the game is still in the
            # active category with nobody able to play it, which is
            # exactly the state this command exists to get out of.
            LOGGER.error(
                "Could not abandon D12 Ball game %s: %s",
                game.game_id, error,
            )
            await interaction.followup.send(
                f"I could not abandon this game: {error}",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "Game abandoned. Its channel has moved to the PBD archive, "
            "and it no longer counts as a game in progress.",
            ephemeral=True,
        )

    async def abandon_and_archive_game(
        self,
        game: D12BallGame,
        abandoned_by: discord.abc.User,
    ) -> None:
        """
        End `game` without a result, archive its channel and take down
        every live prompt it left behind.

        The order matters: the channel lookup and move are the only
        steps that can fail, so they go first and a failure leaves the
        game exactly as it was rather than half-ended. Everything after
        them is local.

        Clearing `message_id` and `turn_message_id` is what stops the
        next restart re-arming the buttons of a game that is over --
        `D12Ball.__init__` restores views off those two ids and reads
        nothing about status.
        """
        channel = await self.fetch_game_channel(game)

        # Said in the channel, not just back to whoever ran the
        # command: the other coach is the person who most needs to know
        # the game they were waiting on is over.
        await channel.send(
            f"**Game abandoned** by {abandoned_by.display_name}. It ends "
            "with no result, and this channel moves to the PBD archive."
        )
        await self.move_channel_to_archive(channel)

        # The prompt is stripped where it stands, so the abandoned
        # channel does not keep a menu that acts on a finished game
        # until the next restart drops it. One edit, and a failure is
        # not worth reporting: the game is over either way.
        if game.turn_message_id is not None:
            try:
                await channel.get_partial_message(
                    game.turn_message_id,
                ).edit(view=None)
            except discord.HTTPException:
                pass

        self.boards.forget(game)

        game.abandon()
        game.message_id = None
        game.turn_message_id = None
        save_games(self.games)

        LOGGER.info(
            "D12 Ball game %s abandoned by %s.", game.game_id, abandoned_by,
        )

    @app_commands.command(
        name="coach",
        description=(
            "Move one of your own player cards between zones and benches."
        ),
    )
    @app_commands.describe(
        player_card="One of your team's player cards.",
        destination="Where to move the card: a zone or a bench.",
    )
    @app_commands.guild_only()
    async def coach(
        self,
        interaction: discord.Interaction,
        player_card: str,
        destination: str,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        side = self.engine.side_for_user(game, interaction.user.id)
        if game.test_game and interaction.user.id == game.player_1_id:
            for candidate_side in (TeamSide.HOME, TeamSide.VISITING):
                setup = match.setup_for_side(candidate_side)
                roster_ids = (
                    setup.field_players
                    + setup.team_board.bench
                    + setup.team_board.back_bench
                )
                if player_card in roster_ids:
                    side = candidate_side
                    break
        if side is None:
            await interaction.followup.send(
                "You are not one of the players in this game. Use "
                "/d12ball ref to move a specific team's card instead.",
                ephemeral=True,
            )
            return

        try:
            match.move_card(side, player_card, destination)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        self.service.persist(game, match)

        player = self.engine.get_player_definition(player_card)
        await self.announce_board_update(
            interaction,
            game,
            f"{self.player_label(match, player)} moved to "
            f"{destination_display_name(destination, match.board.layout.board_size)}.",
        )

    @coach.autocomplete("player_card")
    async def coach_player_card_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        game, match = self.match_for_channel(interaction.channel_id)
        if match is None:
            return []
        side = self.engine.side_for_user(game, interaction.user.id)
        if side is None:
            return []
        setups = (
            [match.home, match.visiting]
            if game.test_game and interaction.user.id == game.player_1_id
            else [match.setup_for_side(side)]
        )
        roster_ids = [
            player_id
            for setup in setups
            for player_id in (
                setup.field_players
                + setup.team_board.bench
                + setup.team_board.back_bench
            )
        ]
        options = [
            (player_id, self.engine.format_roster_player(player_id))
            for player_id in roster_ids
        ]
        return filter_choices(current, options)

    @coach.autocomplete("destination")
    async def coach_destination_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        _, match = self.match_for_channel(interaction.channel_id)
        board_size = match.board.layout.board_size if match else 7
        options = [
            (value, destination_display_name(value, board_size))
            for value in (
                Zone.HOME_GOAL.value,
                Zone.MIDFIELD.value,
                Zone.VISITORS_GOAL.value,
                *BENCH_DESTINATIONS,
            )
        ]
        return filter_choices(current, options)

    @app_commands.command(
        name="ref",
        description=(
            "Move a player card (either team) between its team's zones "
            "and benches."
        ),
    )
    @app_commands.describe(
        player_card="Any player card from either team.",
        destination="Where to move the card: a team's zone or bench.",
    )
    @app_commands.guild_only()
    async def ref(
        self,
        interaction: discord.Interaction,
        player_card: str,
        destination: str,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        try:
            player = self.engine.get_player_definition(player_card)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        try:
            card_side = (
                TeamSide.HOME
                if match.team_for_player(player.player_id) == match.home.team
                else TeamSide.VISITING
            )
        except ValueError:
            await interaction.followup.send(
                f"{player.name} is not on either roster in this match.",
                ephemeral=True,
            )
            return

        dest_side_value, _, dest_target = destination.partition(":")
        try:
            dest_side = TeamSide(dest_side_value)
        except ValueError:
            await interaction.followup.send(
                f"\"{destination}\" is not a valid destination.",
                ephemeral=True,
            )
            return

        if dest_side != card_side:
            team_label = format_team_side_label(
                match.setup_for_side(card_side),
            )
            await interaction.followup.send(
                f"{player.name} plays for {team_label}; move them to "
                f"one of {team_label}'s zones or benches instead.",
                ephemeral=True,
            )
            return

        try:
            match.move_card(card_side, player_card, dest_target)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        self.service.persist(game, match)

        await self.announce_board_update(
            interaction,
            game,
            f"{self.player_label(match, player)} moved to "
            f"{destination_display_name(dest_target, match.board.layout.board_size)}.",
        )

    @ref.autocomplete("player_card")
    async def ref_player_card_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        _, match = self.match_for_channel(interaction.channel_id)
        if match is None:
            return []
        options = [
            (
                player_id,
                self.engine.format_roster_player_with_team(player_id, setup.team),
            )
            for setup in (match.home, match.visiting)
            for player_id in (
                setup.field_players
                + setup.team_board.bench
                + setup.team_board.back_bench
            )
        ]
        return filter_choices(current, options)

    @ref.autocomplete("destination")
    async def ref_destination_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        _, match = self.match_for_channel(interaction.channel_id)
        if match is None:
            return []
        board_size = match.board.layout.board_size
        options = [
            (
                f"{setup.side.value}:{target}",
                f"{format_team_side_label(setup)} - "
                f"{destination_display_name(target, board_size)}",
            )
            for setup in (match.home, match.visiting)
            for target in (
                Zone.HOME_GOAL.value,
                Zone.MIDFIELD.value,
                Zone.VISITORS_GOAL.value,
                *BENCH_DESTINATIONS,
            )
        ]
        return filter_choices(current, options)

    @meeple_group.command(
        name="move",
        description="Move a fielded player's meeple to another space.",
    )
    @app_commands.describe(
        meeple="A currently fielded player.",
        destination="The board space to move them to, e.g. 1.",
    )
    @app_commands.guild_only()
    async def meeple_move(
        self,
        interaction: discord.Interaction,
        meeple: str,
        destination: str,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        try:
            zone, space_index = parse_space_value(destination)
            match.move_meeple(meeple, zone, space_index)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        self.service.persist(game, match)

        player = self.engine.get_player_definition(meeple)
        await self.announce_board_update(
            interaction,
            game,
            f"{self.player_label(match, player)} moved to "
            f"{space_label(zone, space_index, match.board)}.",
        )

    @meeple_move.autocomplete("meeple")
    async def meeple_move_meeple_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        _, match = self.match_for_channel(interaction.channel_id)
        if match is None:
            return []
        options = [
            (
                player_id,
                self.engine.format_roster_player_with_team(player_id, setup.team),
            )
            for setup in (match.home, match.visiting)
            for player_id in setup.field_players
        ]
        return filter_choices(current, options)

    @meeple_move.autocomplete("destination")
    async def meeple_move_destination_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        _, match = self.match_for_channel(interaction.channel_id)
        if match is None:
            return []
        return filter_choices(current, space_choices(match))

    @ball_group.command(
        name="move",
        description="Place the ball on any board space.",
    )
    @app_commands.describe(
        destination="The board space to move the ball to, e.g. 1.",
    )
    @app_commands.guild_only()
    async def ball_move(
        self,
        interaction: discord.Interaction,
        destination: str,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        try:
            zone, space_index = parse_space_value(destination)
            match.move_ball(zone, space_index)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        self.service.persist(game, match)

        possession_team = match.setup_for_side(match.ball.possession).team
        await self.announce_board_update(
            interaction,
            game,
            f"The ball moved to {space_label(zone, space_index, match.board)}. "
            f"{team_display_name(possession_team)} has possession.",
        )

    @ball_move.autocomplete("destination")
    async def ball_move_destination_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        _, match = self.match_for_channel(interaction.channel_id)
        if match is None:
            return []
        return filter_choices(current, space_choices(match))

    @ball_group.command(
        name="possession",
        description="Set which team has possession of the ball.",
    )
    @app_commands.describe(team="The team to give possession to.")
    @app_commands.guild_only()
    async def ball_possession(
        self,
        interaction: discord.Interaction,
        team: str,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        try:
            side = TeamSide(team)
            match.set_possession(side)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        self.service.persist(game, match)

        await interaction.followup.send(
            f"{team_display_name(match.setup_for_side(side).team)} now has "
            "possession."
        )
        await self.refresh_match_image(interaction, game)

    @ball_possession.autocomplete("team")
    async def ball_possession_team_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        _, match = self.match_for_channel(interaction.channel_id)
        if match is None:
            return []
        options = [
            (setup.side.value, format_team_side_label(setup))
            for setup in (match.home, match.visiting)
        ]
        return filter_choices(current, options)

    @ball_group.command(
        name="speed",
        description="Set or adjust the ball's speed (1-12).",
    )
    @app_commands.describe(
        value=(
            "A number to set the speed to, or +1/-1 to adjust it. "
            "Leave blank to increase it by one."
        ),
    )
    @app_commands.guild_only()
    async def ball_speed(
        self,
        interaction: discord.Interaction,
        value: Optional[str] = None,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        try:
            match.ball.speed = resolve_adjustable_value(
                value, match.ball.speed, 1, 12,
            )
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        self.service.persist(game, match)

        await interaction.followup.send(
            f"Ball speed is now {match.ball.speed}."
        )
        await self.refresh_match_image(interaction, game)

    @app_commands.command(
        name="score",
        description="Set or adjust a team's score.",
    )
    @app_commands.describe(
        team="The team to adjust. Defaults to your own team.",
        value=(
            "A number to set the score to, or +1/-1 to adjust it. "
            "Leave blank to increase it by one."
        ),
    )
    @app_commands.guild_only()
    async def score(
        self,
        interaction: discord.Interaction,
        team: Optional[str] = None,
        value: Optional[str] = None,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        if team is not None:
            try:
                side = TeamSide(team)
            except ValueError:
                await interaction.followup.send(
                    f"\"{team}\" is not a valid team.",
                    ephemeral=True,
                )
                return
        else:
            side = self.engine.side_for_user(game, interaction.user.id)
            if side is None:
                await interaction.followup.send(
                    "You are not one of the players in this game; "
                    "specify a team.",
                    ephemeral=True,
                )
                return

        current = (
            match.scoreboard.home_score
            if side == TeamSide.HOME
            else match.scoreboard.visiting_score
        )
        try:
            new_value = resolve_adjustable_value(value, current, 0, 999)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        if side == TeamSide.HOME:
            match.scoreboard.home_score = new_value
        else:
            match.scoreboard.visiting_score = new_value

        self.service.persist(game, match)

        team_name = team_display_name(match.setup_for_side(side).team)
        await interaction.followup.send(
            f"{team_name}'s score is now {new_value} "
            f"({match.scoreboard.home_score}:"
            f"{match.scoreboard.visiting_score})."
        )
        await self.refresh_match_image(interaction, game)

    @score.autocomplete("team")
    async def score_team_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        _, match = self.match_for_channel(interaction.channel_id)
        if match is None:
            return []
        options = [
            (setup.side.value, format_team_side_label(setup))
            for setup in (match.home, match.visiting)
        ]
        return filter_choices(current, options)

    @app_commands.command(
        name="time",
        description="Set or adjust the game clock (00-30) and half.",
    )
    @app_commands.describe(
        value=(
            "A number to set the clock to, or +1/-1 to adjust it. "
            "Leave blank to increase it by one."
        ),
        period="Switch to the first or second half.",
    )
    @app_commands.choices(
        period=[
            app_commands.Choice(name="First Half", value="first_half"),
            app_commands.Choice(name="Second Half", value="second_half"),
        ],
    )
    @app_commands.guild_only()
    async def time(
        self,
        interaction: discord.Interaction,
        value: Optional[str] = None,
        period: Optional[str] = None,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        try:
            match.scoreboard.time = resolve_adjustable_value(
                value, match.scoreboard.time, 0, MAX_DEBUG_CLOCK,
            )
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        if period is not None:
            match.scoreboard.period = MatchPeriod(period)

        self.service.persist(game, match)

        period_label = (
            "First Half"
            if match.scoreboard.period == MatchPeriod.FIRST_HALF
            else "Second Half"
        )
        await interaction.followup.send(
            f"The clock is now {match.scoreboard.time:02d} "
            f"({period_label})."
        )
        await self.refresh_match_image(interaction, game)

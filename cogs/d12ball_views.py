"""
The discord.ui.View classes that drive D12 Ball's interaction flow --
one per prompt a player can be shown (team selection, coin flip, a
maneuver challenge, a skill test, substitutions, and so on). Every view
holds a reference to the D12Ball cog (as `self.cog`) and calls back into
it to run game logic; the views themselves are concerned with rendering
prompts and turning button/select clicks into calls on the cog.
"""

import asyncio
import random
from typing import TYPE_CHECKING, Optional

import discord

from d12ball.components import (
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
)
from d12ball.game import (
    AIOpponent,
    CoinFace,
    D12BallGame,
    Formation,
    GameMode,
    GameStatus,
    HomeChoice,
    Team,
    TieMode,
)
from d12ball.render import (
    TEAM_COLORS,
    render_player_portrait,
    render_skill_test_dice,
)

from gamesaves.d12ball.storage import save_games

from cogs.d12ball_helpers import (
    AI_OPPONENT_NAMES,
    LOGGER,
    ROLE_INITIALS,
    TIE_MODE_LABELS,
    add_full_image_button,
    add_full_image_button_to_response,
    build_home_choice_message,
    build_setup_message,
    contest_noun,
    destination_display_name,
    format_coin_emoji,
    format_player,
    format_player_with_team,
    format_role_bracket,
    format_team_side_label,
    pin_board_message,
    refresh_player_names,
    send_error_fallback,
    space_label,
)

if TYPE_CHECKING:
    from cogs.d12ball import D12Ball

class SafeView(discord.ui.View):
    """
    Base class for every D12 Ball view. discord.py's default behavior
    for an uncaught exception in a button/select callback is to log it
    and otherwise do nothing, which leaves the click looking like it
    had no effect at all. This surfaces a message instead.
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


class GameConfigurationView(SafeView):
    def configuration_start_row(
        self,
        game: Optional[D12BallGame],
    ) -> int:
        """
        The action row the settings block starts on. A view that puts
        its own buttons above the settings (team selection) overrides
        this. Discord only gives us five rows and the block is up to
        four of them -- mode, board size, tie mode, and, for a solo
        game, the AI opponent -- so there is no room to spare.
        """
        return 0

    def add_configuration_buttons(self) -> None:
        game = self.cog.games.get(self.game_id)
        selected_mode = game.mode if game else GameMode.BASIC
        selected_board_size = game.board_size if game else 7
        selected_tie_mode = game.tie_mode if game else TieMode.LEAGUE
        configuration_closed = bool(
            game and game.status != GameStatus.SETUP
        )
        first_row = self.configuration_start_row(game)

        for label, mode in (
            ("Basic", GameMode.BASIC),
            ("Advanced", GameMode.ADVANCED),
        ):
            button = discord.ui.Button(
                label=label,
                style=(
                    discord.ButtonStyle.secondary
                    if mode == selected_mode
                    else discord.ButtonStyle.primary
                ),
                custom_id=f"d12ball:mode:{self.game_id}:{mode.value}",
                disabled=configuration_closed or mode == selected_mode,
                row=first_row,
            )

            async def mode_callback(
                interaction: discord.Interaction,
                selected_mode: GameMode = mode,
            ) -> None:
                await self.select_mode(interaction, selected_mode)

            button.callback = mode_callback
            self.add_item(button)

        for board_size in (6, 7, 9):
            button = discord.ui.Button(
                label=str(board_size),
                style=(
                    discord.ButtonStyle.secondary
                    if board_size == selected_board_size
                    else discord.ButtonStyle.primary
                ),
                custom_id=(
                    f"d12ball:board_size:{self.game_id}:{board_size}"
                ),
                disabled=(
                    configuration_closed
                    or board_size == selected_board_size
                ),
                row=first_row + 1,
            )

            async def board_size_callback(
                interaction: discord.Interaction,
                selected_board_size: int = board_size,
            ) -> None:
                await self.select_board_size(
                    interaction,
                    selected_board_size,
                )

            button.callback = board_size_callback
            self.add_item(button)

        for tie_mode, label in TIE_MODE_LABELS.items():
            button = discord.ui.Button(
                label=label,
                style=(
                    discord.ButtonStyle.secondary
                    if tie_mode == selected_tie_mode
                    else discord.ButtonStyle.primary
                ),
                custom_id=(
                    f"d12ball:tie_mode:{self.game_id}:{tie_mode.value}"
                ),
                disabled=(
                    configuration_closed or tie_mode == selected_tie_mode
                ),
                row=first_row + 2,
            )

            async def tie_mode_callback(
                interaction: discord.Interaction,
                selected: TieMode = tie_mode,
            ) -> None:
                await self.select_tie_mode(interaction, selected)

            button.callback = tie_mode_callback
            self.add_item(button)

        if game is None or not game.is_solo_game:
            return

        selected_ai = game.ai_opponent or AIOpponent.DINKY

        for ai_type, label in AI_OPPONENT_NAMES.items():
            button = discord.ui.Button(
                label=label,
                style=(
                    discord.ButtonStyle.secondary
                    if ai_type == selected_ai
                    else discord.ButtonStyle.primary
                ),
                custom_id=(
                    f"d12ball:ai_opponent:{self.game_id}:{ai_type.value}"
                ),
                disabled=configuration_closed or ai_type == selected_ai,
                row=first_row + 3,
            )

            async def ai_opponent_callback(
                interaction: discord.Interaction,
                selected_ai_type: AIOpponent = ai_type,
            ) -> None:
                await self.select_ai_opponent(interaction, selected_ai_type)

            button.callback = ai_opponent_callback
            self.add_item(button)

    async def validate_configuration_change(
        self,
        interaction: discord.Interaction,
    ) -> Optional[D12BallGame]:
        game = self.cog.games.get(self.game_id)

        if game is None:
            await interaction.response.send_message(
                "I could not find this game.",
                ephemeral=True,
            )
            return None

        if game.status != GameStatus.SETUP:
            await interaction.response.send_message(
                "Game settings can only be changed during setup.",
                ephemeral=True,
            )
            return None

        player_ids = {game.player_1_id}
        if game.player_2_id is not None:
            player_ids.add(game.player_2_id)

        if interaction.user.id not in player_ids:
            await interaction.response.send_message(
                "Only the players in this game can change its settings.",
                ephemeral=True,
            )
            return None

        return game

    async def select_mode(
        self,
        interaction: discord.Interaction,
        selected_mode: GameMode,
    ) -> None:
        game = await self.validate_configuration_change(interaction)
        if game is None:
            return

        if selected_mode == GameMode.ADVANCED:
            await interaction.response.send_message(
                "advanced mode is not yet ready, please play in basic mode",
                ephemeral=True,
            )
            return

        game.mode = GameMode.BASIC
        save_games(self.cog.games)

        refreshed_view = type(self)(
            cog=self.cog,
            game_id=self.game_id,
        )
        await interaction.response.edit_message(
            content=build_setup_message(game),
            view=refreshed_view,
        )

    async def select_tie_mode(
        self,
        interaction: discord.Interaction,
        selected_tie_mode: TieMode,
    ) -> None:
        game = await self.validate_configuration_change(interaction)
        if game is None:
            return

        if selected_tie_mode == TieMode.TOURNAMENT:
            # Refused for the same reason advanced mode is: the extreme
            # shootout a tournament tie goes to isn't implemented yet.
            await interaction.response.send_message(
                "tournament mode is not yet ready, please play in "
                "league mode",
                ephemeral=True,
            )
            return

        game.tie_mode = TieMode.LEAGUE
        save_games(self.cog.games)

        refreshed_view = type(self)(
            cog=self.cog,
            game_id=self.game_id,
        )
        await interaction.response.edit_message(
            content=build_setup_message(game),
            view=refreshed_view,
        )

    async def select_ai_opponent(
        self,
        interaction: discord.Interaction,
        selected_ai_type: AIOpponent,
    ) -> None:
        game = await self.validate_configuration_change(interaction)
        if game is None:
            return

        if selected_ai_type == AIOpponent.DECENT:
            await interaction.response.send_message(
                "Decent AI is not yet ready, please play against Dinky AI.",
                ephemeral=True,
            )
            return

        game.ai_opponent = AIOpponent.DINKY
        save_games(self.cog.games)

        refreshed_view = type(self)(
            cog=self.cog,
            game_id=self.game_id,
        )
        await interaction.response.edit_message(
            content=build_setup_message(game),
            view=refreshed_view,
        )

    async def select_board_size(
        self,
        interaction: discord.Interaction,
        selected_board_size: int,
    ) -> None:
        game = await self.validate_configuration_change(interaction)
        if game is None:
            return

        game.board_size = selected_board_size
        save_games(self.cog.games)

        refreshed_view = type(self)(
            cog=self.cog,
            game_id=self.game_id,
        )
        await interaction.response.edit_message(
            content=build_setup_message(game),
            view=refreshed_view,
        )


class TeamSelectionView(GameConfigurationView):
    def configuration_start_row(
        self,
        game: Optional[D12BallGame],
    ) -> int:
        # Below the team buttons, which a test game needs two rows for
        # (one per player). A test game is never a solo game, so its
        # settings block stops at the tie-mode row and still fits.
        return 2 if game is not None and game.test_game else 1

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        game = self.cog.games.get(game_id)
        teams = [
            ("Orange", Team.ORANGE, discord.ButtonStyle.primary),
            ("Teal", Team.TEAL, discord.ButtonStyle.primary),
            ("Purple", Team.PURPLE, discord.ButtonStyle.primary),
            ("Slime", Team.SLIME, discord.ButtonStyle.primary),
        ]

        player_rows = (1, 2) if game and game.test_game else (None,)
        for player_number in player_rows:
            for label, team, style in teams:
                selected_team = None
                other_team = None
                if game is not None:
                    if player_number == 2:
                        selected_team = game.player_2_team
                        other_team = game.player_1_team
                    else:
                        selected_team = game.player_1_team
                        other_team = game.player_2_team

                unavailable = team in {selected_team, other_team}
                button = discord.ui.Button(
                    label=(
                        f"Player {player_number}: {label}"
                        if player_number is not None
                        else label
                    ),
                    style=(
                        discord.ButtonStyle.secondary
                        if unavailable
                        else style
                    ),
                    custom_id=(
                        f"d12ball:team:{game_id}:{player_number}:{team.value}"
                        if player_number is not None
                        else f"d12ball:team:{game_id}:{team.value}"
                    ),
                    disabled=unavailable,
                    row=(player_number - 1 if player_number else 0),
                )

                async def callback(
                    interaction: discord.Interaction,
                    chosen_team: Team = team,
                    chosen_player_number: Optional[int] = player_number,
                ) -> None:
                    await self.select_team(
                        interaction,
                        chosen_team,
                        chosen_player_number,
                    )

                button.callback = callback
                self.add_item(button)

        self.add_configuration_buttons()

    async def select_team(
        self,
        interaction: discord.Interaction,
        selected_team: Team,
        selected_player_number: Optional[int] = None,
    ) -> None:
        game = self.cog.games.get(self.game_id)

        if game is None:
            await interaction.response.send_message(
                "I could not find this game.",
                ephemeral=True,
            )
            return

        if game.status != GameStatus.SETUP:
            await interaction.response.send_message(
                "Team selection is already closed.",
                ephemeral=True,
            )
            return

        if game.test_game:
            is_player_1 = (
                interaction.user.id == game.player_1_id
                and selected_player_number == 1
            )
            is_player_2 = (
                interaction.user.id == game.player_2_id
                and selected_player_number == 2
            )
        else:
            is_player_1 = interaction.user.id == game.player_1_id
            is_player_2 = (
                game.player_2_id is not None
                and interaction.user.id == game.player_2_id
            )

        if not is_player_1 and not is_player_2:
            await interaction.response.send_message(
                "Only the players in this game can choose teams.",
                ephemeral=True,
            )
            return

        if is_player_1:
            if game.player_2_team == selected_team:
                await interaction.response.send_message(
                    "Player 2 has already selected that team.",
                    ephemeral=True,
                )
                return

            game.player_1_team = selected_team
            if game.player_2_id is None:
                available_ai_teams = [
                    team
                    for team in Team
                    if team != selected_team
                ]

                game.player_2_team = random.choice(
                    available_ai_teams
                )

        else:
            if game.player_1_team == selected_team:
                await interaction.response.send_message(
                    "Player 1 has already selected that team.",
                    ephemeral=True,
                )
                return

            game.player_2_team = selected_team

        save_games(self.cog.games)

        message = build_setup_message(game)

        if game.teams_selected:
            # Resolved before the view is built, because the flip
            # button carries the fortune coin.
            await self.cog.ensure_coin_emojis()
            coin_view = CoinFlipView(
                cog=self.cog,
                game_id=self.game_id,
            )

            await interaction.response.edit_message(
                content=message,
                view=coin_view,
            )
        else:
            refreshed_view = TeamSelectionView(
                cog=self.cog,
                game_id=self.game_id,
            )
            await interaction.response.edit_message(
                content=message,
                view=refreshed_view,
            )

    def build_team_message(
        self,
        game: D12BallGame,
    ) -> str:
        return build_setup_message(game)


class CoinFlipView(GameConfigurationView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        game = self.cog.games.get(game_id)

        self.flip_button = discord.ui.Button(
            label=(
                "Flip a Coin to start the game!"
            ),
            style=discord.ButtonStyle.primary,
            emoji=format_coin_emoji(
                self.cog.coin_emojis,
                CoinFace.FORTUNE,
            ),
            custom_id=f"d12ball:flip_coin:{game_id}",
            disabled=game.coin_flipped if game else False,
            # Last row, under the settings block: this button starts
            # the game, so it belongs below everything it settles.
            row=4,
        )

        self.flip_button.callback = self.flip_coin
        self.add_item(self.flip_button)
        self.add_configuration_buttons()

    async def flip_coin(
        self,
        interaction: discord.Interaction,
    ) -> None:
        game = self.cog.games.get(self.game_id)

        if game is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        allowed_player_ids = {game.player_1_id}

        if game.player_2_id is not None:
            allowed_player_ids.add(game.player_2_id)

        if interaction.user.id not in allowed_player_ids:
            await interaction.response.send_message(
                "Only a player in this game can flip the coin.",
                ephemeral=True,
            )
            return

        if game.coin_flipped:
            refreshed_view = HomeAwaySelectionView(
                cog=self.cog,
                game_id=self.game_id,
            )

            await interaction.response.edit_message(
                content=build_home_choice_message(game),
                view=refreshed_view,
            )

            await interaction.followup.send(
                "The coin has already been flipped.",
                ephemeral=True,
            )
            return

        flipping_player_number = (
            1 if interaction.user.id == game.player_1_id else 2
        )
        face = random.choice((CoinFace.FORTUNE, CoinFace.DOOM))

        refresh_player_names(game, interaction.guild)
        winner_player_number = game.resolve_coin_toss(
            flipping_player_number,
            face,
        )

        game.coin_winner = format_player(game, winner_player_number)
        game.start_game()

        if game.is_solo_game and winner_player_number == 2:
            ai_choice = self.cog.get_ai_strategy(
                game,
            ).choose_home_or_visiting()
            game.choose_home_or_visiting(2, ai_choice)
            self.cog.initialize_standard_match(game)

        refreshed_view = HomeAwaySelectionView(
            cog=self.cog,
            game_id=self.game_id,
        )

        await interaction.response.edit_message(
            content=build_setup_message(
                game,
                mention_players=False,
            ),
            view=None,
        )

        # The coin goes out on its own, with nothing else in the
        # message, which is what makes Discord render it large.
        await interaction.followup.send(
            format_coin_emoji(
                await self.cog.ensure_coin_emojis(),
                game.coin_face,
            ),
        )

        followup_arguments = {
            "view": refreshed_view,
            "wait": True,
        }
        if game.match_state is not None:
            followup_arguments["file"] = await self.cog.build_match_file(game)

        choice_message = await interaction.followup.send(
            build_home_choice_message(game),
            **followup_arguments,
        )
        game.message_id = choice_message.id
        save_games(self.cog.games)

        await add_full_image_button(choice_message, refreshed_view)

        if game.match_state is not None:
            # The kickoff board, and the only pinned one that stays
            # current: this is the persistent message every later
            # refresh edits, so the pin never needs re-cutting.
            await pin_board_message(choice_message)
            await self.cog.begin_setup_coaching(interaction, game)


class HomeAwaySelectionView(SafeView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        game = self.cog.games.get(game_id)
        selected_choice = None
        assignment_complete = bool(
            game and game.home_and_visiting_selected
        )

        if assignment_complete and game is not None:
            selected_choice = (
                HomeChoice.HOME
                if (
                    game.home_player_number
                    == game.coin_winner_player_number
                )
                else HomeChoice.VISITING
            )

        for label, choice in (
            ("Home", HomeChoice.HOME),
            ("Visiting", HomeChoice.VISITING),
        ):
            button = discord.ui.Button(
                label=label,
                style=(
                    discord.ButtonStyle.success
                    if choice == selected_choice
                    else (
                        discord.ButtonStyle.secondary
                        if assignment_complete
                        else discord.ButtonStyle.primary
                    )
                ),
                custom_id=(
                    f"d12ball:home_choice:{game_id}:{choice.value}"
                ),
                disabled=assignment_complete,
            )

            async def callback(
                interaction: discord.Interaction,
                selected_choice: HomeChoice = choice,
            ) -> None:
                await self.select_home_or_visiting(
                    interaction,
                    selected_choice,
                )

            button.callback = callback
            self.add_item(button)

    async def select_home_or_visiting(
        self,
        interaction: discord.Interaction,
        choice: HomeChoice,
    ) -> None:
        game = self.cog.games.get(self.game_id)

        if game is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        if game.home_and_visiting_selected:
            await interaction.response.send_message(
                "Home and visiting teams have already been assigned.",
                ephemeral=True,
            )
            return

        winner_player_number = game.coin_winner_player_number
        refresh_player_names(game, interaction.guild)
        winner_user_id = (
            game.player_1_id
            if winner_player_number == 1
            else game.player_2_id
        )

        if interaction.user.id != winner_user_id:
            await interaction.response.send_message(
                "Only the player who won the coin toss can make this choice.",
                ephemeral=True,
            )
            return

        game.choose_home_or_visiting(winner_player_number, choice)
        self.cog.initialize_standard_match(game)
        save_games(self.cog.games)

        refreshed_view = HomeAwaySelectionView(
            cog=self.cog,
            game_id=self.game_id,
        )
        await interaction.response.edit_message(
            content=build_home_choice_message(game),
            view=refreshed_view,
            attachments=[await self.cog.build_match_file(game)],
        )

        await add_full_image_button_to_response(interaction, refreshed_view)

        await interaction.followup.send(
            f"{format_player_with_team(game, winner_player_number)} chose "
            f"**{choice.value.title()}**."
        )
        await self.cog.begin_setup_coaching(interaction, game)


class RematchView(SafeView):
    """
    The rematch button on a finished game's full-time message: opens a
    fresh game for the same players, with the same settings, and
    archives the game that just ended.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        game = self.cog.games.get(game_id)
        rematch_started = bool(
            game is not None
            and game.rematch_game_id is not None
            and game.rematch_game_id in self.cog.games
        )

        button = discord.ui.Button(
            label="Rematch",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:rematch:{game_id}",
            disabled=rematch_started,
        )
        button.callback = self.start_rematch
        self.add_item(button)

    async def start_rematch(
        self,
        interaction: discord.Interaction,
    ) -> None:
        game = self.cog.games.get(self.game_id)

        if game is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        allowed_player_ids = {game.player_1_id}
        if game.player_2_id is not None:
            allowed_player_ids.add(game.player_2_id)

        if interaction.user.id not in allowed_player_ids:
            await interaction.response.send_message(
                "Only a player in this game can start a rematch.",
                ephemeral=True,
            )
            return

        existing = (
            self.cog.games.get(game.rematch_game_id)
            if game.rematch_game_id is not None
            else None
        )
        if existing is not None:
            await interaction.response.send_message(
                "A rematch has already been started: "
                f"<#{existing.channel_id}>",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            rematch = await self.cog.start_rematch(game, interaction.user)
        except (ValueError, discord.Forbidden, discord.HTTPException) as error:
            await interaction.followup.send(
                f"I could not start the rematch: {error}",
                ephemeral=True,
            )
            return

        try:
            await interaction.message.edit(
                view=RematchView(self.cog, self.game_id),
            )
        except discord.HTTPException as error:
            # The rematch itself is already open, so this is cosmetic:
            # a button that wasn't greyed out just reports the rematch
            # it finds instead of opening another one.
            LOGGER.warning(
                "Could not disable the rematch button for game %s: %s",
                self.game_id, error,
            )

        await interaction.followup.send(
            f"Rematch created: <#{rematch.channel_id}>",
            ephemeral=True,
        )


class BallHandlerSelectionView(SafeView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id
        game = self.cog.games.get(game_id)
        if game is None or game.match_state is None:
            return

        match = self.cog.load_match_state(game)
        # Not eligible_ball_handlers: a ball carrier narrows this to
        # one button, which is the rule showing up as a menu with no
        # choice in it. send_turn_prompt normally skips the view
        # entirely in that case; this is the restore path.
        for player_id in match.turn_handler_candidates():
            player = self.cog.get_player_definition(player_id)
            initials = ROLE_INITIALS[player.role.value]
            button = discord.ui.Button(
                label=f"{player.name} [{initials}]",
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:ball_handler:{game_id}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                selected_player_id: str = player_id,
            ) -> None:
                await self.select_handler(
                    interaction,
                    selected_player_id,
                )

            button.callback = callback
            self.add_item(button)

    async def select_handler(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        match = self.cog.load_match_state(game)
        if match.active_player_id is not None:
            await interaction.response.edit_message(
                content=self.cog.build_turn_prompt(game, match),
                view=PlayerActionView(self.cog, self.game_id),
            )
            await interaction.followup.send(
                "A player has already been selected.",
                ephemeral=True,
            )
            return

        if not self.cog.user_controls_possession(
            interaction.user.id,
            game,
            match,
        ):
            await interaction.response.send_message(
                "Only the player whose team has possession can "
                "choose the ball handler.",
                ephemeral=True,
            )
            return

        try:
            match.select_ball_handler(player_id)
        except ValueError as error:
            await interaction.response.send_message(
                str(error),
                ephemeral=True,
            )
            return

        game.match_state = match.to_dict()
        save_games(self.cog.games)
        await interaction.response.edit_message(
            content=self.cog.build_turn_prompt(game, match),
            view=PlayerActionView(self.cog, self.game_id),
        )


class PlayerActionView(SafeView):
    """
    The turn's choice: shoot, or maneuver. **Shooting is only offered
    from within shooting range**, so short of it a coach is left with
    the one button -- see `MatchState.can_attempt_score` and
    `D12Ball.build_turn_prompt`, which says why the shot is missing.
    Rebuilt from match state on every restart like every other
    persistent view here, so the ball's position always decides afresh.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        game = cog.games.get(game_id)
        can_shoot = True
        if game is not None and game.match_state is not None:
            can_shoot = cog.load_match_state(game).can_attempt_score()

        actions = [
            (
                "Maneuver",
                "maneuver",
                discord.ButtonStyle.primary,
            ),
        ]
        if can_shoot:
            actions.insert(
                0,
                (
                    "Shoot to score",
                    "shoot",
                    discord.ButtonStyle.danger,
                ),
            )

        for label, action, style in actions:
            button = discord.ui.Button(
                label=label,
                style=style,
                custom_id=f"d12ball:action:{game_id}:{action}",
            )

            async def callback(
                interaction: discord.Interaction,
                selected_action: str = action,
                action_label: str = label,
            ) -> None:
                await self.choose_action(
                    interaction,
                    selected_action,
                    action_label,
                )

            button.callback = callback
            self.add_item(button)

    async def choose_action(
        self,
        interaction: discord.Interaction,
        action: str,
        action_label: str,
    ) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        match = self.cog.load_match_state(game)
        if match.active_player_id is None:
            await interaction.response.send_message(
                "Choose a player to handle the ball first.",
                ephemeral=True,
            )
            return

        if not self.cog.user_controls_possession(
            interaction.user.id,
            game,
            match,
        ):
            await interaction.response.send_message(
                "Only the player whose team has possession can "
                "choose this action.",
                ephemeral=True,
            )
            return

        if action == "shoot":
            # The button is only built when the shot is legal, so this
            # is a click on a prompt the ball has since moved out from
            # under -- the same stale-view guard the other choices keep.
            if not match.can_attempt_score():
                await interaction.response.send_message(
                    "The ball is out of shooting range.",
                    ephemeral=True,
                )
                return

            match.pending_action = "shoot"
            game.match_state = match.to_dict()
            save_games(self.cog.games)

            refresh_player_names(game, interaction.guild)
            handler = self.cog.get_player_definition(match.active_player_id)
            offense_number = self.cog.possession_player_number(game, match)
            offense_display = format_player_with_team(game, offense_number)

            await interaction.response.edit_message(
                content=(
                    f"{offense_display} has chosen to {action_label} with "
                    f"{format_role_bracket(handler, self.cog.team_emojis)}."
                ),
                view=None,
            )
            await self.cog.begin_score_attempt(interaction, game, match)
            return

        # Nobody in the ball's zone to challenge with: the maneuver
        # succeeds automatically, and the offense still picks which one
        # (docs/living-rules.md, "Maneuver"). There is no challenger to
        # choose and nothing for the defense to do, so this skips
        # straight to the offense's pick.
        eligible_challengers = match.eligible_challengers()
        if not eligible_challengers:
            match.begin_uncontested_maneuver()
            game.match_state = match.to_dict()
            save_games(self.cog.games)

            await interaction.response.defer()
            await self.cog.drop_turn_prompt(interaction, game)
            await self.cog.announce_uncontested_maneuver(
                interaction, game, match,
            )
            return

        match.pending_action = "maneuver"
        handler = self.cog.get_player_definition(match.active_player_id)
        defender_number = self.cog.defending_player_number(game, match)

        # A defender already sharing the ball's exact space leaves
        # nothing to choose -- the 1-per-team-per-space rule means
        # there's at most one, so it's automatic, the same way it's
        # automatic when the AI is the one picking.
        on_ball_space = [
            player_id
            for player_id in eligible_challengers
            if match.distance_to_ball(player_id) == 0
        ]
        if on_ball_space or (game.is_solo_game and defender_number == 2):
            challenger_id = (
                on_ball_space[0]
                if on_ball_space
                else self.cog.get_ai_strategy(game).choose_challenger(match)
            )

            # This prompt goes rather than being edited down to who
            # chose what: the challenge image posted a moment from now
            # names the handler, the challenger and everything about
            # the matchup. See D12Ball.drop_turn_prompt.
            await interaction.response.defer()
            await self.cog.drop_turn_prompt(interaction, game)
            await self.cog.auto_resolve_challenger(
                interaction, game, match, challenger_id,
            )
            return

        game.match_state = match.to_dict()
        save_games(self.cog.games)

        refresh_player_names(game, interaction.guild)
        defender_mention = format_player_with_team(
            game,
            defender_number,
            mention=True,
        )

        await interaction.response.defer()
        await self.cog.drop_turn_prompt(interaction, game)

        # The handler is named here, unlike in the automatic case
        # above: the defense is being asked to choose a challenger
        # before the challenge image exists, so this is the only place
        # they can read who they would be up against.
        challenge_view = ManeuverChallengeView(self.cog, self.game_id)
        challenge_message = await interaction.followup.send(
            f"{format_role_bracket(handler, self.cog.team_emojis)} will "
            f"maneuver for {handler.team.value.title()}.\n\n"
            f"{defender_mention}, choose which player will maneuver "
            "to challenge for the ball.",
            view=challenge_view,
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
        game.turn_message_id = challenge_message.id
        save_games(self.cog.games)


class ManeuverChallengeView(SafeView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        game = self.cog.games.get(game_id)
        if game is None or game.match_state is None:
            return

        match = self.cog.load_match_state(game)
        for player_id in match.eligible_challengers():
            player = self.cog.get_player_definition(player_id)
            distance = match.distance_to_ball(player_id)
            initials = ROLE_INITIALS[player.role.value]
            button = discord.ui.Button(
                label=f"{player.name} [{initials}] ({distance})",
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:challenger:{game_id}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                selected_player_id: str = player_id,
            ) -> None:
                await self.select_challenger(
                    interaction,
                    selected_player_id,
                )

            button.callback = callback
            self.add_item(button)

    async def select_challenger(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        match = self.cog.load_match_state(game)

        if match.challenger_id is not None:
            await interaction.response.edit_message(
                content=self.cog.build_turn_prompt(game, match),
                view=PlayerActionView(self.cog, self.game_id),
            )
            await interaction.followup.send(
                "A defender has already been chosen.",
                ephemeral=True,
            )
            return

        if not self.cog.user_controls_defense(
            interaction.user.id,
            game,
            match,
        ):
            await interaction.response.send_message(
                "Only the player whose team is defending can make "
                "this choice.",
                ephemeral=True,
            )
            return

        try:
            distance = match.choose_challenger(player_id)
        except ValueError as error:
            await interaction.response.send_message(
                str(error),
                ephemeral=True,
            )
            return

        # Built before the save: a walk-in's tokens can cross the
        # Exhausted threshold, and this description is what tests it.
        walk_in_text = self.cog.describe_challenger_walk_in(
            match,
            player_id,
            distance,
        )

        game.match_state = match.to_dict()
        save_games(self.cog.games)

        # The prompt goes rather than being edited down to "has chosen
        # their challenger" -- the challenge image below says who was
        # picked, and a good deal more. See D12Ball.drop_turn_prompt.
        await interaction.response.defer()
        await self.cog.drop_turn_prompt(interaction, game)
        await self.cog.announce_maneuver_challenge(
            interaction,
            match,
            player_id,
            walk_in_text,
        )

        await self.cog.refresh_match_image(interaction, game)
        await self.cog.begin_maneuver_action_selection(
            interaction,
            game,
            match,
        )


def build_maneuver_choice_text(cog: "D12Ball", side: str) -> str:
    """
    A text summary of the three maneuvers available to `side`, each
    with its effect and how it fares against the other side's three --
    stands in for the full reference image next to the buttons that
    actually make the pick, so a player doesn't have to cross-reference
    a separate image to know what they're choosing.
    """
    maneuvers = (
        cog.maneuver_catalog.offense
        if side == "offense"
        else cog.maneuver_catalog.defense
    )
    lines = []
    for maneuver in sorted(maneuvers, key=lambda item: item.rank):
        defeats, defeated_by, ties_with = cog.maneuver_catalog.relationships(
            maneuver.name, side,
        )
        lines.append(
            f"**{maneuver.name}:** {maneuver.effect} "
            f"(defeats {defeats}, defeated by {defeated_by}, ties with "
            f"{ties_with})"
        )
    return "\n\n".join(lines)


class ManeuverActionPromptView(SafeView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        button = discord.ui.Button(
            label="Choose Your Maneuver",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:maneuver_prompt:{game_id}",
        )
        button.callback = self.open_action_menu
        self.add_item(button)

    async def open_action_menu(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        One shared button for both sides: which ephemeral menu opens
        depends only on who clicked, so nobody has to pick "which
        button is mine" first.
        """
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        match = self.cog.load_match_state(game)
        is_offense_player = self.cog.user_controls_possession(
            interaction.user.id,
            game,
            match,
        )
        is_defense_player = self.cog.user_controls_defense(
            interaction.user.id,
            game,
            match,
        )

        if match.offense_maneuver is None and is_offense_player:
            side = "offense"
        elif (
            match.defense_maneuver is None
            and is_defense_player
            and not match.maneuver_uncontested
        ):
            side = "defense"
        elif is_defense_player and match.maneuver_uncontested:
            await interaction.response.send_message(
                "You have nobody in the ball's zone, so there is no "
                "defensive maneuver to pick.",
                ephemeral=True,
            )
            return
        elif is_offense_player or is_defense_player:
            await interaction.response.send_message(
                "You have already chosen your maneuver.",
                ephemeral=True,
            )
            return
        else:
            await interaction.response.send_message(
                "Only a player in this game can choose a maneuver.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            content=(
                "Pick your maneuver:\n\n"
                f"{build_maneuver_choice_text(self.cog, side)}"
            ),
            view=ManeuverActionSelectView(self.cog, self.game_id, side),
            ephemeral=True,
        )


class ManeuverActionSelectView(SafeView):
    """
    The six maneuver buttons, on the **one ephemeral message in the
    game** -- a coach must not see the other side's pick before the
    reveal, and ephemeral is the only thing Discord offers that hides
    it.

    That makes this the one view a restart cannot re-attach to its
    message: the bot never holds a durable handle to an ephemeral
    message, so there is no id to give `add_view`. It is restored
    message-agnostically instead -- see
    `D12Ball.restore_maneuver_menus`, which is why `timeout` is an
    argument rather than a constant.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        side: str,
        timeout: Optional[float] = 180,
    ):
        super().__init__(timeout=timeout)

        self.cog = cog
        self.game_id = game_id
        self.side = side

        maneuvers = (
            cog.maneuver_catalog.offense
            if side == "offense"
            else cog.maneuver_catalog.defense
        )
        for maneuver in sorted(maneuvers, key=lambda item: item.rank):
            button = discord.ui.Button(
                label=maneuver.name,
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:maneuver_pick:{game_id}:{side}:"
                    f"{maneuver.name}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_name: str = maneuver.name,
            ) -> None:
                await self.pick(interaction, chosen_name)

            button.callback = callback
            self.add_item(button)

        reference_button = discord.ui.Button(
            label="Maneuver Reference",
            style=discord.ButtonStyle.secondary,
            custom_id=f"d12ball:maneuver_reference_button:{game_id}:{side}",
        )
        reference_button.callback = self.show_reference
        self.add_item(reference_button)

    async def show_reference(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            file=self.cog.build_maneuver_reference_file(),
            ephemeral=True,
        )
        await add_full_image_button_to_response(interaction)

    async def pick(
        self,
        interaction: discord.Interaction,
        maneuver_name: str,
    ) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        match = self.cog.load_match_state(game)

        if self.side == "offense":
            authorized = self.cog.user_controls_possession(
                interaction.user.id,
                game,
                match,
            )
            already_chosen = match.offense_maneuver is not None
        else:
            authorized = self.cog.user_controls_defense(
                interaction.user.id,
                game,
                match,
            )
            already_chosen = match.defense_maneuver is not None

        if already_chosen:
            await interaction.response.edit_message(
                content="A maneuver has already been chosen for that side.",
                view=None,
            )
            return

        if not authorized:
            await interaction.response.send_message(
                "Only the player on that side can choose this maneuver.",
                ephemeral=True,
            )
            return

        if self.side == "offense":
            match.choose_offense_maneuver(maneuver_name)
        else:
            match.choose_defense_maneuver(maneuver_name)

        game.match_state = match.to_dict()
        save_games(self.cog.games)

        await interaction.response.edit_message(
            content=f"You chose **{maneuver_name}**.",
            view=None,
        )

        # "Someone has picked, you can't see what" is only worth a
        # message while the other side is still choosing. An
        # uncontested maneuver has nobody else to keep in the dark,
        # and the reveal a moment from now names the pick anyway.
        if not match.maneuver_uncontested:
            side_number = (
                self.cog.possession_player_number(game, match)
                if self.side == "offense"
                else self.cog.defending_player_number(game, match)
            )
            side_display = format_player_with_team(game, side_number)
            await interaction.followup.send(
                f"{side_display} has picked their maneuver.",
            )

        await self.cog.refresh_maneuver_prompt(interaction, game, match)

        if match.maneuver_selections_complete:
            await self.cog.resolve_maneuver(interaction, game, match)


class SkillTestView(SafeView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        button = discord.ui.Button(
            label="Roll the skill test",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:skill_test:{game_id}",
        )
        button.callback = self.roll
        self.add_item(button)

    async def roll(self, interaction: discord.Interaction) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        match = self.cog.load_match_state(game)
        if match.offense_maneuver is None or match.defense_maneuver is None:
            await interaction.response.send_message(
                "This skill test is no longer active.",
                ephemeral=True,
            )
            return

        participant_ids = {game.player_1_id}
        if game.player_2_id is not None:
            participant_ids.add(game.player_2_id)

        if interaction.user.id not in participant_ids:
            await interaction.response.send_message(
                "Only a player in this game can roll the skill test.",
                ephemeral=True,
            )
            return

        # Acknowledge immediately, before the dice image is rendered.
        # Discord invalidates the interaction token if the first
        # response doesn't arrive within 3 seconds, which turns into a
        # NotFound("Unknown interaction") on edit_message farther down
        # if rendering (or anything else on the way there) is slow --
        # deferring buys the rest of this method the usual 15 minutes.
        await interaction.response.defer()

        offense_player = self.cog.get_player_definition(
            match.active_player_id,
        )
        defense_player = self.cog.get_player_definition(
            match.challenger_id,
        )
        offense_skill = self.cog.player_catalog.effective_profile(
            offense_player,
        ).offense
        defense_skill = self.cog.player_catalog.effective_profile(
            defense_player,
        ).defense

        offense_roll = random.randint(1, 12)
        defense_roll = random.randint(1, 12)
        offense_total = offense_roll + offense_skill
        defense_total = defense_roll + defense_skill

        # Role ability -- Midfielder: +3 on a skill test when
        # attempting Low Pass (offense) or Pressure (defense). Injury
        # does not withhold this: what an injured player loses is their
        # own offensive or defensive skill, and only in a contest --
        # every other modifier still applies (see "Injured players" in
        # docs/living-rules.md).
        offense_ability_detail = ""
        if (
            offense_player.role == PlayerRole.MIDFIELDER
            and match.offense_maneuver == "Low Pass"
        ):
            offense_total += 3
            offense_ability_detail = "+3 Midfielder ability"

        defense_ability_detail = ""
        if (
            defense_player.role == PlayerRole.MIDFIELDER
            and match.defense_maneuver == "Pressure"
        ):
            defense_total += 3
            defense_ability_detail = "+3 Midfielder ability"

        modifier_detail = ""
        if match.defense_maneuver == "Steal Intercept":
            modifier = match.ball.speed // 2
            defense_total += modifier
            modifier_detail = f"+{modifier} ball speed modifier"

        # The dice image carries the whole arithmetic -- who rolled,
        # what they rolled, every modifier and the total -- so no
        # message repeats it in text. See render_skill_test_dice.
        offense_detail = [
            f"{offense_player.name} [{ROLE_INITIALS[offense_player.role.value]}]",
            f"Offensive skill +{offense_skill}",
        ]
        if offense_ability_detail:
            offense_detail.append(offense_ability_detail)
        defense_detail = [
            f"{defense_player.name} [{ROLE_INITIALS[defense_player.role.value]}]",
            f"Defensive skill +{defense_skill}",
        ]
        if defense_ability_detail:
            defense_detail.append(defense_ability_detail)
        if modifier_detail:
            defense_detail.append(modifier_detail)
        dice_file = discord.File(
            await asyncio.to_thread(
                render_skill_test_dice,
                [
                    (
                        offense_roll,
                        TEAM_COLORS[offense_player.team],
                        offense_player.team.value.title(),
                        offense_detail,
                        offense_total,
                    ),
                    (
                        defense_roll,
                        TEAM_COLORS[defense_player.team],
                        defense_player.team.value.title(),
                        defense_detail,
                        defense_total,
                    ),
                ]
            ),
            filename="skill_test_dice.png",
        )

        if offense_total == defense_total:
            # The token each side pays for the re-roll counts towards
            # Exhausted straight away, so whoever it pushes over is
            # already flagged when this test finally resolves and the
            # injury checks below are handed out.
            exhaustion_text = "\n".join(
                [
                    self.cog.apply_exhaustion(
                        match,
                        match.active_player_id,
                        1,
                    ),
                    self.cog.apply_exhaustion(
                        match,
                        match.challenger_id,
                        1,
                    ),
                ]
            )
            game.match_state = match.to_dict()
            save_games(self.cog.games)

            await interaction.edit_original_response(
                content=(
                    f"**It's a tie ({offense_total}-{defense_total})!** "
                    f"The skill test must be rolled again.\n"
                    f"{exhaustion_text}\n\nRoll again:"
                ),
                attachments=[dice_file],
                view=SkillTestView(self.cog, self.game_id),
            )
            await self.cog.refresh_match_image(interaction, game)
            return

        outcome = "offense" if offense_total > defense_total else "defense"
        winner_name = (
            match.offense_maneuver
            if outcome == "offense"
            else match.defense_maneuver
        )

        exhausted_participants = [
            player
            for player in (offense_player, defense_player)
            if player.player_id in match.exhausted
        ]

        # Result after the dice, not above them: a message's
        # attachments render below its content, so the winner announced
        # in this message would be read before the roll that decided
        # it. The tie above keeps its text here instead, because that
        # message also carries the roll-again button.
        await interaction.edit_original_response(
            content=None,
            attachments=[dice_file],
            view=None,
        )
        await interaction.followup.send(
            f"## **{winner_name}** wins the skill test!"
        )
        await self.cog.refresh_match_image(interaction, game)

        for player in exhausted_participants:
            await self.cog.run_injury_test(interaction, game, match, player)

        await self.cog.begin_effect_resolution(interaction, game, match, winner_name)


class ScoreAttemptView(SafeView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        button = discord.ui.Button(
            label="Roll the score attempt",
            style=discord.ButtonStyle.danger,
            custom_id=f"d12ball:score_attempt:{game_id}",
        )
        button.callback = self.roll
        self.add_item(button)

    async def roll(self, interaction: discord.Interaction) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        match = self.cog.load_match_state(game)
        if match.pending_action != "shoot" or match.active_player_id is None:
            await interaction.response.send_message(
                "This score attempt is no longer active.",
                ephemeral=True,
            )
            return

        participant_ids = {game.player_1_id}
        if game.player_2_id is not None:
            participant_ids.add(game.player_2_id)

        if interaction.user.id not in participant_ids:
            await interaction.response.send_message(
                "Only a player in this game can roll the score attempt.",
                ephemeral=True,
            )
            return

        shooter = self.cog.get_player_definition(match.active_player_id)
        offense_skill = self.cog.player_catalog.effective_profile(
            shooter,
        ).offense
        speed_modifier = match.ball.speed // 2
        defenders = self.cog.intervening_defenders(match)
        defense_skill_total = sum(skill for _, skill in defenders)

        attacking_setup = match.setup_for_side(match.ball.possession)
        defending_setup = match.setup_for_side(match.defending_side())

        # Two dice, one per human: the attacker adds the shooting
        # player's offensive skill and the ball-speed modifier, the
        # defence adds the defensive skill of every meeple in the way.
        attack_roll = random.randint(1, 12)
        defense_roll = random.randint(1, 12)
        attack_total = attack_roll + offense_skill + speed_modifier
        defense_total = defense_roll + defense_skill_total

        # Role ability -- Striker: +3 on any scoring attempt off a
        # set-up. Injury does not withhold this one, deliberately: an
        # injured player loses their ability modifier on a roll someone
        # is contesting, and nobody contests a shot (see "Injured
        # players" in docs/living-rules.md). Don't add match.injured
        # here to match the skill test.
        striker_bonus = (
            match.pending_shot_is_set_up
            and shooter.role == PlayerRole.STRIKER
        )
        if striker_bonus:
            attack_total += 3

        # Everything that built these two totals is drawn on the dice
        # image, so no message repeats it in text -- see
        # render_skill_test_dice.
        attack_detail = [
            f"{shooter.name} [{ROLE_INITIALS[shooter.role.value]}]",
            f"Offensive skill +{offense_skill}",
        ]
        if speed_modifier:
            attack_detail.append(f"+{speed_modifier} ball speed modifier")
        if striker_bonus:
            attack_detail.append("+3 Striker ability")

        if defenders:
            defense_detail = [
                f"{player.name} [{ROLE_INITIALS[player.role.value]}] +{skill}"
                for player, skill in defenders
            ]
            if len(defenders) > 1:
                defense_detail.append(
                    f"Total defensive skill +{defense_skill_total}"
                )
        else:
            defense_detail = ["No one in the way"]

        dice_file = discord.File(
            await asyncio.to_thread(
                render_skill_test_dice,
                [
                    (
                        attack_roll,
                        TEAM_COLORS[attacking_setup.team],
                        attacking_setup.team.value.title(),
                        attack_detail,
                        attack_total,
                    ),
                    (
                        defense_roll,
                        TEAM_COLORS[defending_setup.team],
                        defending_setup.team.value.title(),
                        defense_detail,
                        defense_total,
                    ),
                ]
            ),
            filename="score_attempt_dice.png",
        )

        scored = attack_total >= defense_total
        if scored:
            match.award_goal()
            verdict = (
                "# GOAL!\n"
                f"{format_role_bracket(shooter, self.cog.team_emojis)} scores "
                f"for {format_team_side_label(attacking_setup)}!\n"
                f"{match.home.team.value.title()} "
                f"{match.scoreboard.home_score}:"
                f"{match.scoreboard.visiting_score} "
                f"{match.visiting.team.value.title()}"
            )
        else:
            verdict = (
                "# Missed attempt!\n"
                f"{format_team_side_label(defending_setup)} manages to avoid a goal! (phew)"
            )

        # A plain score attempt costs no exhaustion and owes no injury
        # check -- only a shot taken off a set-up gains a token, taken
        # after the roll regardless of outcome, and injury checks stay
        # exclusive to skill tests either way.
        set_up_note = ""
        if match.pending_shot_is_set_up:
            set_up_note = "\n\n" + self.cog.apply_exhaustion(
                match, shooter.player_id, 1,
            )

        # Every score attempt is a turnover, win or miss: the clock
        # cost is the shot's own distance to goal, captured before the
        # restart moves the ball, and the team that just defended
        # restarts play -- in the middle of the midfield on a goal
        # (the same kickoff rule as the start of a half), or at the
        # space closest to their own goal on a miss.
        #
        # The shooter stops being the active player right here: unlike
        # a maneuver's turnover (exempted from validate()'s
        # active-player check for as long as challenger_id/offense_
        # maneuver/defense_maneuver stay set), a score attempt has none
        # of those, so a stale active_player_id would trip that check
        # the moment pending_run_back next goes false -- which can
        # happen before reset_maneuver() finally clears it, e.g. inside
        # a deferred loose-ball contest for an empty kickoff space.
        match.active_player_id = None
        space_minutes = match.spaces_to_goal()
        new_possession_side = defending_setup.side
        if scored:
            match.restart_after_goal(new_possession_side)
        else:
            match.restart_after_missed_score(new_possession_side)

        # Save a reconstructible run-back state before refreshing the
        # persistent board. begin_run_back repeats this assignment
        # idempotently when it posts the run-back announcement below.
        match.pending_run_back = True
        match.pending_run_back_distance = space_minutes
        match.pending_run_back_turnover = True
        game.match_state = match.to_dict()
        save_games(self.cog.games)

        # The dice image carries the maths that produced it, and the
        # verdict follows in its own message. A message's attachments
        # always render *below* its content, so a verdict written into
        # this one would be read before the roll it is announcing.
        await interaction.response.edit_message(
            content=None,
            attachments=[dice_file],
            view=None,
        )
        await interaction.followup.send(f"{verdict}{set_up_note}")
        if scored:
            # The scorer, posted under the announcement -- its own
            # message rather than an attachment on it, which would put
            # the portrait above the "GOAL!" it belongs to.
            portrait = await asyncio.to_thread(
                render_player_portrait, shooter.name,
            )
            if portrait is not None:
                await interaction.followup.send(
                    file=discord.File(
                        portrait,
                        filename=f"{shooter.player_id}_goal.png",
                    ),
                )
        await self.cog.refresh_match_image(interaction, game)
        # Goal or miss, the ball is dead and being restarted, so this
        # is a new play and both restarts open a substitution window.
        await self.cog.begin_run_back(
            interaction,
            game,
            match,
            distance_moved=space_minutes,
            turnover_occurred=True,
            new_play=True,
        )


class LowPassChoiceView(SafeView):
    """
    Which teammate-occupied space to pass to -- Low Pass has no fixed
    distance anymore, only the nearest teammate each way within 2
    spaces and one sharing the ball's space, each of which must be a
    *different* player, so the destination is usually the whole choice.
    Where the space picked holds more than one teammate -- ordinary
    under a formation that stacks -- LowPassReceiverView asks which of
    them takes it. A handler with nobody in reach never sees either
    view: resolve_low_pass settles that case without a prompt.
    Reconstructible on restart purely from match state (see
    D12Ball.build_effect_choice_view), the same pattern every other
    persistent view in this cog follows.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game = cog.games.get(game_id)
        if game is None or game.match_state is None:
            return
        match = cog.load_match_state(game)

        for distance, teammate_id in cog.low_pass_candidates(match):
            teammate = cog.get_player_definition(teammate_id)
            origin_flat = match.board.flat_index(
                match.ball.zone, match.ball.space_index,
            )
            target_flat = match.relative_flat_index(
                origin_flat, match.ball.possession, distance,
            )
            zone, space_index = match.board.position_at_flat_index(
                target_flat,
            )
            receivers = cog.low_pass_receivers(match, distance)
            role_initial = ROLE_INITIALS[teammate.role.value]
            if len(receivers) > 1:
                # Naming one of several would misread the choice: the
                # space is what is being picked here, and who receives
                # comes next.
                label = (
                    f"{len(receivers)} players -- "
                    f"{space_label(zone, space_index)}"
                )
            else:
                label = (
                    f"{teammate.name} [{role_initial}] -- "
                    f"{space_label(zone, space_index)}"
                )
            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:low_pass:{game_id}:{distance}",
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_distance: int = distance,
            ) -> None:
                await self.choose(interaction, chosen_distance)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        distance: int,
    ) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return
        match = self.cog.load_match_state(game)

        if not self.cog.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        offense_side = match.ball.possession
        receivers = self.cog.low_pass_receivers(match, distance)
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        target_flat = match.relative_flat_index(
            origin_flat, offense_side, distance,
        )
        zone, space_index = match.board.position_at_flat_index(target_flat)
        team_name = match.setup_for_side(offense_side).team.value.title()

        if len(receivers) > 1:
            await interaction.response.edit_message(
                content=(
                    f"**{interaction.user.display_name} ({team_name})** is "
                    f"passing to {space_label(zone, space_index)}. Which "
                    "player receives it?"
                ),
                view=LowPassReceiverView(self.cog, self.game_id, distance),
            )
            return

        teammate = self.cog.get_player_definition(receivers[0])
        await interaction.response.edit_message(
            content=(
                f"**{interaction.user.display_name} ({team_name})** chose "
                "to pass the ball to "
                f"{format_role_bracket(teammate, self.cog.team_emojis)} at "
                f"{space_label(zone, space_index)}."
            ),
            view=None,
        )
        await self.cog.apply_low_pass(
            interaction, game, match, distance, receiver_id=receivers[0],
        )


class LowPassReceiverView(SafeView):
    """
    Which of the teammates on the destination space takes the pass.
    Only shown when more than one is standing there, which a formation
    that stacks makes ordinary; the pick decides who a Winger's set-up
    offers the shot to.

    Unlike LowPassChoiceView this cannot be rebuilt from match state
    alone -- the destination it belongs to is not written anywhere
    until the pass is applied -- so a restart mid-choice drops back to
    the destination prompt (see D12Ball.build_effect_choice_view).
    Nothing has been committed at that point.
    """

    def __init__(self, cog: "D12Ball", game_id: str, distance: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.distance = distance

        game = cog.games.get(game_id)
        if game is None or game.match_state is None:
            return
        match = cog.load_match_state(game)

        for player_id in cog.low_pass_receivers(match, distance):
            player = cog.get_player_definition(player_id)
            button = discord.ui.Button(
                label=(
                    f"{player.name} [{ROLE_INITIALS[player.role.value]}]"
                )[:80],
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:low_pass_receiver:{game_id}:"
                    f"{distance}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen: str = player_id,
            ) -> None:
                await self.choose(interaction, chosen)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        receiver_id: str,
    ) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return
        match = self.cog.load_match_state(game)

        if not self.cog.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        if receiver_id not in self.cog.low_pass_receivers(
            match, self.distance,
        ):
            await interaction.response.send_message(
                "That player is no longer standing there.",
                ephemeral=True,
            )
            return

        offense_side = match.ball.possession
        receiver = self.cog.get_player_definition(receiver_id)
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        zone, space_index = match.board.position_at_flat_index(
            match.relative_flat_index(origin_flat, offense_side, self.distance)
        )
        team_name = match.setup_for_side(offense_side).team.value.title()

        await interaction.response.edit_message(
            content=(
                f"**{interaction.user.display_name} ({team_name})** chose "
                "to pass the ball to "
                f"{format_role_bracket(receiver, self.cog.team_emojis)} at "
                f"{space_label(zone, space_index)}."
            ),
            view=None,
        )
        await self.cog.apply_low_pass(
            interaction, game, match, self.distance, receiver_id=receiver_id,
        )


class HighPassChoiceView(SafeView):
    """
    Distance for a won High Pass -- 2 or 3 spaces, or up to 4 for a
    Fullback (their ability extends the max, not the min).
    Reconstructible on restart purely from match state, the same
    pattern every other persistent view in this cog follows.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game = cog.games.get(game_id)
        if game is None or game.match_state is None:
            return
        match = cog.load_match_state(game)
        handler = cog.get_player_definition(match.active_player_id)
        max_distance = 4 if handler.role == PlayerRole.FULLBACK else 3

        for distance in range(2, max_distance + 1):
            ability_note = " (Fullback ability)" if distance == 4 else ""
            button = discord.ui.Button(
                label=f"{distance} spaces{ability_note}",
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:high_pass:{game_id}:{distance}",
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_distance: int = distance,
            ) -> None:
                await self.choose(interaction, chosen_distance)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        distance: int,
    ) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return
        match = self.cog.load_match_state(game)

        if not self.cog.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            content=f"Chose **{distance} spaces**.",
            view=None,
        )
        await self.cog.apply_high_pass(interaction, game, match, distance)


class SetUpAttemptChoiceView(SafeView):
    """
    Whether to take an offered scoring-opportunity shot -- a High
    Pass's own 2-space pass, or a Winger's Low Pass ability -- or let
    the maneuver resolve as a normal pass instead. Declining means the
    same thing either way since 2026-08-07, when a 2-space High Pass
    stopped forcing a contest for the ball it had just delivered.

    Not reconstructible on restart the way the rest of this cog's
    views are -- match state doesn't record which maneuver offered
    this choice or who the shooter is, the same narrow crash-window
    gap D12Ball.build_effect_choice_view already accepts for a
    Playmaker's Dribble Advance.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        shooter_id: str,
        distance_moved: int,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.shooter_id = shooter_id
        self.distance_moved = distance_moved

        shooter = cog.get_player_definition(shooter_id)
        attempt_button = discord.ui.Button(
            label=f"{shooter.name} takes the shot",
            style=discord.ButtonStyle.danger,
            custom_id=f"d12ball:setup_attempt:{game_id}:attempt",
        )
        attempt_button.callback = self.attempt
        self.add_item(attempt_button)

        decline_button = discord.ui.Button(
            label="Decline -- resolve as a normal pass",
            style=discord.ButtonStyle.secondary,
            custom_id=f"d12ball:setup_attempt:{game_id}:decline",
        )
        decline_button.callback = self.decline
        self.add_item(decline_button)

    async def attempt(self, interaction: discord.Interaction) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return
        match = self.cog.load_match_state(game)

        if not self.cog.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        shooter = self.cog.get_player_definition(self.shooter_id)
        await interaction.response.edit_message(
            content=(
                f"{format_role_bracket(shooter, self.cog.team_emojis)} "
                "takes the shot."
            ),
            view=None,
        )
        await self.cog.start_set_up_shot(
            interaction, game, match, self.shooter_id,
        )

    async def decline(self, interaction: discord.Interaction) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return
        match = self.cog.load_match_state(game)

        if not self.cog.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            content="Declined the scoring opportunity.",
            view=None,
        )
        await self.cog.decline_scoring_attempt(
            interaction, game, match, self.distance_moved,
        )


class DribbleAdvanceChoiceView(SafeView):
    """
    Playmaker-only: may advance 1 or 2 spaces on a won Dribble
    Advance. Every other role has no choice to make, so
    D12Ball.resolve_dribble_advance never even shows this.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        for distance in (1, 2):
            space_word = "space" if distance == 1 else "spaces"
            button = discord.ui.Button(
                label=f"Advance {distance} {space_word}",
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:dribble_advance:{game_id}:{distance}",
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_distance: int = distance,
            ) -> None:
                await self.choose(interaction, chosen_distance)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        distance: int,
    ) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return
        match = self.cog.load_match_state(game)

        if not self.cog.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        space_word = "space" if distance == 1 else "spaces"
        await interaction.response.edit_message(
            content=f"Chose **{distance} {space_word}**.",
            view=None,
        )
        await self.cog.apply_dribble_advance(interaction, game, match, distance)


class SpeedDeltaChoiceView(SafeView):
    """
    Ball-speed manipulation for Dribble Advance (offense skill) or
    Steal Intercept (defense skill, chosen by the intercepting player
    even though possession has already flipped to their side by the
    time this is shown -- `player_id` pins down whose skill and whose
    controller apply, sidestepping that ambiguity entirely).
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        player_id: str,
        skill_type: str,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.player_id = player_id
        self.skill_type = skill_type

        game = cog.games.get(game_id)
        if game is None or game.match_state is None:
            return
        match = cog.load_match_state(game)
        profile = cog.player_catalog.effective_profile(
            cog.get_player_definition(player_id),
        )
        skill = profile.offense if skill_type == "offense" else profile.defense
        current = match.ball.speed

        seen_targets: set[int] = set()
        for delta in range(-skill, skill + 1):
            target = max(1, min(12, current + delta))
            if target in seen_targets:
                continue
            seen_targets.add(target)

            actual_delta = target - current
            if actual_delta == 0:
                label = f"{target} (no change)"
            else:
                sign = "+" if actual_delta > 0 else ""
                label = f"{target} ({sign}{actual_delta})"

            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:speed:{game_id}:{target}",
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_target: int = target,
            ) -> None:
                await self.choose(interaction, chosen_target)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        target_speed: int,
    ) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return
        match = self.cog.load_match_state(game)

        controller_id = self.cog.controlling_user_id(
            game, match, self.player_id,
        )
        if interaction.user.id != controller_id:
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        # Steal Intercept has already flipped possession (and run the
        # defense back) by the time this view is shown; Dribble
        # Advance never triggers a turnover at all.
        turnover_occurred = match.defense_maneuver == "Steal Intercept" and (
            self.skill_type == "defense"
        )

        # No separate "chose speed N" confirmation -- apply_speed_choice's
        # own "Ball speed is now N" message says the same thing, so just
        # drop the buttons and let that be the one message.
        await interaction.response.edit_message(view=None)
        await self.cog.apply_speed_choice(
            interaction, game, match, target_speed,
            turnover_occurred=turnover_occurred,
        )


class ShooterChoiceView(SafeView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        candidates: list[str],
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        for player_id in candidates:
            player = cog.get_player_definition(player_id)
            initials = ROLE_INITIALS[player.role.value]
            button = discord.ui.Button(
                label=f"{player.name} [{initials}]",
                style=discord.ButtonStyle.danger,
                custom_id=f"d12ball:shooter:{game_id}:{player_id}",
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_player_id: str = player_id,
            ) -> None:
                await self.choose(interaction, chosen_player_id)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        shooter_id: str,
    ) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return
        match = self.cog.load_match_state(game)

        if not self.cog.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        shooter = self.cog.get_player_definition(shooter_id)
        await interaction.response.edit_message(
            content=(
                f"{format_role_bracket(shooter, self.cog.team_emojis)} "
                "takes the shot."
            ),
            view=None,
        )
        await self.cog.start_set_up_shot(interaction, game, match, shooter_id)


class RunBackChoiceView(SafeView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        player_id: str,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.player_id = player_id

        game = cog.games.get(game_id)
        if game is None or game.match_state is None:
            return
        match = cog.load_match_state(game)
        side = (
            TeamSide.HOME
            if player_id in match.home.field_players
            else TeamSide.VISITING
        )
        zone = match.setup_for_side(side).assigned_zone(player_id)

        for space_index in match.placement_spaces_in_zone(
            side, zone, player_id,
        ):
            button = discord.ui.Button(
                label=space_label(zone, space_index),
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:run_back:{game_id}:{player_id}:{space_index}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_space: int = space_index,
            ) -> None:
                await self.choose(interaction, chosen_space)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        space_index: int,
    ) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return
        match = self.cog.load_match_state(game)

        controller_id = self.cog.controlling_user_id(
            game, match, self.player_id,
        )
        if interaction.user.id != controller_id:
            await interaction.response.send_message(
                "Only that team's coach can choose this.",
                ephemeral=True,
            )
            return

        side = (
            TeamSide.HOME
            if self.player_id in match.home.field_players
            else TeamSide.VISITING
        )
        zone = match.setup_for_side(side).assigned_zone(self.player_id)

        try:
            distance = match.run_back_player(
                self.player_id, zone, space_index,
            )
        except ValueError as error:
            await interaction.response.send_message(
                str(error), ephemeral=True,
            )
            return

        exhaustion_text = self.cog.apply_exhaustion(
            match, self.player_id, distance,
        )
        game.match_state = match.to_dict()
        save_games(self.cog.games)

        player = self.cog.get_player_definition(self.player_id)
        await interaction.response.edit_message(
            content=(
                f"{format_role_bracket(player, self.cog.team_emojis)} "
                f"runs back to {space_label(zone, space_index)}."
                f"\n{exhaustion_text}"
            ),
            view=None,
        )
        await self.cog.refresh_match_image(interaction, game)
        await self.cog.continue_run_back(interaction, game, match)


class CoachingView(SafeView):
    """
    Shared plumbing for the Coaching Choice flow -- the four actions a
    coach may take at setup, at a new play's window, and at halftime,
    which are the same four every time. See "Coaching Choice" in
    docs/living-rules.md.

    **The whole flow lives on one message.** Every step edits it
    through `interaction.response.edit_message`, and nothing in the
    flow ever sends another. Two reasons:

    - It used to be a message per step, and a coach making two
      substitutions and a rearrangement put eight of them into the
      channel plus a board refresh apiece. See "Discord's rate limits"
      in CLAUDE.md: the fix for that is always fewer requests.
    - Only the newest message could be restored after a restart, but
      every older one kept a live view. A coach could scroll up and
      click a menu from three steps ago, and it would act on the
      current state.

    `interaction.response.edit_message` is the interaction-callback
    route, so unlike `channel.get_partial_message().edit()` it does not
    compete for the five-in-five bucket the board refresh spends.
    Passing no `attachments` leaves the image alone, so only a step
    that actually moved something re-uploads it.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

    def load(self) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            return None, None
        return game, self.cog.load_match_state(game)

    def side(self, match: MatchState) -> TeamSide:
        return TeamSide(match.pending_coaching_side)

    async def claim(
        self,
        interaction: discord.Interaction,
    ) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        """
        The game and match if this click is allowed to act on the open
        window, or (None, None) after replying with why it isn't.
        """
        game, match = self.load()
        if game is None or match is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return None, None
        if match.pending_coaching_side is None:
            await interaction.response.send_message(
                "That coaching window has already closed.",
                ephemeral=True,
            )
            return None, None
        if interaction.user.id != self.cog.side_controller_id(
            game, self.side(match),
        ):
            await interaction.response.send_message(
                "Only that team's coach can choose this.",
                ephemeral=True,
            )
            return None, None
        return game, match

    async def show(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        view: "CoachingView",
        note: str = "",
        moved: bool = False,
    ) -> None:
        """
        Put `view` up on the coaching message, with `note` under the
        heading. `moved` re-renders the half-field image; without it
        the attachment already there is left alone, which is most
        steps -- opening a submenu changes nothing on the board.
        """
        payload = {
            "content": self.cog.coaching_prompt(
                game, match, self.side(match), note,
            ),
            "view": view,
        }
        if moved:
            payload["attachments"] = [
                await self.cog.coaching_file(game, match, self.side(match))
            ]
        await interaction.response.edit_message(**payload)

    async def back_to_hub(
        self,
        interaction: discord.Interaction,
        note: str = "",
        moved: bool = False,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return
        await self.show(
            interaction,
            game,
            match,
            CoachingHubView(self.cog, self.game_id),
            note=note,
            moved=moved,
        )

    def add_back_button(self, row: Optional[int] = None) -> None:
        # Named for the view it sits on: a custom_id has to be unique
        # within its message, and every one of these steps puts its
        # Back button on the same message as the last.
        button = discord.ui.Button(
            label="Back",
            style=discord.ButtonStyle.secondary,
            custom_id=(
                f"d12ball:coach_back:{self.game_id}:"
                f"{type(self).__name__}"
            ),
            row=row,
        )

        async def callback(interaction: discord.Interaction) -> None:
            await self.back_to_hub(interaction)

        button.callback = callback
        self.add_item(button)

    def player_label(
        self,
        match: MatchState,
        player_id: str,
        with_space: bool = False,
    ) -> str:
        """
        A fielded player on a button: who they are, and where they are.
        Both matter to every choice in this flow and neither is on the
        button otherwise.
        """
        setup = match.setup_for_side(self.side(match))
        zone = setup.assigned_zone(player_id)
        where = destination_display_name(zone.value)
        if with_space:
            position = match.board.meeple_position(player_id)
            where = space_label(*position) if position else where
        return f"{self.cog.format_roster_player(player_id)} - {where}"[:80]


class CoachingOfferView(CoachingView):
    """
    Declare-or-pass, for the side a new play has just handed the window
    to. Only a new play asks: setup and halftime are given rather than
    declared, so both open straight onto the hub.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(cog, game_id)

        declare = discord.ui.Button(
            label="Coach",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:coach_declare:{game_id}",
        )
        declare.callback = self.declare
        self.add_item(declare)

        # Passing is always on offer -- nothing forces a declaration,
        # an injured player included.
        decline = discord.ui.Button(
            label="Pass",
            style=discord.ButtonStyle.secondary,
            custom_id=f"d12ball:coach_pass:{game_id}",
        )
        decline.callback = self.decline
        self.add_item(decline)

    async def declare(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        match.declare_coaching()
        game.match_state = match.to_dict()
        save_games(self.cog.games)

        # No attachments: the offer this replaces already carried the
        # image, and taking the window up moves nobody.
        await self.show(
            interaction,
            game,
            match,
            CoachingHubView(self.cog, self.game_id),
        )

    async def decline(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        setup = match.setup_for_side(self.side(match))
        await interaction.response.edit_message(
            content=(
                f"# Coaching Choice\n**{interaction.user.display_name} "
                f"({setup.team.value.title()}) passed.**"
            ),
            view=None,
        )
        await self.cog.finish_substitution_window(interaction, game, match)


class CoachingHubView(CoachingView):
    """
    The six buttons a Coaching Choice offers. Each opens its own menu
    on this same message and every one of those comes back here.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(cog, game_id)

        game, match = self.load()
        if match is None or match.pending_coaching_side is None:
            return
        side = self.side(match)

        formation = cog.current_formation(match, side)
        # The shape in brackets is the one they are in now, not the one
        # the button switches to, so it says so -- a bare "(2-2-2)"
        # reads as the destination.
        self.add_action(
            "Formation"
            + (f" (currently {formation.value})" if formation else ""),
            f"d12ball:coach_formation:{game_id}",
            self.open_formation,
        )
        self.add_action(
            f"Substitution ({cog.substitution_button_label(match)})",
            f"d12ball:coach_sub:{game_id}",
            self.open_substitution,
            enabled=match.may_substitute()
            and any(
                match.substitution_pool(side, player_id)
                for player_id in match.setup_for_side(side).field_players
            ),
        )
        self.add_action(
            "Zone Assignment",
            f"d12ball:coach_zone:{game_id}",
            self.open_zone_assignment,
        )
        self.add_action(
            "Space Positioning",
            f"d12ball:coach_space:{game_id}",
            self.open_space_positioning,
            row=1,
        )
        self.add_action(
            "Team roster",
            f"d12ball:coach_roster:{game_id}",
            self.show_roster,
            row=1,
            style=discord.ButtonStyle.secondary,
        )
        self.add_action(
            "Done coaching",
            f"d12ball:coach_done:{game_id}",
            self.finish,
            row=1,
            style=discord.ButtonStyle.success,
        )

    def add_action(
        self,
        label: str,
        custom_id: str,
        callback,
        row: int = 0,
        enabled: bool = True,
        style: discord.ButtonStyle = discord.ButtonStyle.primary,
    ) -> None:
        button = discord.ui.Button(
            label=label[:80],
            style=style if enabled else discord.ButtonStyle.secondary,
            custom_id=custom_id,
            row=row,
            disabled=not enabled,
        )
        button.callback = callback
        self.add_item(button)

    async def open_formation(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return
        await self.show(
            interaction,
            game,
            match,
            CoachingFormationView(self.cog, self.game_id),
            note=(
                "Which formation? The numbers read from your own goal "
                "forward. Changing shape re-deals your six by defensive "
                "skill, best defenders furthest back -- move anyone you "
                "want elsewhere afterwards."
            ),
        )

    async def open_substitution(
        self,
        interaction: discord.Interaction,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return
        await self.show(
            interaction,
            game,
            match,
            CoachingSubstitutionOutView(self.cog, self.game_id),
            note="Who comes off?",
        )

    async def open_zone_assignment(
        self,
        interaction: discord.Interaction,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return
        await self.show(
            interaction,
            game,
            match,
            CoachingZoneView(self.cog, self.game_id),
            note=(
                "Which two change places? Their meeples move with them, "
                "so the shape is unchanged."
            ),
        )

    async def open_space_positioning(
        self,
        interaction: discord.Interaction,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return
        await self.show(
            interaction,
            game,
            match,
            CoachingPlaceView(self.cog, self.game_id),
            note="Whose meeple moves?",
        )

    async def show_roster(self, interaction: discord.Interaction) -> None:
        # Deliberately not gated on claim(): reading a roster is not
        # acting on the window, so the coach who is waiting on the
        # other side can look too. Answers privately, so the coaching
        # message stays where it is.
        game, match = self.load()
        if game is None or match is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        setups = self.cog.roster_setups_for_user(
            game, match, interaction.user.id,
        )
        if setups is None:
            await interaction.response.send_message(
                "You are not one of the players in this game. Use "
                "/team_roster with all_teams:true to see both rosters.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "\n\n".join(
                self.cog.build_team_roster_section(match, setup)
                for setup in setups
            ),
            ephemeral=True,
        )

    async def finish(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        side = self.side(match)
        refusal = self.cog.coaching_finish_refusal(match, side)
        if refusal is not None:
            await interaction.response.send_message(refusal, ephemeral=True)
            return

        setup = match.setup_for_side(side)
        await interaction.response.edit_message(
            content=(
                f"# Coaching Choice\n**{format_team_side_label(setup)} "
                "are done.**"
            ),
            view=None,
        )
        await self.cog.finish_substitution_window(interaction, game, match)


class CoachingFormationView(CoachingView):
    """
    Pick a shape. Applying it re-deals the whole side by defensive
    skill and places every meeple, so this is one click rather than the
    six it used to take -- see D12Ball.formation_placement.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(cog, game_id)

        game, match = self.load()
        if match is None or match.pending_coaching_side is None:
            return
        current = cog.current_formation(match, self.side(match))

        for choice in Formation:
            button = discord.ui.Button(
                label=(
                    f"{choice.value}"
                    + (" (current)" if choice == current else "")
                ),
                style=(
                    discord.ButtonStyle.secondary
                    if choice == current
                    else discord.ButtonStyle.primary
                ),
                custom_id=(
                    f"d12ball:coach_formation_pick:{game_id}:{choice.value}"
                ),
                # Picking the shape you are already in changes nothing,
                # and re-dealing would shuffle a coach's own
                # arrangement out from under them.
                disabled=choice == current,
            )

            async def callback(
                interaction: discord.Interaction,
                picked: Formation = choice,
            ) -> None:
                await self.choose(interaction, picked)

            button.callback = callback
            self.add_item(button)

        self.add_back_button(row=1)

    async def choose(
        self,
        interaction: discord.Interaction,
        formation: Formation,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        try:
            note = self.cog.apply_formation(
                match, self.side(match), formation,
            )
        except ValueError as error:
            await interaction.response.send_message(
                str(error), ephemeral=True,
            )
            return

        game.match_state = match.to_dict()
        save_games(self.cog.games)
        await self.back_to_hub(interaction, note=note, moved=True)


class CoachingSubstitutionOutView(CoachingView):
    """Who comes off. Injured players are marked."""

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(cog, game_id)

        game, match = self.load()
        if match is None or match.pending_coaching_side is None:
            return
        side = self.side(match)

        for player_id in match.setup_for_side(side).field_players:
            if not match.substitution_pool(side, player_id):
                continue
            injured = player_id in match.injured
            button = discord.ui.Button(
                label=(
                    f"{self.player_label(match, player_id)}"
                    f"{' - injured' if injured else ''}"
                )[:80],
                style=(
                    discord.ButtonStyle.danger
                    if injured
                    else discord.ButtonStyle.secondary
                ),
                custom_id=f"d12ball:coach_sub_off:{game_id}:{player_id}",
            )

            async def callback(
                interaction: discord.Interaction,
                outgoing: str = player_id,
            ) -> None:
                await self.choose(interaction, outgoing)

            button.callback = callback
            self.add_item(button)

        self.add_back_button(row=4)

    async def choose(
        self,
        interaction: discord.Interaction,
        outgoing_player_id: str,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        player = self.cog.get_player_definition(outgoing_player_id)
        await self.show(
            interaction,
            game,
            match,
            CoachingSubstitutionInView(
                self.cog, self.game_id, outgoing_player_id,
            ),
            note=(
                "Who comes on for "
                f"{format_role_bracket(player, self.cog.team_emojis)}? "
                "They take their zone and their space exactly."
            ),
        )


class CoachingSubstitutionInView(CoachingView):
    """Who comes on for the player just taken off."""

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        outgoing_player_id: str,
    ):
        super().__init__(cog, game_id)
        self.outgoing_player_id = outgoing_player_id

        game, match = self.load()
        if match is None or match.pending_coaching_side is None:
            return

        for player_id in match.substitution_pool(
            self.side(match), outgoing_player_id,
        ):
            button = discord.ui.Button(
                label=cog.format_roster_player(player_id)[:80],
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:coach_sub_on:{game_id}:{player_id}",
            )

            async def callback(
                interaction: discord.Interaction,
                incoming: str = player_id,
            ) -> None:
                await self.choose(interaction, incoming)

            button.callback = callback
            self.add_item(button)

        self.add_back_button(row=4)

    async def choose(
        self,
        interaction: discord.Interaction,
        incoming_player_id: str,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        try:
            note = self.cog.apply_substitution(
                match,
                self.side(match),
                self.outgoing_player_id,
                incoming_player_id,
            )
        except ValueError as error:
            await interaction.response.send_message(
                str(error), ephemeral=True,
            )
            return

        game.match_state = match.to_dict()
        save_games(self.cog.games)
        await self.back_to_hub(interaction, note=note, moved=True)


class CoachingZoneView(CoachingView):
    """
    Exchange two players' zones. Picking the first re-renders with
    everyone in a *different* zone as the second pick -- an exchange
    inside one zone would change nothing about the assignment, and
    moving a meeple within its zone is what space positioning is for.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        first_player_id: Optional[str] = None,
    ):
        super().__init__(cog, game_id)
        self.first_player_id = first_player_id

        game, match = self.load()
        if match is None or match.pending_coaching_side is None:
            return
        setup = match.setup_for_side(self.side(match))
        first_zone = (
            setup.assigned_zone(first_player_id)
            if first_player_id
            else None
        )

        for player_id in setup.field_players:
            if player_id == first_player_id:
                continue
            if (
                first_zone is not None
                and setup.assigned_zone(player_id) == first_zone
            ):
                continue
            button = discord.ui.Button(
                label=self.player_label(match, player_id),
                style=discord.ButtonStyle.secondary,
                custom_id=f"d12ball:coach_zone_pick:{game_id}:{player_id}",
            )

            async def callback(
                interaction: discord.Interaction,
                picked: str = player_id,
            ) -> None:
                await self.pick(interaction, picked)

            button.callback = callback
            self.add_item(button)

        self.add_back_button(row=4)

    async def pick(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        if self.first_player_id is None:
            player = self.cog.get_player_definition(player_id)
            await self.show(
                interaction,
                game,
                match,
                CoachingZoneView(self.cog, self.game_id, player_id),
                note=(
                    "Who does "
                    f"{format_role_bracket(player, self.cog.team_emojis)} "
                    "change places with?"
                ),
            )
            return

        try:
            note = self.cog.apply_position_swap(
                match, self.side(match), self.first_player_id, player_id,
            )
        except ValueError as error:
            await interaction.response.send_message(
                str(error), ephemeral=True,
            )
            return

        game.match_state = match.to_dict()
        save_games(self.cog.games)
        await self.back_to_hub(interaction, note=note, moved=True)


class CoachingPlaceView(CoachingView):
    """Whose meeple moves, within its own assigned zone."""

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(cog, game_id)

        game, match = self.load()
        if match is None or match.pending_coaching_side is None:
            return

        for player_id in match.setup_for_side(
            self.side(match),
        ).field_players:
            button = discord.ui.Button(
                label=self.player_label(match, player_id, with_space=True),
                style=discord.ButtonStyle.secondary,
                custom_id=f"d12ball:coach_place:{game_id}:{player_id}",
            )

            async def callback(
                interaction: discord.Interaction,
                picked: str = player_id,
            ) -> None:
                await self.choose(interaction, picked)

            button.callback = callback
            self.add_item(button)

        self.add_back_button(row=4)

    async def choose(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        player = self.cog.get_player_definition(player_id)
        await self.show(
            interaction,
            game,
            match,
            CoachingPlaceSpaceView(self.cog, self.game_id, player_id),
            note=(
                "Where should "
                f"{format_role_bracket(player, self.cog.team_emojis)} "
                "stand? A space one of your own is already on trades "
                "places with them."
            ),
        )


class CoachingPlaceSpaceView(CoachingView):
    """
    Which space in their own zone. **Every space is offered**, because
    the trade rule keeps coverage satisfied whichever one is picked --
    see MatchState.position_meeple.
    """

    def __init__(self, cog: "D12Ball", game_id: str, player_id: str):
        super().__init__(cog, game_id)
        self.player_id = player_id

        game, match = self.load()
        if match is None or match.pending_coaching_side is None:
            return
        side = self.side(match)
        zone = match.setup_for_side(side).assigned_zone(player_id)
        position = match.board.meeple_position(player_id)
        team_players = set(match.setup_for_side(side).field_players)

        for space_index in range(len(match.board.spaces[zone])):
            if position == (zone, space_index):
                continue
            here = [
                occupant
                for occupant in match.board.spaces[zone][space_index]
                if occupant in team_players
            ]
            button = discord.ui.Button(
                label=(
                    space_label(zone, space_index)
                    + (f" - {len(here)} of yours" if here else " - free")
                ),
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:coach_place_space:{game_id}:"
                    f"{player_id}:{space_index}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen: int = space_index,
            ) -> None:
                await self.choose(interaction, chosen)

            button.callback = callback
            self.add_item(button)

        self.add_back_button(row=4)

    async def choose(
        self,
        interaction: discord.Interaction,
        space_index: int,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        side = self.side(match)
        candidates = match.positioning_swap_candidates(
            side, self.player_id, space_index,
        )
        if len(candidates) > 1:
            player = self.cog.get_player_definition(self.player_id)
            await self.show(
                interaction,
                game,
                match,
                CoachingPlaceSwapView(
                    self.cog, self.game_id, self.player_id, space_index,
                ),
                note=(
                    "More than one of yours is standing there. Who "
                    "comes back to make room for "
                    f"{format_role_bracket(player, self.cog.team_emojis)}?"
                ),
            )
            return

        await apply_positioning(
            self, interaction, game, match, self.player_id, space_index,
        )


async def apply_positioning(
    view: CoachingView,
    interaction: discord.Interaction,
    game: D12BallGame,
    match: MatchState,
    player_id: str,
    space_index: int,
    swap_with: Optional[str] = None,
) -> None:
    """
    Make a space-positioning move and go back to the hub. Shared by the
    two views that can arrive at one: the space pick, and the extra
    pick a stacked target needs.
    """
    try:
        note = view.cog.apply_reposition(
            match,
            view.side(match),
            player_id,
            space_index,
            swap_with=swap_with,
        )
    except ValueError as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return

    game.match_state = match.to_dict()
    save_games(view.cog.games)
    await view.back_to_hub(interaction, note=note, moved=True)


class CoachingPlaceSwapView(CoachingView):
    """
    Which of several teammates on the target space comes back. Only
    reachable where a zone is stacked, which on the three basic shapes
    means board 6's two-space midfield.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        player_id: str,
        space_index: int,
    ):
        super().__init__(cog, game_id)
        self.player_id = player_id
        self.space_index = space_index

        game, match = self.load()
        if match is None or match.pending_coaching_side is None:
            return

        for other_id in match.positioning_swap_candidates(
            self.side(match), player_id, space_index,
        ):
            button = discord.ui.Button(
                label=self.cog.format_roster_player(other_id)[:80],
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:coach_place_swap:{game_id}:{other_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                picked: str = other_id,
            ) -> None:
                await self.choose(interaction, picked)

            button.callback = callback
            self.add_item(button)

        self.add_back_button(row=4)

    async def choose(
        self,
        interaction: discord.Interaction,
        other_player_id: str,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return
        await apply_positioning(
            self,
            interaction,
            game,
            match,
            self.player_id,
            self.space_index,
            swap_with=other_player_id,
        )


class HalftimeView(SafeView):
    """
    Shared plumbing for the halftime flow's per-side prompts: they
    only accept a click from the side currently on the clock, at
    the stage that offered them -- see D12Ball.advance_halftime_stage.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        side: TeamSide,
        stage: str,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.side = side
        self.stage = stage

    def load(self) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            return None, None
        return game, self.cog.load_match_state(game)

    async def claim(
        self,
        interaction: discord.Interaction,
    ) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        game, match = self.load()
        if game is None or match is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return None, None
        if match.pending_halftime_stage != self.stage:
            await interaction.response.send_message(
                "That halftime step has already finished.",
                ephemeral=True,
            )
            return None, None
        if interaction.user.id != self.cog.side_controller_id(game, self.side):
            await interaction.response.send_message(
                "Only that team's coach can choose this.",
                ephemeral=True,
            )
            return None, None
        return game, match


class HalftimeExtraTokenView(HalftimeView):
    """
    Halftime: each side picks one of their own fielded players to lose
    an extra exhaustion token, on top of the automatic recovery every
    fielded player already got in begin_halftime.
    """

    def __init__(self, cog: "D12Ball", game_id: str, side: TeamSide):
        super().__init__(cog, game_id, side, f"extra_token_{side.value}")

        game, match = self.load()
        if match is None or match.pending_halftime_stage != self.stage:
            return
        setup = match.setup_for_side(side)

        for player_id in setup.field_players:
            if player_id in match.injured:
                continue
            tokens = match.exhaustion.get(player_id, 0)
            label = f"{cog.format_roster_player(player_id)} ({tokens})"
            button = discord.ui.Button(
                label=label[:80],
                style=discord.ButtonStyle.secondary,
                custom_id=(
                    f"d12ball:halftime_extra_token:{game_id}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                picked: str = player_id,
            ) -> None:
                await self.choose(interaction, picked)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        player = self.cog.get_player_definition(player_id)
        defense_skill = self.cog.player_catalog.effective_profile(
            player
        ).defense
        removed = match.recover_exhaustion(player_id, 1, defense_skill)
        self.cog.next_halftime_stage(match)
        game.match_state = match.to_dict()
        save_games(self.cog.games)

        remaining = match.exhaustion.get(player_id, 0)
        text = (
            f"{format_role_bracket(player, self.cog.team_emojis)} loses "
            f"an extra exhaustion token (now {remaining})."
            if removed
            else (
                f"{format_role_bracket(player, self.cog.team_emojis)} "
                "had no tokens to lose."
            )
        )
        await interaction.response.edit_message(content=text, view=None)
        await self.cog.refresh_match_image(interaction, game)
        await self.cog.advance_halftime_stage(interaction, game, match)


class LooseBallChoiceView(SafeView):
    """
    Who one side sends after a loose ball, plus the option of sending
    nobody.

    One side at a time, the team that last had possession first: they
    are the ones losing the ball, and offering both at once let
    whoever clicked second answer the first's pick. Once this side
    settles, the cog rebuilds the prompt for the other.

    "Send nobody" is a real move, not a way out of the prompt -- with
    neither side contesting, the ball goes out of bounds and the side
    that last held it loses it (see resolve_loose_ball). It is
    offered even when there's only one candidate, which is why a lone
    candidate isn't auto-picked the way a forced run back is.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        side: str,
        candidates: list[str],
        match: MatchState,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.side = side

        ball_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )

        for player_id in candidates:
            player = cog.get_player_definition(player_id)
            initials = ROLE_INITIALS[player.role.value]
            zone, space_index = match.board.meeple_position(player_id)
            distance = abs(
                match.board.flat_index(zone, space_index) - ball_flat
            )
            space_word = "space" if distance == 1 else "spaces"
            location_note = (
                f"({space_label(zone, space_index)}, {distance} "
                f"{space_word} from the ball)"
            )
            button = discord.ui.Button(
                label=f"{player.name} [{initials}] {location_note}",
                style=(
                    discord.ButtonStyle.primary
                    if side == "offense"
                    else discord.ButtonStyle.danger
                ),
                custom_id=(
                    f"d12ball:loose_ball:{game_id}:{side}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_player_id: str = player_id,
            ) -> None:
                await self.choose(interaction, chosen_player_id)

            button.callback = callback
            self.add_item(button)

        decline = discord.ui.Button(
            label="Send nobody",
            style=discord.ButtonStyle.secondary,
            custom_id=f"d12ball:loose_ball_decline:{game_id}:{side}",
            row=4,
        )
        decline.callback = self.decline
        self.add_item(decline)

    async def claim(
        self,
        interaction: discord.Interaction,
    ) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        """The game and match if this click may settle this side's
        pick, or (None, None) after replying with why it may not."""
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return None, None
        match = self.cog.load_match_state(game)

        if self.cog.loose_ball_side_on_the_clock(match) != self.side:
            await interaction.response.send_message(
                "That side has already answered.",
                ephemeral=True,
            )
            return None, None

        authorized = (
            self.cog.user_controls_possession(
                interaction.user.id, game, match,
            )
            if self.side == "offense"
            else self.cog.user_controls_defense(
                interaction.user.id, game, match,
            )
        )
        if not authorized:
            await interaction.response.send_message(
                "Only the player on that side can choose.",
                ephemeral=True,
            )
            return None, None
        return game, match

    async def choose(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        if self.side == "offense":
            match.choose_loose_ball_offense_player(player_id)
        else:
            match.choose_loose_ball_defense_player(player_id)

        player = self.cog.get_player_definition(player_id)
        await self.settled(
            interaction,
            game,
            match,
            f"{format_role_bracket(player, self.cog.team_emojis)} "
            f"contests the {contest_noun(match)} ({self.side}).",
        )

    async def decline(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        side = (
            match.ball.possession
            if self.side == "offense"
            else match.defending_side()
        )
        match.decline_loose_ball(side)
        await self.settled(
            interaction,
            game,
            match,
            f"{format_team_side_label(match.setup_for_side(side))} send "
            f"nobody after the {contest_noun(match)}.",
        )

    async def settled(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        announcement: str,
    ) -> None:
        """Save this side's answer, then either put the prompt up for
        the other side or resolve."""
        game.match_state = match.to_dict()
        save_games(self.cog.games)

        await interaction.response.edit_message(
            content=announcement, view=None,
        )

        if self.cog.loose_ball_side_on_the_clock(match) is None:
            await self.cog.resolve_loose_ball(interaction, game, match)
            return

        prompt_message = await interaction.followup.send(
            self.cog.build_loose_ball_prompt(game, match),
            view=self.cog.build_loose_ball_view(self.game_id, match),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.cog.games)


class BallRecoveryView(SafeView):
    """
    Which fielded player goes and picks up an out-of-bounds ball,
    offered to the side that won it once the run back is done -- any
    of them, from anywhere on the field, at one exhaustion token per
    space traveled (see D12Ball.begin_ball_recovery).
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game = cog.games.get(game_id)
        if game is None or game.match_state is None:
            return
        match = cog.load_match_state(game)
        side = match.ball.possession

        for player_id in match.setup_for_side(side).field_players:
            player = cog.get_player_definition(player_id)
            initials = ROLE_INITIALS[player.role.value]
            distance = match.distance_to_ball(player_id)
            space_word = "space" if distance == 1 else "spaces"
            button = discord.ui.Button(
                label=(
                    f"{player.name} [{initials}] ({distance} {space_word} "
                    "away)"
                )[:80],
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:ball_recovery:{game_id}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_player_id: str = player_id,
            ) -> None:
                await self.choose(interaction, chosen_player_id)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return
        match = self.cog.load_match_state(game)

        if not match.pending_ball_recovery:
            await interaction.response.send_message(
                "The ball has already been picked up.",
                ephemeral=True,
            )
            return
        if not self.cog.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the side that won the ball can choose.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(view=None)
        await self.cog.apply_ball_recovery(
            interaction, game, match, player_id,
        )


class LooseBallSkillTestView(SafeView):
    """
    The roll that settles a loose ball -- or a High Pass, which runs
    the same contest for an entirely different reason (see
    contest_noun). The custom_id stays `loose_ball_test` either way,
    since it's what already-posted messages are keyed on.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game = cog.games.get(game_id)
        noun = "loose ball"
        if game is not None and game.match_state is not None:
            noun = contest_noun(cog.load_match_state(game))

        button = discord.ui.Button(
            label=f"Roll for the {noun}",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:loose_ball_test:{game_id}",
        )
        button.callback = self.roll
        self.add_item(button)

    async def roll(self, interaction: discord.Interaction) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        match = self.cog.load_match_state(game)
        if (
            not match.pending_loose_ball
            or match.loose_ball_offense_player is None
            or match.loose_ball_defense_player is None
        ):
            await interaction.response.send_message(
                f"This {contest_noun(match)} is no longer active.",
                ephemeral=True,
            )
            return

        participant_ids = {game.player_1_id}
        if game.player_2_id is not None:
            participant_ids.add(game.player_2_id)
        if interaction.user.id not in participant_ids:
            await interaction.response.send_message(
                "Only a player in this game can roll for the "
                f"{contest_noun(match)}.",
                ephemeral=True,
            )
            return

        offense_player = self.cog.get_player_definition(
            match.loose_ball_offense_player,
        )
        defense_player = self.cog.get_player_definition(
            match.loose_ball_defense_player,
        )
        # An injured contestant adds no skill modifier -- their own
        # offensive or defensive skill stays off the roll, and that is
        # the whole of the disadvantage here (see "Injured players" in
        # docs/living-rules.md). It is only the skill: every other
        # modifier still applies, which is why the ball speed modifier
        # below is added without asking about injury.
        offense_injured = match.loose_ball_offense_player in match.injured
        defense_injured = match.loose_ball_defense_player in match.injured
        offense_skill = (
            0
            if offense_injured
            else self.cog.player_catalog.effective_profile(
                offense_player,
            ).offense
        )
        defense_skill = (
            0
            if defense_injured
            else self.cog.player_catalog.effective_profile(
                defense_player,
            ).defense
        )

        offense_roll = random.randint(1, 12)
        defense_roll = random.randint(1, 12)
        offense_total = offense_roll + offense_skill
        defense_total = defense_roll + defense_skill

        # A High Pass's receiver adds the ball speed modifier to keep
        # what the pass delivered (2026-08-07). A genuine loose ball is
        # nobody's yet, so neither side gets it there.
        modifier_detail = []
        if match.pending_loose_ball_is_high_pass:
            modifier = match.ball.speed // 2
            offense_total += modifier
            modifier_detail = [f"+{modifier} ball speed modifier"]

        # No text breakdown alongside: the dice image already names
        # both players and shows every modifier that built the totals.
        dice_file = discord.File(
            await asyncio.to_thread(
                render_skill_test_dice,
                [
                    (
                        offense_roll,
                        TEAM_COLORS[offense_player.team],
                        offense_player.team.value.title(),
                        [
                            f"{offense_player.name} "
                            f"[{ROLE_INITIALS[offense_player.role.value]}]",
                            "Injured — no skill modifier"
                            if offense_injured
                            else f"Offensive skill +{offense_skill}",
                        ] + modifier_detail,
                        offense_total,
                    ),
                    (
                        defense_roll,
                        TEAM_COLORS[defense_player.team],
                        defense_player.team.value.title(),
                        [
                            f"{defense_player.name} "
                            f"[{ROLE_INITIALS[defense_player.role.value]}]",
                            "Injured — no skill modifier"
                            if defense_injured
                            else f"Defensive skill +{defense_skill}",
                        ],
                        defense_total,
                    ),
                ]
            ),
            filename="loose_ball_dice.png",
        )

        if offense_total == defense_total:
            # As in SkillTestView: the re-roll's token counts towards
            # Exhausted now, so it is in force for the injury checks
            # this contest hands out once it resolves.
            exhaustion_text = "\n".join(
                [
                    self.cog.apply_exhaustion(
                        match, match.loose_ball_offense_player, 1,
                    ),
                    self.cog.apply_exhaustion(
                        match, match.loose_ball_defense_player, 1,
                    ),
                ]
            )
            game.match_state = match.to_dict()
            save_games(self.cog.games)

            await interaction.response.edit_message(
                content=(
                    f"**It's a tie ({offense_total}-{defense_total})!** "
                    f"The skill test must be rolled again.\n"
                    f"{exhaustion_text}\n\nRoll again:"
                ),
                attachments=[dice_file],
                view=LooseBallSkillTestView(self.cog, self.game_id),
            )
            await self.cog.refresh_match_image(interaction, game)
            return

        outcome = "offense" if offense_total > defense_total else "defense"
        winner_side = (
            match.ball.possession
            if outcome == "offense"
            else match.defending_side()
        )
        turnover_occurred = winner_side != match.ball.possession
        winner_number = (
            self.cog.possession_player_number(game, match)
            if outcome == "offense"
            else self.cog.defending_player_number(game, match)
        )
        winner_mention = format_player_with_team(
            game, winner_number, mention=True,
        )
        winner_player = (
            offense_player if outcome == "offense" else defense_player
        )

        exhausted_participants = [
            player
            for player in (offense_player, defense_player)
            if player.player_id in match.exhausted
        ]
        distance_moved = match.pending_loose_ball_distance
        is_high_pass = match.pending_loose_ball_is_high_pass

        match.ball.possession = winner_side
        if turnover_occurred:
            match.ball.speed = 1
        match.pending_loose_ball = False
        match.loose_ball_offense_player = None
        match.loose_ball_defense_player = None
        game.match_state = match.to_dict()
        save_games(self.cog.games)

        turnover_line = "# Turnover!\n\n" if turnover_occurred else ""
        winner_bracket = format_role_bracket(
            winner_player, self.cog.team_emojis,
        )
        if is_high_pass:
            outcome_line = (
                f"{winner_bracket} wins possession off the high pass! "
                f"{winner_mention} has possession."
                if turnover_occurred
                else f"{winner_bracket} keeps possession after the high "
                f"pass! {winner_mention} has possession."
            )
        else:
            outcome_line = (
                f"{winner_bracket} wins the loose ball! {winner_mention} "
                "has possession."
            )
        # The result follows the dice in its own message, the way every
        # other skill test announces itself -- a message's attachments
        # render below its content, so writing the outcome into this
        # one would put it above the roll that decided it. The tie
        # above is the exception, since that message carries the
        # roll-again button. See SkillTestView.roll.
        await interaction.response.edit_message(
            content=None,
            attachments=[dice_file],
            view=None,
        )
        await interaction.followup.send(
            f"{turnover_line}{outcome_line}",
            # The edit this replaced never pinged the winner, and the
            # prompt that follows does; one ping per turn is plenty.
            allowed_mentions=discord.AllowedMentions(
                users=False, roles=False, everyone=False,
            ),
        )
        await self.cog.refresh_match_image(interaction, game)

        for player in exhausted_participants:
            await self.cog.run_injury_test(interaction, game, match, player)

        # Winning a live ball off the other side -- a loose ball or a
        # long High Pass -- is a steal however it was contested, so no
        # substitution window either way.
        await self.cog.begin_run_back(
            interaction, game, match,
            distance_moved=distance_moved,
            turnover_occurred=turnover_occurred,
        )



"""
Setup: team selection, game settings, the coin toss, the
home-or-visiting choice, and the rematch offer at full time. The
pre-game lobby that now precedes all of this is in `lobby.py`.
"""

import aiohttp
import discord
import random
from typing import Optional, TYPE_CHECKING

from d12ball import tutorial
from d12ball.game import (
    AIOpponent,
    COLOR_TEAMS,
    CoinFace,
    D12BallGame,
    GameMode,
    GameStatus,
    HomeChoice,
    SPECIES_TEAMS,
    Team,
    paired_team,
    team_display_name,
)
from d12ball.render import TEAM_COLORS
from gamesaves.d12ball.storage import save_games
from cogs.d12ball_helpers import (
    ADVANCED_MODULES,
    AI_OPPONENT_NAMES,
    LOGGER,
    advanced_module_label,
    build_full_image_button,
    build_home_choice_message,
    build_setup_message,
    format_coin_emoji,
    format_player,
    format_player_with_team,
    is_game_helper,
    refresh_player_names,
    toggle_advanced_module,
)

from cogs.d12ball_views.base import SafeView

if TYPE_CHECKING:
    from cogs.d12ball import D12Ball


class GameConfigurationView(SafeView):
    def configuration_start_row(
        self,
        game: Optional[D12BallGame],
    ) -> int:
        """
        The action row the settings block starts on. A view that puts
        its own buttons above the settings (team selection) overrides
        this. Discord only gives us five rows and the block is up to
        three of them -- mode, board size, and, for a solo game, the
        AI opponent -- so there is little room to spare.
        """
        return 0

    def add_configuration_buttons(self) -> None:
        game = self.cog.games.get(self.game_id)
        selected_mode = game.mode if game else GameMode.BASIC
        selected_board_size = game.board_size if game else 7
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

        # The two halves of advanced mode ride on the mode row, since
        # they are what narrows the switch beside them -- and only when
        # it is switched on, because a basic game plays neither and a
        # pair of dead buttons says nothing a coach can act on. Four
        # buttons of Discord's five, so the row still has room.
        if selected_mode == GameMode.ADVANCED:
            for module_key in ADVANCED_MODULES:
                field, _ = ADVANCED_MODULES[module_key]
                button = discord.ui.Button(
                    label=advanced_module_label(game, module_key),
                    style=(
                        discord.ButtonStyle.success
                        if getattr(game, field)
                        else discord.ButtonStyle.secondary
                    ),
                    custom_id=(
                        f"d12ball:module:{self.game_id}:{module_key}"
                    ),
                    disabled=configuration_closed,
                    row=first_row,
                )

                async def module_callback(
                    interaction: discord.Interaction,
                    module_key: str = module_key,
                ) -> None:
                    await self.select_module(interaction, module_key)

                button.callback = module_callback
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
                row=first_row + 2,
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

        if not self.may_act_in_game(interaction, game):
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

        # **Advanced mode is one switch over two modules** -- the
        # second set of maneuvers and the species abilities -- and
        # picking it here brings both. Which of them a game actually
        # plays is the pair of toggles beside these buttons; a coach
        # who wants neither picks Basic. The two are deliberately left
        # as they are when the mode goes back to Basic, so a mis-click
        # on the mode does not undo them.
        game.mode = selected_mode

        # Advanced mode's extra maneuvers need the room a nine-space
        # board gives them, so picking it defaults the board size to 9
        # -- a coach may still pick 6 or 7 afterwards, and the setup
        # message keeps recommending 9 either way (see
        # build_setup_message).
        if selected_mode == GameMode.ADVANCED:
            game.board_size = 9
        save_games(self.cog.games)

        refreshed_view = type(self)(
            cog=self.cog,
            game_id=self.game_id,
        )
        await interaction.response.edit_message(
            content=build_setup_message(game, self.cog.team_emojis),
            view=refreshed_view,
        )

    async def select_module(
        self,
        interaction: discord.Interaction,
        module_key: str,
    ) -> None:
        """
        Turn one half of advanced mode off, or back on. The rule about
        the last one still on is `toggle_advanced_module`'s, shared
        with the lobby's own settings -- see "Species abilities in the
        bot".
        """
        game = await self.validate_configuration_change(interaction)
        if game is None:
            return

        refusal = toggle_advanced_module(game, module_key)
        if refusal is not None:
            await interaction.response.send_message(refusal, ephemeral=True)
            return

        save_games(self.cog.games)

        refreshed_view = type(self)(
            cog=self.cog,
            game_id=self.game_id,
        )
        await interaction.response.edit_message(
            content=build_setup_message(game, self.cog.team_emojis),
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
            content=build_setup_message(game, self.cog.team_emojis),
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
            content=build_setup_message(game, self.cog.team_emojis),
            view=refreshed_view,
        )


class TeamSelectionView(GameConfigurationView):
    """
    Team picking, and nothing else -- since the 2026-08-17 eight-team
    split, a side's choice needs two rows (a color row and a species
    row), so this no longer shares a screen with the mode/board-size/
    AI-opponent settings the way it did at four teams: four buttons in
    one row left three more for settings, eight across two rows leaves
    at most one. Settings move to their own step, which costs nothing
    new -- CoinFlipView already carries them alongside the flip button,
    with rows to spare.

    A normal game's two sides still share one screen: whichever human
    clicks a button picks their own side, exactly as at four teams. A
    **test game** -- one person playing both sides, so there is only
    ever one user to click anything -- used to show both sides' rows on
    the same screen; two sides at two rows apiece is four, which would
    leave nothing for a shared row's worth of ambiguity anyway, so it
    now prompts them one after another instead, each with the full
    two-row budget to itself. `_picking_player_number` is the only
    place that decides which screen a test game is on: `None` once
    neither side needs asking (a normal game), 1 while Player 1 has not
    chosen, 2 once they have and Player 2 has not.
    """

    def configuration_start_row(
        self,
        game: Optional[D12BallGame],
    ) -> int:
        # Settings no longer live on this view at all -- see the class
        # docstring. Kept only because GameConfigurationView expects an
        # override point; add_configuration_buttons is never called
        # here.
        return 0

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        game = self.cog.games.get(game_id)
        player_number = self.picking_player_number(game)
        excluded = self.excluded_teams(game, player_number)

        for row, row_teams in enumerate((COLOR_TEAMS, SPECIES_TEAMS)):
            for team in row_teams:
                unavailable = team in excluded
                label = team_display_name(team)
                button = discord.ui.Button(
                    label=(
                        f"Player {player_number}: {label}"
                        if player_number is not None
                        else label
                    ),
                    style=(
                        discord.ButtonStyle.secondary
                        if unavailable
                        else discord.ButtonStyle.primary
                    ),
                    custom_id=(
                        f"d12ball:team:{game_id}:{player_number}:{team.value}"
                        if player_number is not None
                        else f"d12ball:team:{game_id}:{team.value}"
                    ),
                    disabled=unavailable,
                    row=row,
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

    @staticmethod
    def picking_player_number(
        game: Optional[D12BallGame],
    ) -> Optional[int]:
        """
        `None` for a normal game's shared row; 1 or 2 for a test
        game's sequential screens, the side that has not chosen yet.
        Player 1 always goes first, since nothing else orders them.
        """
        if game is None or not game.test_game:
            return None
        if game.player_1_team is None:
            return 1
        return 2

    @staticmethod
    def excluded_teams(
        game: Optional[D12BallGame],
        player_number: Optional[int],
    ) -> set[Team]:
        """
        Every team this screen must refuse: whichever side(s) already
        have one, and that team's own `paired_team()`.

        **The pairing is refused for its color, not for its roster.**
        A color team and its species team share a hex (`TEAM_COLORS`
        gives Fire Demons Orange's own `#FFA500`), so that one match
        would draw both sides' cards, meeples and tokens in the same
        color -- the board is where a coach reads which meeples are
        theirs, and there is nothing else on it that says. Every other
        color/species matchup is offered and playable: the 2 or 3
        players those rosters share are fielded as two cards, one a
        side. See "One player, both sides" in CLAUDE.md.
        """
        if game is None:
            return set()

        if player_number == 1:
            # The sequential test-game screen for whoever goes first:
            # nothing is chosen yet, by construction.
            already_chosen: list[Team] = []
        elif player_number == 2:
            # The sequential test-game screen for whoever goes second:
            # only the side that has already gone is excluded here.
            already_chosen = (
                [game.player_1_team]
                if game.player_1_team is not None
                else []
            )
        else:
            # The shared row (a normal game) refuses on behalf of
            # either side, whichever has already picked.
            already_chosen = [
                team
                for team in (game.player_1_team, game.player_2_team)
                if team is not None
            ]

        excluded: set[Team] = set()
        for team in already_chosen:
            excluded.add(team)
            excluded.add(paired_team(team))
        return excluded

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
            if not is_game_helper(interaction.user):
                await interaction.response.send_message(
                    "Only the players in this game can choose teams.",
                    ephemeral=True,
                )
                return

            # A game helper holds neither side, so **which side this
            # pick lands on has to be settled here** rather than read
            # off the clicker -- see "Who may act on a game" in
            # CLAUDE.md. A test game's button names it outright; a
            # normal game's two sides share one row, so it goes to the
            # side that has not chosen yet, Player 1 first. That is the
            # same order `picking_player_number` puts a test game's
            # sequential screens in, and it is the order the shared row
            # is filled in anyway. Getting this wrong is silent: the
            # `else` below would have quietly given every helper's pick
            # to Player 2.
            is_player_1 = (
                selected_player_number == 1
                if game.test_game
                else game.player_1_team is None
            )
            is_player_2 = not is_player_1

        excluded = self.excluded_teams(
            game, selected_player_number if game.test_game else None,
        )
        if selected_team in excluded:
            # A stale click on a screen this game has moved past --
            # the button should already have been disabled, but a
            # second browser tab or a slow double-click can still get
            # one through.
            await interaction.response.send_message(
                "That team is no longer available.",
                ephemeral=True,
            )
            return

        if is_player_1:
            game.player_1_team = selected_team
            if game.player_2_id is None:
                available_ai_teams = [
                    team
                    for team in Team
                    if team != selected_team
                    and team != paired_team(selected_team)
                ]

                game.player_2_team = random.choice(
                    available_ai_teams
                )

        else:
            game.player_2_team = selected_team

        save_games(self.cog.games)

        message = build_setup_message(game, self.cog.team_emojis)

        if game.teams_selected:
            # Resolved before the view is built, because the flip
            # button carries the fortune coin. This is also where
            # game settings become editable again -- see the class
            # docstring.
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
        return build_setup_message(game, self.cog.team_emojis)


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

    def settle_coin_toss(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        flipping_player_number: int,
    ) -> None:
        """
        Throw the coin, record who won it, and -- in a solo game Dinky
        won -- take Dinky's side for it.
        """
        face = random.choice((CoinFace.FORTUNE, CoinFace.DOOM))

        refresh_player_names(game, interaction.guild)
        winner_player_number = game.resolve_coin_toss(
            flipping_player_number,
            face,
        )

        game.coin_winner = format_player(game, winner_player_number)
        game.start_game()

        if not (game.is_solo_game and winner_player_number == 2):
            return

        # The tutorial's script is written for a coach with the ball at
        # kickoff, so Dinky takes the visiting side and leaves them
        # home. `DinkyAI.choose_home_or_visiting` is a coin flip of its
        # own and is overridden here rather than inside the strategy:
        # it takes no arguments, so it cannot know which game is
        # asking, and a tutorial is a property of the game. The coach's
        # own half of this is the rail on HomeAwaySelectionView.
        ai_choice = (
            HomeChoice.VISITING
            if game.tutorial
            else self.cog.engine.get_ai_strategy(
                game,
            ).choose_home_or_visiting()
        )
        game.choose_home_or_visiting(2, ai_choice)
        self.cog.engine.initialize_standard_match(game)

    async def announce_coin_toss(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        """
        Retire the setup prompt, show the coin, and put the
        home-or-visiting choice up.

        **The choice message becomes the game's persistent message**,
        which is what every later board refresh edits -- so a board
        write never touches the post the channel opened with. See
        "Discord's rate limits".
        """
        await interaction.response.edit_message(
            content=build_setup_message(
                game,
                self.cog.team_emojis,
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

        # No board yet, even when the match already exists (a solo game
        # whose AI won the toss and chose for itself). The first board
        # this message carries is the one the kickoff posts -- so
        # nothing is drawn until both coaches have finished setting up
        # and there is a kickoff to show. See
        # D12Ball.finish_setup_coaching.
        choice_message = await interaction.followup.send(
            build_home_choice_message(game, self.cog.team_emojis),
            view=HomeAwaySelectionView(
                cog=self.cog,
                game_id=self.game_id,
            ),
            wait=True,
        )
        game.message_id = choice_message.id
        save_games(self.cog.games)

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

        if not self.may_act_in_game(interaction, game):
            await interaction.response.send_message(
                "Only a player in this game can flip the coin.",
                ephemeral=True,
            )
            return

        if game.coin_flipped:
            # A second click on a prompt the toss has already answered:
            # put the choice back rather than only refusing, since the
            # message they clicked is the one carrying it.
            await interaction.response.edit_message(
                content=build_home_choice_message(game, self.cog.team_emojis),
                view=HomeAwaySelectionView(
                    cog=self.cog,
                    game_id=self.game_id,
                ),
            )

            await interaction.followup.send(
                "The coin has already been flipped.",
                ephemeral=True,
            )
            return

        # The coin is read from the flipping player's point of view, so
        # it has to be flipped *as* somebody -- a game helper is neither
        # player, and flips on Player 1's behalf. Which of the two it is
        # changes nothing but the wording: the coin is fair either way,
        # so the winner is as likely to be one as the other.
        self.settle_coin_toss(
            interaction,
            game,
            2 if interaction.user.id == game.player_2_id else 1,
        )

        await self.announce_coin_toss(interaction, game)

        if game.match_state is not None:
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

        # A tutorial is scripted from the kickoff forward and its coach
        # starts with the ball, so a coach who wins the toss is railed
        # onto Home -- built disabled rather than hidden, like every
        # other rail. Dinky's half of this is in CoinFlipView.flip_coin.
        tutorial_home_only = bool(
            game is not None and game.tutorial and not assignment_complete
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
                disabled=(
                    assignment_complete
                    or (tutorial_home_only and choice != HomeChoice.HOME)
                ),
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

        if not self.may_act_for(interaction, winner_user_id):
            await interaction.response.send_message(
                "Only the player who won the coin toss can make this choice.",
                ephemeral=True,
            )
            return

        game.choose_home_or_visiting(winner_player_number, choice)
        self.cog.engine.initialize_standard_match(game)
        save_games(self.cog.games)

        refreshed_view = HomeAwaySelectionView(
            cog=self.cog,
            game_id=self.game_id,
        )
        # The match exists from here, but its board does not go up
        # until both coaches are done setting up -- see the same note
        # on the coin flip, and D12Ball.finish_setup_coaching.
        await interaction.response.edit_message(
            content=build_home_choice_message(game, self.cog.team_emojis),
            view=refreshed_view,
        )

        winner = format_player_with_team(
            game, winner_player_number, self.cog.team_emojis,
        )
        await interaction.followup.send(
            f"{winner} chose **{choice.value.title()}**."
        )
        await self.cog.begin_setup_coaching(interaction, game)


class RematchView(SafeView):
    """
    The two buttons on a finished game's full-time message. Rematch
    opens a fresh game for the same players, with the same settings,
    and archives the game that just ended. Archive is the other half of
    that: the pair who are not playing again still want the channel
    filed away, and until now the only way to do it was to abandon a
    game that had already finished.

    Both are drawn greyed out once what they do has been done, which is
    what makes the view worth rebuilding rather than mutating -- see
    refresh_buttons.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        archived: Optional[bool] = None,
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

        # A rematch archives the channel on its way out, so the two
        # buttons grey out together -- the state is read off the
        # channel rather than off the game, because that is where it
        # lives and because /d12ball abandon_game and a moderator
        # dragging the channel by hand both get there without the game
        # record hearing about it.
        #
        # `archived` is how a caller that has *just* moved the channel
        # says so, and it is not an optimisation: discord.py's
        # `TextChannel.edit` returns a new channel object and leaves
        # the cached one alone, so the cache is only corrected when the
        # GUILD_CHANNEL_UPDATE event lands. A view rebuilt in the same
        # breath as the move -- which is both of refresh_buttons'
        # callers -- would otherwise read the category the channel has
        # just left and draw the button live again.
        if archived is None:
            archived = game is not None and self.cog.game_channel_is_archived(game)

        archive_button = discord.ui.Button(
            label="Archive",
            style=discord.ButtonStyle.secondary,
            custom_id=f"d12ball:archive:{game_id}",
            disabled=archived,
        )
        archive_button.callback = self.archive_channel
        self.add_item(archive_button)

    async def refresh_buttons(
        self,
        message: Optional[discord.Message],
        archived: Optional[bool] = None,
    ) -> None:
        """
        Redraw both buttons in the state they are now in, keeping the
        full-image link that was put on the message after it was sent.

        Editing a view replaces it wholesale and the link is not one of
        this view's own children, so rebuilding without re-adding it
        would take the link off the one board a finished game leaves in
        the channel. Every failure is swallowed with a warning: the
        thing the click did has already happened, and a button that was
        not greyed out reports it rather than doing it twice.

        `archived` is passed straight to the rebuilt view; both callers
        reach here having moved the channel themselves, which is a
        thing the channel cache does not yet know -- see __init__.
        """
        if message is None:
            return

        view = RematchView(self.cog, self.game_id, archived=archived)
        link = build_full_image_button(message)
        if link is not None:
            view.add_item(link)

        try:
            await message.edit(view=view)
        except (discord.HTTPException, aiohttp.ClientError) as error:
            LOGGER.warning(
                "Could not refresh the full-time buttons for game %s: %s",
                self.game_id, error,
            )

    async def archive_channel(
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

        # The same gate as the recovery commands: either player, or
        # anyone the server trusts with manage_channels. Wider than the
        # rematch's, which opens a game two people have to play.
        if not self.cog.may_administer_game(interaction, game):
            await interaction.response.send_message(
                "Only a player in this game, or someone who can manage "
                "channels, can archive it.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await self.cog.archive_game_channel(game)
        except (ValueError, discord.Forbidden, discord.HTTPException) as error:
            await interaction.followup.send(
                f"I could not archive this channel: {error}",
                ephemeral=True,
            )
            return

        await self.refresh_buttons(interaction.message, archived=True)

        await interaction.followup.send(
            "This channel has moved to the PBD archive. Nothing in it is "
            "deleted -- it is the record of the game.",
            ephemeral=True,
        )

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

        # Either player, or a game helper -- the same gate as the
        # Archive button beside it. A rematch opens a game two people
        # have to play, which is why this was players-only; getting two
        # people back into a game is exactly what a helper is for.
        if not self.may_act_in_game(interaction, game):
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

        # Cosmetic: the rematch itself is already open, and a button
        # that wasn't greyed out just reports the rematch it finds
        # instead of opening another one. The archive button greys out
        # in the same edit, since start_rematch has just moved the
        # channel -- which it has to be told, the cache being a step
        # behind the move.
        await self.refresh_buttons(interaction.message, archived=True)

        await interaction.followup.send(
            f"Rematch created: <#{rematch.channel_id}>",
            ephemeral=True,
        )

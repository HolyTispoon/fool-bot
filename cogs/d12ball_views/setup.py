"""
Setup: team selection, game settings, the coin toss, the
home-or-visiting choice, and the rematch offer at full time. The
pre-game lobby that now precedes all of this is in `lobby.py`.

Every change a view here makes to the game record goes through
`GameService` -- `configure`, `pick_team`, `flip_coin`,
`choose_home_or_visiting` (step 8 of docs/architecture-migration.md):
the record rules on it and refuses with `RuleRefusal`, the service
saves once, and the view shows the refusal or redraws itself. Nothing
in this module decides who may pick what, and nothing in it saves.
"""

import aiohttp
import discord
from typing import Optional, TYPE_CHECKING

from d12ball.components import RuleRefusal
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
    VALID_BOARD_SIZES,
    team_display_name,
)
from cogs.d12ball_helpers import (
    AI_OPPONENT_NAMES,
    GAME_MODE_BUTTONS,
    LOGGER,
    build_full_image_button,
    build_home_choice_message,
    build_setup_message,
    format_coin_emoji,
    format_player_with_team,
    get_team_emoji,
    is_game_helper,
    refresh_player_names,
    send_new_prompt,
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

        for label, mode in GAME_MODE_BUTTONS:
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

        for board_size in sorted(VALID_BOARD_SIZES):
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

    async def change_setting(
        self,
        interaction: discord.Interaction,
        setting: str,
        value: object,
    ) -> None:
        """
        One setting, through `GameService.configure`, and the block
        redrawn. Whether this click may change the game's settings is
        the only thing decided here -- either player, or a game helper
        -- and every other reason for nothing to happen is the
        record's, shown as it says it.
        """
        game = self.cog.games.get(self.game_id)

        if game is None:
            await interaction.response.send_message(
                "I could not find this game.",
                ephemeral=True,
            )
            return

        if not self.may_act_in_game(interaction, game):
            await interaction.response.send_message(
                "Only the players in this game can change its settings.",
                ephemeral=True,
            )
            return

        try:
            self.cog.service.configure(self.game_id, setting, value)
        except RuleRefusal as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        refreshed_view = type(self)(
            cog=self.cog,
            game_id=self.game_id,
        )
        await interaction.response.edit_message(
            content=self.cog.render_text(build_setup_message(game), game),
            view=refreshed_view,
        )

    async def select_mode(
        self,
        interaction: discord.Interaction,
        selected_mode: GameMode,
    ) -> None:
        await self.change_setting(interaction, "mode", selected_mode)

    async def select_ai_opponent(
        self,
        interaction: discord.Interaction,
        selected_ai_type: AIOpponent,
    ) -> None:
        await self.change_setting(interaction, "ai", selected_ai_type)

    async def select_board_size(
        self,
        interaction: discord.Interaction,
        selected_board_size: int,
    ) -> None:
        await self.change_setting(interaction, "board", selected_board_size)


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
    two-row budget to itself. Which screen a test game is on, and
    which teams a screen greys out, are the record's
    (`D12BallGame.picking_player_number`, `teams_open_to` over
    `excluded_teams`): the same reading `GameService.pick_team` refuses
    a stale click against, and the one the web table offers from.
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
        player_number = (
            game.picking_player_number() if game is not None else None
        )
        # The record's one answer to "which may this picker press"
        # (`D12BallGame.teams_open_to`), which the web table reads too.
        offered = (
            set(game.teams_open_to(player_number))
            if game is not None
            else set(Team)
        )

        for row, row_teams in enumerate((COLOR_TEAMS, SPECIES_TEAMS)):
            for team in row_teams:
                unavailable = team not in offered
                label = team_display_name(team)
                button = discord.ui.Button(
                    label=(
                        f"Player {player_number}: {label}"
                        if player_number is not None
                        else label
                    ),
                    emoji=get_team_emoji(cog.team_emojis, team),
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

        # Whose pick this is. A test game's button names the side and
        # its one user holds both; a normal game's coach picks their
        # own; a game helper holds neither, so their pick lands where
        # the record says (`team_pick_lands_on`).
        if game.test_game:
            is_player = interaction.user.id == game.player_1_id
            player_number = selected_player_number
        else:
            is_player = interaction.user.id in (
                game.player_1_id, game.player_2_id,
            )
            player_number = 1 if interaction.user.id == game.player_1_id else 2

        if not is_player:
            if not is_game_helper(interaction.user):
                await interaction.response.send_message(
                    "Only the players in this game can choose teams.",
                    ephemeral=True,
                )
                return
            player_number = game.team_pick_lands_on(selected_player_number)

        try:
            self.cog.service.pick_team(
                self.game_id, player_number, selected_team,
            )
        except RuleRefusal as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        message = self.cog.render_text(build_setup_message(game), game)

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
        return self.cog.render_text(build_setup_message(game), game)


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
            content=self.cog.render_text(
                build_setup_message(game, mention_players=False), game,
            ),
            view=None,
        )

        # The coin goes out on its own, with nothing else in the
        # message, which is what makes Discord render it large.
        await send_new_prompt(
            interaction,
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
        # `d12ball.flow.periods.finish_setup_coaching`.
        choice_message = await send_new_prompt(
            interaction,
            self.cog.render_text(build_home_choice_message(game), game),
            view=HomeAwaySelectionView(
                cog=self.cog,
                game_id=self.game_id,
            ),
        )
        game.message_id = choice_message.id
        self.cog.service.save()

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

        # The names the record carries are refreshed from the server

        # before the toss names its winner. A game helper is neither
        # player, and flips on Player 1's behalf: the coin is fair
        # either way, so the winner is as likely to be one as the
        # other, and the service words the toss from the flipper's
        # point of view.
        refresh_player_names(game, interaction.guild)
        try:
            self.cog.service.flip_coin(
                self.game_id,
                2 if interaction.user.id == game.player_2_id else 1,
            )
        except RuleRefusal as error:
            if game.coin_flipped:
                # A second click on a prompt the toss has already
                # answered: put the choice back rather than only
                # refusing, since the message they clicked is the one
                # carrying it. The sentence is the record's.
                await interaction.response.edit_message(
                    content=self.cog.render_text(
                        build_home_choice_message(game), game,
                    ),
                    view=HomeAwaySelectionView(
                        cog=self.cog,
                        game_id=self.game_id,
                    ),
                )
                await interaction.followup.send(str(error), ephemeral=True)
            else:
                await interaction.response.send_message(
                    str(error), ephemeral=True,
                )
            return

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

        # The record's rail (`D12BallGame.home_choice_rail`): a
        # tutorial's coach is Home whoever wins the toss. Built
        # disabled rather than hidden, like every other rail, and
        # refused by the record if pressed anyway.
        rail = (
            None if game is None
            else game.home_choice_rail(game.coin_winner_player_number)
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
                    or (rail is not None and choice != rail)
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

        try:
            self.cog.service.choose_home_or_visiting(
                self.game_id, winner_player_number, choice,
            )
        except RuleRefusal as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        refreshed_view = HomeAwaySelectionView(
            cog=self.cog,
            game_id=self.game_id,
        )
        # The match exists from here, but its board does not go up
        # until both coaches are done setting up -- see the same note
        # on the coin flip, and `d12ball.flow.periods.finish_setup_coaching`.
        await interaction.response.edit_message(
            content=self.cog.render_text(build_home_choice_message(game), game),
            view=refreshed_view,
        )

        winner = self.cog.render_text(
            format_player_with_team(game, winner_player_number), game,
        )
        await send_new_prompt(
            interaction, f"{winner} chose **{choice.value.title()}**.",
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

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
from math import ceil
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

import aiohttp
import discord

from d12ball import tutorial
from d12ball.components import (
    MatchState,
    MANEUVER_TIER_BASIC,
    PlayerDefinition,
    PlayerRole,
    TeamSetup,
    TeamSide,
    Zone,
)
from d12ball.game import (
    AIOpponent,
    CoinFace,
    COLOR_TEAMS,
    D12BallGame,
    Formation,
    GameMode,
    GameStatus,
    HomeChoice,
    SPECIES_TEAMS,
    Team,
    paired_team,
    team_display_name,
)
from d12ball.render import (
    TEAM_COLORS,
    render_player_portrait,
    render_skill_test_dice,
)

from gamesaves.d12ball.storage import save_games

from cogs.d12ball_helpers import (
    AI_OPPONENT_NAMES,
    ERROR_RECOVERY_ADVICE,
    LOGGER,
    ROLE_INITIALS,
    add_full_image_button,
    add_full_image_button_to_response,
    build_full_image_button,
    build_home_choice_message,
    build_setup_message,
    contest_noun,
    destination_display_name,
    format_coin_emoji,
    format_goal_time,
    format_player,
    format_player_with_team,
    format_role_bracket,
    format_team_side_label,
    refresh_player_names,
    send_error_fallback,
    space_label,
    travel_space_label,
)

if TYPE_CHECKING:
    from cogs.d12ball import D12Ball


def contestant_detail(
    player: PlayerDefinition,
    skill_word: str,
    skill: int,
    injured: bool = False,
) -> list[str]:
    """
    The lines naming one side of a contest on the dice image: who is
    rolling, and what they add to it.

    `injured` is only ever passed by the contests injury actually bites
    in -- the loose ball, the long High Pass and the shootout, where an
    injured contestant's own skill stays off the roll and nothing else
    does. A maneuver's skill test and a score attempt are untouched by
    it and pass nothing, which is the rule rather than an omission; see
    "Injured players" in docs/living-rules.md.
    """
    return [
        f"{player.name} [{ROLE_INITIALS[player.role.value]}]",
        "Injured — no skill modifier"
        if injured
        else f"{skill_word} skill +{skill}",
    ]


async def render_contest_dice(
    contestants: list[tuple[int, Team, list[str], int]],
    filename: str,
) -> discord.File:
    """
    The dice image behind every two-sided roll in the game -- a skill
    test, a loose ball, a score attempt, a shootout test -- as
    `(roll, team, detail lines, total)` a side.

    The image carries the whole arithmetic, which is why no message
    that posts one repeats it in text. Rendering is Pillow and pure
    CPU, so it goes to a worker thread; see "Discord's rate limits" in
    CLAUDE.md.
    """
    return discord.File(
        await asyncio.to_thread(
            render_skill_test_dice,
            [
                (
                    roll,
                    TEAM_COLORS[team],
                    team_display_name(team),
                    detail,
                    total,
                )
                for roll, team, detail, total in contestants
            ],
        ),
        filename=filename,
    )


class SafeView(discord.ui.View):
    """
    Base class for every D12 Ball view. discord.py's default behavior
    for an uncaught exception in a button/select callback is to log it
    and otherwise do nothing, which leaves the click looking like it
    had no effect at all. This surfaces a message instead.

    Every subclass carries `self.cog` and `self.game_id`, set in
    `__init__` before anything below is ever called -- that is what
    lets `load_match`/`require_match` read them rather than take them
    as parameters.
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
            "Something went wrong handling that click. "
            f"{ERROR_RECOVERY_ADVICE}",
        )

    def load_match(
        self,
    ) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        """
        `(game, match)` for `self.game_id`, or `(None, None)` when the
        game is gone or has no match state yet -- the lookup nearly
        every view opens with, in `__init__` and in most of its
        callbacks. Silent: `__init__` has no interaction to reply to,
        which is why this doesn't reply and `require_match` does.
        """
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            return None, None
        return game, self.cog.engine.load_match_state(game)

    async def require_match(
        self,
        interaction: discord.Interaction,
    ) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        """
        Same lookup as `load_match`, replying "I could not find the
        saved data for this game." and returning `(None, None)` when it
        comes up empty -- the shape nearly every callback opens with,
        once there is an interaction to answer.
        """
        game, match = self.load_match()
        if game is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
        return game, match

    def is_game_participant(self, game: D12BallGame, user_id: int) -> bool:
        """
        Whether `user_id` is one of the two coaches in `game` -- never
        the AI, which has no user id to be. See "Every roll is a
        coach's" in CLAUDE.md: any coach in the game may press a roll
        button, not only the one it happens to be about, so this is
        the whole of the check and callers word their own refusal.
        """
        participant_ids = {game.player_1_id}
        if game.player_2_id is not None:
            participant_ids.add(game.player_2_id)
        return user_id in participant_ids


    def pay_skill_test_tie(
        self,
        game: D12BallGame,
        match: MatchState,
        first_player_id: str,
        second_player_id: str,
        offense_total: int,
        defense_total: int,
    ) -> str:
        """
        Charge both contestants the re-roll's exhaustion token, save,
        and word the tie -- shared by the maneuver skill test and the
        loose ball (which the long High Pass also comes through).

        The token counts towards Exhausted straight away, so whoever it
        pushes over is already flagged when the test finally resolves
        and hands out its injury checks.

        The edit that posts this stays with the caller: one of the two
        has deferred and answers on `edit_original_response`, the other
        has not and answers on `interaction.response.edit_message`, and
        a flag here would hide a difference that is real.
        """
        exhaustion_text = "\n".join(
            [
                self.cog.apply_exhaustion(match, first_player_id, 1),
                self.cog.apply_exhaustion(match, second_player_id, 1),
            ]
        )
        self.cog.persist(game, match)

        return (
            f"**It's a tie ({offense_total}-{defense_total})!** "
            f"The skill test must be rolled again.\n"
            f"{exhaustion_text}\n\nRoll again:"
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

        # **Advanced mode is the second set of maneuvers, and only
        # that.** Its other half -- a unique ability per player -- is
        # not built: the sheet's advanced ability column is empty for
        # all thirty-six, so there is nothing to import. A coach
        # picking it here gets six cards a side instead of three and
        # the roster they already know.
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
            await interaction.response.send_message(
                "Only the players in this game can choose teams.",
                ephemeral=True,
            )
            return

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

        message = build_setup_message(game)

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
            build_home_choice_message(game),
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
            # A second click on a prompt the toss has already answered:
            # put the choice back rather than only refusing, since the
            # message they clicked is the one carrying it.
            await interaction.response.edit_message(
                content=build_home_choice_message(game),
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

        self.settle_coin_toss(
            interaction,
            game,
            1 if interaction.user.id == game.player_1_id else 2,
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

        if interaction.user.id != winner_user_id:
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
            content=build_home_choice_message(game),
            view=refreshed_view,
        )

        await interaction.followup.send(
            f"{format_player_with_team(game, winner_player_number)} chose "
            f"**{choice.value.title()}**."
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


class BallHandlerSelectionView(SafeView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id
        game, match = self.load_match()
        if game is None:
            return

        # Not eligible_ball_handlers: a ball carrier narrows this to
        # one button, which is the rule showing up as a menu with no
        # choice in it. send_turn_prompt normally skips the view
        # entirely in that case; this is the restore path.
        for player_id in match.turn_handler_candidates():
            player = self.cog.engine.get_player_definition(player_id)
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
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if match.active_player_id is not None:
            await interaction.response.edit_message(
                content=self.cog.engine.build_turn_prompt(game, match),
                view=PlayerActionView(self.cog, self.game_id),
            )
            await interaction.followup.send(
                "A player has already been selected.",
                ephemeral=True,
            )
            return

        if not self.cog.engine.user_controls_possession(
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

        self.cog.persist(game, match)
        await interaction.response.edit_message(
            content=self.cog.engine.build_turn_prompt(game, match),
            view=PlayerActionView(self.cog, self.game_id),
        )


class PlayerActionView(SafeView):
    """
    The turn's choice: shoot, maneuver, or cede the ball to coach.
    **Shooting is only offered from within shooting range and ceding
    only from outside it**, so a coach never sees both -- see
    `MatchState.can_attempt_score`, `MatchState.may_cede_possession`,
    and `D12Ball.build_turn_prompt`, which says why whichever one is
    missing is missing. Rebuilt from match state on every restart like
    every other persistent view here, so the ball's position always
    decides afresh.
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
        can_cede = False
        if game is not None and game.match_state is not None:
            match = cog.engine.load_match_state(game)
            can_shoot = match.can_attempt_score()
            can_cede = match.may_cede_possession()

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
        if can_cede:
            # Grey, and last: it is the turn a coach takes when there
            # is nothing else worth taking, and it should never sit
            # beside Maneuver as an equal.
            actions.append(
                (
                    "Cede ball to coach",
                    "cede",
                    discord.ButtonStyle.secondary,
                ),
            )

        # A tutorial beat names the one action it wants pressed, and
        # the rest are built **disabled** rather than left out: a coach
        # should see that shooting and ceding exist and read in the
        # lesson why neither is theirs yet. See d12ball/tutorial.py.
        allowed = tutorial.allowed_actions(
            self.cog.tutorial_beat(game) if game is not None else None
        )

        for label, action, style in actions:
            button = discord.ui.Button(
                label=label,
                style=style,
                custom_id=f"d12ball:action:{game_id}:{action}",
                disabled=allowed is not None and action not in allowed,
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
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if match.active_player_id is None:
            await interaction.response.send_message(
                "Choose a player to handle the ball first.",
                ephemeral=True,
            )
            return

        if not self.cog.engine.user_controls_possession(
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

        # The button was built disabled, so this is a click on a prompt
        # from an earlier beat still sitting in the channel -- the same
        # stale-view guard the shot and the cede keep.
        allowed = tutorial.allowed_actions(self.cog.tutorial_beat(game))
        if allowed is not None and action not in allowed:
            await interaction.response.send_message(
                "The tutorial is on this step's action. Use the prompt "
                "at the bottom of the channel.",
                ephemeral=True,
            )
            return

        if action == "shoot":
            await self.begin_shot_action(
                interaction, game, match, action_label,
            )
            return

        if action == "cede":
            await self.begin_cede_action(interaction, game, match)
            return

        await self.begin_maneuver_action(interaction, game, match)

    async def begin_shot_action(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        action_label: str,
    ) -> None:
        """Take the shot on, and say who is taking it."""
        # The button is only built when the shot is legal, so this is a
        # click on a prompt the ball has since moved out from under --
        # the same stale-view guard the other choices keep.
        if not match.can_attempt_score():
            await interaction.response.send_message(
                "The ball is out of shooting range.",
                ephemeral=True,
            )
            return

        match.pending_action = "shoot"
        self.cog.persist(game, match)

        refresh_player_names(game, interaction.guild)
        handler = self.cog.engine.get_player_definition(match.active_player_id)
        offense_number = self.cog.engine.possession_player_number(game, match)
        offense_display = format_player_with_team(game, offense_number)

        await interaction.response.edit_message(
            content=(
                f"{offense_display} has chosen to {action_label} with "
                f"{format_role_bracket(handler, self.cog.team_emojis, match.team_for_player(handler.player_id))}."
            ),
            view=None,
        )
        await self.cog.begin_score_attempt(interaction, game, match)

    async def begin_cede_action(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Put the cost of giving the ball up in front of the coach before
        anything happens. Ceding is the one turn action that hands the
        opponent the ball and it sits one button along from Maneuver,
        so it is confirmed rather than taken -- see CedeConfirmView.
        """
        # Same stale-view guard the shot keeps, and the same two
        # reasons the button would not have been built: the ball has
        # moved into shooting range since, or the side has spent its
        # once-a-half Coaching Choice elsewhere.
        if not match.may_cede_possession():
            await interaction.response.send_message(
                "The ball is in shooting range now, so there is "
                "nothing to cede for."
                if match.can_attempt_score()
                else "Your side has already called its Coaching "
                "Choice this half.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            content=self.cog.engine.cede_confirmation(game, match),
            view=CedeConfirmView(
                self.cog, self.game_id, interaction.message.content,
            ),
        )

    async def begin_maneuver_action(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Start a maneuver, which reaches the offense's pick by one of
        three routes: nobody to challenge at all, a challenger settled
        without asking, or the defending coach's own choice.
        """
        # Nobody left to challenge with at all -- a side with a meeple
        # anywhere on the board has a candidate, so this needs an empty
        # field: the maneuver succeeds automatically and the offense
        # still picks which one
        # (docs/living-rules.md, "Maneuvers"). There is no challenger to
        # choose and nothing for the defense to do, so this skips
        # straight to the offense's pick. A defense that is offered a
        # challenge and sends nobody lands in the same place, from
        # ManeuverChallengeView.decline.
        if not match.eligible_challengers():
            match.begin_uncontested_maneuver()
            self.cog.persist(game, match)

            await interaction.response.defer()
            await self.cog.drop_turn_prompt(interaction, game)
            await self.cog.announce_uncontested_maneuver(
                interaction, game, match,
            )
            return

        match.pending_action = "maneuver"
        defender_number = self.cog.engine.defending_player_number(game, match)

        # One defender already sharing the ball's exact space leaves
        # nothing to choose -- they pay nothing to challenge, so the
        # challenge is neither theirs to decline nor a pick between
        # players, and it goes ahead the same way it does when the AI
        # is the one picking. Two of them is a pick, and the defending
        # coach makes it (the author, 2026-08-17): they are the whole
        # of the choice, since nobody may be walked in past them. See
        # MatchState.challenge_candidates.
        on_ball_space = match.automatic_challengers()
        if len(on_ball_space) == 1 or (
            game.is_solo_game and defender_number == 2
        ):
            challenger_id = (
                on_ball_space[0]
                if len(on_ball_space) == 1
                else self.cog.engine.get_ai_strategy(game).choose_challenger(match)
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

        self.cog.persist(game, match)

        await self.send_challenger_prompt(
            interaction, game, match, defender_number,
        )

    async def send_challenger_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        defender_number: int,
    ) -> None:
        """
        Ask the defending coach who challenges, when the answer is
        genuinely theirs to give.
        """
        refresh_player_names(game, interaction.guild)
        handler = self.cog.engine.get_player_definition(match.active_player_id)
        defender_mention = format_player_with_team(
            game,
            defender_number,
            mention=True,
        )

        await interaction.response.defer()
        await self.cog.drop_turn_prompt(interaction, game)

        # The handler is named here, unlike in the automatic case:
        # the defense is being asked to choose a challenger
        # before the challenge image exists, so this is the only place
        # they can read who they would be up against.
        # Two defenders on the ball are the whole of the choice and
        # neither of them can be kept back, so the prompt must not
        # offer what the view does not build -- see
        # MatchState.challenge_candidates.
        ask = (
            "choose which player will maneuver to challenge for the "
            "ball, or send nobody and let the maneuver through."
            if match.may_decline_challenge()
            else "these players are already on the ball, so one of "
            "them has to challenge -- choose which."
        )
        handler_team = match.team_for_player(handler.player_id)
        challenge_view = ManeuverChallengeView(self.cog, self.game_id)
        challenge_message = await interaction.followup.send(
            f"{format_role_bracket(handler, self.cog.team_emojis, handler_team)} will "
            f"maneuver for {team_display_name(handler_team)}.\n\n"
            f"{defender_mention}, {ask}",
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


class CedeConfirmView(SafeView):
    """
    "Are you sure?" for the one turn action that hands the other team
    the ball -- see `D12Ball.begin_cede`. Every other choice a coach
    makes can be argued with afterwards; this one gives the ball away
    and spends a once-a-half declaration, and it sits one button along
    from Maneuver.

    **It replaces the turn prompt in place rather than posting a
    second message**, so Back is genuinely a way out (it puts the
    prompt back, word for word, which is why `prompt` is carried
    rather than rebuilt -- `build_turn_prompt` can no longer tell
    whether the handler was carrying the ball) and the confirmed click
    can drop the prompt the ordinary way. It is an
    `interaction.response.edit_message` at both ends, so unlike a board
    write it costs nothing out of the channel's edit bucket.

    A restart between opening this and answering it leaves the buttons
    dead -- a restart re-arms the message with `PlayerActionView`, this
    view being nothing the match records. The coach is one `/d12ball
    resume` from the turn prompt they started at, and nothing has
    happened to the match in the meantime.
    """

    def __init__(self, cog: "D12Ball", game_id: str, prompt: str):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id
        self.prompt = prompt

        confirm = discord.ui.Button(
            label="Cede and coach",
            style=discord.ButtonStyle.danger,
            custom_id=f"d12ball:cede_confirm:{game_id}",
        )
        confirm.callback = self.confirm
        self.add_item(confirm)

        back = discord.ui.Button(
            label="Back",
            style=discord.ButtonStyle.secondary,
            custom_id=f"d12ball:cede_cancel:{game_id}",
        )
        back.callback = self.back
        self.add_item(back)

    async def claim(
        self,
        interaction: discord.Interaction,
    ) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        """The game and match, if this click may act on them."""
        game, match = await self.require_match(interaction)
        if game is None:
            return None, None

        if not self.cog.engine.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the team with the ball can give it up.",
                ephemeral=True,
            )
            return None, None
        return game, match

    async def back(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        await interaction.response.edit_message(
            content=self.prompt,
            view=PlayerActionView(self.cog, self.game_id),
        )

    async def confirm(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        # Asked again rather than trusted from the click that opened
        # this: the prompt underneath is a live message and the match
        # can have moved on under it.
        if not match.may_cede_possession():
            await interaction.response.edit_message(
                content=self.prompt,
                view=PlayerActionView(self.cog, self.game_id),
            )
            await interaction.followup.send(
                "The ball can no longer be ceded from here.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        await self.cog.begin_cede(interaction, game, match)


class ManeuverChallengeView(SafeView):
    """
    Who the defense puts up against the maneuver -- or nobody. The
    candidates are `MatchState.challenge_candidates`: the nearest
    defender either side of the ball, from any zone (see "Sending a
    player" in docs/living-rules.md), or the defenders already standing
    on the ball wherever there are any. Walking in costs 1 token per
    space, and the author's 2026-08-12 ruling is that a defense may
    refuse to pay it and let the maneuver through; a defender on the
    ball pays nothing, so that challenge is not theirs to refuse and no
    Send nobody button is built.

    **One defender on the ball never reaches this prompt** -- there is
    nothing to choose. Two or more do, since which of them challenges
    is the coach's call (the author, 2026-08-17) and a challenge is
    settled on defensive skill.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        game, match = self.load_match()
        if game is None:
            return

        for player_id in match.challenge_candidates():
            player = self.cog.engine.get_player_definition(player_id)
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

        # Asked rather than assumed: this view is normally only built
        # where the choice is real, but a restart can re-attach it to a
        # prompt saved with a defender standing on the ball -- and that
        # challenge is not the defense's to refuse.
        if match.may_decline_challenge():
            decline = discord.ui.Button(
                label="Send nobody",
                style=discord.ButtonStyle.secondary,
                custom_id=f"d12ball:challenge_decline:{game_id}",
                row=4,
                # Railed during the tutorial's beat 3: the coach has
                # nobody standing near the ball there, and letting
                # Dinky's maneuver through unchallenged would leave
                # nothing for the lesson's Pressure to defend against.
                disabled=cog.tutorial_railed_option(
                    cog.games.get(game_id),
                    "challenge_decline",
                    ("never",),
                ) == "never",
            )
            decline.callback = self.decline
            self.add_item(decline)

    async def claim(
        self,
        interaction: discord.Interaction,
    ) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        """
        The game and match if this click may still settle the
        challenge, or (None, None) after replying with why it may not.
        Both answers come through here, because either one closes the
        question: a challenger walks in, or the defense sends nobody
        and the maneuver goes unchallenged.
        """
        game, match = await self.require_match(interaction)
        if game is None:
            return None, None

        if match.challenger_id is not None or match.maneuver_uncontested:
            await interaction.response.edit_message(
                content=self.cog.engine.build_turn_prompt(game, match),
                view=PlayerActionView(self.cog, self.game_id),
            )
            await interaction.followup.send(
                "A defender has already been chosen."
                if match.challenger_id is not None
                else "This maneuver has already gone unchallenged.",
                ephemeral=True,
            )
            return None, None

        if not self.cog.engine.user_controls_defense(
            interaction.user.id,
            game,
            match,
        ):
            await interaction.response.send_message(
                "Only the player whose team is defending can make "
                "this choice.",
                ephemeral=True,
            )
            return None, None

        return game, match

    async def select_challenger(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
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

        self.cog.persist(game, match)

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

    async def decline(self, interaction: discord.Interaction) -> None:
        """
        Send nobody: the maneuver goes unchallenged, exactly as it does
        when the defense has nobody to send at all. Nothing moves
        and nobody is charged, so there is no board to refresh -- the
        one thing a challenge would have cost is the walk-in this
        refuses to pay.
        """
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        try:
            match.begin_uncontested_maneuver()
        except ValueError as error:
            await interaction.response.send_message(
                str(error),
                ephemeral=True,
            )
            return

        self.cog.persist(game, match)

        await interaction.response.defer()
        await self.cog.drop_turn_prompt(interaction, game)
        await self.cog.announce_uncontested_maneuver(
            interaction, game, match,
        )


# Discord's own component limits: five rows to a message, five buttons
# to a row.
MAX_BUTTON_ROWS = 5
MAX_BUTTONS_PER_ROW = 5


def even_button_rows(
    buttons: list[discord.ui.Button],
) -> list[list[discord.ui.Button]]:
    """
    Split one side's maneuver buttons into as few rows as Discord
    allows, and then **evenly** across them.

    Six advanced cards do not fit a row, and chunking at the limit
    would lay them out five and one -- which reads as a row plus an
    afterthought rather than as one hand. Two rows of three is the same
    number of rows and says what it is.
    """
    if not buttons:
        return []
    rows = ceil(len(buttons) / MAX_BUTTONS_PER_ROW)
    per_row = ceil(len(buttons) / rows)
    return [
        buttons[start:start + per_row]
        for start in range(0, len(buttons), per_row)
    ]


class ManeuverActionPromptView(SafeView):
    """
    The maneuver pick, on **one public message carrying both sides'
    buttons**.

    It used to be two steps: a public prompt with a single "Choose Your
    Maneuver" button that opened an ephemeral menu of the clicking
    coach's own cards. The ephemeral menu was never about privacy of
    the *cards* -- the twelve of them and the defeat cycle are public
    information either coach may ask for at any time. What has to stay
    hidden is the **pick**, and that is hidden by the reply to the
    click being ephemeral, not by the menu being private. Discord tells
    nobody else who pressed what, so a coach reading this message
    cannot tell whether the other side has clicked, and the message is
    never edited to say (see `D12Ball.close_maneuver_prompt`).

    So the extra click bought nothing but the round trip. It existed
    because an ephemeral message must answer *that coach's own*
    interaction, and only one of the two coaches is ever holding a live
    interaction when a maneuver begins -- whoever picked Maneuver, or
    picked the challenger. Putting the buttons on the message removes
    the need for either coach to hold one.

    Two things follow, and both are improvements:

    - **A restart re-attaches this like any other view.** It is on a
      real message recorded in `turn_message_id`, so `on_ready` handles
      it through `pending_turn_view` and the message-agnostic
      `add_view` registration the ephemeral menu needed is gone. (The
      shootout's two menus are still ephemeral and still need it -- see
      `D12Ball.restore_shootout_menus`.)
    - **The uploads halve.** One public hand image and one public field
      strip, against a hand and a field to each of two coaches.

    **Every side on the prompt keeps its buttons for the whole
    maneuver**, picked or not. The message is deliberately never
    edited, so the buttons a restored view dispatches have to match the
    buttons sitting on the message; taking a picked side's row away
    would leave those clicks answered by nothing. `pick` refuses the
    second click instead. Which sides are on it at all is
    `RulesEngine.maneuver_pick_sides`.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        timeout: Optional[float] = None,
    ):
        super().__init__(timeout=timeout)

        self.cog = cog
        self.game_id = game_id

        game, match = self.load_match()
        sides = (
            cog.engine.maneuver_pick_sides(game, match)
            if game is not None and match is not None
            else ("offense",)
        )
        self.sides = sides

        rows: list[list[discord.ui.Button]] = []

        for side in sides:
            # **The hand is the engine's answer, not the whole
            # catalog.** A basic game is three cards and an advanced one
            # is six, and an unchallenged maneuver is basic whatever the
            # mode -- see `RulesEngine.maneuver_tiers`. Asking there is
            # what keeps these buttons, the hand image above them and
            # `pick`'s own check from disagreeing about what a coach may
            # play.
            maneuvers = (
                cog.engine.maneuver_hand(game, match, side)
                if game is not None and match is not None
                else cog.maneuver_catalog.for_tier(side, MANEUVER_TIER_BASIC)
            )

            # A tutorial beat rails the coach onto one card, and the
            # others are built **disabled** rather than left out -- the
            # whole point of the lesson is reading what the hand holds.
            # Dinky's side is never on this prompt at all, so this only
            # ever narrows a human's. See d12ball/tutorial.py.
            allowed = (
                tutorial.allowed_maneuvers(cog.tutorial_beat(game), side)
                if game is not None
                else None
            )

            buttons = []
            for maneuver in maneuvers:
                button = discord.ui.Button(
                    label=maneuver.name,
                    # The cards' own two colours, so a coach picks their
                    # row out of a prompt holding both without reading
                    # the labels: offense red, defense green, exactly as
                    # `d12ball/cards.py` and the reference hexagon draw
                    # them.
                    style=(
                        discord.ButtonStyle.danger
                        if side == "offense"
                        else discord.ButtonStyle.success
                    ),
                    custom_id=(
                        f"d12ball:maneuver_pick:{game_id}:{side}:"
                        f"{maneuver.key}"
                    ),
                    disabled=(
                        allowed is not None and maneuver.key not in allowed
                    ),
                )

                async def callback(
                    interaction: discord.Interaction,
                    chosen_side: str = side,
                    chosen_key: str = maneuver.key,
                ) -> None:
                    await self.pick(interaction, chosen_side, chosen_key)

                button.callback = callback
                buttons.append(button)

            rows.extend(even_button_rows(buttons))

        # Its own row where there is one, so a grey button does not read
        # as the tail of a coloured row. Its custom_id carries the game
        # like the picks do but no side: the hexagon is the same picture
        # for both coaches.
        reference = discord.ui.Button(
            label="Maneuver Reference",
            style=discord.ButtonStyle.secondary,
            custom_id=f"d12ball:maneuver_reference:{game_id}",
        )
        reference.callback = self.show_reference
        if len(rows) < MAX_BUTTON_ROWS:
            rows.append([reference])
        else:
            # Only reachable if a side ever grows past what four rows
            # hold. Falling back to the first row with space keeps the
            # reference reachable rather than raising on view build.
            next(row for row in rows if len(row) < MAX_BUTTONS_PER_ROW).append(
                reference
            )

        for index, row in enumerate(rows):
            for button in row:
                button.row = index
                self.add_item(button)

    async def show_reference(self, interaction: discord.Interaction) -> None:
        """
        The defeat cycle, ephemeral to the coach who asked.

        Ephemeral for the pick's own reason rather than its own:
        answering in the channel would tell the other side that this
        coach is still choosing. The image is public information either
        coach may ask for at any time, so nothing is hidden by it --
        only the timing.
        """
        await interaction.response.send_message(
            file=self.cog.build_maneuver_reference_file(
                self.cog.reference_tier(self.cog.games.get(self.game_id))
            ),
            ephemeral=True,
        )
        # The hexagon's labels are small print at the size Discord shows
        # an image inline, the same reason the hand carries a link. No
        # view goes with it, so there are no buttons for the edit to
        # drop. Webhook route -- see "Discord's rate limits".
        await add_full_image_button_to_response(interaction)

    def pick_refusal(
        self,
        game: D12BallGame,
        match: MatchState,
        side: str,
        maneuver_key: str,
        user_id: int,
    ) -> Optional[str]:
        """
        Why this click cannot be taken as a pick, or None.

        **Authorization is answered first**, and that ordering is a
        rule rather than a habit: the other coach's row is sitting on
        the same message, so replying "that side has already chosen"
        to a click on it would say whether they had.
        """
        if side == "offense":
            authorized = self.cog.engine.user_controls_possession(
                user_id, game, match,
            )
            already_chosen = match.offense_maneuver is not None
        else:
            authorized = self.cog.engine.user_controls_defense(
                user_id, game, match,
            )
            already_chosen = match.defense_maneuver is not None

        if not authorized:
            return "Only the player on that side can choose this maneuver."

        if already_chosen:
            return "You have already chosen your maneuver."

        # An older prompt can still be sitting in the channel, so the
        # rail is re-read here rather than trusted from the build --
        # exactly as the distances are in HighPassChoiceView.choose.
        allowed = tutorial.allowed_maneuvers(
            self.cog.tutorial_beat(game), side,
        )
        if allowed is not None and maneuver_key not in allowed:
            return (
                "This step of the tutorial wants "
                f"**{self.cog.engine.maneuver_name(allowed[0])}**. Use the "
                "prompt at the bottom of the channel."
            )

        # Same reason as the rail above: an advanced card clicked off an
        # older prompt would be a maneuver this turn does not play.
        playable = {
            maneuver.key
            for maneuver in self.cog.engine.maneuver_hand(game, match, side)
        }
        if maneuver_key not in playable:
            return (
                "That maneuver isn't in your hand for this turn. Use the "
                "prompt at the bottom of the channel."
            )

        return None

    async def pick(
        self,
        interaction: discord.Interaction,
        side: str,
        maneuver_key: str,
    ) -> None:
        """
        One coach's pick, answered **ephemerally** -- which is the whole
        of what keeps it secret now that the buttons are public. The
        prompt itself is untouched, so the other coach sees no change of
        any kind.
        """
        game, match = await self.require_match(interaction)
        if game is None:
            return

        refusal = self.pick_refusal(
            game, match, side, maneuver_key, interaction.user.id,
        )
        if refusal is not None:
            await interaction.response.send_message(refusal, ephemeral=True)
            return

        if side == "offense":
            match.choose_offense_maneuver(maneuver_key)
        else:
            match.choose_defense_maneuver(maneuver_key)

        self.cog.persist(game, match)

        await interaction.response.send_message(
            "You chose "
            f"**{self.cog.engine.maneuver_name(maneuver_key)}**.",
            ephemeral=True,
        )

        # "Someone has picked, you can't see what" is only worth a
        # message while the other side is still choosing. An
        # uncontested maneuver has nobody else to keep in the dark,
        # and the reveal a moment from now names the pick anyway.
        if not match.maneuver_uncontested:
            side_number = (
                self.cog.engine.possession_player_number(game, match)
                if side == "offense"
                else self.cog.engine.defending_player_number(game, match)
            )
            side_display = format_player_with_team(game, side_number)
            await interaction.followup.send(
                f"{side_display} has picked their maneuver.",
            )

        await self.cog.close_maneuver_prompt(interaction, game, match)

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

    def score_skill_test(
        self,
        game: D12BallGame,
        match: MatchState,
        offense_player: PlayerDefinition,
        defense_player: PlayerDefinition,
    ) -> tuple[list[tuple[int, Team, list[str], int]], int, int]:
        """
        Roll the maneuver skill test and add everything that counts
        towards it, as the two sides `render_contest_dice` draws plus
        the totals the outcome is read off.

        The dice image carries the whole arithmetic -- who rolled, what
        they rolled, every modifier and the total -- which is why no
        message that posts one repeats it in text.

        Nothing here is withheld for injury. What an injured player
        loses is their own offensive or defensive skill and only in a
        contest, which is the loose ball and the shootout; a maneuver's
        skill test pays every modifier to an injured player. See
        "Injured players" in docs/living-rules.md.
        """
        offense_skill = self.cog.player_catalog.effective_profile(
            offense_player,
        ).offense
        defense_skill = self.cog.player_catalog.effective_profile(
            defense_player,
        ).defense

        scripted = self.cog.tutorial_dice(game, "skill_test", 2)
        offense_roll, defense_roll = (
            scripted if scripted else
            (random.randint(1, 12), random.randint(1, 12))
        )
        offense_total = offense_roll + offense_skill
        defense_total = defense_roll + defense_skill

        offense_detail = contestant_detail(
            offense_player, "Offensive", offense_skill,
        )
        defense_detail = contestant_detail(
            defense_player, "Defensive", defense_skill,
        )

        # Role ability -- Midfielder: +3 on a skill test when
        # attempting Low Pass (offense) or Pressure (defense).
        #
        # **Read by rank, so an advanced card inherits it.** The
        # Midfielder's +3 and the ball speed modifier below are listed
        # against both cards on their rank in the sheet's own
        # `Interactions` column, and neither contradicts what the
        # advanced card does. The three that *do* contradict -- the
        # Fullback on Clear, the Playmaker on Dribble Burst, the
        # Fullback's pass distance on Setup Pass -- are the author's to
        # settle and are deliberately not inherited anywhere; see
        # "Still open" in docs/advanced-maneuver-matrix.md.
        if (
            offense_player.role == PlayerRole.MIDFIELDER
            and match.offense_maneuver in ("low_pass", "skilled_pass")
        ):
            offense_total += 3
            offense_detail.append("+3 Midfielder ability")

        if (
            defense_player.role == PlayerRole.MIDFIELDER
            and match.defense_maneuver in ("pressure", "double_team")
        ):
            defense_total += 3
            defense_detail.append("+3 Midfielder ability")

        if match.defense_maneuver in ("steal", "intercept"):
            modifier = match.ball.speed // 2
            defense_total += modifier
            defense_detail.append(f"+{modifier} ball speed modifier")

        # **A won Double Team lands on the *next* maneuver**: both
        # defenders challenge the ball holder, and both add their
        # defensive skill. `double_team_defenders` is challenger-first
        # and holds the second only while `pending_double_team` is set,
        # which one card sets and a new play clears -- so this is a
        # no-op in every game that never played it.
        double_team_detail = ""
        partners = [
            player_id
            for player_id in self.cog.engine.double_team_defenders(match)
            if player_id != match.challenger_id
        ]
        for player_id in partners:
            partner = self.cog.engine.get_player_definition(player_id)
            partner_skill = self.cog.player_catalog.effective_profile(
                partner
            ).defense
            defense_total += partner_skill
            double_team_detail = (
                f"+{partner_skill} {partner.name} (Double Team)"
            )
        if double_team_detail:
            defense_detail.append(double_team_detail)

        return (
            [
                (
                    offense_roll,
                    match.team_for_player(offense_player.player_id),
                    offense_detail,
                    offense_total,
                ),
                (
                    defense_roll,
                    match.team_for_player(defense_player.player_id),
                    defense_detail,
                    defense_total,
                ),
            ],
            offense_total,
            defense_total,
        )

    async def roll(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if match.offense_maneuver is None or match.defense_maneuver is None:
            await interaction.response.send_message(
                "This skill test is no longer active.",
                ephemeral=True,
            )
            return

        if not self.is_game_participant(game, interaction.user.id):
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

        offense_player = self.cog.engine.get_player_definition(
            match.active_player_id,
        )
        defense_player = self.cog.engine.get_player_definition(
            match.challenger_id,
        )

        contestants, offense_total, defense_total = self.score_skill_test(
            game, match, offense_player, defense_player,
        )
        dice_file = await render_contest_dice(
            contestants, filename="skill_test_dice.png",
        )

        if offense_total == defense_total:
            await interaction.edit_original_response(
                content=self.pay_skill_test_tie(
                    game,
                    match,
                    match.active_player_id,
                    match.challenger_id,
                    offense_total,
                    defense_total,
                ),
                attachments=[dice_file],
                view=SkillTestView(self.cog, self.game_id),
            )
            await self.cog.refresh_match_image(interaction, game)
            return

        outcome = "offense" if offense_total > defense_total else "defense"
        winner_key = (
            match.offense_maneuver
            if outcome == "offense"
            else match.defense_maneuver
        )
        winner_name = self.cog.engine.maneuver_name(winner_key)

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

        # The effect is on the far side of the injury tests now that
        # each of those is a click of its own, so it is handed over as
        # the queue's continuation rather than awaited here -- see
        # begin_injury_tests. With nobody exhausted this still resolves
        # in the same breath as the roll.
        await self.cog.begin_injury_tests(
            interaction,
            game,
            match,
            exhausted_participants,
            {"kind": "maneuver_effect", "winner_key": winner_key},
        )


class InjuryTestView(SafeView):
    """
    The injury test one exhausted participant owes after a contest.
    Posted one at a time by `continue_injury_tests`, which is also what
    the click hands the turn back to.

    The player is in the custom_id as well as the queue, so a coach who
    scrolls back to the first of two prompts and clicks it again cannot
    roll the second player's test with it.
    """

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

        button = discord.ui.Button(
            label="Roll the injury test",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:injury_test:{game_id}:{player_id}",
        )
        button.callback = self.roll
        self.add_item(button)

    async def roll(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if self.player_id not in match.pending_injury_tests:
            await interaction.response.send_message(
                "This injury test is no longer active.",
                ephemeral=True,
            )
            return

        if not self.is_game_participant(game, interaction.user.id):
            await interaction.response.send_message(
                "Only a player in this game can roll the injury test.",
                ephemeral=True,
            )
            return

        # Deferred before the die is rendered, for the reason spelled
        # out in SkillTestView.roll.
        await interaction.response.defer()

        await self.cog.run_injury_test(
            interaction,
            game,
            match,
            self.cog.engine.get_player_definition(self.player_id),
        )


class OwnGoalRollView(SafeView):
    """
    The roll that decides an own goal Pressure has pushed a side into.
    One roll, by one player, but any coach in the game may press it --
    the same as the skill test and the score attempt, and what keeps a
    solo game moving when the risk is the AI's.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        button = discord.ui.Button(
            label="Roll for the own goal",
            style=discord.ButtonStyle.danger,
            custom_id=f"d12ball:own_goal:{game_id}",
        )
        button.callback = self.roll
        self.add_item(button)

    async def roll(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not match.pending_own_goal or match.active_player_id is None:
            await interaction.response.send_message(
                "This own goal roll is no longer active.",
                ephemeral=True,
            )
            return

        if not self.is_game_participant(game, interaction.user.id):
            await interaction.response.send_message(
                "Only a player in this game can roll for the own goal.",
                ephemeral=True,
            )
            return

        # Deferred before the dice are rendered, for the reason spelled
        # out in SkillTestView.roll.
        await interaction.response.defer()

        await self.cog.run_own_goal_roll(interaction, game, match)


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

    def score_score_attempt(
        self,
        match: MatchState,
        shooter: PlayerDefinition,
        attacking_setup: TeamSetup,
        defending_setup: TeamSetup,
    ) -> tuple[list[tuple[int, Team, list[str], int]], int, int]:
        """
        Roll the shot and price the wall in front of it, as the two
        sides `render_contest_dice` draws plus the totals the verdict
        is read off.

        Everything that built the two totals is drawn on the dice
        image, which is why no message that posts one repeats it in
        text.
        """
        offense_skill = self.cog.player_catalog.effective_profile(
            shooter,
        ).offense
        speed_modifier = match.ball_speed_modifier()
        defenders = self.cog.engine.intervening_defenders(match)
        # What each defender is worth here, not what they are worth --
        # a defender off the ball adds half their skill, rounded up.
        # See ShotDefender.
        defense_skill_total = sum(defender.value for defender in defenders)

        # Two dice, one per human: the attacker adds the shooting
        # player's offensive skill and the ball-speed modifier, the
        # defence adds the defensive skill of every meeple in the way.
        # The speed modifier is signed -- an overshot High Pass pays it
        # against the shot -- so it is added, never abs()'d.
        attack_roll = random.randint(1, 12)
        defense_roll = random.randint(1, 12)
        attack_total = attack_roll + offense_skill + speed_modifier
        defense_total = defense_roll + defense_skill_total

        attack_detail = contestant_detail(shooter, "Offensive", offense_skill)
        if speed_modifier:
            attack_detail.append(f"{speed_modifier:+d} ball speed modifier")

        # Role ability -- Striker: +3 on any scoring attempt off a
        # set-up. Injury does not withhold this one, deliberately: an
        # injured player loses their ability modifier on a roll someone
        # is contesting, and nobody contests a shot (see "Injured
        # players" in docs/living-rules.md). Don't add match.injured
        # here to match the skill test.
        if match.pending_shot_is_set_up and shooter.role == PlayerRole.STRIKER:
            attack_total += 3
            attack_detail.append("+3 Striker ability")

        if defenders:
            defense_detail = [
                f"{defender.player.name} "
                f"[{ROLE_INITIALS[defender.player.role.value]}] "
                f"+{defender.value}"
                + ("" if defender.on_ball else f" (half of {defender.defense})")
                for defender in defenders
            ]
            if len(defenders) > 1:
                defense_detail.append(
                    f"Total defensive skill +{defense_skill_total}"
                )
        else:
            defense_detail = ["No one in the way"]

        return (
            [
                (
                    attack_roll,
                    attacking_setup.team,
                    attack_detail,
                    attack_total,
                ),
                (
                    defense_roll,
                    defending_setup.team,
                    defense_detail,
                    defense_total,
                ),
            ],
            attack_total,
            defense_total,
        )

    def settle_score_attempt(
        self,
        game: D12BallGame,
        match: MatchState,
        shooter: PlayerDefinition,
        attacking_setup: TeamSetup,
        defending_setup: TeamSetup,
        scored: bool,
    ) -> tuple[str, int]:
        """
        Credit the goal or the miss, restart play from it, and word the
        verdict -- with the clock cost the run back behind it is owed.
        """
        if scored:
            # Logged as it is credited, and stamped with the clock as
            # it stands: the shot's own cost is charged afterwards, so
            # this is the minute the ball crossed the line rather than
            # the minute play restarted.
            match.award_goal(shooter.player_id)
            verdict = (
                "# GOAL!\n"
                f"{format_role_bracket(shooter, self.cog.team_emojis, match.team_for_player(shooter.player_id))} scores "
                f"for {format_team_side_label(attacking_setup)} on "
                f"**{format_goal_time(match.goals[-1])}**!\n"
                f"{team_display_name(match.home.team)} "
                f"{match.scoreboard.home_score}:"
                f"{match.scoreboard.visiting_score} "
                f"{team_display_name(match.visiting.team)}"
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
        if match.pending_shot_is_set_up:
            verdict += "\n\n" + self.cog.apply_exhaustion(
                match, shooter.player_id, 1,
            )

        # Every score attempt is a turnover, win or miss: the clock
        # cost is a flat space minute (2026-08-16), plus the cost of
        # whatever maneuver set it up if this was a set-up shot rather
        # than an ordinary one -- pending_shot_setup_cost is 0 for an
        # ordinary shot, so this is 1 there and maneuver-cost-plus-1
        # for a set-up. The team that just defended restarts play --
        # in the middle of the midfield on a goal (the same kickoff
        # rule as the start of a half), or at the space closest to
        # their own goal on a miss.
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
        space_minutes = 1 + match.pending_shot_setup_cost
        new_possession_side = defending_setup.side
        if scored:
            match.restart_after_goal(new_possession_side)
        else:
            # Unlike a goal's kickoff space, nothing guarantees an
            # arrangement covers the space closest to the defending
            # side's own goal -- so, since 2026-08-24, this restart
            # owes the same pickup an out-of-bounds ball does rather
            # than falling through to a two-sided loose ball. Set
            # before the reset (in roll, via begin_run_back's
            # new_play): begin_ball_recovery checks
            # eligible_ball_handlers() first and asks nobody when the
            # arrangement already covers it.
            match.restart_after_missed_score(new_possession_side)
            match.pending_ball_recovery = True

        # Save a reconstructible run-back state before refreshing the
        # persistent board. begin_run_back repeats this assignment
        # idempotently when it posts the run-back announcement.
        match.pending_run_back = True
        match.pending_run_back_distance = space_minutes
        match.pending_run_back_turnover = True
        self.cog.persist(game, match)

        return verdict, space_minutes

    async def roll(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if match.pending_action != "shoot" or match.active_player_id is None:
            await interaction.response.send_message(
                "This score attempt is no longer active.",
                ephemeral=True,
            )
            return

        if not self.is_game_participant(game, interaction.user.id):
            await interaction.response.send_message(
                "Only a player in this game can roll the score attempt.",
                ephemeral=True,
            )
            return

        shooter = self.cog.engine.get_player_definition(match.active_player_id)
        attacking_setup = match.setup_for_side(match.ball.possession)
        defending_setup = match.setup_for_side(match.defending_side())

        contestants, attack_total, defense_total = self.score_score_attempt(
            match, shooter, attacking_setup, defending_setup,
        )
        dice_file = await render_contest_dice(
            contestants, filename="score_attempt_dice.png",
        )

        scored = attack_total >= defense_total
        verdict, space_minutes = self.settle_score_attempt(
            game, match, shooter, attacking_setup, defending_setup, scored,
        )

        # The dice image carries the maths that produced it, and the
        # verdict follows in its own message. A message's attachments
        # always render *below* its content, so a verdict written into
        # this one would be read before the roll it is announcing.
        await interaction.response.edit_message(
            content=None,
            attachments=[dice_file],
            view=None,
        )
        await interaction.followup.send(verdict)
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
        # No board refresh here: every path out of begin_run_back
        # below puts one up within the same click, over a position
        # this one would draw a moment before. A new play goes to
        # announce_new_play_reset, which restores both arrangements
        # and posts the settled board through post_new_play_board;
        # last possession goes to end_period, which refreshes in both
        # of its own branches. So this drew a board nobody reads --
        # the restarted ball without the reset behind it -- and, worse,
        # it took the game's write window, pushing the board that *is*
        # worth reading out of the render post_new_play_board already
        # has in hand and into a trailing pass. See "Discord's rate
        # limits" in CLAUDE.md.
        #
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

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        key: str = "low_pass",
        free: bool = False,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        # Which card is being resolved, so the destinations offered are
        # the ones that card actually reaches -- a Skilled Pass reaches
        # any teammate within 3 spaces, ahead or behind. `free` is the
        # unopposed pass Skilled Pass's cost hands the defense, which
        # charges no clock.
        self.key = key
        self.free = free

        game, match = self.load_match()
        if game is None:
            return

        for distance, teammate_id in cog.engine.pass_candidates(match, key):
            teammate = cog.engine.get_player_definition(teammate_id)
            origin_flat = match.board.flat_index(
                match.ball.zone, match.ball.space_index,
            )
            target_flat = match.relative_flat_index(
                origin_flat, match.ball.possession, distance,
            )
            zone, space_index = match.board.position_at_flat_index(
                target_flat,
            )
            receivers = cog.engine.low_pass_receivers(match, distance)
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
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        offense_side = match.ball.possession
        receivers = self.cog.engine.low_pass_receivers(match, distance)
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        target_flat = match.relative_flat_index(
            origin_flat, offense_side, distance,
        )
        zone, space_index = match.board.position_at_flat_index(target_flat)
        team_name = team_display_name(match.setup_for_side(offense_side).team)

        if len(receivers) > 1:
            await interaction.response.edit_message(
                content=(
                    f"**{interaction.user.display_name} ({team_name})** is "
                    f"passing to {space_label(zone, space_index)}. Which "
                    "player receives it?"
                ),
                view=LowPassReceiverView(
                    self.cog, self.game_id, distance,
                    key=self.key, free=self.free,
                ),
            )
            return

        teammate = self.cog.engine.get_player_definition(receivers[0])
        await interaction.response.edit_message(
            content=(
                f"**{interaction.user.display_name} ({team_name})** chose "
                "to pass the ball to "
                f"{format_role_bracket(teammate, self.cog.team_emojis, match.team_for_player(teammate.player_id))} at "
                f"{space_label(zone, space_index)}."
            ),
            view=None,
        )
        await self.cog.apply_low_pass(
            interaction, game, match, distance, receiver_id=receivers[0],
            key=self.key, free=self.free,
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

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        distance: int,
        key: str = "low_pass",
        free: bool = False,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.distance = distance
        self.key = key
        self.free = free

        game, match = self.load_match()
        if game is None:
            return

        for player_id in cog.engine.low_pass_receivers(match, distance):
            player = cog.engine.get_player_definition(player_id)
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
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        if receiver_id not in self.cog.engine.low_pass_receivers(
            match, self.distance,
        ):
            await interaction.response.send_message(
                "That player is no longer standing there.",
                ephemeral=True,
            )
            return

        offense_side = match.ball.possession
        receiver = self.cog.engine.get_player_definition(receiver_id)
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        zone, space_index = match.board.position_at_flat_index(
            match.relative_flat_index(origin_flat, offense_side, self.distance)
        )
        team_name = team_display_name(match.setup_for_side(offense_side).team)

        await interaction.response.edit_message(
            content=(
                f"**{interaction.user.display_name} ({team_name})** chose "
                "to pass the ball to "
                f"{format_role_bracket(receiver, self.cog.team_emojis, match.team_for_player(receiver.player_id))} at "
                f"{space_label(zone, space_index)}."
            ),
            view=None,
        )
        await self.cog.apply_low_pass(
            interaction, game, match, self.distance, receiver_id=receiver_id,
            key=self.key, free=self.free,
        )


class SetupPassChoiceView(SafeView):
    """
    Where a won **Setup Pass** lands: 0, 1 or 3 spaces, and the
    teammate standing there takes a scoring opportunity.

    Reconstructible on restart from match state, the same as every
    other persistent view here -- but only reached at all while
    `pending_effect_continuation` says the speed half of the card is
    already done, which is what `build_effect_choice_view` reads.

    **Every distance that fits on the field is offered**, whether or
    not a teammate is standing there (the author, 2026-08-25) -- the
    button says which, and picking one out into empty space leaves the
    ball lying there rather than being refused. `0` is the one
    exception: it means a teammate sharing the passer's own space, so
    it is on the menu only while somebody else is standing there. With
    nothing at all on the menu -- the passer on the last space of the
    field with nobody beside them -- the view is not shown and the pass
    goes out (see `D12Ball.apply_setup_pass_out`).
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game, match = self.load_match()
        if game is None:
            return

        for distance in cog.engine.setup_pass_distances(match):
            note = (
                "same space"
                if distance == 0
                else cog.engine.high_pass_destination_note(match, distance)
            )
            # 1 is a distance this card offers and the High Pass does
            # not, so this is the one pass menu that can read "1
            # spaces" if nothing here says otherwise.
            space_word = "space" if distance == 1 else "spaces"
            button = discord.ui.Button(
                label=f"{distance} {space_word} ({note})",
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:setup_pass:{game_id}:{distance}",
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
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        # Re-read rather than trusted: this prompt carries no message
        # id, so an older one still in the channel dispatches here too.
        if distance not in self.cog.engine.setup_pass_distances(match):
            await interaction.response.edit_message(
                content=(
                    "That distance is not on offer any more -- 0 spaces "
                    "needs a teammate in your own space, and every other "
                    "distance has to fit on the field. Use "
                    "`/d12ball resume` to put the choice back up."
                ),
                view=None,
                attachments=[],
            )
            return

        team_name = team_display_name(
            match.setup_for_side(match.ball.possession).team
        )
        # The field strip goes with the question: it shows the ball
        # where it was before the pass, so leaving it under the answer
        # would put a stale position in the channel.
        await interaction.response.edit_message(
            content=(
                f"**{interaction.user.display_name} ({team_name})** picks "
                f"out a **Setup Pass** of {distance}."
            ),
            view=None,
            attachments=[],
        )
        await self.cog.apply_setup_pass(interaction, game, match, distance)


class SetupPassPushBackView(SafeView):
    """
    **Setup Pass's cost**, put to the coach who beat it: how far back
    the ball is driven -- 1, 2 or 3 spaces -- before it is left loose.

    The choice belongs to the *defending* side, which is the side that
    won the maneuver, so this is the one prompt in a maneuver's effect
    that the defense answers and the offense watches.

    Not reconstructible from match state: by the time it is up, the
    deflection has already landed and nothing on the match says a
    push-back is owed. A restart mid-choice comes back to whatever
    `pending_turn_view` makes of the position, which is the same gap
    `SetUpAttemptChoiceView` has and for the same reason -- nothing has
    been applied yet.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game, match = self.load_match()
        if game is None:
            return

        offense_side = match.ball.possession
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        for distance in (1, 2, 3):
            target_flat = match.relative_flat_index(
                origin_flat, offense_side, -distance,
            )
            if abs(target_flat - origin_flat) != distance:
                continue
            zone, space_index = match.board.position_at_flat_index(target_flat)
            button = discord.ui.Button(
                label=(
                    f"{distance} back ({space_label(zone, space_index)})"
                ),
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:setup_pass_push:{game_id}:{distance}",
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
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_defense(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the coach who beat the Setup Pass can choose.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(view=None)
        await self.cog.apply_setup_pass_push_back(
            interaction, game, match, distance,
        )


class HighPassChoiceView(SafeView):
    """
    Distance for a won High Pass -- 2 or 3 spaces, or up to 4 for a
    Fullback (their ability extends the max, not the min).
    Reconstructible on restart purely from match state, the same
    pattern every other persistent view in this cog follows.

    **Only distances that fit on the field are offered** (2026-08-10),
    from D12Ball.high_pass_distance_options: a longer pass that lands
    where a shorter one already would is the same pass at a
    disadvantage, so a Fullback near the end is not offered 4 and
    nobody is offered 3 when a 2 fits. When nothing fits the view is
    not shown at all -- resolve_high_pass sends the pass straight to
    its overshoot rather than putting up one answer three times.

    **The prompt carries the field strip**, for the reason the maneuver
    cards do: which distance to throw is a question about where
    everybody is standing and how far the end of the field is, and the
    persistent board has scrolled away by this point in a turn. It is
    an attachment on the prompt rather than a message of its own --
    unlike the field under the cards, which shares its message with the
    hand and would be laid out beside it -- so `choose` can strip it
    with `attachments=[]` in the edit it was already making. Leaving it
    under the answer would show the ball where it was before the pass.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game, match = self.load_match()
        if game is None:
            return

        distances = cog.engine.high_pass_distance_options(match)
        railed = cog.tutorial_railed_option(game, "high_pass", distances)

        for distance in distances:
            ability_note = " (Fullback ability)" if distance == 4 else ""
            destination_note = cog.engine.high_pass_destination_note(match, distance)
            button = discord.ui.Button(
                label=(
                    f"{distance} spaces{ability_note} ({destination_note})"
                ),
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:high_pass:{game_id}:{distance}",
                disabled=railed is not None and distance != railed,
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
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        # A click on a menu the ball has since moved out from under --
        # an older prompt still sitting in the channel, since these
        # buttons carry no message id. The distances are read off the
        # match rather than off the view for exactly that reason.
        if distance not in self.cog.engine.high_pass_distance_options(match):
            await interaction.response.send_message(
                f"A {distance}-space pass runs off the end of the field "
                "from where the ball is now.",
                ephemeral=True,
            )
            return

        railed = self.cog.tutorial_railed_option(
            game, "high_pass",
            self.cog.engine.high_pass_distance_options(match),
        )
        if railed is not None and distance != railed:
            await interaction.response.send_message(
                "The tutorial is on one step of a single continuous game, "
                "so this choice is fixed. Use the prompt at the "
                "bottom of the channel.",
                ephemeral=True,
            )
            return

        # `attachments=[]` takes the field strip with the question it
        # answered. It shows the ball where it was *before* the pass, so
        # leaving it under the answer would put a stale position in the
        # channel for the rest of the game -- the same reason the run
        # back drops its snapshot on the click.
        await interaction.response.edit_message(
            content=f"Chose **{distance} spaces**.",
            view=None,
            attachments=[],
        )
        await self.cog.apply_high_pass(interaction, game, match, distance)


class SetUpAttemptChoiceView(SafeView):
    """
    Whether to take an offered scoring-opportunity shot -- a High
    Pass's own 2-space pass, a High Pass that overshoots the field, or
    a Winger's Low Pass ability -- or let the maneuver resolve as a
    normal pass instead. Declining meant the same thing everywhere
    between 2026-08-07, when a 2-space High Pass stopped forcing a
    contest for the ball it had just delivered, and 2026-08-10, when an
    overshoot started offering a shot *or* a contest, both at the same
    disadvantage: `contest_on_decline` is that one case, and the button
    says so rather than promising a normal pass it will not deliver.

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
        contest_on_decline: bool = False,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.shooter_id = shooter_id
        self.distance_moved = distance_moved
        self.contest_on_decline = contest_on_decline

        shooter = cog.engine.get_player_definition(shooter_id)
        attempt_button = discord.ui.Button(
            label=f"{shooter.name} takes the shot",
            style=discord.ButtonStyle.danger,
            custom_id=f"d12ball:setup_attempt:{game_id}:attempt",
        )
        attempt_button.callback = self.attempt
        self.add_item(attempt_button)

        decline_button = discord.ui.Button(
            label=(
                "Decline -- contest for the ball"
                if contest_on_decline
                else "Decline -- resolve as a normal pass"
            ),
            style=discord.ButtonStyle.secondary,
            custom_id=f"d12ball:setup_attempt:{game_id}:decline",
            # The tutorial ends on this shot, so declining it would end
            # the script on a pass and no goal.
            disabled=cog.tutorial_railed_option(
                cog.games.get(game_id),
                "setup_attempt",
                ("attempt", "decline"),
            ) == "attempt",
        )
        decline_button.callback = self.decline
        self.add_item(decline_button)

    async def attempt(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        shooter = self.cog.engine.get_player_definition(self.shooter_id)
        await interaction.response.edit_message(
            content=(
                f"{format_role_bracket(shooter, self.cog.team_emojis, match.team_for_player(shooter.player_id))} "
                "takes the shot."
            ),
            view=None,
        )
        await self.cog.start_set_up_shot(
            interaction, game, match, self.shooter_id,
            maneuver_cost=self.distance_moved,
        )

    async def decline(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_possession(
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
            contest=self.contest_on_decline,
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

        # The two distances are two spaces, and which they are depends
        # on where the handler is standing and which way their side
        # attacks -- neither of which "1 or 2" tells a coach. Naming
        # the destination also shows when the longer dribble buys
        # nothing, because the field ran out and both clamp to the same
        # space.
        game = cog.games.get(game_id)
        match = (
            cog.engine.load_match_state(game)
            if game is not None and game.match_state is not None
            else None
        )

        railed = cog.tutorial_railed_option(game, "dribble_advance", (1, 2))

        for distance in (1, 2):
            space_word = "space" if distance == 1 else "spaces"
            destination = (
                match.relative_move_destination(
                    match.active_player_id, match.ball.possession, distance,
                )
                if match is not None and match.active_player_id is not None
                else None
            )
            destination_note = (
                f" ({space_label(*destination)})"
                if destination is not None
                else ""
            )
            button = discord.ui.Button(
                label=f"Advance {distance} {space_word}{destination_note}",
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:dribble_advance:{game_id}:{distance}",
                # Railed during the tutorial: where the ball ends up is
                # what the next beat is written against.
                disabled=railed is not None and distance != railed,
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
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        railed = self.cog.tutorial_railed_option(
            game, "dribble_advance", (1, 2),
        )
        if railed is not None and distance != railed:
            await interaction.response.send_message(
                "The tutorial is on one step of a single continuous game, "
                "so this choice is fixed. Use the prompt at the "
                "bottom of the channel.",
                ephemeral=True,
            )
            return

        space_word = "space" if distance == 1 else "spaces"
        await interaction.response.edit_message(
            content=f"Chose **{distance} {space_word}**.",
            view=None,
        )
        await self.cog.apply_dribble_advance(interaction, game, match, distance)


class DribbleBurstChoiceView(SafeView):
    """
    How far a won Dribble Burst runs: 1 up to
    `DRIBBLE_BURST_MAX_DISTANCE`, less anything the end of the field
    takes away. Shaped like DribbleAdvanceChoiceView, which is the
    other dribble that asks a distance, and reconstructible on restart
    from match state alone (see D12Ball.build_effect_choice_view).

    **Every button carries its price**, because the exhaustion is a
    token a space and that is the whole of what makes the shorter runs
    worth offering -- the same reasoning as RunBackChoiceView's
    `M2 (4 spaces)` labels, where the distance *is* the cost. The
    Playmaker's token off comes out of the total rather than off each
    space, so it is named once beside the run it discounts rather than
    subtracted from every label.

    A handler already on the last space of the field never sees this:
    resolve_dribble_burst applies a run of 0 without a prompt.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game, match = self.load_match()
        if game is None or match.active_player_id is None:
            # No handler means no run to price. Only reachable in the
            # same narrow crash window every other reconstructed view
            # has; the empty view falls back to PlayerActionView.
            return

        handler_id = match.active_player_id
        playmaker = (
            cog.engine.get_player_definition(handler_id).role
            == PlayerRole.PLAYMAKER
        )

        for distance in cog.engine.dribble_burst_distances(match):
            space_word = "space" if distance == 1 else "spaces"
            # Naming the destination is what "3 spaces" does not say:
            # which way this side attacks and where that lands is read
            # off the board, and the board has usually scrolled away.
            destination = match.relative_move_destination(
                handler_id, match.ball.possession, distance,
            )
            tokens = max(0, distance - (1 if playmaker else 0))
            token_word = "token" if tokens == 1 else "tokens"
            button = discord.ui.Button(
                label=(
                    f"{distance} {space_word} "
                    f"({space_label(*destination)}, {tokens} {token_word})"
                ),
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:dribble_burst:{game_id}:{distance}",
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
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        # A stale click: an older prompt in the channel, or one the
        # handler has since been moved out from under. The menu carries
        # no message id, so this is the check that catches it -- the
        # same refusal HighPassChoiceView makes for the same reason.
        if distance not in self.cog.engine.dribble_burst_distances(match):
            await interaction.response.send_message(
                "That distance is no longer available.",
                ephemeral=True,
            )
            return

        space_word = "space" if distance == 1 else "spaces"
        await interaction.response.edit_message(
            content=f"Chose **{distance} {space_word}**.",
            view=None,
        )
        await self.cog.apply_dribble_burst(interaction, game, match, distance)


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

        game, match = self.load_match()
        if game is None:
            return
        profile = cog.player_catalog.effective_profile(
            cog.engine.get_player_definition(player_id),
        )
        skill = profile.offense if skill_type == "offense" else profile.defense
        current = match.ball.speed

        # The targets are collected before any button is built, because
        # the tutorial's speed rail is "take the highest offered" -- the
        # cap is the stealer's own defensive skill, so the script cannot
        # name a number. See D12Ball.tutorial_railed_option.
        targets: list[int] = []
        for delta in range(-skill, skill + 1):
            target = max(1, min(12, current + delta))
            if target not in targets:
                targets.append(target)
        railed = cog.tutorial_railed_option(game, "speed", targets)

        for target in targets:
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
                # Railed during the tutorial -- the ball speed a steal
                # leaves behind is still on the ball when the striker
                # shoots two beats later.
                disabled=railed is not None and target != railed,
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
        game, match = await self.require_match(interaction)
        if game is None:
            return

        controller_id = self.cog.engine.controlling_user_id(
            game, match, self.player_id,
        )
        if interaction.user.id != controller_id:
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        # A steal -- basic or Intercept -- has already flipped possession
        # (and run the defense back) by the time this view is shown; a
        # dribble never triggers a turnover at all.
        turnover_occurred = match.defense_maneuver in ("steal", "intercept") and (
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


class TutorialContinueView(SafeView):
    """
    A single "Continue" button gating whatever comes next in a run of
    tutorial narration -- see D12Ball.post_tutorial_note. Two or more
    plain-text messages posted back to back with no click between them
    are exactly what gets scrolled past in Discord, so a note that has
    something following it is held here until the coach presses on,
    rather than dumped alongside the rest of the burst.

    Not restart-safe, the same tradeoff the rest of the tutorial makes
    -- see the module docstring in d12ball/tutorial.py: what a restart
    loses is a lesson's text, and a dead Continue button here is the
    same kind of loss. It is never registered with `bot.add_view`, so
    a restart while one is up leaves it unclickable; the game itself
    is unaffected; the coach's own next real action still works.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        on_continue: Callable[[discord.Interaction], Awaitable[None]],
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self._on_continue = on_continue

        button = discord.ui.Button(
            label="Continue",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:tutorial_continue:{game_id}",
        )
        button.callback = self._continue
        self.add_item(button)

    async def _continue(self, interaction: discord.Interaction) -> None:
        game, _ = self.load_match()
        if game is None or not self.is_game_participant(
            game, interaction.user.id,
        ):
            await interaction.response.send_message(
                "Only a coach in this game can continue.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(view=None)
        await self._on_continue(interaction)


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
            player = cog.engine.get_player_definition(player_id)
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
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        shooter = self.cog.engine.get_player_definition(shooter_id)
        await interaction.response.edit_message(
            content=(
                f"{format_role_bracket(shooter, self.cog.team_emojis, match.team_for_player(shooter.player_id))} "
                "takes the shot."
            ),
            view=None,
        )
        await self.cog.start_set_up_shot(interaction, game, match, shooter_id)


class RunBackPlayerChoiceView(SafeView):
    """
    Which of two teammates sharing a space runs back out of it -- the
    author's call, 2026-08-17; see "Running back after a steal" in
    docs/living-rules.md. The pair only differ in who they are, so the
    code has no business preferring one, and it used to keep whichever
    the space's occupant list started with.

    **It is only ever built where the choice is real.** A stack the
    ball's holder is standing in has one player to spare and no
    question to ask, and `next_run_back_step` hands that straight to
    the space prompt below.

    The answer is an edit of this same message rather than a new one:
    the board was uploaded for the "who" and is just as much the
    picture the "where" is read off, so re-posting would pay for the
    same render twice. That means carrying the full-image link across
    by hand -- editing a view replaces it wholesale, so the link has to
    be rebuilt onto the new one from the attachment already there (see
    add_full_image_button).
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        candidates: list[str],
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.candidates = list(candidates)

        game = cog.games.get(game_id)
        match = (
            cog.engine.load_match_state(game)
            if game is not None and game.match_state is not None
            else None
        )

        for player_id in self.candidates:
            player = cog.engine.get_player_definition(player_id)
            position = (
                match.board.meeple_position(player_id)
                if match is not None
                else None
            )
            button = discord.ui.Button(
                # The space is on the label because a stack can span
                # more than one of them: two pairs in a three-space
                # zone with one space free is four candidates, and
                # which pair they come from is the whole difference.
                label=(
                    f"{player.name} — {space_label(*position)}"
                    if position is not None
                    else player.name
                ),
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:run_back_who:{game_id}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_player: str = player_id,
            ) -> None:
                await self.choose(interaction, chosen_player)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        controller_id = self.cog.engine.controlling_user_id(game, match, player_id)
        if interaction.user.id != controller_id:
            await interaction.response.send_message(
                "Only that team's coach can choose this.",
                ephemeral=True,
            )
            return

        side = (
            TeamSide.HOME
            if player_id in match.home.field_players
            else TeamSide.VISITING
        )
        # Nothing is written until the space is picked, so a click on a
        # prompt the board has moved out from under is caught by asking
        # the position again rather than by a saved flag.
        if player_id not in self.cog.engine.run_back_crowded(match, side):
            await interaction.response.send_message(
                "They no longer have to run back.", ephemeral=True,
            )
            return

        space_view = RunBackChoiceView(self.cog, self.game_id, player_id)
        link = build_full_image_button(interaction.message)
        if link is not None:
            space_view.add_item(link)

        await interaction.response.edit_message(
            content=self.cog.run_back_space_prompt(
                match, side, player_id, f"<@{controller_id}>",
            ),
            view=space_view,
        )


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

        game, match = self.load_match()
        if game is None:
            return
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
                # The distance is on the label because it is the price:
                # a run back costs a token a space, so the two spaces of
                # a zone are rarely the same offer. See
                # travel_space_label.
                label=travel_space_label(
                    zone,
                    space_index,
                    match.run_back_distance(player_id, zone, space_index),
                ),
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
        game, match = await self.require_match(interaction)
        if game is None:
            return

        controller_id = self.cog.engine.controlling_user_id(
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
        self.cog.persist(game, match)

        player = self.cog.engine.get_player_definition(self.player_id)
        await interaction.response.edit_message(
            content=(
                f"{format_role_bracket(player, self.cog.team_emojis, match.team_for_player(player.player_id))} "
                f"runs back to {space_label(zone, space_index)}."
                f"\n{exhaustion_text}"
            ),
            view=None,
            # The board this prompt was asked over shows the player
            # still displaced, so it goes with the question rather than
            # standing under the answer. The refresh below puts the
            # board they moved to on the persistent message.
            attachments=[],
        )
        await self.cog.refresh_match_image(interaction, game)
        await self.cog.continue_run_back(interaction, game, match)


class CoachingView(SafeView):
    """
    Shared plumbing for the Coaching Choice flow -- the four actions a
    coach may take at setup, at a new play's window and at halftime,
    which are the same four every time; the window between full time
    and the shootout offers the substitution alone. See "Coaching
    Choice" in docs/living-rules.md.

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
        return self.load_match()

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
                "That Coaching Choice has already closed.",
                ephemeral=True,
            )
            return None, None
        if interaction.user.id != self.cog.engine.side_controller_id(
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
            "content": self.cog.engine.coaching_prompt(
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
        where = destination_display_name(zone.value, match.board.layout.board_size)
        if with_space:
            position = match.board.meeple_position(player_id)
            where = space_label(*position) if position else where
        return f"{self.cog.engine.format_roster_player(player_id)} - {where}"[:80]


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
        self.cog.persist(game, match)

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
                f"({team_display_name(setup.team)}) passed.**"
            ),
            view=None,
        )
        await self.cog.finish_substitution_window(interaction, game, match)


class CoachingHubView(CoachingView):
    """
    The buttons a Coaching Choice offers -- six of them, or three at
    full time. Each opens its own menu on this same message and every
    one of those comes back here.

    **The window before the shootout offers the substitution alone**,
    so the three positional buttons are not built at all rather than
    built and disabled: there is nothing a coach could do to enable
    them, and a shootout is not played on the board. That is the
    occasion's own property (`offers_positioning`) rather than a check
    on which occasion this is -- and it is why the three openers below
    need no stale-click guard, since a window that closes takes its
    view with it (see `finish`) and every hub is rebuilt from the state
    it is put up against.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(cog, game_id)

        game, match = self.load()
        if match is None or match.pending_coaching_side is None:
            return
        side = self.side(match)
        occasion = match.coaching_occasion
        positioning = occasion is None or occasion.offers_positioning

        if positioning:
            formation = cog.engine.current_formation(match, side)
            # The shape in brackets is the one they are in now, not the
            # one the button switches to, so it says so -- a bare
            # "(2-2-2)" reads as the destination.
            self.add_action(
                "Formation"
                + (f" (currently {formation.value})" if formation else ""),
                f"d12ball:coach_formation:{game_id}",
                self.open_formation,
            )
        self.add_action(
            f"Substitution ({cog.engine.substitution_button_label(match)})",
            f"d12ball:coach_sub:{game_id}",
            self.open_substitution,
            enabled=match.may_substitute()
            and bool(match.substitution_pool(side)),
        )
        if positioning:
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

        setups = self.cog.engine.roster_setups_for_user(
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
        refusal = self.cog.engine.coaching_finish_refusal(match, side)
        if refusal is not None:
            await interaction.response.send_message(refusal, ephemeral=True)
            return

        # What they did, while the window still remembers it: closing
        # it clears the record, and every note the flow put up along
        # the way was written over by the step after it -- this
        # message is the only place a coach's substitutions survive.
        setup = match.setup_for_side(side)
        changes = self.cog.coaching_summary(match, side)
        await interaction.response.edit_message(
            content="\n".join(
                [
                    "# Coaching Choice",
                    f"**{format_team_side_label(setup)} are done.**",
                    *(
                        changes
                        or ["No substitutions, and no change of shape."]
                    ),
                ]
            ),
            view=None,
        )
        await self.cog.finish_substitution_window(interaction, game, match)


class CoachingFormationView(CoachingView):
    """
    Pick a shape. Applying it re-deals the whole side by defensive
    skill and places every meeple, so this is one click rather than the
    six it used to take -- see D12Ball.formation_placement.

    Only the shapes this match's board plays are offered
    (D12Ball.available_formations): 3-2-1 and 1-2-3 are the nine-space
    board's, so on 6 and 7 there is nothing to grey out and three
    buttons is the whole menu.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(cog, game_id)

        game, match = self.load()
        if match is None or match.pending_coaching_side is None:
            return
        current = cog.engine.current_formation(match, self.side(match))

        for choice in cog.engine.available_formations(match):
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
            note = self.cog.engine.apply_formation(
                match, self.side(match), formation,
            )
        except ValueError as error:
            await interaction.response.send_message(
                str(error), ephemeral=True,
            )
            return

        self.cog.persist(game, match)
        await self.back_to_hub(interaction, note=note, moved=True)


class CoachingSubstitutionOutView(CoachingView):
    """Who comes off. Injured players are marked."""

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(cog, game_id)

        game, match = self.load()
        if match is None or match.pending_coaching_side is None:
            return
        side = self.side(match)
        # Who may come on does not depend on who goes off, so this is
        # all-or-nothing: with both benches spent there is nobody to
        # offer for anybody, and the hub has already disabled the
        # button that opens this. It used to be a per-player filter,
        # from when the back bench opened only for an injured swap.
        if not match.substitution_pool(side):
            self.add_back_button(row=4)
            return

        for player_id in match.setup_for_side(side).field_players:
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

        player = self.cog.engine.get_player_definition(outgoing_player_id)
        await self.show(
            interaction,
            game,
            match,
            CoachingSubstitutionInView(
                self.cog, self.game_id, outgoing_player_id,
            ),
            note=(
                "Who comes on for "
                f"{format_role_bracket(player, self.cog.team_emojis, match.team_for_player(player.player_id))}? "
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

        for player_id in match.substitution_pool(self.side(match)):
            button = discord.ui.Button(
                label=cog.engine.format_roster_player(player_id)[:80],
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

        self.cog.persist(game, match)
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
            player = self.cog.engine.get_player_definition(player_id)
            await self.show(
                interaction,
                game,
                match,
                CoachingZoneView(self.cog, self.game_id, player_id),
                note=(
                    "Who does "
                    f"{format_role_bracket(player, self.cog.team_emojis, match.team_for_player(player.player_id))} "
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

        self.cog.persist(game, match)
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

        player = self.cog.engine.get_player_definition(player_id)
        await self.show(
            interaction,
            game,
            match,
            CoachingPlaceSpaceView(self.cog, self.game_id, player_id),
            note=(
                "Where should "
                f"{format_role_bracket(player, self.cog.team_emojis, match.team_for_player(player.player_id))} "
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
            player = self.cog.engine.get_player_definition(self.player_id)
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
                    f"{format_role_bracket(player, self.cog.team_emojis, match.team_for_player(player.player_id))}?"
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

    view.cog.persist(game, match)
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
                label=self.cog.engine.format_roster_player(other_id)[:80],
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
        return self.load_match()

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
        if interaction.user.id != self.cog.engine.side_controller_id(game, self.side):
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
            label = f"{cog.engine.format_roster_player(player_id)} ({tokens})"
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

        player = self.cog.engine.get_player_definition(player_id)
        defense_skill = self.cog.player_catalog.effective_profile(
            player
        ).defense
        removed = match.recover_exhaustion(player_id, 1, defense_skill)
        self.cog.engine.next_halftime_stage(match)
        self.cog.persist(game, match)

        remaining = match.exhaustion.get(player_id, 0)
        text = (
            f"{format_role_bracket(player, self.cog.team_emojis, match.team_for_player(player.player_id))} loses "
            f"an extra exhaustion token (now {remaining})."
            if removed
            else (
                f"{format_role_bracket(player, self.cog.team_emojis, match.team_for_player(player.player_id))} "
                "had no tokens to lose."
            )
        )
        await interaction.response.edit_message(content=text, view=None)
        await self.cog.refresh_match_image(interaction, game)
        await self.cog.advance_halftime_stage(interaction, game, match)


class LooseBallChoiceView(SafeView):
    """
    Who one side sends after a loose ball, plus the option of sending
    nobody. The candidates are the nearest player either side of the
    ball, from any zone (see "Sending a player" in
    docs/living-rules.md).

    One side at a time, the team that last had possession first: they
    are the ones losing the ball, and offering both at once let
    whoever clicked second answer the first's pick. Once this side
    settles, the cog rebuilds the prompt for the other.

    "Send nobody" is a real move, not a way out of the prompt -- with
    neither side contesting, the ball goes out of bounds and the side
    that last held it loses it (see resolve_loose_ball). It is
    offered even when there's only one candidate, which is why a lone
    candidate isn't auto-picked the way a forced run back is.

    **It is not offered to a side with somebody standing on the ball**
    (may_decline_loose_ball): they contest for nothing, so there is no
    walk-in for that coach to refuse to pay. Such a prompt is only ever
    a pick between two or more of them -- one is settled without asking.
    Built, not disabled: there is nothing a coach could do to enable it.
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
            player = cog.engine.get_player_definition(player_id)
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

        if match.may_decline_loose_ball(
            match.ball.possession
            if side == "offense"
            else match.defending_side()
        ):
            decline = discord.ui.Button(
                label="Send nobody",
                style=discord.ButtonStyle.secondary,
                custom_id=f"d12ball:loose_ball_decline:{game_id}:{side}",
                row=4,
                # Railed during the tutorial. Waving the ball through
                # would not derail the story -- Dinky takes it either
                # way -- but the lesson beside this prompt is that both
                # sides send somebody, and a greyed button is the one
                # way to say so on the prompt itself.
                disabled=cog.tutorial_railed_option(
                    cog.games.get(game_id),
                    "loose_ball_decline",
                    ("never",),
                ) == "never",
            )
            decline.callback = self.decline
            self.add_item(decline)

    async def claim(
        self,
        interaction: discord.Interaction,
    ) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        """The game and match if this click may settle this side's
        pick, or (None, None) after replying with why it may not."""
        game, match = await self.require_match(interaction)
        if game is None:
            return None, None

        if self.cog.engine.loose_ball_side_on_the_clock(match) != self.side:
            await interaction.response.send_message(
                "That side has already answered.",
                ephemeral=True,
            )
            return None, None

        authorized = (
            self.cog.engine.user_controls_possession(
                interaction.user.id, game, match,
            )
            if self.side == "offense"
            else self.cog.engine.user_controls_defense(
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

        player = self.cog.engine.get_player_definition(player_id)
        await self.settled(
            interaction,
            game,
            match,
            f"{format_role_bracket(player, self.cog.team_emojis, match.team_for_player(player.player_id))} "
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
        # The button is not built for a side with somebody on the ball,
        # so this is a stale click -- a prompt a restart re-attached
        # from before the ball reached them. Same reason
        # ManeuverChallengeView.decline re-checks its own.
        if not match.may_decline_loose_ball(side):
            await interaction.response.send_message(
                "Somebody of theirs is standing on the ball -- they "
                "contest it, and cannot be held back.",
                ephemeral=True,
            )
            return

        if self.cog.tutorial_railed_option(
            game, "loose_ball_decline", ("never",),
        ) == "never":
            await interaction.response.send_message(
                "This step of the tutorial is about fighting for a "
                "loose ball -- send somebody after it.",
                ephemeral=True,
            )
            return

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
        self.cog.persist(game, match)

        await interaction.response.edit_message(
            content=announcement, view=None,
        )

        if self.cog.engine.loose_ball_side_on_the_clock(match) is None:
            await self.cog.resolve_loose_ball(interaction, game, match)
            return

        prompt_message = await interaction.followup.send(
            self.cog.engine.build_loose_ball_prompt(game, match),
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
    Which player goes and picks up an out-of-bounds or ceded ball,
    offered to the side that won it once everyone is back on their
    arrangement -- the nearest either side of it, from any zone, at one
    exhaustion token per space traveled (see "Sending a player" in
    docs/living-rules.md, and D12Ball.begin_ball_recovery).
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game, match = self.load_match()
        if game is None:
            return
        side = match.ball.possession

        for player_id in match.contest_candidates(side):
            player = cog.engine.get_player_definition(player_id)
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
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not match.pending_ball_recovery:
            await interaction.response.send_message(
                "The ball has already been picked up.",
                ephemeral=True,
            )
            return
        if not self.cog.engine.user_controls_possession(
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
            noun = contest_noun(cog.engine.load_match_state(game))

        button = discord.ui.Button(
            label=f"Roll for the {noun}",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:loose_ball_test:{game_id}",
        )
        button.callback = self.roll
        self.add_item(button)

    def score_loose_ball(
        self,
        game: D12BallGame,
        match: MatchState,
        offense_player: PlayerDefinition,
        defense_player: PlayerDefinition,
    ) -> tuple[list[tuple[int, Team, list[str], int]], int, int]:
        """
        Roll the contest for the ball and add what counts towards it,
        as the two sides `render_contest_dice` draws plus the totals
        the winner is read off. Serves the loose ball and the long High
        Pass alike, which is the only contest injury and the ball speed
        modifier both bite in.

        No text breakdown goes alongside it: the dice image already
        names both players and shows every modifier that built the
        totals.
        """
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

        scripted = self.cog.tutorial_dice(game, "loose_ball", 2)
        offense_roll, defense_roll = (
            scripted if scripted else
            (random.randint(1, 12), random.randint(1, 12))
        )
        offense_total = offense_roll + offense_skill
        defense_total = defense_roll + defense_skill

        offense_detail = contestant_detail(
            offense_player, "Offensive", offense_skill,
            injured=offense_injured,
        )

        # A High Pass's receiver adds the ball speed modifier to keep
        # what the pass delivered (2026-08-07). A genuine loose ball is
        # nobody's yet, so neither side gets it there.
        #
        # The modifier is signed: this contest is also where a declined
        # overshoot set-up lands, and an overshoot pays the modifier
        # against the receiver in the contest exactly as it would have
        # against the shot (2026-08-10). See ball_speed_modifier.
        if match.pending_loose_ball_is_high_pass:
            modifier = match.ball_speed_modifier()
            offense_total += modifier
            offense_detail.append(f"{modifier:+d} ball speed modifier")

        return (
            [
                (
                    offense_roll,
                    match.team_for_player(offense_player.player_id),
                    offense_detail,
                    offense_total,
                ),
                (
                    defense_roll,
                    match.team_for_player(defense_player.player_id),
                    contestant_detail(
                        defense_player,
                        "Defensive",
                        defense_skill,
                        injured=defense_injured,
                    ),
                    defense_total,
                ),
            ],
            offense_total,
            defense_total,
        )

    def settle_loose_ball_winner(
        self,
        game: D12BallGame,
        match: MatchState,
        offense_player: PlayerDefinition,
        defense_player: PlayerDefinition,
        offense_total: int,
        defense_total: int,
    ) -> tuple[str, list[PlayerDefinition], int, bool]:
        """
        Give the ball to whoever won the contest and word the result:
        the announcement, who owes an injury test, and the two things
        the run back behind it needs -- both read off the match before
        this clears them.
        """
        outcome = "offense" if offense_total > defense_total else "defense"
        winner_side = (
            match.ball.possession
            if outcome == "offense"
            else match.defending_side()
        )
        turnover_occurred = winner_side != match.ball.possession
        winner_number = (
            self.cog.engine.possession_player_number(game, match)
            if outcome == "offense"
            else self.cog.engine.defending_player_number(game, match)
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
        # Whoever won the contest is holding the ball, and takes the
        # next turn -- the receiver who kept a long High Pass, or
        # either side's contestant who won a loose ball. Confirmed by
        # the author 2026-08-09; see "Choosing the handler" in
        # docs/living-rules.md.
        match.set_ball_carrier(winner_player.player_id)
        match.pending_loose_ball = False
        match.loose_ball_offense_player = None
        match.loose_ball_defense_player = None
        self.cog.persist(game, match)

        turnover_line = "# Turnover!\n\n" if turnover_occurred else ""
        winner_bracket = format_role_bracket(
            winner_player,
            self.cog.team_emojis,
            match.team_for_player(winner_player.player_id),
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

        return (
            f"{turnover_line}{outcome_line}",
            exhausted_participants,
            distance_moved,
            turnover_occurred,
        )

    async def roll(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

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

        if not self.is_game_participant(game, interaction.user.id):
            await interaction.response.send_message(
                "Only a player in this game can roll for the "
                f"{contest_noun(match)}.",
                ephemeral=True,
            )
            return

        offense_player = self.cog.engine.get_player_definition(
            match.loose_ball_offense_player,
        )
        defense_player = self.cog.engine.get_player_definition(
            match.loose_ball_defense_player,
        )

        contestants, offense_total, defense_total = self.score_loose_ball(
            game, match, offense_player, defense_player,
        )
        dice_file = await render_contest_dice(
            contestants, filename="loose_ball_dice.png",
        )

        if offense_total == defense_total:
            await interaction.response.edit_message(
                content=self.pay_skill_test_tie(
                    game,
                    match,
                    match.loose_ball_offense_player,
                    match.loose_ball_defense_player,
                    offense_total,
                    defense_total,
                ),
                attachments=[dice_file],
                view=LooseBallSkillTestView(self.cog, self.game_id),
            )
            await self.cog.refresh_match_image(interaction, game)
            return

        (
            announcement,
            exhausted_participants,
            distance_moved,
            turnover_occurred,
        ) = self.settle_loose_ball_winner(
            game, match, offense_player, defense_player,
            offense_total, defense_total,
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
            announcement,
            # The edit this replaced never pinged the winner, and the
            # prompt that follows does; one ping per turn is plenty.
            allowed_mentions=discord.AllowedMentions(
                users=False, roles=False, everyone=False,
            ),
        )
        await self.cog.refresh_match_image(interaction, game)

        # Winning a live ball off the other side -- a loose ball or a
        # long High Pass -- is a steal however it was contested, so no
        # substitution window either way. The run back waits behind
        # whatever injury tests this contest owes, and carries its two
        # arguments through the queue because nothing left in the match
        # still says what they were -- see begin_injury_tests.
        await self.cog.begin_injury_tests(
            interaction,
            game,
            match,
            exhausted_participants,
            {
                "kind": "run_back",
                "distance_moved": distance_moved,
                "turnover_occurred": turnover_occurred,
            },
        )




class ShootoutView(SafeView):
    """
    Shared plumbing for the shootout's public prompts: load the game,
    and work out which side the person clicking coaches.

    Every prompt in the shootout is **one button both coaches share**,
    the way the maneuver prompt is: which menu opens depends only on
    who clicked, so nobody has to find "which button is mine" first.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

    def load(self) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        return self.load_match()

    def owes(self, match: MatchState, side: TeamSide) -> bool:
        """Whether this prompt is still waiting on `side`."""
        raise NotImplementedError

    async def claim(
        self,
        interaction: discord.Interaction,
    ) -> Optional[tuple[D12BallGame, MatchState, TeamSide]]:
        """
        Which side the person clicking is answering for.

        **A side that still owes an answer wins**, because in a test
        game one user coaches both and would otherwise never be able
        to answer for the second: the home side is theirs, so the
        visiting order could never be set. The maneuver prompt picks
        its ephemeral menu the same way and for the same reason.
        """
        game, match = self.load()
        if game is None or match is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return None

        if not match.pending_shootout:
            await interaction.response.send_message(
                "This game is not in the extreme shootout.",
                ephemeral=True,
            )
            return None

        theirs = [
            side
            for side in (TeamSide.HOME, TeamSide.VISITING)
            if self.cog.engine.side_controller_id(game, side) == interaction.user.id
        ]
        if not theirs:
            await interaction.response.send_message(
                "Only a coach in this game can do that.",
                ephemeral=True,
            )
            return None

        for side in theirs:
            if self.owes(match, side):
                return game, match, side

        return game, match, theirs[0]


class ShootoutOrderPromptView(ShootoutView):
    """The public button that opens a coach's own ordering menu."""

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(cog, game_id)

        button = discord.ui.Button(
            label="Set Your Shooting Order",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:shootout_order_prompt:{game_id}",
        )
        button.callback = self.open_menu
        self.add_item(button)

    def owes(self, match: MatchState, side: TeamSide) -> bool:
        return not match.shootout_order_complete(side)

    async def open_menu(self, interaction: discord.Interaction) -> None:
        claimed = await self.claim(interaction)
        if claimed is None:
            return
        game, match, side = claimed

        if match.shootout_order_complete(side):
            # A coach may look at their order but not reorder it, so
            # this shows it rather than reopening the menu.
            await interaction.response.send_message(
                "Your order is set:\n"
                f"{self.cog.shootout_order_text(match, side)}",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            content=self.cog.shootout_order_text(match, side),
            view=ShootoutOrderSelectView(self.cog, self.game_id, side),
            ephemeral=True,
        )


class ShootoutOrderSelectView(SafeView):
    """
    A coach putting their six in order, one click at a time, on an
    ephemeral message -- the other coach must not see it, and
    ephemeral is the only thing Discord offers that hides it. That
    makes this and `ShootoutPickSelectView` the shootout's share of
    the problem the maneuver menu has: no durable message id, so a
    restart re-registers them message-agnostically instead (see
    `D12Ball.restore_shootout_menus`, which is also why `timeout` is
    an argument rather than a constant).

    **The part-built order is on the match, not on this view**, so a
    coach who ordered five and lost the bot comes back to five rather
    than to an empty menu -- see `MatchState.add_to_shootout_order`.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        side: TeamSide,
        timeout: Optional[float] = 600,
    ):
        super().__init__(timeout=timeout)

        self.cog = cog
        self.game_id = game_id
        self.side = TeamSide(side)

        game = cog.games.get(game_id)
        match = (
            cog.engine.load_match_state(game)
            if game is not None and game.match_state is not None
            else None
        )
        remaining = (
            match.shootout_order_remaining(self.side)
            if match is not None
            else []
        )

        for player_id in remaining:
            button = discord.ui.Button(
                label=cog.engine.shootout_button_label(match, player_id),
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:shootout_order:{game_id}:"
                    f"{self.side.value}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_id: str = player_id,
            ) -> None:
                await self.pick(interaction, chosen_id)

            button.callback = callback
            self.add_item(button)

        restart = discord.ui.Button(
            label="Start Over",
            style=discord.ButtonStyle.secondary,
            custom_id=(
                f"d12ball:shootout_order_restart:{game_id}:{self.side.value}"
            ),
            row=1,
        )
        restart.callback = self.restart
        self.add_item(restart)

    async def load(
        self,
        interaction: discord.Interaction,
    ) -> Optional[tuple[D12BallGame, MatchState]]:
        game, match = await self.require_match(interaction)
        if game is None:
            return None

        if (
            not match.pending_shootout
            or self.cog.engine.side_controller_id(game, self.side)
            != interaction.user.id
        ):
            await interaction.response.edit_message(
                content="That order is no longer being asked for.",
                view=None,
            )
            return None

        return game, match

    async def restart(self, interaction: discord.Interaction) -> None:
        loaded = await self.load(interaction)
        if loaded is None:
            return
        game, match = loaded

        if match.shootout_order_complete(self.side):
            await interaction.response.edit_message(
                content=(
                    "Your order is already set, and an order cannot be "
                    "changed once it is."
                ),
                view=None,
            )
            return

        match.clear_shootout_order(self.side)
        self.cog.persist(game, match)

        await interaction.response.edit_message(
            content=self.cog.shootout_order_text(match, self.side),
            view=ShootoutOrderSelectView(self.cog, self.game_id, self.side),
        )

    async def pick(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        loaded = await self.load(interaction)
        if loaded is None:
            return
        game, match = loaded

        try:
            match.add_to_shootout_order(self.side, player_id)
        except ValueError as error:
            # A click on a stale copy of the menu -- a coach who
            # scrolled back, or one restored after a restart.
            await interaction.response.edit_message(
                content=(
                    f"{error}\n\n"
                    f"{self.cog.shootout_order_text(match, self.side)}"
                ),
                view=(
                    None
                    if match.shootout_order_complete(self.side)
                    else ShootoutOrderSelectView(
                        self.cog, self.game_id, self.side,
                    )
                ),
            )
            return

        self.cog.persist(game, match)

        settled = match.shootout_order_complete(self.side)
        await interaction.response.edit_message(
            content=self.cog.shootout_order_text(match, self.side),
            view=(
                None
                if settled
                else ShootoutOrderSelectView(
                    self.cog, self.game_id, self.side,
                )
            ),
        )

        if not settled:
            return

        await interaction.followup.send(
            f"{format_team_side_label(match.setup_for_side(self.side))} "
            "has set their shooting order."
        )

        if match.shootout_orders_complete:
            await self.cog.close_shootout_prompt(interaction, game)
            await self.cog.advance_shootout(interaction, game, match)


class ShootoutPickPromptView(ShootoutView):
    """The public button that opens a sudden-death shooter pick."""

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(cog, game_id)

        button = discord.ui.Button(
            label="Choose Your Shooter",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:shootout_pick_prompt:{game_id}",
        )
        button.callback = self.open_menu
        self.add_item(button)

    def owes(self, match: MatchState, side: TeamSide) -> bool:
        return match.shootout_shooter(side) is None

    async def open_menu(self, interaction: discord.Interaction) -> None:
        claimed = await self.claim(interaction)
        if claimed is None:
            return
        game, match, side = claimed

        if match.shootout_shooter(side) is not None:
            await interaction.response.send_message(
                "You have already chosen your shooter.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            content=(
                "Choose who goes out next. Everyone who has not shot "
                "yet this round is eligible."
            ),
            view=ShootoutPickSelectView(self.cog, self.game_id, side),
            ephemeral=True,
        )


class ShootoutPickSelectView(SafeView):
    """
    The sudden-death shooter pick, ephemeral for the same reason the
    ordering menu is: neither coach may see the other's before the
    reveal.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        side: TeamSide,
        timeout: Optional[float] = 600,
    ):
        super().__init__(timeout=timeout)

        self.cog = cog
        self.game_id = game_id
        self.side = TeamSide(side)

        game = cog.games.get(game_id)
        match = (
            cog.engine.load_match_state(game)
            if game is not None and game.match_state is not None
            else None
        )
        eligible = (
            match.shootout_eligible(self.side) if match is not None else []
        )

        for player_id in eligible:
            button = discord.ui.Button(
                label=cog.engine.shootout_button_label(match, player_id),
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:shootout_pick:{game_id}:"
                    f"{self.side.value}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_id: str = player_id,
            ) -> None:
                await self.pick(interaction, chosen_id)

            button.callback = callback
            self.add_item(button)

    async def pick(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if (
            not match.pending_shootout
            or self.cog.engine.side_controller_id(game, self.side)
            != interaction.user.id
        ):
            await interaction.response.edit_message(
                content="That pick is no longer being asked for.",
                view=None,
            )
            return

        if match.shootout_shooter(self.side) is not None:
            await interaction.response.edit_message(
                content="You have already chosen your shooter.",
                view=None,
            )
            return

        try:
            match.set_shootout_shooter(self.side, player_id)
        except ValueError as error:
            await interaction.response.edit_message(
                content=str(error),
                view=None,
            )
            return

        self.cog.persist(game, match)

        player = self.cog.engine.get_player_definition(player_id)
        await interaction.response.edit_message(
            content=(
                "You send out "
                f"{format_role_bracket(player, self.cog.team_emojis, match.team_for_player(player.player_id))}."
            ),
            view=None,
        )
        await interaction.followup.send(
            f"{format_team_side_label(match.setup_for_side(self.side))} "
            "has chosen their shooter."
        )

        if match.shootout_shooters_complete:
            await self.cog.close_shootout_prompt(interaction, game)
            await self.cog.advance_shootout(interaction, game, match)


class ShootoutTestView(ShootoutView):
    """
    The roll that settles one shootout skill test. Either coach may
    press it, like every other roll in the game.

    It carries the "look at your order" button as well, because this
    is the message a coach is looking at for most of a shootout: the
    order prompt is deleted once both sides have set theirs, and a
    coach may look at their own order any time they like -- they just
    may not reorder it.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(cog, game_id)

        button = discord.ui.Button(
            label="Roll the skill test",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:shootout_test:{game_id}",
        )
        button.callback = self.roll
        self.add_item(button)

        review = discord.ui.Button(
            label="Your Order",
            style=discord.ButtonStyle.secondary,
            custom_id=f"d12ball:shootout_review:{game_id}",
        )
        review.callback = self.review
        self.add_item(review)

    def owes(self, match: MatchState, side: TeamSide) -> bool:
        # Nothing is owed here -- both coaches may look at their own,
        # so whichever side is theirs is the answer.
        return True

    async def review(self, interaction: discord.Interaction) -> None:
        """
        A coach's own order, or -- in sudden death, which has none --
        who they have left to send out this round. Ephemeral, so the
        other coach learns nothing from it.
        """
        claimed = await self.claim(interaction)
        if claimed is None:
            return
        _, match, side = claimed

        if match.shootout_round > 1:
            remaining = [
                format_role_bracket(
                    self.cog.engine.get_player_definition(player_id),
                    self.cog.team_emojis,
                    match.team_for_player(player_id),
                )
                for player_id in match.shootout_eligible(side)
            ]
            await interaction.response.send_message(
                "\n".join(
                    [
                        "Still to go out this round:",
                        *remaining,
                    ]
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            self.cog.shootout_order_text(match, side),
            ephemeral=True,
        )

    def score_shootout_test(
        self,
        match: MatchState,
    ) -> tuple[list, dict, dict]:
        """
        Roll both shooters and total them up, as the sides
        `render_contest_dice` draws plus the totals and the players
        behind them.

        Both sides add their **offensive** skill -- a shootout has no
        defender -- and an injured player adds none at all, the same
        withholding the loose ball and the long High Pass make. See
        "Extreme shootout" in docs/living-rules.md.
        """
        totals: dict[TeamSide, int] = {}
        players = {}
        dice = []

        for side in (TeamSide.HOME, TeamSide.VISITING):
            player = self.cog.engine.get_player_definition(
                match.shootout_shooter(side),
            )
            players[side] = player
            injured = player.player_id in match.injured
            skill = (
                0
                if injured
                else self.cog.player_catalog.effective_profile(player).offense
            )
            roll = random.randint(1, 12)
            totals[side] = roll + skill
            dice.append(
                (
                    roll,
                    match.setup_for_side(side).team,
                    contestant_detail(
                        player, "Offensive", skill, injured=injured,
                    ),
                    totals[side],
                )
            )

        return dice, totals, players

    def settle_shootout_test(
        self,
        match: MatchState,
        totals: dict,
        players: dict,
    ) -> tuple[Optional[TeamSide], str]:
        """
        Award the goal, if there is one, and word the result.

        **A shootout skill test is not re-rolled.** A tie scores for
        nobody and the shootout moves on, which is the one place the
        game settles a tied skill test by leaving it tied.
        """
        home_total = totals[TeamSide.HOME]
        visiting_total = totals[TeamSide.VISITING]

        if home_total == visiting_total:
            return None, (
                f"**A tie, {home_total}-{visiting_total}.** Neither "
                "side scores."
            )

        winner = (
            TeamSide.HOME
            if home_total > visiting_total
            else TeamSide.VISITING
        )
        scorer = players[winner]
        match.award_shootout_goal(winner, scorer.player_id)
        return winner, (
            "## "
            f"{format_role_bracket(scorer, self.cog.team_emojis, match.team_for_player(scorer.player_id))} "
            "scores!"
        )

    async def roll(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not match.pending_shootout or not match.shootout_shooters_complete:
            await interaction.response.send_message(
                "That skill test has already been rolled.",
                ephemeral=True,
            )
            return

        if not self.is_game_participant(game, interaction.user.id):
            await interaction.response.send_message(
                "Only a player in this game can roll the skill test.",
                ephemeral=True,
            )
            return

        # Deferred before the dice are rendered, for the reason spelled
        # out in SkillTestView.roll.
        await interaction.response.defer()

        dice, totals, players = self.score_shootout_test(match)
        dice_file = await render_contest_dice(
            dice, filename="shootout_dice.png",
        )
        winner, outcome = self.settle_shootout_test(match, totals, players)

        # The goal and the retirement go out in one save, so a restart
        # between this roll and what follows it can never re-roll a
        # test that has already been paid for -- see
        # finish_shootout_test.
        match.finish_shootout_test()
        self.cog.persist(game, match)

        # Result under the dice, not above them, for the reason
        # SkillTestView.roll gives: attachments render below content.
        await interaction.edit_original_response(
            content=None,
            attachments=[dice_file],
            view=None,
        )
        await interaction.followup.send(
            f"{outcome}\n"
            f"Extreme shootout: {self.cog.engine.shootout_running_score(match)}"
        )
        if winner is not None:
            await self.cog.refresh_match_image(interaction, game)

        # A shootout test owes no injury checks (2026-08-15). It costs
        # no exhaustion either -- it is not one of the ways to gain a
        # token -- so an Exhausted shooter carries that into the
        # shootout and out the other side unchanged. The round goes
        # straight on to the next test, which is what the injury
        # queue's continuation did once the queue drained.
        await self.cog.continue_shootout(interaction, game, match)

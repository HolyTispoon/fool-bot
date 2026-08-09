import asyncio
import hashlib
import io
import random
import time
import uuid
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from d12ball.ai import build_ai_strategies, AIStrategy
from d12ball.components import (
    SETUP_AREAS,
    FormationShape,
    MatchPeriod,
    MatchState,
    PlayerDefinition,
    PlayerRole,
    TeamSetup,
    TeamSide,
    Zone,
    kickoff_space_index,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
    zone_for_area,
)
from d12ball.game import (
    AIOpponent,
    CoinFace,
    D12BallGame,
    Formation,
    GameMode,
    GameStatus,
    Team,
    TieMode,
)
from d12ball.render import (
    TEAM_COLORS,
    ZONE_LABELS,
    ChallengeSide,
    render_injury_test_die,
    render_maneuver_challenge,
    render_maneuver_reference_image,
    render_match_image,
    render_own_goal_dice,
    render_score_attempt,
)

from gamesaves.d12ball.storage import (
    load_games,
    save_games,
)

from cogs.d12ball_helpers import (
    BENCH_DESTINATIONS,
    COIN_EMOJI_NAMES,
    EMOJI_REFETCH_INTERVAL,
    HIGH_PASS_CONTEST_HEADLINE,
    LOGGER,
    PBD_ARCHIVE_CATEGORY_NAME,
    PBD_GAMES_CATEGORY_NAME,
    ROLE_INITIALS,
    add_full_image_button,
    add_full_image_button_to_response,
    area_display_name,
    board_image_filename,
    build_full_time_summary,
    build_game_channel_name,
    contest_noun,
    destination_display_name,
    fetch_application_emojis,
    filter_choices,
    format_ai_name,
    format_player_with_team,
    format_role_bracket,
    format_team_side_label,
    get_exhaust_emoji,
    get_exhausted_emoji,
    get_injured_emoji,
    get_or_create_category,
    load_coin_emojis,
    load_condition_emojis,
    load_team_emojis,
    parse_space_value,
    pin_board_message,
    refresh_player_names,
    resolve_adjustable_value,
    send_error_fallback,
    space_choices,
    space_label,
)
from cogs.d12ball_views import (
    BallHandlerSelectionView,
    BallRecoveryView,
    CoinFlipView,
    DribbleAdvanceChoiceView,
    HalftimeExtraTokenView,
    HalftimeRepositionView,
    HighPassChoiceView,
    HomeAwaySelectionView,
    LooseBallChoiceView,
    LooseBallSkillTestView,
    LowPassChoiceView,
    ManeuverActionPromptView,
    ManeuverChallengeView,
    PlayerActionView,
    RematchView,
    RunBackChoiceView,
    ScoreAttemptView,
    SetUpAttemptChoiceView,
    ShooterChoiceView,
    SkillTestView,
    SpeedDeltaChoiceView,
    SubstitutionMenuView,
    SubstitutionOfferView,
    TeamSelectionView,
)


# The halftime sequence's stages, in order -- see D12Ball.advance_halftime_stage.
# Each side gets its own extra-exhaustion-token choice, its own full
# substitution declaration (see begin_halftime_substitutions), and its own
# free repositioning pass, home before visiting throughout.
HALFTIME_STAGES = (
    "extra_token_home",
    "extra_token_visiting",
    "subs_home",
    "subs_visiting",
    "reposition_home",
    "reposition_visiting",
)


# The most placements one run back may make before it is treated as
# stuck. Twelve players a side is the whole board several times over,
# so this only ever fires on a bug -- see continue_run_back.
MAX_RUN_BACK_PASSES = 60


# How often one game's persistent board message may be refreshed.
#
# The arithmetic, because it is not obvious: `message_id` is not one of
# Discord's major rate-limit parameters, so every
# `PATCH /channels/{id}/messages/{id}` in a game's channel shares one
# bucket -- about five requests in five seconds. A refresh costs *two*
# of them (the attachment, then the link button), and
# refresh_maneuver_prompt spends more of the same bucket during a turn.
# Holding refreshes more than five seconds apart is what keeps the
# board to one refresh per window, which leaves the rest of that
# budget for the prompts. See "The board message is one bucket" in
# CLAUDE.md.
BOARD_REFRESH_INTERVAL = 6.0


class D12Ball(commands.GroupCog, group_name="d12ball"):
    ball_group = app_commands.Group(
        name="ball",
        description="Move the ball and manage possession, speed.",
    )
    meeple_group = app_commands.Group(
        name="meeple",
        description="Move meeples on the board.",
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.games = load_games()
        self.player_catalog = load_player_catalog()
        self.basic_ruleset = load_basic_ruleset()
        self.maneuver_catalog = load_maneuver_catalog()
        self.maneuver_reference_image_bytes = render_maneuver_reference_image(
            self.maneuver_catalog
        ).read()
        self.coin_emojis: dict[CoinFace, str] = {}
        # When the coin emoji were last asked after, on the monotonic
        # clock -- see ensure_coin_emojis. None, not 0.0: monotonic
        # counts from boot on Linux, so on a host that starts the bot
        # as it comes up, 0.0 reads as "asked a moment ago" and skips
        # the first retry.
        self.coin_emojis_checked_at: Optional[float] = None
        self.condition_emojis: dict[str, str] = {}
        self.team_emojis: dict[Team, str] = {}
        self.ai_strategies = build_ai_strategies(
            self.player_catalog,
            self.maneuver_catalog,
        )
        # Per game: when its board message was last edited, the
        # trailing refresh waiting to edit it again, and a digest of
        # the board already sitting on the message. See
        # refresh_match_image.
        self.board_refreshed_at: dict[str, float] = {}
        self.board_refresh_tasks: dict[str, "asyncio.Task[None]"] = {}
        self.board_png_digests: dict[str, bytes] = {}

        restored_views = 0

        for game in self.games.values():
            setup_view = None
            if game.coin_flipped and not game.home_and_visiting_selected:
                setup_view = HomeAwaySelectionView(
                    cog=self,
                    game_id=game.game_id,
                )
            elif game.teams_selected and not game.coin_flipped:
                setup_view = CoinFlipView(
                    cog=self,
                    game_id=game.game_id,
                )
            elif not game.teams_selected:
                setup_view = TeamSelectionView(
                    cog=self,
                    game_id=game.game_id,
                )

            if setup_view is not None and game.message_id is not None:
                self.bot.add_view(
                    setup_view,
                    message_id=game.message_id,
                )
                restored_views += 1

            if game.rematch_message_id is not None:
                # A finished game's full-time message. Its button stays
                # live indefinitely -- nobody is obliged to ask for the
                # rematch the same day they lost.
                self.bot.add_view(
                    RematchView(self, game.game_id),
                    message_id=game.rematch_message_id,
                )
                restored_views += 1

            if (
                game.turn_message_id is not None
                and game.match_state is not None
            ):
                try:
                    match = self.load_match_state(game)
                except ValueError as error:
                    # Saved state that no longer passes validate() (e.g.
                    # a crash that saved state mid-effect, before the
                    # rest of the pipeline could finish) shouldn't take
                    # every other game's button views down with it on
                    # startup -- log it so it reaches #logs and needs
                    # fixing, and move on to the next game.
                    LOGGER.error(
                        "Could not restore views for game %s: %s",
                        game.game_id, error,
                    )
                    continue
                if match.pending_halftime_stage is not None:
                    # Halftime resets active_player_id before its own
                    # stages run, so it has to be checked ahead of the
                    # "no ball handler yet" branch below, which would
                    # otherwise misread halftime as kickoff.
                    stage = match.pending_halftime_stage
                    if stage == "extra_token_home":
                        turn_view = HalftimeExtraTokenView(
                            self, game.game_id, TeamSide.HOME,
                        )
                    elif stage == "extra_token_visiting":
                        turn_view = HalftimeExtraTokenView(
                            self, game.game_id, TeamSide.VISITING,
                        )
                    elif stage in ("subs_home", "subs_visiting"):
                        # Always the menu: halftime never asks whether
                        # to declare, so there is no offer to come back
                        # to, unlike an ordinary turnover's window
                        # below.
                        turn_view = SubstitutionMenuView(self, game.game_id)
                    else:
                        # reposition_home / reposition_visiting -- a
                        # part-made zone/space pick is not persisted
                        # and restarts at the reposition menu, the
                        # same simplification a run-back choice makes.
                        side = (
                            TeamSide.HOME
                            if stage == "reposition_home"
                            else TeamSide.VISITING
                        )
                        turn_view = HalftimeRepositionView(
                            self, game.game_id, side,
                        )
                elif match.active_player_id is None:
                    turn_view = BallHandlerSelectionView(self, game.game_id)
                elif match.pending_substitution_side is not None:
                    # A window mid-flight comes back as either the
                    # offer or the menu. A part-made choice (picked
                    # who goes off, not yet who comes on) is not
                    # persisted and restarts at the menu, the same way
                    # a run-back choice does.
                    turn_view = (
                        SubstitutionMenuView(self, game.game_id)
                        if match.pending_substitution_declared
                        else SubstitutionOfferView(self, game.game_id)
                    )
                elif match.pending_run_back:
                    turn_view = self.build_run_back_view(
                        game.game_id, match,
                    ) or PlayerActionView(self, game.game_id)
                elif match.pending_ball_recovery:
                    # An out-of-bounds ball whose run back has already
                    # finished, waiting on the winning side to send
                    # someone to pick it up.
                    turn_view = BallRecoveryView(self, game.game_id)
                elif match.pending_loose_ball:
                    if (
                        match.loose_ball_offense_player is not None
                        and match.loose_ball_defense_player is not None
                    ):
                        turn_view = LooseBallSkillTestView(
                            self, game.game_id,
                        )
                    else:
                        turn_view = self.build_loose_ball_view(
                            game.game_id, match,
                        ) or PlayerActionView(self, game.game_id)
                elif match.pending_action == "shoot":
                    turn_view = ScoreAttemptView(self, game.game_id)
                elif (
                    match.pending_action == "maneuver"
                    and match.challenger_id is None
                ):
                    turn_view = ManeuverChallengeView(self, game.game_id)
                elif (
                    match.challenger_id is not None
                    or match.maneuver_uncontested
                ):
                    # challenger_id is only ever set while a maneuver is
                    # in progress and cleared by reset_maneuver(), so
                    # it alone disambiguates this from any other phase
                    # -- pending_action itself is cleared to None by
                    # choose_challenger() right when the challenger is
                    # picked, so it can't be relied on from here on.
                    # maneuver_uncontested says the same thing for a
                    # maneuver that never had a challenger, and is
                    # cleared by the same reset.
                    if not match.maneuver_selections_complete:
                        turn_view = ManeuverActionPromptView(
                            self, game.game_id,
                        )
                    elif (
                        not match.maneuver_uncontested
                        and self.maneuver_catalog.resolve(
                            match.offense_maneuver, match.defense_maneuver,
                        ) == "tie"
                    ):
                        turn_view = SkillTestView(self, game.game_id)
                    else:
                        turn_view = self.build_effect_choice_view(
                            game.game_id, match,
                        ) or PlayerActionView(self, game.game_id)
                else:
                    turn_view = PlayerActionView(self, game.game_id)
                self.bot.add_view(
                    turn_view,
                    message_id=game.turn_message_id,
                )
                restored_views += 1

        LOGGER.info(
            "Loaded %d saved D12 Ball games and restored %d button "
            "views.",
            len(self.games),
            restored_views,
        )

    async def cog_load(self) -> None:
        # One fetch, three lookups. Each loader used to make its own
        # call to the same endpoint, so every startup asked Discord for
        # the identical list three times over.
        application_emojis = await fetch_application_emojis(self.bot)

        if application_emojis is None:
            # fetch_application_emojis has already said so. Leave the
            # mappings empty and let everything fall back; the next
            # coin toss retries.
            return

        self.coin_emojis = await load_coin_emojis(
            self.bot, application_emojis,
        )
        self.condition_emojis = await load_condition_emojis(
            self.bot, application_emojis,
        )
        self.team_emojis = await load_team_emojis(
            self.bot, application_emojis,
        )

    async def cog_unload(self) -> None:
        """
        Drop any board refresh still waiting on its window. The reload
        that follows builds a new cog with its own games, so a task
        holding the old one would edit from state nothing else can see.
        """
        for task in list(self.board_refresh_tasks.values()):
            task.cancel()

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """
        Catch-all for exceptions raised anywhere in a /d12ball command
        (including group subcommands like /d12ball ball move) that
        weren't already handled as an expected ValueError, e.g. a
        dropped connection to Discord. Without this, discord.py just
        logs it and the command looks like it silently did nothing.
        """
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

    async def ensure_coin_emojis(self) -> dict[CoinFace, str]:
        """
        The coin emoji, retrying the lookup while any are missing.

        Uploading the emoji to the application therefore takes effect
        without needing a restart -- but no more often than
        EMOJI_REFETCH_INTERVAL. An application that has never had them
        uploaded is short of them on every single toss, so the retry
        used to mean an HTTP request per coin flip, forever, for a
        lookup whose answer had not changed since startup.
        """
        if len(self.coin_emojis) >= len(COIN_EMOJI_NAMES):
            return self.coin_emojis

        now = time.monotonic()
        if (
            self.coin_emojis_checked_at is not None
            and now - self.coin_emojis_checked_at < EMOJI_REFETCH_INTERVAL
        ):
            return self.coin_emojis
        self.coin_emojis_checked_at = now

        application_emojis = await fetch_application_emojis(self.bot)
        if application_emojis is not None:
            self.coin_emojis = await load_coin_emojis(
                self.bot, application_emojis,
            )

        return self.coin_emojis

    def get_next_game_number(
        self,
        guild: discord.Guild,
    ) -> int:
        existing_numbers = [
            game.game_number
            for game in self.games.values()
            if game.guild_id == guild.id
        ]

        if not existing_numbers:
            return 1

        return max(existing_numbers) + 1

    def formation_shape(self, formation: Formation) -> FormationShape:
        return self.basic_ruleset.formations[Formation(formation)]

    def initialize_standard_match(
        self,
        game: D12BallGame,
    ) -> MatchState:
        if not game.home_and_visiting_selected:
            raise ValueError(
                "Home and visiting teams must be selected first."
            )
        if game.player_1_team is None or game.player_2_team is None:
            raise ValueError("Both teams must be selected first.")

        home_team = (
            game.player_1_team
            if game.home_player_number == 1
            else game.player_2_team
        )
        visiting_team = (
            game.player_1_team
            if game.visiting_player_number == 1
            else game.player_2_team
        )
        match = MatchState.standard(
            catalog=self.player_catalog,
            ruleset=self.basic_ruleset,
            board_size=game.board_size,
            home_team=home_team,
            visiting_team=visiting_team,
        )
        game.ruleset_id = match.ruleset_id
        game.player_data_version = match.player_data_version
        game.match_state = match.to_dict()
        return match

    def load_match_state(self, game: D12BallGame) -> MatchState:
        if game.match_state is None:
            raise ValueError("This game does not have initialized match state.")
        match = MatchState.from_dict(
            game.match_state,
            self.basic_ruleset,
        )
        match.validate(self.player_catalog)
        return match

    def game_for_channel(self, channel_id: int) -> Optional[D12BallGame]:
        for game in self.games.values():
            if game.channel_id == channel_id:
                return game
        return None

    def side_for_user(
        self,
        game: D12BallGame,
        user_id: int,
    ) -> Optional[TeamSide]:
        """
        Which side (home/visiting) a Discord user controls in this
        game, or None if they are not one of its two players, or the
        home/visiting assignment has not been made yet.
        """
        if not game.home_and_visiting_selected:
            return None

        if user_id == game.player_1_id:
            player_number = 1
        elif game.player_2_id is not None and user_id == game.player_2_id:
            player_number = 2
        else:
            return None

        if player_number == game.home_player_number:
            return TeamSide.HOME
        if player_number == game.visiting_player_number:
            return TeamSide.VISITING
        return None

    async def defer_and_get_match(
        self,
        interaction: discord.Interaction,
    ) -> Optional[tuple[D12BallGame, MatchState]]:
        """
        Defer the interaction and load the game/match tied to the
        current channel, replying with an ephemeral error and
        returning None when there isn't one to work with.
        """
        await interaction.response.defer()

        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            await interaction.followup.send(
                "There is no D12 Ball match in progress in this channel.",
                ephemeral=True,
            )
            return None

        match = self.load_match_state(game)
        return game, match

    def get_player_definition(
        self,
        player_id: str,
    ) -> PlayerDefinition:
        return self.player_catalog.player_by_id(player_id)

    def possession_player_number(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> Optional[int]:
        if match.ball.possession == TeamSide.HOME:
            return game.home_player_number
        return game.visiting_player_number

    def possession_user_id(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> Optional[int]:
        player_number = self.possession_player_number(game, match)
        if player_number == 1:
            return game.player_1_id
        if player_number == 2:
            return game.player_2_id
        return None

    def user_controls_possession(
        self,
        user_id: int,
        game: D12BallGame,
        match: MatchState,
    ) -> bool:
        return self.possession_user_id(game, match) == user_id

    def defending_player_number(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> Optional[int]:
        offense_number = self.possession_player_number(game, match)
        if offense_number == 1:
            return 2
        if offense_number == 2:
            return 1
        return None

    def defending_user_id(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> Optional[int]:
        player_number = self.defending_player_number(game, match)
        if player_number == 1:
            return game.player_1_id
        if player_number == 2:
            return game.player_2_id
        return None

    def user_controls_defense(
        self,
        user_id: int,
        game: D12BallGame,
        match: MatchState,
    ) -> bool:
        return self.defending_user_id(game, match) == user_id

    def get_ai_strategy(self, game: D12BallGame) -> AIStrategy:
        return self.ai_strategies[game.ai_opponent or AIOpponent.DINKY]

    def build_maneuver_reference_file(self) -> discord.File:
        return discord.File(
            io.BytesIO(self.maneuver_reference_image_bytes),
            filename="maneuver_reference.png",
        )

    def intervening_defenders(
        self,
        match: MatchState,
    ) -> list[tuple[PlayerDefinition, int]]:
        """
        Every defending player between the ball and the goal it is being
        shot at, each paired with the defensive skill they add to the
        defence's side of a score attempt.
        """
        defenders = []
        for player_id in match.defenders_between_ball_and_goal():
            player = self.get_player_definition(player_id)
            defense = self.player_catalog.effective_profile(player).defense
            defenders.append((player, defense))
        return defenders

    async def begin_score_attempt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Post what the score attempt is made of, then the roll prompt.
        The composition is a message of its own, and an image for the
        same reason the maneuver challenge is one (see
        build_maneuver_challenge_file): a shot is decided by skills and
        abilities that a line of prose lists without showing.
        """
        await interaction.followup.send(
            file=await self.build_score_attempt_file(match),
        )

        # The one thing the image doesn't show is how the two rolls are
        # read against each other, so it rides on the prompt -- which
        # becomes the dice image the moment it is answered, taking the
        # explanation with it once it is no longer needed.
        prompt_message = await interaction.followup.send(
            "Either player can roll. Both sides roll one d12; the "
            "attacker scores on a total equal to or higher than the "
            "defence.",
            view=ScoreAttemptView(self, game.game_id),
            wait=True,
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def auto_resolve_challenger(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        challenger_id: str,
    ) -> None:
        """
        Apply an already-decided challenger pick and move straight on
        to maneuver-action selection -- no human choice involved,
        either because the AI made the pick or because a defender
        already shares the ball's space, leaving nothing to choose
        (see PlayerActionView.choose_action).
        """
        distance = match.choose_challenger(challenger_id)
        # Built before the save: the walk-in's tokens can cross the
        # Exhausted threshold, and that flag is set while the
        # description is put together. See apply_exhaustion.
        walk_in_text = self.describe_challenger_walk_in(
            match, challenger_id, distance,
        )
        game.match_state = match.to_dict()
        save_games(self.games)

        await self.announce_maneuver_challenge(
            interaction, match, challenger_id, walk_in_text,
        )
        await self.refresh_match_image(interaction, game)
        await self.begin_maneuver_action_selection(interaction, game, match)

    async def announce_uncontested_maneuver(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Say that there is nobody to challenge, then go straight to the
        offense's pick. No matchup image: it draws two players against
        each other and there is only one.
        """
        handler = self.get_player_definition(match.active_player_id)
        defense_setup = match.setup_for_side(match.defending_side())

        await interaction.followup.send(
            f"**Unchallenged!** {format_team_side_label(defense_setup)} "
            "have nobody in "
            f"{destination_display_name(match.ball.zone.value)} to "
            f"challenge {format_role_bracket(handler, self.team_emojis)}, "
            "so whichever maneuver the offense picks succeeds."
        )
        await self.begin_maneuver_action_selection(interaction, game, match)

    async def begin_maneuver_action_selection(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Kick off the simultaneous maneuver-action choice once a
        challenger has been chosen: the AI opponent rolls immediately,
        and any human side gets a prompt to open their private
        maneuver menu.

        An uncontested maneuver comes through here too, and waits on
        the offense alone -- there is no defender to pick a defensive
        maneuver, and nothing secret about a pick with nobody to
        conceal it from, but the prompt is the same one so the coach
        reads the same menu they always do.
        """
        if game.is_solo_game:
            ai_strategy = self.get_ai_strategy(game)

            if self.possession_player_number(game, match) == 2:
                match.choose_offense_maneuver(
                    ai_strategy.choose_maneuver_action("offense")
                )
            if (
                not match.maneuver_uncontested
                and self.defending_player_number(game, match) == 2
            ):
                match.choose_defense_maneuver(
                    ai_strategy.choose_maneuver_action("defense")
                )

        game.match_state = match.to_dict()
        save_games(self.games)

        if match.maneuver_selections_complete:
            await self.resolve_maneuver(interaction, game, match)
            return

        waiting_on = []
        if match.offense_maneuver is None:
            waiting_on.append(
                format_player_with_team(
                    game,
                    self.possession_player_number(game, match),
                    mention=True,
                )
            )
        if not match.maneuver_uncontested and match.defense_maneuver is None:
            waiting_on.append(
                format_player_with_team(
                    game,
                    self.defending_player_number(game, match),
                    mention=True,
                )
            )

        instruction = (
            "choose a maneuver. Use the button to make your pick."
            if match.maneuver_uncontested
            else (
                "both sides will now choose a maneuver privately. Use "
                "the button to make your pick."
            )
        )
        prompt_view = ManeuverActionPromptView(self, game.game_id)
        prompt_message = await interaction.followup.send(
            f"{' and '.join(waiting_on)}, {instruction}",
            view=prompt_view,
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def resolve_maneuver(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        offense_name = match.offense_maneuver
        defense_name = match.defense_maneuver
        offense_number = self.possession_player_number(game, match)
        defense_number = self.defending_player_number(game, match)
        offense_display = format_player_with_team(game, offense_number)
        defense_display = format_player_with_team(game, defense_number)

        if match.maneuver_uncontested:
            # Nothing to reveal against and nothing to rank: the
            # offense's pick is the winner, and its effect runs the
            # same pipeline a decisive win always does.
            await interaction.followup.send(
                f"{offense_display} chose **{offense_name}**, "
                f"unchallenged.\n\n## **{offense_name}** succeeds!"
            )
            await self.begin_effect_resolution(
                interaction, game, match, offense_name,
            )
            return

        reveal = (
            f"{offense_display} chose **{offense_name}**.\n"
            f"{defense_display} chose **{defense_name}**."
        )

        outcome = self.maneuver_catalog.resolve(offense_name, defense_name)

        if outcome != "tie":
            winner_name = (
                offense_name if outcome == "offense" else defense_name
            )
            # Headed the same way a won skill test is (see
            # SkillTestView.roll), so the two ways a maneuver can be
            # won read alike. Whoever resolves the effect isn't named
            # here: an effect with a choice in it prompts them by name
            # itself, and one without needs nobody to do anything.
            await interaction.followup.send(
                f"{reveal}\n\n## **{winner_name}** wins!"
            )
            await self.begin_effect_resolution(interaction, game, match, winner_name)
            return

        exhaustion_text = (
            self.apply_exhaustion(match, match.active_player_id, 1)
            + "\n"
            + self.apply_exhaustion(match, match.challenger_id, 1)
        )
        game.match_state = match.to_dict()
        save_games(self.games)

        offense_player = self.get_player_definition(match.active_player_id)
        defense_player = self.get_player_definition(match.challenger_id)
        offense_skill = self.player_catalog.effective_profile(
            offense_player,
        ).offense
        defense_skill = self.player_catalog.effective_profile(
            defense_player,
        ).defense

        # This reveal is a permanent message, separate from the roll
        # prompt below, so it survives every re-roll intact instead of
        # being edited away.
        await interaction.followup.send(
            f"{reveal}\n\n"
            f"**{offense_name}** ties with **{defense_name}** — skill "
            "test!\n\n"
            f"{format_role_bracket(offense_player, self.team_emojis)}: offense skill "
            f"{offense_skill}\n"
            f"{format_role_bracket(defense_player, self.team_emojis)}: defense skill "
            f"{defense_skill}\n\n"
            + exhaustion_text,
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=False,
                everyone=False,
            ),
        )
        await self.refresh_match_image(interaction, game)

        test_message = await interaction.followup.send(
            "Either player can roll:",
            view=SkillTestView(self, game.game_id),
            wait=True,
        )
        game.turn_message_id = test_message.id
        save_games(self.games)

    async def run_injury_test(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        player: PlayerDefinition,
    ) -> None:
        """
        Automatic injury test for an exhausted player who has just
        taken part in a skill test: roll a d12, and if it doesn't beat
        their current exhaustion token count, they become injured.

        Exhausted is judged when the test resolves, not when it
        started, and against every token they hold by then -- the one
        each participant pays to enter the test and one more each time
        a tie sends it back to be rolled again, all of which count. A
        player the test itself pushed over their defensive skill rolls
        this check for that same test.
        """
        if player.player_id in match.injured:
            return

        roll = random.randint(1, 12)
        current_tokens = match.exhaustion.get(player.player_id, 0)
        safe = roll > current_tokens
        dice_file = discord.File(
            await asyncio.to_thread(
                render_injury_test_die,
                roll,
                TEAM_COLORS[player.team],
                player.team.value.title(),
                player.name,
                safe,
            ),
            filename="injury_test_die.png",
        )

        if safe:
            content = (
                f"{format_role_bracket(player, self.team_emojis)} is exhausted and rolls "
                f"an injury test: {roll} beats their {current_tokens} "
                "exhaustion tokens — safe."
            )
        else:
            match.mark_injured(player.player_id)
            game.match_state = match.to_dict()
            save_games(self.games)

            content = (
                f"{format_role_bracket(player, self.team_emojis)} is exhausted and rolls "
                f"an injury test: {roll} does not beat their "
                f"{current_tokens} exhaustion tokens — injury! "
                f"{format_role_bracket(player, self.team_emojis)} now has the condition "
                f"**injured** {get_injured_emoji(self.condition_emojis)}. "
                "Their exhaustion "
                "tokens are removed; they are no longer exhausted and "
                "cannot gain more exhaustion tokens or make another "
                "injury check."
            )
            await self.refresh_match_image(interaction, game)

        await interaction.followup.send(content, file=dice_file)

    def controlling_user_id(
        self,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
    ) -> Optional[int]:
        """
        The Discord user controlling whichever team `player_id` belongs
        to, independent of ball possession -- safe to call right after
        a turnover flips possession, unlike possession_user_id.
        """
        side = (
            TeamSide.HOME
            if player_id in match.home.field_players
            else TeamSide.VISITING
        )
        number = (
            game.home_player_number
            if side == TeamSide.HOME
            else game.visiting_player_number
        )
        if number == 1:
            return game.player_1_id
        if number == 2:
            return game.player_2_id
        return None

    def side_controlled_by_ai(
        self,
        game: D12BallGame,
        match: MatchState,
        side: str,
    ) -> bool:
        if not game.is_solo_game:
            return False
        number = (
            self.possession_player_number(game, match)
            if side == "offense"
            else self.defending_player_number(game, match)
        )
        return number == 2

    def build_effect_choice_view(
        self,
        game_id: str,
        match: MatchState,
    ) -> Optional[discord.ui.View]:
        """
        Reconstruct whichever initial effect-choice prompt is pending
        for a decisively-won maneuver, purely from match state -- used
        both to restore it on a bot restart and (implicitly, by the
        same logic) to post it the first time. Returns None for a
        maneuver that needs no choice (Block Deflect, Pressure) or an
        unrecognized winner -- those resolve synchronously and should
        never actually leave this state persisted except in a narrow
        crash window, which falls back to PlayerActionView.

        A Playmaker's Dribble Advance has two possible pending prompts
        (distance, then speed) with nothing in match state to tell
        them apart, so a restart in that narrow window guesses the
        first one -- the same class of crash-window gap as the
        unrecognized-winner case above. A won Low Pass or High Pass
        that has moved on to its scoring-opportunity attempt/decline
        choice (SetUpAttemptChoiceView) has the same gap, as does a
        Low Pass waiting on which of several teammates on the
        destination space receives it (LowPassReceiverView): this
        always reconstructs the first-stage distance choice instead.
        Nothing has been applied by then, so the coach re-picks.
        """
        if match.maneuver_uncontested:
            winner_name = match.offense_maneuver
        else:
            outcome = self.maneuver_catalog.resolve(
                match.offense_maneuver, match.defense_maneuver,
            )
            if outcome == "tie":
                return None
            winner_name = (
                match.offense_maneuver
                if outcome == "offense"
                else match.defense_maneuver
            )
        if winner_name == "Low Pass":
            return LowPassChoiceView(self, game_id)
        if winner_name == "High Pass":
            return HighPassChoiceView(self, game_id)
        if winner_name == "Dribble Advance":
            handler = self.get_player_definition(match.active_player_id)
            if handler.role == PlayerRole.PLAYMAKER:
                return DribbleAdvanceChoiceView(self, game_id)
            return SpeedDeltaChoiceView(
                self, game_id, match.active_player_id, "offense",
            )
        if winner_name == "Steal Intercept":
            return SpeedDeltaChoiceView(
                self, game_id, match.challenger_id, "defense",
            )
        return None

    def build_run_back_view(
        self,
        game_id: str,
        match: MatchState,
    ) -> Optional[discord.ui.View]:
        """
        Reconstruct the run-back prompt for whichever displaced player
        still needs a real choice. Any forced placements are always
        applied immediately in continue_run_back, before a message is
        ever posted, so anyone still displaced by the time this is
        called needs an actual choice.
        """
        for side in (TeamSide.HOME, TeamSide.VISITING):
            displaced = self.run_back_displaced(match, side)
            if displaced:
                return RunBackChoiceView(self, game_id, displaced[0])
        return None

    async def begin_effect_resolution(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        winner_name: str,
    ) -> None:
        """
        Dispatch a decisively-won maneuver to its effect.
        `offense_maneuver`/`defense_maneuver`/`active_player_id`/
        `challenger_id` all stay set until the whole pipeline (effect,
        any run-back, time) finishes -- reset_maneuver() only happens
        at the very end, in finish_maneuver_resolution -- so a bot
        restart mid-choice can still reconstruct exactly where things
        left off (see build_effect_choice_view).
        """
        handlers = {
            "Low Pass": self.resolve_low_pass,
            "Dribble Advance": self.resolve_dribble_advance,
            "High Pass": self.resolve_high_pass,
            "Block Deflect": self.resolve_block_deflect,
            "Steal Intercept": self.resolve_steal_intercept,
            "Pressure": self.resolve_pressure,
        }
        handler = handlers.get(winner_name)
        if handler is None:
            # Unrecognized maneuver name (future data) -- nothing to
            # automate; leave it to a human, same as before this pass.
            await self.finish_maneuver_resolution(interaction, game, match)
            return
        await handler(interaction, game, match)

    # -- Low Pass --------------------------------------------------

    def low_pass_candidates(
        self,
        match: MatchState,
    ) -> list[tuple[int, str]]:
        """
        A Low Pass has at most three destinations, as (distance,
        receiver) pairs ordered back-to-front for display: the nearest
        teammate ahead of the ball within 2 spaces, the nearest one
        behind it within 2, and a teammate sharing the ball's own
        space. The ball can only be passed to a space someone is
        already standing on.

        **Nearest, not any.** A teammate 2 spaces ahead is no longer a
        destination when another one stands 1 space ahead -- each
        direction offers only the closest, so the choice is between
        directions rather than between distances (2026-08-07).

        **A pass has to reach a different player.** The ball handler
        can't pass to themselves to hold the ball, so distance 0 is a
        candidate only when a *second* offensive player is standing on
        the ball's space, and the receiver named for it is that other
        player. A handler with nobody within two spaces has no legal
        Low Pass at all -- see resolve_low_pass, which is where that
        case is handled rather than here.

        The receiver named here is only the *first* teammate on that
        space, which is all a destination button needs. Where more
        than one is standing there -- ordinary under a formation that
        stacks -- who actually receives the pass is the passer's
        choice: see low_pass_receivers.
        """
        offense_side = match.ball.possession
        offense_players = set(match.setup_for_side(offense_side).field_players)
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )

        candidates: list[tuple[int, str]] = []
        # Each run stops at its first hit: the nearest teammate is the
        # only one that direction offers.
        for distances in ((-1, -2), (0,), (1, 2)):
            for distance in distances:
                receivers = self.low_pass_receivers(match, distance)
                if receivers:
                    candidates.append((distance, receivers[0]))
                    break
        return candidates

    def low_pass_receivers(
        self,
        match: MatchState,
        distance: int,
    ) -> list[str]:
        """
        Every teammate a Low Pass of `distance` could be played to --
        the offensive players standing on that space, minus the
        handler, who cannot pass to themselves.

        Usually one, and then the destination *is* the choice. A
        formation that stacks (2-3-1 or 1-3-2 on a six-space board)
        makes two ordinary, and which of them receives the ball is the
        passer's to pick: it decides who a Winger's set-up hands the
        shot to. Empty when the distance runs off the end of the
        board, or when the space holds nobody but the handler.
        """
        offense_side = match.ball.possession
        offense_players = set(match.setup_for_side(offense_side).field_players)
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        target_flat = match.relative_flat_index(
            origin_flat, offense_side, distance,
        )
        # relative_flat_index() clamps to the board edge -- if that
        # shortened the move, this distance doesn't reach an actual
        # space and isn't a candidate.
        if abs(target_flat - origin_flat) != abs(distance):
            return []

        zone, space_index = match.board.position_at_flat_index(target_flat)
        return [
            player_id
            for player_id in match.board.spaces[zone][space_index]
            if player_id in offense_players
            and player_id != match.active_player_id
        ]

    async def resolve_low_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        candidates = self.low_pass_candidates(match)

        if not candidates:
            # A Low Pass has to reach a different player, so a handler
            # with no teammate within two spaces has won the maneuver
            # and has nowhere to put the ball. The ball goes a space
            # forward and is loose, and its speed still rises by 1
            # (2026-08-07) -- the maneuver's speed bonus doesn't depend
            # on the pass finding anyone.
            offense_side = match.ball.possession
            actual_distance = match.move_ball_relative(offense_side, 1)
            match.ball.speed = min(12, match.ball.speed + 1)
            game.match_state = match.to_dict()
            save_games(self.games)

            # Nothing to move onto at the far end of the field: the
            # ball is loose where it already is.
            movement_note = (
                "the ball rolls a space forward"
                if actual_distance
                else "the ball stays where it is"
            )
            await self.refresh_match_image(interaction, game)
            await self.begin_loose_ball(
                interaction,
                game,
                match,
                distance_moved=max(actual_distance, 1),
                lead_in=(
                    "**Low Pass:** there is no teammate within two "
                    "spaces to receive it, and a pass can't be played "
                    f"to the passer -- {movement_note}. "
                    f"Ball speed is now {match.ball.speed}."
                ),
                headline=(
                    "**Loose ball!** Nobody is there to collect the "
                    "pass -- each side may send a nearby player to "
                    "contest it."
                ),
            )
            return

        if self.side_controlled_by_ai(game, match, "offense"):
            strategy = self.get_ai_strategy(game)
            distance = strategy.choose_low_pass(match, candidates)
            await self.apply_low_pass(
                interaction,
                game,
                match,
                distance,
                receiver_id=strategy.choose_low_pass_receiver(
                    match, self.low_pass_receivers(match, distance),
                ),
            )
            return

        mention = format_player_with_team(
            game,
            self.possession_player_number(game, match),
            mention=True,
        )
        prompt_message = await interaction.followup.send(
            f"{mention}, choose your Low Pass:",
            view=LowPassChoiceView(self, game.game_id),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def apply_low_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance: int,
        receiver_id: Optional[str] = None,
    ) -> None:
        offense_side = match.ball.possession
        handler = self.get_player_definition(match.active_player_id)
        # Read before the ball moves, because the receivers are
        # relative to where it is now. `receiver_id` is who the passer
        # picked out of a shared space; without one -- a single
        # occupant, so nothing was asked -- it is whoever is standing
        # there. Either way this is the player the pass was aimed at,
        # which is not always the same as whoever the landing space's
        # occupant list happens to start with -- see the Winger branch
        # below.
        receivers = self.low_pass_receivers(match, distance)
        if receiver_id not in receivers:
            receiver_id = receivers[0] if receivers else None

        actual_distance = match.move_ball_relative(offense_side, distance)
        match.ball.speed = min(12, match.ball.speed + 1)
        # A pass across a shared space sends the passer a space forward
        # (2026-08-07) -- the ball hasn't gone anywhere, so this is what
        # the maneuver buys. Clamped at the far end of the field, where
        # there is nowhere to run to.
        passer_advance = (
            match.move_player_relative(match.active_player_id, offense_side, 1)
            if distance == 0
            else 0
        )
        game.match_state = match.to_dict()
        save_games(self.games)

        if distance == 0:
            movement_note = "goes to a teammate in the same space"
            if passer_advance:
                movement_note += (
                    f", and {format_role_bracket(handler, self.team_emojis)} "
                    "moves a space forward"
                )
        else:
            direction = "forward" if distance > 0 else "backward"
            space_word = "space" if actual_distance == 1 else "spaces"
            movement_note = f"moves {actual_distance} {space_word} {direction}"
        content = (
            f"**Low Pass:** the ball {movement_note}. "
            f"Ball speed is now {match.ball.speed}."
        )
        # Time always advances at least 1 space minute, even on a
        # distance-0 pass across a shared space.
        distance_moved = max(actual_distance, 1)

        # Role ability -- Winger: the receiving player may attempt a
        # scoring opportunity right where the pass lands, whatever the
        # distance -- unlike High Pass's set-up, this doesn't require
        # reaching the space nearest the goal. It does require the
        # other team's half, like any other shot: the ability frees the
        # set-up from a distance, not from where a goal can be scored
        # from.
        if handler.role != PlayerRole.WINGER or not match.can_attempt_score(
            offense_side,
        ):
            await self.refresh_match_image(interaction, game)
            await self.finish_maneuver_resolution(
                interaction,
                game,
                match,
                distance_moved=distance_moved,
                lead_in=content,
            )
            return

        if receiver_id is None:
            # Only reachable if the board changed under a stale
            # choice; fall back to whoever is on the ball's space.
            receiver_id = match.eligible_ball_handlers()[0]
        await self.refresh_match_image(interaction, game)
        await self.offer_scoring_attempt_choice(
            interaction,
            game,
            match,
            shooter_id=receiver_id,
            distance_moved=distance_moved,
            lead_in=(
                f"{content} "
                f"{format_role_bracket(handler, self.team_emojis)}'s Winger "
                "ability can turn this into a scoring opportunity!"
            ),
        )

    # -- Dribble Advance ---------------------------------------------

    async def resolve_dribble_advance(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        # Role ability -- Playmaker: may advance 2 spaces instead of
        # the usual 1. Everyone else has no choice to make here, so
        # they skip straight to applying the fixed 1-space advance.
        handler = self.get_player_definition(match.active_player_id)
        if handler.role != PlayerRole.PLAYMAKER:
            await self.apply_dribble_advance(interaction, game, match, 1)
            return

        if self.side_controlled_by_ai(game, match, "offense"):
            distance = self.get_ai_strategy(
                game
            ).choose_dribble_advance_distance(match)
            await self.apply_dribble_advance(
                interaction, game, match, distance
            )
            return

        mention = format_player_with_team(
            game,
            self.possession_player_number(game, match),
            mention=True,
        )
        prompt_message = await interaction.followup.send(
            f"{mention}, choose your Dribble Advance distance "
            "(Playmaker ability):",
            view=DribbleAdvanceChoiceView(self, game.game_id),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def apply_dribble_advance(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance: int,
    ) -> None:
        offense_side = match.ball.possession
        actual_distance = match.move_player_relative(
            match.active_player_id, offense_side, distance,
        )
        match.set_ball_space(
            *match.board.meeple_position(match.active_player_id)
        )
        game.match_state = match.to_dict()
        save_games(self.games)

        handler = self.get_player_definition(match.active_player_id)
        await self.refresh_match_image(interaction, game)

        space_word = "space" if actual_distance == 1 else "spaces"
        ability_note = (
            " (Playmaker ability)"
            if handler.role == PlayerRole.PLAYMAKER and distance > 1
            else ""
        )

        await self.offer_speed_choice(
            interaction,
            game,
            match,
            player_id=match.active_player_id,
            skill_type="offense",
            lead_in=(
                f"**Dribble Advance:** "
                f"{format_role_bracket(handler, self.team_emojis)} and the "
                f"ball move forward {actual_distance} {space_word}"
                f"{ability_note}."
            ),
        )

    # -- High Pass -----------------------------------------------------

    async def resolve_high_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        handler = self.get_player_definition(match.active_player_id)
        max_distance = 4 if handler.role == PlayerRole.FULLBACK else 3

        if self.side_controlled_by_ai(game, match, "offense"):
            distance = self.get_ai_strategy(game).choose_high_pass_distance(
                match, max_distance,
            )
            await self.apply_high_pass(interaction, game, match, distance)
            return

        mention = format_player_with_team(
            game,
            self.possession_player_number(game, match),
            mention=True,
        )
        prompt_message = await interaction.followup.send(
            f"{mention}, choose your High Pass distance:",
            view=HighPassChoiceView(self, game.game_id),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def apply_high_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance: int,
    ) -> None:
        offense_side = match.ball.possession
        handler = self.get_player_definition(match.active_player_id)
        # Role ability -- Fullback: can choose to pass up to 4 spaces
        # instead of the usual 2-3 max (see HighPassChoiceView).
        fullback_bonus = handler.role == PlayerRole.FULLBACK and distance == 4

        actual_distance = match.move_ball_relative(offense_side, distance)
        game.match_state = match.to_dict()
        save_games(self.games)

        space_word = "space" if actual_distance == 1 else "spaces"
        ability_note = " (Fullback ability)" if fullback_bonus else ""
        content = (
            f"**High Pass:** the ball moves {actual_distance} {space_word} "
            f"forward{ability_note}."
        )

        # A pass of 2 is received cleanly: no contest at all
        # (2026-08-07), and it may set up a scoring opportunity for
        # whoever it lands on -- unlike the old fixed-2 High Pass,
        # this no longer requires overshooting the field. A longer
        # pass never offers it, whether or not it happens to overshoot.
        setup_candidates = []
        if distance == 2:
            setup_candidates = self.set_up_shot_candidates(
                match, offense_side,
            )

        if setup_candidates:
            await self.refresh_match_image(interaction, game)
            await self.offer_scoring_attempt_choice(
                interaction,
                game,
                match,
                shooter_id=setup_candidates[0],
                distance_moved=actual_distance,
                lead_in=f"{content} That reaches a teammate -- a scoring "
                "opportunity!",
            )
            return

        # No scoring-opportunity option (or the requested distance
        # wasn't a 2). If nobody from the offense is standing where the
        # pass landed, this isn't the High Pass "receiver must win a
        # skill test" contest at all -- it's a plain loose ball (or an
        # uncontested turnover), exactly like any other maneuver that
        # overshoots into empty or enemy territory.
        receiver_candidates = self.scoring_opportunity_candidates(
            match, offense_side,
        )

        # A 2-space pass that found its receiver but not the other
        # team's half is just a pass: it was received cleanly, and the
        # only thing the half rule takes away is the shot. Falling
        # through would hand it to the long-pass contest below, which
        # a pass of 2 has never had to win.
        if distance == 2 and receiver_candidates:
            await self.refresh_match_image(interaction, game)
            await self.finish_maneuver_resolution(
                interaction, game, match, distance_moved=actual_distance,
                lead_in=content,
            )
            return

        if not receiver_candidates:
            await self.refresh_match_image(interaction, game)
            await self.finish_maneuver_resolution(
                interaction, game, match, distance_moved=actual_distance,
                lead_in=content,
            )
            return

        # A teammate is standing right where the pass landed, and the
        # pass went 3 or more -- a distance of 2 with a teammate there
        # took the set-up branch above, since both branches ask
        # scoring_opportunity_candidates the same question. A long
        # High Pass still forces a skill test to keep the ball, unlike
        # any other maneuver. That receiver is the automatic offense
        # contestant, and a defender already sharing the same space
        # (spaces are shared between both sides -- see
        # defenders_between_ball_and_goal) is likewise automatic; only
        # a side with nobody exactly there still has to pick someone
        # nearby to send.
        defender_on_space = self.scoring_opportunity_candidates(
            match, match.defending_side(),
        )
        await self.refresh_match_image(interaction, game)
        await self.begin_loose_ball(
            interaction,
            game,
            match,
            actual_distance,
            lead_in=content,
            headline=HIGH_PASS_CONTEST_HEADLINE,
            is_high_pass=True,
            forced_offense_player=receiver_candidates[0],
            forced_defense_player=(
                defender_on_space[0] if defender_on_space else None
            ),
        )

    async def offer_scoring_attempt_choice(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        *,
        shooter_id: str,
        distance_moved: int,
        lead_in: str,
    ) -> None:
        """
        Offer the offense a chance to attempt a scoring-opportunity
        shot instead of letting a maneuver resolve normally -- used by
        a High Pass's 2-space pass and a Winger's Low Pass. Declining
        always resolves the maneuver as a normal pass; a 2-space High
        Pass stopped forcing a contest instead on 2026-08-07.
        """
        if self.side_controlled_by_ai(game, match, "offense"):
            attempt = self.get_ai_strategy(
                game
            ).choose_scoring_opportunity_attempt(match)
            if lead_in:
                await interaction.followup.send(lead_in)
            if attempt:
                await self.start_set_up_shot(
                    interaction, game, match, shooter_id,
                )
            else:
                await self.decline_scoring_attempt(
                    interaction, game, match, distance_moved,
                )
            return

        shooter = self.get_player_definition(shooter_id)
        prompt_message = await interaction.followup.send(
            f"{lead_in}\n\n"
            f"{format_role_bracket(shooter, self.team_emojis)} can attempt "
            "the scoring opportunity, or let it go:",
            view=SetUpAttemptChoiceView(
                self, game.game_id, shooter_id, distance_moved,
            ),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def decline_scoring_attempt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int,
    ) -> None:
        """
        Let go of a scoring opportunity: the maneuver that offered it
        resolves as it otherwise would have.
        """
        await self.finish_maneuver_resolution(
            interaction, game, match, distance_moved=distance_moved,
        )

    def set_up_shot_candidates(
        self,
        match: MatchState,
        offense_side: TeamSide,
    ) -> list[str]:
        """
        Who could take a set-up's shot where the ball has landed:
        `scoring_opportunity_candidates`, and nobody at all unless the
        ball is in the other team's half, since a set-up's shot is an
        ordinary score attempt and obeys the same rule about where a
        shot may be taken from.

        The two are separate because only some callers of
        `scoring_opportunity_candidates` are asking about a shot -- a
        long High Pass asks it to find the receiver who has to contest
        for the ball, and that has nothing to do with where the goal
        is.
        """
        if not match.can_attempt_score(offense_side):
            return []
        return self.scoring_opportunity_candidates(match, offense_side)

    def scoring_opportunity_candidates(
        self,
        match: MatchState,
        offense_side: TeamSide,
    ) -> list[str]:
        """
        Offensive players occupying the ball's current (overshot)
        space -- the field of shooter candidates a set-up offers,
        shared by High Pass and a Winger's Low Pass.
        """
        offense_setup = match.setup_for_side(offense_side)
        occupants = match.board.spaces[match.ball.zone][
            match.ball.space_index
        ]
        return [
            player_id
            for player_id in occupants
            if player_id in offense_setup.field_players
        ]

    # -- Loose ball (a pass landing on an empty space) -----------------

    def is_landing_space_empty(self, match: MatchState) -> bool:
        return not match.board.spaces[match.ball.zone][match.ball.space_index]

    async def check_for_loose_ball(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int,
        lead_in: str = "",
    ) -> bool:
        """
        The one check every maneuver-effect path runs through, via
        finish_maneuver_resolution: does the possessing team actually
        have a player on the ball's space? If not, this detours into
        whatever loose-ball flow applies instead of letting the turn
        proceed with nobody eligible to act -- returns True when it
        took that detour, so the caller stops instead of continuing.
        """
        if match.eligible_ball_handlers():
            return False

        if self.is_landing_space_empty(match):
            await self.begin_loose_ball(
                interaction, game, match, distance_moved, lead_in=lead_in,
            )
            return True

        # Not empty, but nobody from the possessing team is there --
        # an opposing player is already standing on the ball. Clean,
        # uncontested turnover: no movement, no skill test.
        new_side = match.defending_side()
        recoverer_id = match.board.spaces[match.ball.zone][
            match.ball.space_index
        ][0]
        player = self.get_player_definition(recoverer_id)
        match.set_possession(new_side)
        match.ball.speed = 1
        game.match_state = match.to_dict()
        save_games(self.games)

        prefix = f"{lead_in}\n\n" if lead_in else ""
        await interaction.followup.send(
            f"{prefix}# Turnover!\n"
            f"{format_role_bracket(player, self.team_emojis)} is already "
            f"there -- {format_team_side_label(match.setup_for_side(new_side))} "
            "wins the loose ball uncontested."
        )
        await self.refresh_match_image(interaction, game)
        # A loose ball the other team picks up is a steal, so no
        # substitution window -- the ball never went dead.
        await self.begin_run_back(
            interaction, game, match,
            distance_moved=distance_moved, turnover_occurred=True,
        )
        return True

    def loose_ball_candidates(
        self,
        match: MatchState,
        side: TeamSide,
    ) -> list[str]:
        """
        Who `side` may send after a loose ball: their own fielded
        players in the ball's zone, and nobody else. A side with none
        there sends nobody, which is not a failure state -- with
        neither side able (or willing) to send anyone, the ball is out
        of bounds, and resolve_loose_ball takes it from there.
        """
        return match.fielded_players_in_zone(side, match.ball.zone)

    def loose_ball_sides_ready(
        self,
        match: MatchState,
    ) -> tuple[bool, bool]:
        """
        Whether the offense/defense pick is settled -- made, declined,
        or moot because that side has nobody in the zone to send.
        """
        offense_ready = (
            match.loose_ball_offense_player is not None
            or match.loose_ball_offense_declined
            or not self.loose_ball_candidates(match, match.ball.possession)
        )
        defense_ready = (
            match.loose_ball_defense_player is not None
            or match.loose_ball_defense_declined
            or not self.loose_ball_candidates(match, match.defending_side())
        )
        return offense_ready, defense_ready

    def auto_resolve_loose_ball_picks(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Settle whichever side can't get a real human choice, i.e. is
        AI-controlled. A side with no candidates at all is left unset
        -- resolve_loose_ball reads that as "nobody available", not
        "still deciding".

        A lone candidate is *not* auto-picked, unlike a forced run
        back: sending them is optional, and declining is what puts the
        ball out of bounds, so one candidate is still a real choice
        between two outcomes.
        """
        for side, skill_type, choose in (
            (
                match.ball.possession,
                "offense",
                match.choose_loose_ball_offense_player,
            ),
            (
                match.defending_side(),
                "defense",
                match.choose_loose_ball_defense_player,
            ),
        ):
            picked, declined = (
                (match.loose_ball_offense_player,
                 match.loose_ball_offense_declined)
                if skill_type == "offense"
                else (match.loose_ball_defense_player,
                      match.loose_ball_defense_declined)
            )
            if picked is not None or declined:
                continue

            candidates = self.loose_ball_candidates(match, side)
            if not candidates:
                continue
            if self.side_controlled_by_ai(game, match, skill_type):
                # The AI always contests -- it has no decline policy,
                # and going out of bounds by choice is never obviously
                # right (see d12ball/ai.py).
                choose(
                    self.get_ai_strategy(game).choose_loose_ball_player(
                        candidates, skill_type,
                    )
                )

    def loose_ball_side_on_the_clock(
        self,
        match: MatchState,
    ) -> Optional[str]:
        """
        Which side still owes a pick, "offense" or "defense" -- or
        None when the contest is settled either way.

        The side that last held possession chooses first and alone.
        Both used to be offered at once, which handed whoever clicked
        second the other's answer to decide against; a loose ball is
        theirs to lose, so they commit first.
        """
        offense_ready, defense_ready = self.loose_ball_sides_ready(match)
        if not offense_ready:
            return "offense"
        if not defense_ready:
            return "defense"
        return None

    def loose_ball_prompt_side(self, match: MatchState) -> TeamSide:
        """The board side whose turn it is to pick."""
        return (
            match.ball.possession
            if self.loose_ball_side_on_the_clock(match) == "offense"
            else match.defending_side()
        )

    def build_loose_ball_view(
        self,
        game_id: str,
        match: MatchState,
    ) -> Optional[discord.ui.View]:
        """
        Reconstruct the loose-ball pick prompt for the one side
        currently on the clock -- purely from match state, so a bot
        restart mid-pick reconstructs correctly, same as
        build_run_back_view.
        """
        skill_type = self.loose_ball_side_on_the_clock(match)
        if skill_type is None:
            return None
        side = self.loose_ball_prompt_side(match)
        return LooseBallChoiceView(
            self,
            game_id,
            skill_type,
            self.loose_ball_candidates(match, side),
            match,
        )

    def build_loose_ball_prompt(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> str:
        """Who is being asked, and for what."""
        skill_type = self.loose_ball_side_on_the_clock(match)
        number = (
            self.possession_player_number(game, match)
            if skill_type == "offense"
            else self.defending_player_number(game, match)
        )
        mention = format_player_with_team(game, number, mention=True)
        noun = contest_noun(match)
        if skill_type == "offense":
            return (
                f"{mention}, you had the ball -- send a player from the "
                f"zone after the {noun}, or send nobody:"
            )
        return (
            f"{mention}, choose who contests the {noun}, or send nobody:"
        )

    async def begin_loose_ball(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int,
        lead_in: str = "",
        headline: str = (
            "**Loose ball!** The pass lands in an empty space -- each "
            "side may send a nearby player to contest it."
        ),
        is_high_pass: bool = False,
        forced_offense_player: Optional[str] = None,
        forced_defense_player: Optional[str] = None,
    ) -> None:
        """
        `distance_moved` (the pass's own clamped travel) is stashed on
        `match` by begin_loose_ball() -- the pick and, if it comes to
        one, the skill test both span later interactions that can't
        see a Python-level parameter from this call, so everything
        downstream reads it back from match state instead.

        `lead_in` is narration from the pass that hasn't been posted
        yet -- it rides along on this function's own first message.

        `headline` overrides the default "lands in an empty space"
        framing -- a High Pass reuses this same contest even when the
        landing space isn't empty (a 3+ space pass, or a declined
        2-space one, always makes the receiver win a skill test to
        keep the ball), so its own call site passes wording that
        doesn't claim emptiness.

        `forced_offense_player`/`forced_defense_player` skip that
        side's pick entirely -- a High Pass forces the contest even
        when a side is already standing right on the landing space,
        and that occupant is the only sensible contestant for their
        side, not a fresh pick from the whole zone.
        """
        match.begin_loose_ball(distance_moved, is_high_pass=is_high_pass)
        if forced_offense_player is not None:
            match.choose_loose_ball_offense_player(forced_offense_player)
        if forced_defense_player is not None:
            match.choose_loose_ball_defense_player(forced_defense_player)
        self.auto_resolve_loose_ball_picks(game, match)
        game.match_state = match.to_dict()
        save_games(self.games)

        prefix = f"{lead_in}\n\n" if lead_in else ""
        await interaction.followup.send(f"{prefix}{headline}")

        if self.loose_ball_side_on_the_clock(match) is None:
            await self.resolve_loose_ball(interaction, game, match)
            return

        prompt_message = await interaction.followup.send(
            self.build_loose_ball_prompt(game, match),
            view=self.build_loose_ball_view(game.game_id, match),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def resolve_loose_ball(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        offense_player_id = match.loose_ball_offense_player
        defense_player_id = match.loose_ball_defense_player
        distance_moved = match.pending_loose_ball_distance
        is_high_pass = match.pending_loose_ball_is_high_pass
        ball_noun = contest_noun(match)

        if offense_player_id is None and defense_player_id is None:
            # Out of bounds: nobody could be sent, or nobody was. The
            # side that last held the ball loses it, and the side that
            # just won it owes a player on the ball's space -- placed
            # after the run back, not before, or the run back would
            # pull that player straight back off the ball again.
            winning_side = match.defending_side()
            reason = (
                "Nobody is sent after it"
                if match.loose_ball_offense_declined
                or match.loose_ball_defense_declined
                else "Neither side has a player in the zone"
            )
            # Assigned rather than set_possession'd: that insists on a
            # player of the new side already standing on the ball,
            # and out of bounds is precisely the case where nobody is
            # -- pending_ball_recovery is the promise that somebody
            # will be, once the run back is done.
            match.ball.possession = winning_side
            match.ball.speed = 1
            match.pending_loose_ball = False
            match.pending_ball_recovery = True
            game.match_state = match.to_dict()
            save_games(self.games)

            await interaction.followup.send(
                f"**Out of bounds!** {reason} -- "
                f"{format_team_side_label(match.setup_for_side(winning_side))} "
                "take over.\n\n# Turnover!\nOnce everyone has run back, "
                "they place a player on the ball."
            )
            await self.refresh_match_image(interaction, game)
            # Out of bounds is the one loose ball that is a new play
            # rather than a steal: nobody took the ball off anyone, it
            # simply went dead and is being brought back in.
            await self.begin_run_back(
                interaction, game, match,
                distance_moved=distance_moved,
                turnover_occurred=True,
                new_play=True,
            )
            return

        if defense_player_id is None:
            player = self.get_player_definition(offense_player_id)
            recovery_distance = match.distance_to_ball(offense_player_id)
            match.move_meeple(
                offense_player_id, match.ball.zone, match.ball.space_index,
            )
            exhaustion_text = self.apply_exhaustion(
                match, offense_player_id, recovery_distance,
            )
            match.pending_loose_ball = False
            game.match_state = match.to_dict()
            save_games(self.games)

            recovery_line = (
                f"{format_role_bracket(player, self.team_emojis)} keeps "
                "possession after the high pass, uncontested."
                if is_high_pass
                else f"{format_role_bracket(player, self.team_emojis)} "
                "recovers the loose ball uncontested."
            )
            await interaction.followup.send(
                f"{recovery_line}\n{exhaustion_text}"
            )
            await self.refresh_match_image(interaction, game)
            await self.begin_run_back(
                interaction, game, match,
                distance_moved=distance_moved, turnover_occurred=False,
            )
            return

        if offense_player_id is None:
            # Only the defending side went for it -- because the side
            # in possession had nobody in the zone, or sent nobody.
            # Not out of bounds: that is the branch above, where
            # neither side ends up with a player to send.
            player = self.get_player_definition(defense_player_id)
            recovery_distance = match.distance_to_ball(defense_player_id)
            match.move_meeple(
                defense_player_id, match.ball.zone, match.ball.space_index,
            )
            exhaustion_text = self.apply_exhaustion(
                match, defense_player_id, recovery_distance,
            )
            match.ball.possession = match.defending_side()
            match.ball.speed = 1
            match.pending_loose_ball = False
            game.match_state = match.to_dict()
            save_games(self.games)

            headline = (
                f"{format_role_bracket(player, self.team_emojis)} "
                "picks off the high pass, uncontested."
                if is_high_pass
                else f"{format_role_bracket(player, self.team_emojis)} "
                "recovers the loose ball uncontested."
            )
            await interaction.followup.send(
                "# Turnover!\n"
                f"{headline} "
                f"{format_team_side_label(match.setup_for_side(match.ball.possession))} "
                f"now has possession -- {format_role_bracket(player, self.team_emojis)} "
                f"gets to the ball.\n{exhaustion_text}"
            )
            await self.refresh_match_image(interaction, game)
            # Picked off rather than restarted -- a steal, and so no
            # substitution window.
            await self.begin_run_back(
                interaction, game, match,
                distance_moved=distance_moved, turnover_occurred=True,
            )
            return

        # Both sides have a candidate -- move them both in, charge each
        # their own recovery distance in exhaustion, and run the actual
        # skill test.
        offense_recovery_distance = match.distance_to_ball(offense_player_id)
        defense_recovery_distance = match.distance_to_ball(defense_player_id)
        match.move_meeple(
            offense_player_id, match.ball.zone, match.ball.space_index,
        )
        match.move_meeple(
            defense_player_id, match.ball.zone, match.ball.space_index,
        )
        exhaustion_text = "\n".join(
            [
                self.apply_exhaustion(
                    match, offense_player_id, offense_recovery_distance,
                ),
                self.apply_exhaustion(
                    match, defense_player_id, defense_recovery_distance,
                ),
            ]
        )
        game.match_state = match.to_dict()
        save_games(self.games)
        await self.refresh_match_image(interaction, game)

        offense_player = self.get_player_definition(offense_player_id)
        defense_player = self.get_player_definition(defense_player_id)
        offense_skill = self.player_catalog.effective_profile(
            offense_player,
        ).offense
        defense_skill = self.player_catalog.effective_profile(
            defense_player,
        ).defense

        # Who is defending what differs between the two: a High Pass's
        # receiver already has the ball and is being challenged for it,
        # where a loose ball belongs to nobody yet and both sides are
        # going for it.
        contest_line = (
            f"{format_role_bracket(defense_player, self.team_emojis)} "
            f"(defense skill {defense_skill}) challenges "
            f"{format_role_bracket(offense_player, self.team_emojis)} "
            f"(offense skill {offense_skill}) for the high pass -- the "
            "receiver must win this skill test to keep possession!"
            if is_high_pass
            else f"{format_role_bracket(offense_player, self.team_emojis)} "
            f"(offense skill {offense_skill}) and "
            f"{format_role_bracket(defense_player, self.team_emojis)} "
            f"(defense skill {defense_skill}) both contest the "
            f"{ball_noun} -- skill test!"
        )
        test_message = await interaction.followup.send(
            f"{contest_line}\n{exhaustion_text}\n\nEither "
            "player can roll:",
            view=LooseBallSkillTestView(self, game.game_id),
            wait=True,
        )
        game.turn_message_id = test_message.id
        save_games(self.games)

    async def begin_shooter_choice(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        candidates: list[str],
        lead_in: str = "",
    ) -> None:
        """
        `lead_in` is narration from the pass that set this scoring
        opportunity up -- it rides along on the "choose who takes the
        shot" prompt when a human has to pick. When the pick is
        automatic there's no prompt to attach it to, so it's posted on
        its own instead of being dropped.
        """
        if len(candidates) == 1 or self.side_controlled_by_ai(
            game, match, "offense",
        ):
            if len(candidates) == 1:
                shooter_id = candidates[0]
            else:
                shooter_id = self.get_ai_strategy(game).choose_shooter(
                    candidates, match,
                )
            if lead_in:
                await interaction.followup.send(lead_in)
            await self.start_set_up_shot(interaction, game, match, shooter_id)
            return

        mention = format_player_with_team(
            game,
            self.possession_player_number(game, match),
            mention=True,
        )
        prefix = f"{lead_in}\n\n" if lead_in else ""
        prompt_message = await interaction.followup.send(
            f"{prefix}{mention}, choose who takes the shot:",
            view=ShooterChoiceView(self, game.game_id, candidates),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def start_set_up_shot(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        shooter_id: str,
    ) -> None:
        match.active_player_id = shooter_id
        match.pending_action = "shoot"
        match.pending_shot_is_set_up = True
        game.match_state = match.to_dict()
        save_games(self.games)

        shooter = self.get_player_definition(shooter_id)
        await interaction.followup.send(
            f"{format_role_bracket(shooter, self.team_emojis)} takes the "
            "shot off the set-up."
        )
        await self.begin_score_attempt(interaction, game, match)

    # -- Block Deflect -------------------------------------------------

    async def resolve_block_deflect(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        offense_side = match.ball.possession
        defense_side = match.defending_side()
        defender = self.get_player_definition(match.challenger_id)

        # Role ability -- Fullback: deflects the ball back 2 spaces
        # instead of the usual 1.
        fullback_bonus = defender.role == PlayerRole.FULLBACK
        deflect_distance = 2 if fullback_bonus else 1

        # Overshoot: the deflection is clamped short of the full
        # distance, i.e. the ball was already close enough to the
        # offense's own goal that there was nowhere to put it. That no
        # longer risks an own goal -- only Pressure does -- it sets up
        # a scoring opportunity for the defense instead, who are now
        # the side standing next to the goal the ball just reached.
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        target_flat = match.relative_flat_index(
            origin_flat, offense_side, -deflect_distance,
        )
        overshot = abs(target_flat - origin_flat) < deflect_distance

        actual_distance = match.move_ball_relative(
            offense_side, -deflect_distance,
        )
        match.ball.speed = max(1, match.ball.speed - 1)
        game.match_state = match.to_dict()
        save_games(self.games)

        space_word = "space" if actual_distance == 1 else "spaces"
        ability_note = " (Fullback ability)" if fullback_bonus else ""
        content = (
            f"**Block Deflect:** the ball moves {actual_distance} "
            f"{space_word} back{ability_note}. Ball speed is now "
            f"{match.ball.speed}."
        )

        # A shot has to come from the other team's half, and this one
        # always does: an overshoot means the ball reached the space
        # closest to the offense's own goal, which is as deep in the
        # deflecting team's attacking half as the field goes. So this
        # asks scoring_opportunity_candidates rather than
        # set_up_shot_candidates -- the half check could never fail
        # here, and a branch that cannot be taken reads as if it could.
        candidates = []
        if overshot:
            candidates = self.scoring_opportunity_candidates(
                match, defense_side,
            )

        if not candidates:
            await self.refresh_match_image(interaction, game)
            # Block Deflect's time cost is a fixed 1 space minute per
            # the rules table, not "distance traveled" like Low/High
            # Pass, so this doesn't shrink if the move was clamped at
            # the edge (or grow with the Fullback's extra distance).
            await self.finish_maneuver_resolution(
                interaction, game, match, distance_moved=1, lead_in=content,
            )
            return

        # A defender standing right where the ball ends up gets a shot
        # at the goal it's now next to -- that's a turnover before the
        # shot, same as any other change of possession, so the score
        # attempt reads the correct attacking/defending sides.
        match.ball.possession = defense_side
        match.ball.speed = 1
        game.match_state = match.to_dict()
        save_games(self.games)

        await self.refresh_match_image(interaction, game)
        await self.begin_shooter_choice(
            interaction,
            game,
            match,
            candidates,
            lead_in=f"{content} That overshoots the field -- a scoring "
            "opportunity!",
        )

    # -- Steal Intercept -------------------------------------------------

    async def resolve_steal_intercept(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        new_possession_side = match.defending_side()
        challenger_id = match.challenger_id

        # The turnover happens first, then both the interceptor and the
        # ball fall back 1 space -- toward the *new* possessing side's
        # own goal, not the old side's. Moving the challenger's meeple
        # (not just the ball) and re-deriving the ball's space from it
        # keeps the two in the same space, so possession can be assigned
        # directly without set_possession's occupancy check.
        match.ball.possession = new_possession_side
        # Every turnover drops the ball's speed back to 1 -- the
        # defender's manipulate-speed choice below applies to that
        # reset value, not whatever the speed was before the steal.
        match.ball.speed = 1
        actual_distance = match.move_player_relative(
            challenger_id, new_possession_side, -1,
        )
        match.set_ball_space(*match.board.meeple_position(challenger_id))
        game.match_state = match.to_dict()
        save_games(self.games)

        space_word = "space" if actual_distance == 1 else "spaces"
        challenger = self.get_player_definition(challenger_id)
        new_possession = match.setup_for_side(match.ball.possession)
        await self.refresh_match_image(interaction, game)

        # Ball-speed manipulation is offered after run-back finishes,
        # not here -- see begin_run_back's speed_choice_after.
        await self.begin_run_back(
            interaction,
            game,
            match,
            stays_player_id=challenger_id,
            speed_choice_after=True,
            lead_in=(
                "**Steal Intercept:**\n"
                "# Turnover!\n"
                f"{format_role_bracket(challenger, self.team_emojis)} "
                f"steals the ball. "
                f"{format_team_side_label(new_possession)} now has "
                f"possession, then falls back {actual_distance} "
                f"{space_word} toward their own goal with the ball."
            ),
        )

    # -- Pressure --------------------------------------------------------

    async def resolve_pressure(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        offense_side = match.ball.possession
        defense_side = match.defending_side()

        # Own-goal risk: Pressure is the only maneuver that threatens
        # one now, and only when the ball-holder is already at the
        # space closest to their own goal, i.e. pushing them back
        # further isn't possible.
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        target_flat = match.relative_flat_index(origin_flat, offense_side, -1)
        overshot = abs(target_flat - origin_flat) < 1

        actual_distance = match.move_player_relative(
            match.active_player_id, offense_side, -1,
        )
        match.set_ball_space(
            *match.board.meeple_position(match.active_player_id)
        )
        match.move_player_relative(match.challenger_id, defense_side, 1)

        handler = self.get_player_definition(match.active_player_id)
        defender = self.get_player_definition(match.challenger_id)
        space_word = "space" if actual_distance == 1 else "spaces"
        content = (
            f"**Pressure:** "
            f"{format_role_bracket(handler, self.team_emojis)} and the "
            f"ball go back {actual_distance} {space_word}. "
            f"{format_role_bracket(defender, self.team_emojis)} moves "
            "forward."
        )

        if overshot:
            game.match_state = match.to_dict()
            save_games(self.games)
            await interaction.followup.send(
                f"{content}\n\nThat overshoots toward their own goal!",
            )
            await self.refresh_match_image(interaction, game)
            # An own goal takes priority over the Defender's steal
            # ability below: if it's conceded, the point is already
            # over, and stealing a ball that was just kicked off from
            # the restart wouldn't mean anything.
            await self.run_own_goal_roll(
                interaction, game, match, distance_moved=1,
            )
            return

        # Role ability -- Defender: also steals the ball on a Pressure
        # win, on top of the normal effect above.
        stolen = defender.role == PlayerRole.DEFENDER
        if stolen:
            match.ball.possession = defense_side
            match.ball.speed = 1
            content += (
                "\n\n# Turnover!\n"
                f"{format_role_bracket(defender, self.team_emojis)} "
                "steals the ball (Defender ability)! "
                f"{format_team_side_label(match.setup_for_side(defense_side))} "
                "now has possession."
            )

        game.match_state = match.to_dict()
        save_games(self.games)

        await self.refresh_match_image(interaction, game)

        # Fixed 1 space minute per the rules table, independent of
        # clamping, same reasoning as Block Deflect above.
        if stolen:
            # The stealing player keeps the ball and stays put --
            # everyone else who's out of position runs back.
            await self.begin_run_back(
                interaction,
                game,
                match,
                lead_in=content,
                stays_player_id=match.challenger_id,
            )
        else:
            await self.finish_maneuver_resolution(
                interaction, game, match, distance_moved=1, lead_in=content,
            )

    # -- Ball-speed manipulation (Dribble Advance / Steal Intercept) --

    async def offer_speed_choice(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
        skill_type: str,
        turnover_occurred: bool = False,
        distance_moved: int = 1,
        lead_in: str = "",
    ) -> None:
        """
        Always the last human choice in a maneuver's effect -- speed is
        manipulated after any run-back it caused (Steal Intercept), so
        this leads straight into finish_maneuver_resolution once
        chosen. `turnover_occurred`/`distance_moved` are just carried
        through to that call.

        `lead_in` is narration from the maneuver that led here -- it
        rides along on the speed-choice prompt when a human picks, or
        gets forwarded to apply_speed_choice to ride along on its own
        message when the pick is automatic.
        """
        skill = self.player_catalog.effective_profile(
            self.get_player_definition(player_id),
        )
        skill_value = skill.offense if skill_type == "offense" else skill.defense

        controller_id = self.controlling_user_id(game, match, player_id)
        is_ai = game.is_solo_game and controller_id == game.player_2_id

        if is_ai:
            delta = self.get_ai_strategy(game).choose_speed_delta(skill_value)
            target_speed = max(1, min(12, match.ball.speed + delta))
            await self.apply_speed_choice(
                interaction,
                game,
                match,
                target_speed,
                turnover_occurred=turnover_occurred,
                distance_moved=distance_moved,
                lead_in=lead_in,
            )
            return

        mention = f"<@{controller_id}>" if controller_id else "Someone"
        prefix = f"{lead_in}\n\n" if lead_in else ""
        prompt_message = await interaction.followup.send(
            f"{prefix}{mention}, manipulate the ball's speed (up to "
            f"{skill_value}):",
            view=SpeedDeltaChoiceView(
                self, game.game_id, player_id, skill_type,
            ),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def apply_speed_choice(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        target_speed: int,
        turnover_occurred: bool = False,
        distance_moved: int = 1,
        lead_in: str = "",
    ) -> None:
        match.ball.speed = target_speed
        game.match_state = match.to_dict()
        save_games(self.games)

        prefix = f"{lead_in}\n\n" if lead_in else ""
        await interaction.followup.send(
            f"{prefix}Ball speed is now **{target_speed}**."
        )
        await self.refresh_match_image(interaction, game)

        await self.finish_maneuver_resolution(
            interaction,
            game,
            match,
            distance_moved=distance_moved,
            turnover_occurred=turnover_occurred,
        )

    # -- Own goal ----------------------------------------------------

    async def run_own_goal_roll(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int,
    ) -> None:
        """
        Automatic: 2d12 at an advantage (take the higher), plus the
        ball-handler's offensive skill, safe on 7+. No button -- there's
        no opposing roll to wait for.

        Making the attempt costs the rolling player 1 exhaust token,
        win or lose, on top of whatever the maneuver that triggered the
        risk already charged. It is not a skill test, so it owes no
        injury check.
        """
        offense_player = self.get_player_definition(match.active_player_id)
        offense_skill = self.player_catalog.effective_profile(
            offense_player,
        ).offense

        rolls = (random.randint(1, 12), random.randint(1, 12))
        taken = max(rolls)
        total = taken + offense_skill

        # Charged before either branch saves the match, so the token
        # and any Exhausted flag it sets are written out with the rest
        # of the roll's outcome -- see apply_exhaustion.
        exhaustion_text = self.apply_exhaustion(
            match, offense_player.player_id, 1,
        )

        safe = total >= 7

        offense_setup = match.setup_for_side(match.ball.possession)
        dice_file = discord.File(
            await asyncio.to_thread(
                render_own_goal_dice,
                list(rolls),
                TEAM_COLORS[offense_setup.team],
                safe,
            ),
            filename="own_goal_dice.png",
        )

        breakdown = (
            f"**Own goal risk!** "
            f"{format_role_bracket(offense_player, self.team_emojis)} "
            f"rolls at an advantage: higher of {rolls[0]}/{rolls[1]} "
            f"is {taken}, + {offense_skill} (offensive skill) "
            f"= {total}"
        )

        if safe:
            verdict = f"## Own goal avoided!\n\n{exhaustion_text}"
        else:
            conceding_side = match.ball.possession
            match.concede_own_goal()
            match.restart_after_goal(conceding_side)
            match.pending_run_back = True
            match.pending_run_back_distance = distance_moved
            match.pending_run_back_turnover = True
            game.match_state = match.to_dict()
            save_games(self.games)
            verdict = (
                f"# Own goal!\n"
                f"{match.home.team.value.title()} {match.scoreboard.home_score}:"
                f"{match.scoreboard.visiting_score} "
                f"{match.visiting.team.value.title()}\n\n"
                f"{exhaustion_text}"
            )

        # The verdict follows the dice in its own message rather than
        # riding above them -- see SkillTestView.roll for why every
        # result is announced this way round.
        await interaction.followup.send(breakdown, file=dice_file)
        await interaction.followup.send(verdict)
        await self.refresh_match_image(interaction, game)
        if safe:
            game.match_state = match.to_dict()
            save_games(self.games)
            await self.finish_maneuver_resolution(
                interaction,
                game,
                match,
                distance_moved=distance_moved,
            )
        else:
            # A conceded own goal restarts from the kickoff space
            # exactly as any other goal does, so it is a new play.
            await self.begin_run_back(
                interaction,
                game,
                match,
                distance_moved=distance_moved,
                turnover_occurred=True,
                new_play=True,
            )

    # -- Run-back (after a turnover) ----------------------------------

    def side_is_ai(
        self,
        game: D12BallGame,
        side: TeamSide,
    ) -> bool:
        if not game.is_solo_game:
            return False
        return self.side_player_number(game, side) == 2

    def side_player_number(
        self,
        game: D12BallGame,
        side: TeamSide,
    ) -> int:
        return (
            game.home_player_number
            if TeamSide(side) == TeamSide.HOME
            else game.visiting_player_number
        )

    def side_controller_id(
        self,
        game: D12BallGame,
        side: TeamSide,
    ) -> Optional[int]:
        """
        The Discord user coaching `side`. Unlike controlling_user_id
        this needs no player card, so it can be asked about a side
        that has nobody selected -- which is the case throughout a
        substitution window.
        """
        number = self.side_player_number(game, side)
        if number == 1:
            return game.player_1_id
        if number == 2:
            return game.player_2_id
        return None

    def apply_substitution(
        self,
        match: MatchState,
        side: TeamSide,
        outgoing_player_id: str,
        incoming_player_id: str,
    ) -> str:
        """
        Make one swap and describe it. Raises ValueError with the
        rule that refused it if the swap is not allowed.
        """
        was_injured = outgoing_player_id in match.injured
        from_back_bench = (
            incoming_player_id
            in match.setup_for_side(side).player_board.back_bench
        )

        match.substitute(side, outgoing_player_id, incoming_player_id)
        match.pending_substitution_used += 1

        outgoing = self.get_player_definition(outgoing_player_id)
        incoming = self.get_player_definition(incoming_player_id)
        text = (
            f"{format_role_bracket(incoming, self.team_emojis)} comes on "
            f"for {format_role_bracket(outgoing, self.team_emojis)}"
            f"{' (injured)' if was_injured else ''}."
        )

        if from_back_bench:
            # Half the tokens, rounded up, come off a returning
            # player -- but Exhausted is whatever the remainder says,
            # so it has to be re-tested rather than assumed cleared.
            defense_skill = self.player_catalog.effective_profile(
                incoming
            ).defense
            remaining = match.exhaustion.get(incoming_player_id, 0)
            exhaust_emoji = get_exhaust_emoji(self.condition_emojis)
            text += (
                f"\nBack on from the back bench, down to {remaining} "
                f"exhaustion {'token' if remaining == 1 else 'tokens'} "
                f"{exhaust_emoji * remaining}."
            )
            if match.mark_exhausted_if_needed(
                incoming_player_id, defense_skill,
            ):
                text += (
                    f" Still **Exhausted** -- {remaining} is over a "
                    f"defensive skill of {defense_skill}."
                )

        remaining_subs = match.substitutions_remaining()
        if remaining_subs:
            text += f"\n{remaining_subs} substitution left."
        return text

    def apply_position_swap(
        self,
        match: MatchState,
        side: TeamSide,
        player_id: str,
        other_player_id: str,
    ) -> str:
        match.swap_field_positions(side, player_id, other_player_id)

        setup = match.setup_for_side(side)
        first = self.get_player_definition(player_id)
        second = self.get_player_definition(other_player_id)
        return (
            f"{format_role_bracket(first, self.team_emojis)} is now "
            f"assigned to "
            f"{destination_display_name(setup.assigned_zone(player_id).value)}"
            f" and {format_role_bracket(second, self.team_emojis)} to "
            f"{destination_display_name(setup.assigned_zone(other_player_id).value)}"
            ". Rearranging costs no exhaustion -- place their meeples below."
        )

    def current_formation(
        self,
        match: MatchState,
        side: TeamSide,
    ) -> Optional[Formation]:
        """
        The formation a side is standing in, or None for a shape no
        formation describes -- which /coach and /ref can leave behind,
        since they move cards one at a time and answer to nothing.
        """
        setup = match.setup_for_side(side)
        counts = {
            area: len(setup.zones[zone_for_area(side, area)])
            for area in SETUP_AREAS
        }
        for formation, shape in self.basic_ruleset.formations.items():
            if shape.counts() == counts:
                return formation
        return None

    def apply_formation_change(
        self,
        match: MatchState,
        side: TeamSide,
        formation: Formation,
        assignment: dict[str, list[str]],
    ) -> str:
        """
        Move a side into `formation`, with `assignment` saying which
        of their six fielded cards fills each area. Nobody's meeple
        moves: whoever now stands outside their new zone is displaced,
        and the coach either places them by hand (free, right after
        this) or leaves it to the next run back.
        """
        side = TeamSide(side)
        shape = self.formation_shape(formation)

        for area in SETUP_AREAS:
            if len(assignment.get(area, [])) != shape.count(area):
                raise ValueError(
                    f"{formation.value} puts {shape.count(area)} "
                    f"players in {area_display_name(area)}."
                )

        match.reassign_field_zones(
            side,
            {
                zone_for_area(side, area): list(assignment[area])
                for area in SETUP_AREAS
            },
        )

        setup = match.setup_for_side(side)
        lines = [
            f"**{format_team_side_label(setup)} switch to "
            f"{formation.value}.**"
        ]
        for area in SETUP_AREAS:
            zone = zone_for_area(side, area)
            names = ", ".join(
                self.format_roster_player(player_id)
                for player_id in assignment[area]
            )
            lines.append(
                f"{destination_display_name(zone.value)}: {names}"
            )
        lines.append(
            "Rearranging costs no exhaustion -- place their meeples below."
        )
        return "\n".join(lines)

    def apply_reposition(
        self,
        match: MatchState,
        side: TeamSide,
        player_id: str,
        space_index: int,
    ) -> str:
        setup = match.setup_for_side(side)
        zone = setup.assigned_zone(player_id)
        match.reposition_player(side, player_id, space_index)

        player = self.get_player_definition(player_id)
        return (
            f"{format_role_bracket(player, self.team_emojis)} moves to "
            f"{space_label(zone, space_index)}. No exhaustion cost."
        )

    def apply_meeple_swap(
        self,
        match: MatchState,
        side: TeamSide,
        player_id: str,
        other_player_id: str,
    ) -> str:
        match.swap_meeple_positions(side, player_id, other_player_id)

        first = self.get_player_definition(player_id)
        second = self.get_player_definition(other_player_id)
        return (
            f"{format_role_bracket(first, self.team_emojis)} and "
            f"{format_role_bracket(second, self.team_emojis)} trade "
            "places. No exhaustion cost."
        )

    async def begin_substitution_window(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
        is_response: bool = False,
        lead_in: str = "",
        spends_declaration: bool = True,
        auto_declare: bool = False,
    ) -> None:
        """
        Offer `side` the window. A declaration is once a half, so a
        side that has already spent theirs is never offered one. An
        injured player on the field is named in the heading but
        compels nothing -- leaving them on is the coach's call.

        `auto_declare` skips the declare-or-pass offer and opens the
        substitution menu directly, and `spends_declaration` False
        leaves the side's once-a-half declaration unspent. Halftime
        passes both: its substitutions are not a declaration anyone
        chose to make, so there is nothing to ask and nothing to
        charge for (see begin_halftime_substitutions).
        """
        side = TeamSide(side)
        match.open_substitution_window(
            side,
            is_response=is_response,
            spends_declaration=spends_declaration,
        )
        game.match_state = match.to_dict()
        save_games(self.games)

        if self.side_is_ai(game, side):
            await self.run_ai_substitution_window(
                interaction, game, match, lead_in=lead_in,
            )
            return

        setup = match.setup_for_side(side)
        controller_id = self.side_controller_id(game, side)
        mention = f"<@{controller_id}>" if controller_id else "Someone"
        prefix = f"{lead_in}\n\n" if lead_in else ""

        if auto_declare:
            match.declare_substitution()
            game.match_state = match.to_dict()
            save_games(self.games)
            await self.prompt_substitution_menu(
                interaction, game, match, lead_in=lead_in,
            )
            return

        if is_response:
            heading = (
                f"{format_team_side_label(setup)} may answer with **one** "
                "substitution and rearrange their formation."
            )
        else:
            heading = (
                f"{format_team_side_label(setup)} restart play and may "
                "declare substitutions -- up to **two** swaps and a "
                "rearrangement, once a half."
            )

        # An injured player is worth pointing out, but only as a
        # nudge: nothing compels a side to get them off, and a coach
        # may leave them on, disadvantaged, all game.
        injured_ids = match.injured_field_players(side)
        if injured_ids:
            injured = ", ".join(
                format_role_bracket(
                    self.get_player_definition(player_id), self.team_emojis,
                )
                for player_id in injured_ids
            )
            verb = "is" if len(injured_ids) == 1 else "are"
            heading += f"\n{injured} {verb} injured and still on the field."

        prompt = await interaction.followup.send(
            f"{prefix}# Substitutions\n{mention}, {heading}",
            view=SubstitutionOfferView(self, game.game_id),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt.id
        save_games(self.games)

    async def prompt_substitution_menu(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        Put the take-off / rearrange / done menu back up after every
        action, so a side can use its whole allowance without the flow
        deciding for them when they are finished.

        `lead_in` rides above the menu on the first prompt of a window
        that was never offered as a choice (halftime's), which is the
        only place the window's own heading has nowhere else to go.
        """
        if match.pending_substitution_side is None:
            return
        side = TeamSide(match.pending_substitution_side)
        setup = match.setup_for_side(side)
        controller_id = self.side_controller_id(game, side)
        mention = f"<@{controller_id}>" if controller_id else "Someone"

        remaining = match.substitutions_remaining()
        allowance = (
            f"{remaining} substitution{'s' if remaining != 1 else ''} left"
            if remaining
            else "No substitutions left"
        )
        prefix = f"{lead_in}\n" if lead_in else ""
        prompt = await interaction.followup.send(
            f"{prefix}{mention}, {format_team_side_label(setup)}: "
            f"{allowance}. "
            "Take a player off, exchange two positions, or finish.",
            view=SubstitutionMenuView(self, game.game_id),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt.id
        save_games(self.games)

    async def run_ai_substitution_window(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        side = TeamSide(match.pending_substitution_side)
        strategy = self.get_ai_strategy(game)
        lines: list[str] = []

        while match.substitutions_remaining():
            choice = strategy.choose_substitution(match, side)
            if choice is None:
                break
            if not match.pending_substitution_declared:
                match.declare_substitution()
            outgoing_player_id, incoming_player_id = choice
            try:
                lines.append(
                    self.apply_substitution(
                        match, side, outgoing_player_id, incoming_player_id,
                    )
                )
            except ValueError as error:
                LOGGER.error(
                    "AI substitution refused in game %s: %s",
                    game.game_id, error,
                )
                break

        game.match_state = match.to_dict()
        save_games(self.games)

        setup = match.setup_for_side(side)
        prefix = f"{lead_in}\n\n" if lead_in else ""
        if lines:
            body = "\n".join(lines)
            await interaction.followup.send(
                f"{prefix}# Substitutions\n"
                f"{format_team_side_label(setup)} declares:\n{body}"
            )
            await self.refresh_match_image(interaction, game)
        elif prefix:
            await interaction.followup.send(lead_in)

        await self.finish_substitution_window(interaction, game, match)

    async def finish_substitution_window(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Hand the window on, or give up on it and let the run back go
        ahead. The other team only gets its single answering
        substitution because a declaration actually happened -- a side
        that passes takes the opposing reply down with it.

        A side that used its window comes out of it standing where its
        coach put them, and that becomes the arrangement the next new
        play restores. A side that passed changed nothing, so their
        existing arrangement stands untouched.
        """
        declared = match.pending_substitution_declared
        was_response = match.pending_substitution_is_response
        side = (
            TeamSide(match.pending_substitution_side)
            if match.pending_substitution_side
            else None
        )
        match.close_substitution_window()
        if declared and side is not None:
            match.set_assigned_positions(side)
        game.match_state = match.to_dict()
        save_games(self.games)

        if match.pending_halftime_stage in ("subs_home", "subs_visiting"):
            # Halftime gives each side its own independent declaration
            # rather than a turnover's declare-then-respond pairing, so
            # this always moves on to the next halftime stage instead
            # of offering the other side a response.
            self.next_halftime_stage(match)
            game.match_state = match.to_dict()
            save_games(self.games)
            await self.advance_halftime_stage(interaction, game, match)
            return

        if declared and not was_response and side is not None:
            other_side = (
                TeamSide.VISITING
                if side == TeamSide.HOME
                else TeamSide.HOME
            )
            await self.begin_substitution_window(
                interaction, game, match, other_side, is_response=True,
            )
            return

        await self.announce_run_back(interaction, game, match)

    async def begin_run_back(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int = 1,
        turnover_occurred: bool = True,
        new_play: bool = False,
        stays_player_id: Optional[str] = None,
        speed_choice_after: bool = False,
        lead_in: str = "",
    ) -> None:
        """
        `distance_moved`/`turnover_occurred` describe the maneuver that
        triggered this run-back, stashed on `match` so they survive the
        multi-turn choice flow and reach finish_maneuver_resolution
        correctly once run-back itself (which only ever costs
        exhaustion, never time) is done.

        `new_play` says the ball changed hands because play stopped and
        is restarting -- a goal, an own goal, a missed attempt, a ball
        out of bounds -- rather than because the other team took it off
        them. Only a new play opens a substitution window; a steal
        (Steal Intercept, a Defender's Pressure steal, a loose ball or
        a long High Pass the other side wins) runs everyone back and
        plays straight on. See "Steals and new plays",
        docs/living-rules.md. It is not persisted: it is consumed here,
        and by the time anything is saved the state already says which
        of the two happened -- a window open, or a run back pending.

        `stays_player_id` is set only for a turnover created by a
        steal (Steal Intercept, or the Defender's Pressure-ability
        steal) -- that player keeps the ball and is exempt from
        running back, unlike every other turnover (a goal, a missed
        shot, Block Deflect's scoring opportunity), where nobody gets
        that exemption.

        `speed_choice_after` is set only for Steal Intercept -- once
        run-back finishes, its defender still gets to manipulate the
        ball's speed, offered only after players are back in position
        rather than before (see continue_run_back).

        `lead_in` is narration from the triggering effect that hasn't
        been posted yet -- it rides along on whichever message this
        run-back sends first (see continue_run_back).

        A turnover that happens while last possession is already in
        force ends the period immediately instead: no run-back, no
        substitution window, and (for a steal) no run-back or
        speed-manipulation follow-up either -- the triggering effect's
        own state change (e.g. Steal Intercept's turnover and 1-space
        fallback) has already been applied and saved by the caller,
        this just skips everything downstream of that. The maneuver
        that *declares* last possession is not that turnover and isn't
        caught here: its own clock advance happens later, in
        finish_maneuver_resolution, so it runs back like any other.

        A resolution that left possession where it was doesn't run a
        run-back at all: "every time there's a turnover for any
        reason (steal, goal etc.) players have to run back" is the
        whole of when one happens ("Turnovers and running back",
        docs/living-rules.md).
        Keeping the ball -- a receiver winning their High Pass, a
        loose ball the possessing side recovers -- leaves whoever is
        out of position out of position, and charges nobody, until a
        turnover does come. This is called with turnover_occurred
        False anyway so the tail of the flow (the clock, the next
        offensive choice) stays in one place.
        """
        if turnover_occurred and match.scoreboard.last_possession:
            await self.end_period(interaction, game, match, lead_in=lead_in)
            return

        if not turnover_occurred:
            await self.finish_maneuver_resolution(
                interaction,
                game,
                match,
                distance_moved=distance_moved,
                turnover_occurred=False,
                lead_in=lead_in,
            )
            return

        match.pending_run_back = True
        match.pending_run_back_distance = distance_moved
        match.pending_run_back_turnover = turnover_occurred
        match.pending_run_back_stays_player_id = stays_player_id
        match.pending_run_back_speed_choice = speed_choice_after
        game.match_state = match.to_dict()
        save_games(self.games)

        # A new play resets both sides to the shape their coaches set,
        # free of exhaustion, and only then opens the substitution
        # window -- a coach who declares rearranges from their own
        # formation rather than from wherever open play scattered them,
        # and a coach who passes has already got what passing gives
        # them. It also leaves nobody displaced, so the run back that
        # follows finds nothing to do and falls through to whatever the
        # restart still owes (the kickoff space, an out-of-bounds
        # pickup).
        #
        # A steal does none of this: the ball is still live, so the
        # coaches get no pause and the ordinary run back stands.
        if new_play:
            await self.announce_new_play_reset(interaction, game, match, lead_in)
            lead_in = ""
            winning_side = match.ball.possession
            if match.may_declare_substitution(winning_side):
                await self.begin_substitution_window(
                    interaction, game, match, winning_side,
                )
                return

        await self.announce_run_back(interaction, game, match, lead_in)

    async def announce_new_play_reset(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        Put both sides back on the arrangement their coaches last set
        and say so. Nobody pays a token for it -- see
        MatchState.restore_assigned_positions.

        This is where a new play's board goes out and gets pinned: the
        reset is the arrangement the play starts from, and it is the
        one moment in the restart where nothing is still moving. What
        the restart still owes (a kickoff fill, an out-of-bounds
        pickup) lands on the persistent board afterwards.
        """
        moved: list[str] = []
        for side in (TeamSide.HOME, TeamSide.VISITING):
            for player_id, zone, space_index in (
                match.restore_assigned_positions(side)
            ):
                player = self.get_player_definition(player_id)
                moved.append(
                    f"{format_role_bracket(player, self.team_emojis)} to "
                    f"{space_label(zone, space_index)}"
                )
        game.match_state = match.to_dict()
        save_games(self.games)

        prefix = f"{lead_in}\n\n" if lead_in else ""
        body = (
            "Both teams reset to the positions their coaches last set, "
            "free of exhaustion:\n" + "\n".join(moved)
            if moved
            else "Both teams are already standing where their coaches "
            "last set them."
        )
        await self.post_new_play_board(
            interaction, game, f"{prefix}# New play\n{body}",
        )

    async def announce_run_back(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        The run back proper, split out of begin_run_back because a new
        play's substitution window sits in between and has to resolve
        before this can start.

        With nobody displaced there is nothing to explain, and heading
        an empty run back "Players run back!" reads as a bug. That is
        every new play: the reset put both sides back on their own
        arrangement, so only the speed note is left to say.
        """
        turnover_occurred = match.pending_run_back_turnover
        prefix = f"{lead_in}\n\n" if lead_in else ""
        # Speed manipulation (Steal Intercept) always happens after
        # run-back now, so a turnover's ball speed is still at its
        # reset value of 1 here.
        speed_note = "The ball speed goes down to **1**." if turnover_occurred else ""
        displaced = any(
            self.run_back_displaced(match, side)
            for side in (TeamSide.HOME, TeamSide.VISITING)
        )
        if displaced:
            await interaction.followup.send(
                f"{prefix}# Players run back!\n"
                "Players return to an open space in their assigned zone and "
                "gain 1 exhaustion token for every space traveled. Forced "
                "locations are handled automatically; when there is a choice, "
                f"the coach will be prompted to pick a location. {speed_note}"
            )
        elif prefix or speed_note:
            await interaction.followup.send(f"{prefix}{speed_note}".strip())
        await self.continue_run_back(interaction, game, match)

    def run_back_displaced(
        self,
        match: MatchState,
        side: TeamSide,
    ) -> list[str]:
        """
        `match.displaced_players(side)` (outside their zone) plus
        `match.crowded_players(side)` (doubled up with a same-zone
        teammate, when the zone has room to spread out), minus the
        player who stole the ball this run-back (if any) -- see
        begin_run_back.
        """
        stays_player_id = match.pending_run_back_stays_player_id
        combined = match.displaced_players(side) + match.crowded_players(side)
        return [
            player_id
            for player_id in combined
            if player_id != stays_player_id
        ]

    def describe_run_back_options(
        self,
        match: MatchState,
        side: TeamSide,
        player_id: str,
    ) -> str:
        """The spaces `player_id` may run back to in their own zone,
        for the run-back prompt -- so the coach sees every option up
        front, alongside the buttons that offer the same choice."""
        zone = match.setup_for_side(side).assigned_zone(player_id)
        spaces = match.placement_spaces_in_zone(side, zone, player_id)
        if not spaces:
            return "No space in their zone."
        options = ", ".join(space_label(zone, index) for index in spaces)
        return f"Options: {options}"

    def apply_forced_run_backs(self, match: MatchState) -> None:
        """
        Place every run-back that isn't a choice: a zone whose open
        spaces exactly match the players who need one has only one
        arrangement, so nobody is asked. Repeats until a pass changes
        nothing, since placing one zone's players can settle another.

        Silent, and it does not save -- the caller does both.
        """
        applied_forced = True
        while applied_forced:
            applied_forced = False
            for side in (TeamSide.HOME, TeamSide.VISITING):
                by_zone: dict[Zone, list[str]] = {}
                for player_id in self.run_back_displaced(match, side):
                    zone = match.setup_for_side(side).assigned_zone(
                        player_id
                    )
                    by_zone.setdefault(zone, []).append(player_id)

                for zone, players in by_zone.items():
                    open_spaces = match.open_spaces_in_zone(side, zone)
                    if len(open_spaces) != len(players):
                        continue
                    for player_id, space_index in zip(players, open_spaces):
                        distance = match.run_back_player(
                            player_id, zone, space_index,
                        )
                        match.add_exhaustion(player_id, distance)
                        # A forced run back is applied silently, so
                        # there is no message here to carry the
                        # threshold test the way apply_exhaustion's
                        # does -- but the flag still has to be set
                        # before the caller's save.
                        self.retest_exhausted(match, player_id)
                    applied_forced = True

    def next_run_back_choice(
        self,
        match: MatchState,
    ) -> Optional[tuple[TeamSide, str]]:
        """
        The next side and player still owed a run-back with a real
        choice in it, home before visiting, or None when both sides
        are settled.
        """
        for side in (TeamSide.HOME, TeamSide.VISITING):
            displaced = self.run_back_displaced(match, side)
            if displaced:
                return side, displaced[0]
        return None

    async def continue_run_back(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        Auto-place every forced run-back (no real choice: the open
        spaces in a zone exactly match the players who need one) right
        away, then either present a choice for the next player who has
        a real one, or finish once nobody is displaced.

        `lead_in` only ever applies to the first message this call (or
        the resumption in RunBackChoiceView) sends -- every call site
        that already consumed it passes none.

        Every placement made without asking anyone -- the forced ones,
        the AI's choices, the drop back that fills an empty kickoff --
        collects into one message and one board refresh, flushed when
        the cascade reaches a coach's choice or runs out. It used to
        post a message and re-upload the board per player, which after
        a steal that scatters a 4-1-1 side is a dozen-odd REST calls
        into one channel with nothing between them, and enough to be
        rate limited for it. Nobody is reading the intermediate boards
        anyway: the one worth looking at is the one where everyone has
        finished moving.
        """
        # Lines describing placements already applied and saved, and
        # not yet posted. `lead_in` is consumed by whichever message
        # goes out first, which may be this one or the prompt below.
        notes: list[str] = []

        # Every pass either places somebody or ends the cascade, so
        # this can only be reached if a placement left the player it
        # moved still owed one. That should not be possible -- see
        # placement_spaces_in_zone -- but as a recursion it was bounded
        # by the interpreter and as a loop it is not, and a spin here
        # hangs the event loop for every game at once. An ERROR,
        # because a run back that will not settle needs someone to
        # look at it.
        remaining_passes = MAX_RUN_BACK_PASSES

        async def flush() -> bool:
            """
            Post the automatic placements so far, with the board they
            produced. True when there was something to post.
            """
            nonlocal lead_in, notes

            if not notes:
                return False

            prefix = f"{lead_in}\n\n" if lead_in else ""
            body = "\n".join(notes)
            notes = []
            lead_in = ""
            await interaction.followup.send(f"{prefix}{body}")
            await self.refresh_match_image(interaction, game)
            return True

        while True:
            remaining_passes -= 1
            if remaining_passes < 0:
                LOGGER.error(
                    "Giving up on the run back for D12 Ball game %s after "
                    "%d placements: it is not settling. The match is saved "
                    "as it stands.",
                    game.game_id,
                    MAX_RUN_BACK_PASSES,
                )
                break

            self.apply_forced_run_backs(match)
            game.match_state = match.to_dict()
            save_games(self.games)

            choice = self.next_run_back_choice(match)

            if choice is not None:
                side, player_id = choice
                zone = match.setup_for_side(side).assigned_zone(player_id)
                player = self.get_player_definition(player_id)

                if self.side_is_ai(game, side):
                    space_index = self.get_ai_strategy(
                        game
                    ).choose_run_back_space(
                        match.placement_spaces_in_zone(side, zone, player_id)
                    )
                    distance = match.run_back_player(
                        player_id, zone, space_index,
                    )
                    exhaustion_text = self.apply_exhaustion(
                        match, player_id, distance,
                    )
                    game.match_state = match.to_dict()
                    save_games(self.games)

                    notes.append(
                        f"{format_role_bracket(player, self.team_emojis)} "
                        f"runs back to {space_label(zone, space_index)}."
                        f"\n{exhaustion_text}"
                    )
                    continue

                # A coach's choice ends the cascade here: say what has
                # happened so far, show the board it left, and ask.
                if not await flush():
                    await self.refresh_match_image(interaction, game)

                controller_number = (
                    game.home_player_number
                    if side == TeamSide.HOME
                    else game.visiting_player_number
                )
                controller_id = (
                    game.player_1_id
                    if controller_number == 1
                    else game.player_2_id
                )
                mention = f"<@{controller_id}>" if controller_id else "Someone"
                prefix = f"{lead_in}\n\n" if lead_in else ""
                options_note = self.describe_run_back_options(
                    match, side, player_id,
                )

                prompt_message = await interaction.followup.send(
                    f"{prefix}{mention}, choose where "
                    f"{format_role_bracket(player, self.team_emojis)} runs "
                    f"back to:\n{options_note}",
                    view=RunBackChoiceView(self, game.game_id, player_id),
                    wait=True,
                    allowed_mentions=discord.AllowedMentions(
                        users=True, roles=False, everyone=False,
                    ),
                )
                game.turn_message_id = prompt_message.id
                save_games(self.games)
                return

            if match.pending_kickoff_fill:
                # A goal (or own goal) restarts play with nobody
                # necessarily standing on the kickoff space -- the
                # conceding side's two midfield players could easily
                # both be elsewhere in the zone from open play.
                # Whoever's closest drops back to start the kickoff, at
                # the usual run-back cost, once every other run-back is
                # settled.
                #
                # Asked here rather than back in restart_after_goal
                # because everyone has moved since: the new play's
                # reset, and any placement its substitution window
                # made. Somebody standing on the space already settles
                # it for nothing.
                if match.eligible_ball_handlers():
                    match.pending_kickoff_fill = False
                    game.match_state = match.to_dict()
                    save_games(self.games)
                    continue

                candidates = match.kickoff_fill_candidates()
                if candidates:
                    player_id = candidates[0]
                    player = self.get_player_definition(player_id)
                    distance = match.fill_kickoff(player_id)
                    exhaustion_text = self.apply_exhaustion(
                        match, player_id, distance,
                    )
                    game.match_state = match.to_dict()
                    save_games(self.games)

                    notes.append(
                        f"{format_role_bracket(player, self.team_emojis)} "
                        "drops back to "
                        f"{space_label(match.ball.zone, match.ball.space_index)} "
                        f"to start the kickoff.\n{exhaustion_text}"
                    )
                    continue

                # Nobody fielded in midfield at all (both benched or
                # injured) -- nothing to place. Clear the flag and let
                # the loose-ball check downstream handle the empty
                # kickoff.
                match.pending_kickoff_fill = False

            break

        await flush()

        # Nobody is displaced on either side -- run-back is done.
        match.pending_run_back = False
        distance_moved = match.pending_run_back_distance
        turnover_occurred = match.pending_run_back_turnover
        speed_choice_after = match.pending_run_back_speed_choice
        stays_player_id = match.pending_run_back_stays_player_id
        match.pending_run_back_speed_choice = False
        game.match_state = match.to_dict()
        save_games(self.games)

        if match.pending_ball_recovery:
            # An out-of-bounds ball is still lying there with nobody
            # on it. Now that everyone is back in position, the side
            # that won it sends someone to pick it up -- from
            # anywhere on the field, at the usual per-space cost.
            await self.begin_ball_recovery(
                interaction, game, match, lead_in=lead_in,
            )
            return

        if speed_choice_after:
            # Steal Intercept: the defender who stole the ball still
            # gets to manipulate its speed, now that everyone is back
            # in position.
            await self.offer_speed_choice(
                interaction,
                game,
                match,
                player_id=stays_player_id,
                skill_type="defense",
                turnover_occurred=turnover_occurred,
                distance_moved=distance_moved,
                lead_in=lead_in,
            )
            return

        # Run-back itself only ever costs exhaustion, not time -- the
        # time cost is whatever the triggering maneuver's own ball
        # movement was, stashed by begin_run_back.
        await self.finish_maneuver_resolution(
            interaction,
            game,
            match,
            distance_moved=distance_moved,
            turnover_occurred=turnover_occurred,
            lead_in=lead_in,
        )

    # -- Out-of-bounds recovery (after the run back) ------------------

    async def begin_ball_recovery(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        Ask the side that won an out-of-bounds ball which of their
        fielded players goes and stands on it -- any of them, from
        anywhere on the field, at one exhaustion token per space
        traveled.

        Deliberately the last thing that happens: run the run back
        first and this player is placed once and stays, where placing
        them before it would only have them run back off the ball and
        leave it loose all over again.
        """
        side = match.ball.possession
        candidates = match.setup_for_side(side).field_players
        if not candidates:
            # Nobody fielded at all -- nothing to place. Let the
            # loose-ball check downstream deal with it, the same way
            # an empty kickoff is handled.
            match.pending_ball_recovery = False
            game.match_state = match.to_dict()
            save_games(self.games)
            await self.finish_maneuver_resolution(
                interaction, game, match,
                distance_moved=match.pending_run_back_distance,
                turnover_occurred=True,
                lead_in=lead_in,
            )
            return

        if self.side_is_ai(game, side):
            # Nearest, not best: this walk costs a token per space and
            # wins nothing, so the only thing worth optimizing is how
            # much it costs.
            await self.apply_ball_recovery(
                interaction,
                game,
                match,
                min(candidates, key=match.distance_to_ball),
                lead_in=lead_in,
            )
            return

        number = (
            game.home_player_number
            if side == TeamSide.HOME
            else game.visiting_player_number
        )
        mention = format_player_with_team(game, number, mention=True)
        prefix = f"{lead_in}\n\n" if lead_in else ""
        prompt_message = await interaction.followup.send(
            f"{prefix}{mention}, everyone is back in position -- send a "
            "player to pick the ball up at "
            f"{space_label(match.ball.zone, match.ball.space_index)}:",
            view=BallRecoveryView(self, game.game_id),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def apply_ball_recovery(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
        lead_in: str = "",
    ) -> None:
        player = self.get_player_definition(player_id)
        # The triggering maneuver's own travel, for the clock. It
        # outlives the run back that just finished (only
        # reset_maneuver clears it) precisely so this step, which can
        # span a restart, can still read it back.
        distance_moved = match.pending_run_back_distance
        distance = match.recover_out_of_bounds_ball(player_id)
        exhaustion_text = self.apply_exhaustion(match, player_id, distance)
        game.match_state = match.to_dict()
        save_games(self.games)

        prefix = f"{lead_in}\n\n" if lead_in else ""
        await interaction.followup.send(
            f"{prefix}"
            f"{format_role_bracket(player, self.team_emojis)} picks the "
            f"ball up at "
            f"{space_label(match.ball.zone, match.ball.space_index)}."
            f"\n{exhaustion_text}"
        )
        await self.refresh_match_image(interaction, game)
        await self.finish_maneuver_resolution(
            interaction,
            game,
            match,
            distance_moved=distance_moved,
            turnover_occurred=True,
        )

    # -- Clock, period transitions, and the turn loop -----------------

    async def finish_maneuver_resolution(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int = 1,
        turnover_occurred: bool = False,
        lead_in: str = "",
    ) -> None:
        """
        The tail of every maneuver-effect path once movement, speed,
        any turnover, and run-back are all settled: advance the clock,
        end the period if this turnover closes out last possession,
        clear the maneuver state, and hand the offensive choice back to
        whoever now has the ball.

        The maneuver that puts the clock on 15 never ends the period,
        even when it is itself a turnover: last possession is the
        possession that starts there, so whoever comes out of that
        maneuver with the ball gets to play it out and only loses the
        period when *they* lose the ball. Only a turnover under a last
        possession that was already in force ends it -- which is the
        case begin_run_back catches earlier, before any run back.

        `lead_in`, if given, is narration from earlier in the same
        effect that hasn't been posted yet -- it rides along on this
        function's own first message instead of being sent separately,
        so a deterministic effect (no further human choice in between)
        reads as one message rather than a chain of them.

        Checked first, before the clock moves: does the possessing team
        actually have a player on the ball's space? If the maneuver left
        it somewhere they don't -- an empty space, or one only the other
        team occupies -- this detours into the loose-ball flow instead,
        which re-enters this function itself once it's settled.
        """
        if await self.check_for_loose_ball(
            interaction, game, match, distance_moved, lead_in=lead_in,
        ):
            return

        entered_last_possession = match.advance_time(distance_moved)
        if entered_last_possession:
            prefix = f"{lead_in}\n\n" if lead_in else ""
            possessing_side = format_team_side_label(
                match.setup_for_side(match.ball.possession)
            )
            body = (
                "The turnover that got here doesn't end it -- "
                f"{possessing_side} came out of that maneuver with the "
                "ball, so they play last possession out."
                if turnover_occurred
                else "Play continues until the ball turns over, which "
                "ends the period."
            )
            await interaction.followup.send(
                f"{prefix}The clock reaches 15 -- this is now **last "
                f"possession**. {body}"
            )
            lead_in = ""

        if (
            turnover_occurred
            and match.scoreboard.last_possession
            and not entered_last_possession
        ):
            await self.end_period(interaction, game, match, lead_in=lead_in)
            return

        match.reset_maneuver()
        game.match_state = match.to_dict()
        save_games(self.games)

        # One last board refresh with everything settled (run-back,
        # speed choice, own-goal, etc. may have landed after the last
        # refresh inside the effect itself), right before the
        # offensive choice comes back up. The snapshot below is that
        # same board, so it is drawn once and uploaded twice.
        png = await self.render_match_png(game)
        await self.refresh_match_image(interaction, game, png=png)

        prefix = f"{lead_in}\n\n" if lead_in else ""
        snapshot = await interaction.followup.send(
            content=(
                f"{prefix}Ball is now "
                f"{space_label(match.ball.zone, match.ball.space_index)}, "
                f"{format_team_side_label(match.setup_for_side(match.ball.possession))} "
                f"has possession. Time has advanced {distance_moved}, now "
                f"at {match.scoreboard.time:02d}."
            ),
            file=self.match_file_from_png(game, png),
            wait=True,
        )
        await add_full_image_button(snapshot)

        try:
            await self.send_turn_prompt(interaction, game)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)

    async def end_period(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        The turnover that closes out last possession: transition to the
        second half, or end the game at full time. Halftime recovery,
        formation changes, substitutions, and the extreme shootout are
        all out of scope here -- announced as hand-apply instructions,
        the same way score-attempt cleanup already defers its own
        unautomated pieces.
        """
        prefix = f"{lead_in}\n\n" if lead_in else ""

        if match.scoreboard.period == MatchPeriod.FIRST_HALF:
            match.scoreboard.period = MatchPeriod.SECOND_HALF
            match.scoreboard.time = 0
            match.scoreboard.last_possession = False
            # A declaration is once every half, so both sides get
            # theirs back -- including a side that had to spend the
            # first half's on an injury.
            match.declared_substitution.clear()
            match.close_substitution_window()
            kickoff_index = kickoff_space_index(
                len(match.board.spaces[Zone.MIDFIELD]),
                TeamSide.VISITING,
            )
            match.set_ball_space(Zone.MIDFIELD, kickoff_index)
            match.ball.possession = TeamSide.VISITING
            match.ball.speed = 1
            match.reset_maneuver()
            game.match_state = match.to_dict()
            save_games(self.games)

            await interaction.followup.send(
                f"{prefix}**End of the first half!** The clock reaches 15 "
                "and the ball turns over -- the period ends."
            )
            await self.refresh_match_image(interaction, game)
            await self.begin_halftime(interaction, game, match)
            return

        match.reset_maneuver()
        game.match_state = match.to_dict()
        save_games(self.games)
        game.finish_game()
        save_games(self.games)

        full_time = await interaction.followup.send(
            f"{prefix}**Full time!** The clock reaches 15 and the ball "
            "turns over -- the game ends.\n\n"
            f"{build_full_time_summary(game, match)}",
            view=RematchView(self, game.game_id),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
            wait=True,
        )
        # Remembered so the rematch button comes back after a restart:
        # the channel stays where it is until someone clicks it, which
        # can be days later.
        game.rematch_message_id = full_time.id
        save_games(self.games)
        await self.refresh_match_image(interaction, game)

    # -- Halftime ------------------------------------------------------

    async def begin_halftime(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Kicks off halftime cleanup once end_period has already flipped
        the period, reset the clock, and moved the ball to the
        second-half kickoff space: automatic exhaustion recovery for
        every fielded player, then the rest of the sequence (each
        side's extra-token choice, substitution window, and free
        repositioning) driven by `match.pending_halftime_stage` --
        see advance_halftime_stage.
        """
        recovery_lines = []
        for side in (TeamSide.HOME, TeamSide.VISITING):
            for player_id in match.setup_for_side(side).field_players:
                player = self.get_player_definition(player_id)
                defense_skill = self.player_catalog.effective_profile(
                    player
                ).defense
                removed = match.recover_exhaustion(player_id, 1, defense_skill)
                if removed:
                    remaining = match.exhaustion.get(player_id, 0)
                    recovery_lines.append(
                        f"{format_role_bracket(player, self.team_emojis)} "
                        f"recovers 1 exhaustion token (now {remaining})."
                    )

        game.match_state = match.to_dict()
        save_games(self.games)

        body = (
            "\n".join(recovery_lines)
            if recovery_lines
            else "No fielded player had any exhaustion tokens to recover."
        )
        await interaction.followup.send(
            f"# Halftime\nEvery fielded player recovers 1 exhaustion "
            f"token:\n{body}"
        )
        await self.refresh_match_image(interaction, game)

        match.pending_halftime_stage = HALFTIME_STAGES[0]
        game.match_state = match.to_dict()
        save_games(self.games)
        await self.advance_halftime_stage(interaction, game, match)

    def next_halftime_stage(self, match: MatchState) -> None:
        """
        Advance `match.pending_halftime_stage` to the next entry in
        HALFTIME_STAGES, or clear it once the sequence is exhausted.
        Callers are responsible for saving the match afterward.
        """
        stage = match.pending_halftime_stage
        if stage not in HALFTIME_STAGES:
            match.pending_halftime_stage = None
            return
        index = HALFTIME_STAGES.index(stage)
        match.pending_halftime_stage = (
            HALFTIME_STAGES[index + 1]
            if index + 1 < len(HALFTIME_STAGES)
            else None
        )

    async def advance_halftime_stage(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """Dispatch to whichever halftime stage comes next, or finish."""
        stage = match.pending_halftime_stage
        if stage == "extra_token_home":
            await self.begin_halftime_extra_token(
                interaction, game, match, TeamSide.HOME,
            )
        elif stage == "extra_token_visiting":
            await self.begin_halftime_extra_token(
                interaction, game, match, TeamSide.VISITING,
            )
        elif stage == "subs_home":
            await self.begin_halftime_substitutions(
                interaction, game, match, TeamSide.HOME,
            )
        elif stage == "subs_visiting":
            await self.begin_halftime_substitutions(
                interaction, game, match, TeamSide.VISITING,
            )
        elif stage == "reposition_home":
            await self.begin_halftime_reposition(
                interaction, game, match, TeamSide.HOME,
            )
        elif stage == "reposition_visiting":
            await self.begin_halftime_reposition(
                interaction, game, match, TeamSide.VISITING,
            )
        else:
            await self.finish_halftime(interaction, game, match)

    async def begin_halftime_extra_token(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
    ) -> None:
        """
        The coach's choice of one fielded player to lose an extra
        exhaustion token, on top of the automatic recovery every
        fielded player already got in begin_halftime.
        """
        setup = match.setup_for_side(side)
        eligible = [
            player_id
            for player_id in setup.field_players
            if player_id not in match.injured
        ]

        if not eligible:
            self.next_halftime_stage(match)
            game.match_state = match.to_dict()
            save_games(self.games)
            await self.advance_halftime_stage(interaction, game, match)
            return

        if self.side_is_ai(game, side):
            player_id = max(
                eligible, key=lambda pid: match.exhaustion.get(pid, 0),
            )
            defense_skill = self.player_catalog.effective_profile(
                self.get_player_definition(player_id)
            ).defense
            removed = match.recover_exhaustion(player_id, 1, defense_skill)
            self.next_halftime_stage(match)
            game.match_state = match.to_dict()
            save_games(self.games)

            if removed:
                player = self.get_player_definition(player_id)
                remaining = match.exhaustion.get(player_id, 0)
                await interaction.followup.send(
                    f"{format_team_side_label(setup)} removes an extra "
                    "exhaustion token from "
                    f"{format_role_bracket(player, self.team_emojis)} "
                    f"(now {remaining})."
                )
                await self.refresh_match_image(interaction, game)
            await self.advance_halftime_stage(interaction, game, match)
            return

        controller_id = self.side_controller_id(game, side)
        mention = f"<@{controller_id}>" if controller_id else "Someone"
        prompt = await interaction.followup.send(
            f"{mention}, {format_team_side_label(setup)}: choose one "
            "fielded player to lose an extra exhaustion token.",
            view=HalftimeExtraTokenView(self, game.game_id, side),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt.id
        save_games(self.games)

    async def begin_halftime_substitutions(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
    ) -> None:
        """
        Give `side` a full substitution window (see
        begin_substitution_window) -- unlike a turnover's
        declare-then-respond pairing, halftime gives each side its own
        independent window, so finish_substitution_window routes back
        into the halftime sequence instead of chaining to the other
        side's response.

        Nobody is asked whether to declare, and nothing is charged for
        it: halftime substitutions just happen ("the coach can change
        their team's formation and the players' assignment as they
        please", End of Time), and they leave the side's once-a-half
        declaration unspent for the second half. A side with nothing
        it wants to change finishes the menu without doing anything,
        which is the same as passing used to be.
        """
        setup = match.setup_for_side(side)
        await self.begin_substitution_window(
            interaction,
            game,
            match,
            side,
            spends_declaration=False,
            auto_declare=True,
            lead_in=(
                f"# Substitutions\n{format_team_side_label(setup)} may "
                "substitute for the second half -- up to **two** swaps and "
                "a rearrangement. Halftime is free: this doesn't spend "
                "their once-a-half declaration."
            ),
        )

    async def begin_halftime_reposition(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
    ) -> None:
        """
        Free placement of any of `side`'s fielded meeples to any open
        board space, not limited to their assigned zone -- "the coach
        can change... the players' assignment as they please" (End of
        Time). The visiting side alone is gated on finishing with a
        player standing on the kickoff space, since they're the ones
        who have to kick off the second half.
        """
        setup = match.setup_for_side(side)

        if self.side_is_ai(game, side):
            lines = []
            if (
                side == TeamSide.VISITING
                and not match.kickoff_space_occupied_by(TeamSide.VISITING)
            ):
                kickoff_flat = match.board.flat_index(
                    match.ball.zone, match.ball.space_index,
                )

                def distance(player_id: str) -> int:
                    position = match.board.meeple_position(player_id)
                    if position is None:
                        return 10**6
                    return abs(
                        match.board.flat_index(*position) - kickoff_flat
                    )

                nearest = min(setup.field_players, key=distance)
                match.reposition_meeple_anywhere(
                    TeamSide.VISITING,
                    nearest,
                    match.ball.zone,
                    match.ball.space_index,
                )
                player = self.get_player_definition(nearest)
                lines.append(
                    f"{format_role_bracket(player, self.team_emojis)} "
                    "takes the kickoff spot at "
                    f"{space_label(match.ball.zone, match.ball.space_index)}."
                )

            # Same as the human path (HalftimeRepositionView.finish):
            # wherever this side finishes halftime is the arrangement a
            # new play restores.
            match.set_assigned_positions(side)
            self.next_halftime_stage(match)
            game.match_state = match.to_dict()
            save_games(self.games)

            if lines:
                await interaction.followup.send(
                    f"{format_team_side_label(setup)} repositions:\n"
                    + "\n".join(lines)
                )
                await self.refresh_match_image(interaction, game)
            await self.advance_halftime_stage(interaction, game, match)
            return

        controller_id = self.side_controller_id(game, side)
        mention = f"<@{controller_id}>" if controller_id else "Someone"
        kickoff_note = (
            " The visiting team must have a player on "
            f"{space_label(match.ball.zone, match.ball.space_index)} to "
            "kick off the second half before finishing."
            if side == TeamSide.VISITING
            else ""
        )
        prompt = await interaction.followup.send(
            f"{mention}, {format_team_side_label(setup)}: reposition any "
            "fielded meeple to any space on the board, free of "
            f"exhaustion, or finish.{kickoff_note}",
            view=HalftimeRepositionView(self, game.game_id, side),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt.id
        save_games(self.games)

    async def finish_halftime(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The last step of halftime -- the visiting kickoff-space
        guarantee is already enforced before this is reached (see
        HalftimeRepositionView.finish), so this just clears the
        halftime flag and hands play to the second half.
        """
        match.pending_halftime_stage = None
        game.match_state = match.to_dict()
        save_games(self.games)

        # A half begins the way any other new play does: with the board
        # everyone is about to play from, posted and pinned.
        await self.post_new_play_board(
            interaction,
            game,
            "**Halftime is over.** The second half kicks off with "
            f"{format_team_side_label(match.visiting)} in possession.",
        )

        try:
            await self.send_turn_prompt(interaction, game)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)

    async def refresh_maneuver_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Re-render the public "choose your maneuver" prompt after one
        side picks, and delete it once every side it was waiting on
        has: its button has nothing left to open, and the resolution
        posted underneath it is what the channel should end on. An
        uncontested maneuver is waiting on the offense alone, so its
        prompt goes on that one pick.

        Deleting clears `turn_message_id` with it, so nothing tries to
        edit or re-attach a view to a message that is gone; whatever
        prompt the resolution posts next sets its own.
        """
        if game.turn_message_id is None or interaction.channel is None:
            return

        all_chosen = match.maneuver_selections_complete

        try:
            prompt_message = interaction.channel.get_partial_message(
                game.turn_message_id,
            )
            if all_chosen:
                await prompt_message.delete()
            else:
                await prompt_message.edit(
                    view=ManeuverActionPromptView(self, game.game_id),
                )
        except (discord.NotFound, discord.HTTPException):
            pass

        if all_chosen:
            game.turn_message_id = None
            save_games(self.games)

    def retest_exhausted(self, match: MatchState, player_id: str) -> bool:
        """
        Re-test a player's Exhausted flag against their own defensive
        skill. True only on the transition, so callers can announce it
        once.

        `MatchState` deliberately does not carry the skill the
        threshold is measured against, so this test can only happen up
        here -- which is exactly why it has to run before the state is
        written out. See `apply_exhaustion`.
        """
        player = self.get_player_definition(player_id)
        return match.mark_exhausted_if_needed(
            player_id,
            self.player_catalog.effective_profile(player).defense,
        )

    def apply_exhaustion(
        self,
        match: MatchState,
        player_id: str,
        amount: int,
    ) -> str:
        """
        Charge `amount` exhaustion tokens, re-test Exhausted, and
        describe both.

        Charging and testing belong in one step. They used to be two:
        callers added the tokens, saved the match, and only then built
        the message that ran the threshold test -- so the flag the
        test set was never written out. The next interaction reloaded
        the saved state and saw a player over their defensive skill
        who was not marked Exhausted, which cost a skill test the
        injury check for anyone the test's own tokens pushed over.
        Anything that charges exhaustion should call this and save
        afterwards.
        """
        match.add_exhaustion(player_id, amount)
        return self.describe_exhaustion_gain(match, player_id, amount)

    def describe_exhaustion_gain(
        self,
        match: MatchState,
        player_id: str,
        amount: int,
    ) -> str:
        """
        Text describing an exhaustion-token gain that has already been
        applied to `match` — the running total, plus a line the moment
        it pushes the player's token count past their defense skill.

        Testing the threshold is a state change, so this has to be
        called before `match` is saved -- prefer `apply_exhaustion`,
        which keeps the two together, wherever the tokens are being
        charged here rather than inside `MatchState`.
        """
        player = self.get_player_definition(player_id)
        if player_id in match.injured:
            return (
                f"{format_role_bracket(player, self.team_emojis)} is injured "
                f"{get_injured_emoji(self.condition_emojis)} and gains no "
                "exhaustion tokens."
            )
        if amount <= 0:
            return (
                f"{format_role_bracket(player, self.team_emojis)} was "
                "already there -- no exhaustion cost."
            )

        exhaust_emoji = get_exhaust_emoji(self.condition_emojis)
        total = match.exhaustion.get(player_id, 0)
        token_word = "token" if amount == 1 else "tokens"
        text = (
            f"{format_role_bracket(player, self.team_emojis)} gains {amount} exhaustion "
            f"{token_word} {exhaust_emoji * amount} (now {total} total)."
        )

        defense_skill = self.player_catalog.effective_profile(player).defense
        if self.retest_exhausted(match, player_id):
            exhausted_emoji = get_exhausted_emoji(self.condition_emojis)
            text += (
                f"\n{format_role_bracket(player, self.team_emojis)} now has the condition "
                f"**exhausted** {exhausted_emoji} — {total} exhaustion "
                f"tokens exceeds their defense skill of {defense_skill}."
            )
        return text

    def describe_challenger_walk_in(
        self,
        match: MatchState,
        defender_id: str,
        distance: int,
    ) -> str:
        """
        The challenger's walk-in and what it cost, or "" when they were
        already on the ball's space.

        Like every other exhaustion message this tests the Exhausted
        threshold as it writes it, so it has to be built before `match`
        is saved -- see apply_exhaustion.
        """
        if distance <= 0:
            return ""

        defender = self.get_player_definition(defender_id)
        space_word = "space" if distance == 1 else "spaces"
        return (
            f"{defender.name} has moved {distance} {space_word}."
            f"\n{self.describe_exhaustion_gain(match, defender_id, distance)}"
        )

    def challenge_side(
        self,
        player_id: str,
        attacking: bool,
        modifiers: tuple[str, ...] = (),
    ) -> ChallengeSide:
        """
        A player as a matchup image draws them. The ability is the
        short form: this is a caption under a portrait, next to
        another player's, and the sentence version wrapped to three
        lines and set the height of the whole image. The full text is
        still what the roster and the rules listing show.
        """
        player = self.get_player_definition(player_id)
        profile = self.player_catalog.effective_profile(player)
        return ChallengeSide(
            name=player.name,
            role=ROLE_INITIALS[player.role.value],
            team_color=TEAM_COLORS[player.team],
            team_label=player.team.value.title(),
            skill_name="Offensive" if attacking else "Defensive",
            skill=profile.offense if attacking else profile.defense,
            ability=profile.short_ability,
            modifiers=modifiers,
        )

    async def build_maneuver_challenge_file(
        self,
        match: MatchState,
        defender_id: str,
    ) -> discord.File:
        """
        The matchup about to be contested, as a picture. It stands in
        for the two lines of prose that used to announce a challenge:
        the players' skills and abilities are what a coach weighs while
        choosing a maneuver, and neither was in the text.

        Drawn in a worker thread for the same reason the board is --
        see render_match_png.
        """
        return discord.File(
            await asyncio.to_thread(
                render_maneuver_challenge,
                self.challenge_side(match.active_player_id, attacking=True),
                self.challenge_side(defender_id, attacking=False),
                location=(
                    f"{space_label(match.ball.zone, match.ball.space_index)}"
                    f" — {ZONE_LABELS[match.ball.zone].title()}"
                ),
            ),
            filename="maneuver_challenge.png",
        )

    async def build_score_attempt_file(self, match: MatchState) -> discord.File:
        """
        What the shot is made of: the shooter with the modifiers this
        particular attempt earns them, and every defender between them
        and the goal.

        The two modifiers are listed on the shooter rather than folded
        into their skill, because both are conditions of this attempt
        and not of the player -- the ball speed is spent on the shot,
        and the Striker's +3 only applies off a set-up.
        """
        shooter = self.get_player_definition(match.active_player_id)
        speed_modifier = match.ball.speed // 2
        defenders = self.intervening_defenders(match)
        defending_setup = match.setup_for_side(match.defending_side())

        modifiers = []
        if speed_modifier:
            modifiers.append(
                f"+{speed_modifier} ball speed ({match.ball.speed})"
            )
        if match.pending_shot_is_set_up and shooter.role == PlayerRole.STRIKER:
            modifiers.append("+3 Striker ability")

        return discord.File(
            await asyncio.to_thread(
                render_score_attempt,
                self.challenge_side(
                    shooter.player_id,
                    attacking=True,
                    modifiers=tuple(modifiers),
                ),
                [
                    self.challenge_side(player.player_id, attacking=False)
                    for player, _ in defenders
                ],
                location=(
                    f"{space_label(match.ball.zone, match.ball.space_index)}"
                    f" → {format_team_side_label(defending_setup)} goal"
                ),
            ),
            filename="score_attempt.png",
        )

    async def announce_maneuver_challenge(
        self,
        interaction: discord.Interaction,
        match: MatchState,
        defender_id: str,
        walk_in_text: str,
    ) -> None:
        """
        Post the matchup image, with the challenger's walk-in above it
        rather than below: the image is meant to sit directly on top of
        the maneuver prompt, which is the message a coach is reading it
        for.
        """
        if walk_in_text:
            await interaction.followup.send(
                walk_in_text,
                allowed_mentions=discord.AllowedMentions(
                    users=False, roles=False, everyone=False,
                ),
            )
        await interaction.followup.send(
            file=await self.build_maneuver_challenge_file(match, defender_id),
        )

    async def drop_turn_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        """
        Delete the prompt whose choice has just been made, the same way
        refresh_maneuver_prompt drops the maneuver prompt once both
        sides have picked: what it asked for is settled, and the
        challenge image posted underneath says who is involved better
        than the "has chosen to..." line the message would otherwise be
        edited down to.

        The caller must have acknowledged the interaction already
        (`response.defer()`), since deleting is not itself a response.
        """
        try:
            await interaction.delete_original_response()
        except (discord.NotFound, discord.HTTPException):
            pass

        if game.turn_message_id is not None:
            game.turn_message_id = None
            save_games(self.games)

    async def refresh_match_image(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        png: Optional[bytes] = None,
    ) -> None:
        """
        Bring the persistent board message up to date, at most once
        every BOARD_REFRESH_INTERVAL for a given game.

        Discord buckets message edits per message, and this one message
        is edited from fifty-odd places -- a single click walks through
        several of them, and each is two edits (see
        `write_board_message`). That is what was earning the 429s, and
        the intermediate boards are worth nothing: a coach reads the
        board once everything has finished moving. So a refresh that
        arrives inside the window does not queue behind the last one,
        it *replaces* it -- one trailing refresh is scheduled, and by
        the time it runs it draws whatever the state has become.

        `png` is an already-rendered board, for a caller that is
        posting the same one somewhere else in the same breath and
        should not pay to draw it twice. It is only used when the
        refresh happens now; a deferred one re-draws, because the
        board it was handed will be stale by the time it runs.
        """
        if game.message_id is None or interaction.channel is None:
            return

        now = time.monotonic()
        last = self.board_refreshed_at.get(game.game_id)

        if last is not None and now - last < BOARD_REFRESH_INTERVAL:
            self.schedule_board_refresh(
                interaction.channel, game, last + BOARD_REFRESH_INTERVAL - now,
            )
            return

        self.board_refreshed_at[game.game_id] = now
        await self.write_board_message(interaction.channel, game, png)

    def schedule_board_refresh(
        self,
        channel: discord.TextChannel,
        game: D12BallGame,
        delay: float,
    ) -> None:
        """
        Arrange for the board to be brought up to date once the window
        is open again, unless one is already arranged.

        One pending refresh per game is all that is ever needed: it
        renders when it runs, so a refresh asked for after it was
        scheduled but before it fired is already covered by it.
        """
        if game.game_id in self.board_refresh_tasks:
            return

        async def run() -> None:
            try:
                await asyncio.sleep(delay)
                self.board_refreshed_at[game.game_id] = time.monotonic()
                await self.write_board_message(channel, game)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Nothing above this to catch it -- an exception left
                # in a task surfaces as asyncio's own "never retrieved"
                # record, naming neither the game nor this code.
                LOGGER.error(
                    "Could not refresh the board for D12 Ball game %s.",
                    game.game_id,
                    exc_info=True,
                )
            finally:
                self.board_refresh_tasks.pop(game.game_id, None)

        # The loop keeps only a weak reference to a task, so the handle
        # is held here to keep this one from being collected mid-sleep.
        self.board_refresh_tasks[game.game_id] = asyncio.create_task(run())

    async def write_board_message(
        self,
        channel: discord.TextChannel,
        game: D12BallGame,
        png: Optional[bytes] = None,
    ) -> None:
        """
        The two edits a board refresh actually costs: the attachment,
        and then the link button that could not be cut until the
        attachment had a URL.

        A board identical to the one already on the message is not
        written at all. Plenty of steps refresh without moving anything
        a coach can see -- picking a receiver, choosing a maneuver --
        and the render is deterministic, so byte-equality is the whole
        test. Those refreshes cost two requests out of a bucket that
        only has about five, and bought nothing.

        This is a nicety layered on top of state that has already been
        saved, not the thing carrying the turn forward -- a dropped
        connection here (aiohttp.ClientError, e.g. a reset or a bad SSL
        record on a flaky link) shouldn't abort the caller and strand
        the turn before it reaches the next prompt, any more than a 404
        or a Discord-side HTTP error already doesn't.
        """
        if game.message_id is None:
            return

        if png is None:
            png = await self.render_match_png(game)

        digest = hashlib.sha256(png).digest()
        if self.board_png_digests.get(game.game_id) == digest:
            return

        try:
            board_message = channel.get_partial_message(game.message_id)
            updated_message = await board_message.edit(
                attachments=[self.match_file_from_png(game, png)],
            )
        except (discord.NotFound, discord.HTTPException, aiohttp.ClientError):
            return

        # Recorded only once the upload has landed, so a failed edit
        # leaves the next refresh believing it still has work to do.
        self.board_png_digests[game.game_id] = digest

        # The link has to be re-cut because the edit above uploaded a
        # new file, and setting a view replaces the one already there,
        # so the message's own home/visiting buttons get rebuilt with
        # it. Those are inert once the assignment is made, which is the
        # only state a board refresh runs in; before it, this message
        # is still the team/coin prompt and its buttons are live.
        if game.home_and_visiting_selected:
            await add_full_image_button(
                updated_message,
                HomeAwaySelectionView(cog=self, game_id=game.game_id),
            )

    def format_roster_player(self, player_id: str) -> str:
        player = self.get_player_definition(player_id)
        initials = ROLE_INITIALS[player.role.value]
        return f"{player.name} ({initials})"

    def format_roster_player_with_team(self, player_id: str) -> str:
        player = self.get_player_definition(player_id)
        initials = ROLE_INITIALS[player.role.value]
        return f"{player.name} ({player.team.value.title()}, {initials})"

    def format_team_roster_entry(
        self,
        match: MatchState,
        player_id: str,
        location: Optional[str] = None,
        show_abilities: bool = False,
    ) -> str:
        """
        One roster line. `location` is the space the player stands on
        (e.g. "H1") for a player on the board, and None on a bench --
        the group heading above the line already names the place, so
        the line only has to say where within it.
        """
        player = self.get_player_definition(player_id)
        tokens = match.exhaustion.get(player_id, 0)

        conditions = []
        if player_id in match.exhausted:
            conditions.append(
                f"exhausted {get_exhausted_emoji(self.condition_emojis)}"
            )
        if player_id in match.injured:
            conditions.append(
                f"injured {get_injured_emoji(self.condition_emojis)}"
            )

        entry = format_role_bracket(player, self.team_emojis)
        if location is not None:
            entry += f" — {location}"
        entry += f" — {tokens} {get_exhaust_emoji(self.condition_emojis)}"
        if conditions:
            entry += f" — {', '.join(conditions)}"
        if show_abilities:
            ability = self.player_catalog.effective_profile(player).ability
            entry += f"\n     *{ability}*"
        return entry

    def roster_places(
        self,
        match: MatchState,
        setup: TeamSetup,
    ) -> list[tuple[str, list[tuple[str, Optional[str]]]]]:
        """
        The team's roster grouped by where its players actually are:
        each board zone in board order, then the bench, then the back
        bench. Each group is (heading, [(player_id, space label or
        None)]), with the players inside a zone ordered by space.

        Grouped by the meeple's *current* zone rather than the zone its
        card is assigned to, because that is where the player is -- a
        maneuver can leave a player standing outside their zone until
        they run back (see MatchState.displaced_players). Every roster
        player appears exactly once: anyone without a meeple falls
        through to whichever bench holds them.
        """
        roster_order = {
            player.player_id: index
            for index, player in enumerate(
                self.player_catalog.teams[setup.team].players
            )
        }
        placed: dict[Zone, list[tuple[int, int, str]]] = {
            zone: [] for zone in Zone
        }
        for player_id in roster_order:
            position = match.board.meeple_position(player_id)
            if position is None:
                continue
            zone, space_index = position
            placed[zone].append(
                (space_index, roster_order[player_id], player_id)
            )

        on_board = {
            player_id
            for occupants in placed.values()
            for _, _, player_id in occupants
        }
        groups: list[tuple[str, list[tuple[str, Optional[str]]]]] = [
            (
                destination_display_name(zone.value),
                [
                    (player_id, space_label(zone, space_index))
                    for space_index, _, player_id in sorted(placed[zone])
                ],
            )
            for zone in Zone
        ]
        for bench, benched in (
            ("bench", setup.player_board.bench),
            ("back_bench", setup.player_board.back_bench),
        ):
            groups.append(
                (
                    destination_display_name(bench),
                    [
                        (player_id, None)
                        for player_id in benched
                        if player_id not in on_board
                    ],
                )
            )
        return groups

    def roster_setups_for_user(
        self,
        game: D12BallGame,
        match: MatchState,
        user_id: int,
        all_teams: bool = False,
    ) -> Optional[list[TeamSetup]]:
        """
        Whose rosters `user_id` gets to see: their own team's by
        default, both when they asked for both or when they are running
        both sides of a test game, and None when they are not playing
        this game at all -- callers turn that into an explanation.
        """
        if all_teams or (game.test_game and user_id == game.player_1_id):
            return [match.home, match.visiting]
        side = self.side_for_user(game, user_id)
        if side is None:
            return None
        return [match.setup_for_side(side)]

    def build_team_roster_section(
        self,
        match: MatchState,
        setup: TeamSetup,
        show_abilities: bool = False,
    ) -> str:
        lines = [f"**{format_team_side_label(setup)}**"]
        for heading, members in self.roster_places(match, setup):
            lines.append(f"\n__{heading}__")
            if not members:
                lines.append("*nobody*")
                continue
            lines.extend(
                self.format_team_roster_entry(
                    match,
                    player_id,
                    location=location,
                    show_abilities=show_abilities,
                )
                for player_id, location in members
            )
        return "\n".join(lines)

    def build_turn_prompt(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> str:
        player_number = self.possession_player_number(game, match)
        controller = format_player_with_team(
            game,
            player_number,
            mention=player_number is not None,
        )

        if match.active_player_id is None:
            return (
                f"{controller}, it is your turn.\n\n"
                "Choose which player in the ball's space will take "
                "an action."
            )

        handler = self.format_roster_player(match.active_player_id)
        # PlayerActionView drops the shoot button in a team's own half,
        # so say why rather than leaving a coach to wonder where it
        # went.
        action_line = (
            "Choose an action:"
            if match.can_attempt_score()
            else (
                "The ball has not reached the other team's half, so there "
                "is no shot from here -- only a maneuver:"
            )
        )
        return (
            f"{controller}, it is your turn.\n\n"
            f"{handler} will be handling the ball.\n\n"
            f"{action_line}"
        )

    async def play_ai_turn(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Play out the AI opponent's turn with possession: pick a ball
        handler, then shoot if the ball is already on the space
        closest to the opponent's goal, otherwise always maneuver.
        """
        ai_name = format_ai_name(game.ai_opponent)
        ai_strategy = self.get_ai_strategy(game)
        handler_id = ai_strategy.choose_ball_handler(match)
        match.select_ball_handler(handler_id)
        handler = self.get_player_definition(handler_id)
        action = ai_strategy.choose_action(match)

        if action == "shoot":
            match.pending_action = "shoot"
            game.match_state = match.to_dict()
            save_games(self.games)

            await interaction.followup.send(
                f"{ai_name} has chosen to shoot to score with "
                f"{format_role_bracket(handler, self.team_emojis)}.",
            )
            await self.begin_score_attempt(interaction, game, match)
            return

        # Unchallenged, so the AI's pick succeeds outright -- the same
        # branch a human offense takes, see
        # PlayerActionView.choose_action.
        eligible_challengers = match.eligible_challengers()
        if not eligible_challengers:
            match.begin_uncontested_maneuver()
            game.match_state = match.to_dict()
            save_games(self.games)

            await interaction.followup.send(
                f"{ai_name} has chosen to maneuver with "
                f"{format_role_bracket(handler, self.team_emojis)}."
            )
            await self.announce_uncontested_maneuver(
                interaction, game, match,
            )
            return

        match.pending_action = "maneuver"

        # A defender already sharing the ball's exact space leaves
        # nothing to choose -- see PlayerActionView.choose_action.
        on_ball_space = [
            player_id
            for player_id in eligible_challengers
            if match.distance_to_ball(player_id) == 0
        ]
        if on_ball_space:
            game.match_state = match.to_dict()
            save_games(self.games)

            # Nothing is announced here: the challenge image
            # auto_resolve_challenger posts names the handler the AI
            # picked, along with everything else about the matchup.
            await self.auto_resolve_challenger(
                interaction, game, match, on_ball_space[0],
            )
            return

        game.match_state = match.to_dict()
        save_games(self.games)

        defender_number = self.defending_player_number(game, match)
        defender_mention = format_player_with_team(
            game,
            defender_number,
            mention=True,
        )

        challenge_view = ManeuverChallengeView(self, game.game_id)
        challenge_message = await interaction.followup.send(
            f"{ai_name} will maneuver with "
            f"{format_role_bracket(handler, self.team_emojis)}.\n\n"
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
        save_games(self.games)

    async def send_turn_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        refresh_player_names(game, interaction.guild)
        match = self.load_match_state(game)
        eligible_handlers = match.eligible_ball_handlers()
        if not eligible_handlers:
            raise ValueError(
                "The team in possession has no player in the ball's space."
            )

        offense_number = self.possession_player_number(game, match)
        if game.is_solo_game and offense_number == 2:
            await self.play_ai_turn(interaction, game, match)
            return

        if len(eligible_handlers) == 1:
            match.select_ball_handler(eligible_handlers[0])
            game.match_state = match.to_dict()
            view: discord.ui.View = PlayerActionView(
                self,
                game.game_id,
            )
        else:
            view = BallHandlerSelectionView(
                self,
                game.game_id,
            )

        turn_message = await interaction.followup.send(
            self.build_turn_prompt(game, match),
            view=view,
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
        game.turn_message_id = turn_message.id
        save_games(self.games)

    async def render_match_png(self, game: D12BallGame) -> bytes:
        """
        The board as PNG bytes. The Pillow render is pure CPU work with
        no awaits in it, so it runs in a worker thread via to_thread --
        run inline, it would block the single asyncio event loop for
        every game and every user for as long as the render takes.

        Bytes rather than a `discord.File`, because uploading a File
        consumes the stream inside it: a turn that puts the same board
        in two places (the persistent message and the snapshot under
        the result) needs two Files over one render, not two renders.
        """
        match = self.load_match_state(game)
        home_player = format_player_with_team(
            game,
            game.home_player_number,
        )
        visiting_player = format_player_with_team(
            game,
            game.visiting_player_number,
        )
        period = (
            "First Half"
            if match.scoreboard.period.value == "first_half"
            else "Second Half"
        )
        title = (
            f"PBD{game.game_number} - {home_player} vs. "
            f"{visiting_player}, {period}"
        )
        image = await asyncio.to_thread(
            render_match_image,
            match,
            self.player_catalog,
            title=title,
        )
        return image.getvalue()

    def match_file_from_png(
        self,
        game: D12BallGame,
        png: bytes,
    ) -> discord.File:
        """One upload of an already-rendered board."""
        return discord.File(
            io.BytesIO(png),
            filename=board_image_filename(game.game_number),
        )

    async def build_match_file(self, game: D12BallGame) -> discord.File:
        """Render the board and wrap it for a single upload."""
        return self.match_file_from_png(
            game, await self.render_match_png(game),
        )

    async def post_new_play_board(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        message: str,
    ) -> None:
        """
        The board at the top of a new play -- a kickoff, halftime, or
        the restart after a goal, an own goal, a missed shot or a ball
        out of bounds -- posted as its own message and pinned.

        These are the boards worth coming back to, which is why they
        are the ones pinned; see pin_board_message for what happens at
        the pin cap. Everything else a turn puts out still goes to the
        persistent board message only.

        The persistent message is brought in line with the same render
        rather than a second one, exactly as announce_board_update
        does.
        """
        png = await self.render_match_png(game)
        snapshot = await interaction.followup.send(
            message,
            file=self.match_file_from_png(game, png),
            wait=True,
        )
        await add_full_image_button(snapshot)
        await self.refresh_match_image(interaction, game, png=png)
        await pin_board_message(snapshot)

    async def announce_board_update(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        message: str,
    ) -> None:
        """
        Confirm a manual board correction (/coach, /ref, /meeple move,
        /ball move/possession/speed, /score, /time) with a fresh
        snapshot attached directly to the reply, in addition to
        keeping the persistent board message in sync.

        Both show the same board, so it is rendered once and uploaded
        twice.
        """
        png = await self.render_match_png(game)
        snapshot = await interaction.followup.send(
            message,
            file=self.match_file_from_png(game, png),
            wait=True,
        )
        await add_full_image_button(snapshot)
        await self.refresh_match_image(interaction, game, png=png)

    async def fetch_game_channel(
        self,
        game: D12BallGame,
    ) -> discord.TextChannel:
        """
        The channel a game is played in. Split out from archiving so
        that a `discord.NotFound` raised here means one thing only --
        the channel is gone -- and cannot be confused with a 404 from
        the category or the move that follows it.
        """
        guild = self.bot.get_guild(game.guild_id)
        if guild is None:
            raise ValueError("The server for this game is not available.")

        channel = guild.get_channel(game.channel_id)
        if channel is None:
            channel = await guild.fetch_channel(game.channel_id)

        if not isinstance(channel, discord.TextChannel):
            raise ValueError("The channel for this game is not a text channel.")

        return channel

    async def move_channel_to_archive(
        self,
        channel: discord.TextChannel,
    ) -> None:
        if (
            channel.category is not None
            and channel.category.name.casefold()
            == PBD_ARCHIVE_CATEGORY_NAME.casefold()
        ):
            return

        archive_category = await get_or_create_category(
            channel.guild,
            PBD_ARCHIVE_CATEGORY_NAME,
            "Create the category for finished PBD games.",
        )
        await channel.edit(
            category=archive_category,
            reason="Move a finished D12 Ball game to the PBD archive.",
        )

    async def archive_game_channel(
        self,
        game: D12BallGame,
    ) -> None:
        await self.move_channel_to_archive(await self.fetch_game_channel(game))

    async def finish_and_archive_game(
        self,
        game_id: str,
    ) -> D12BallGame:
        game = self.games.get(game_id)
        if game is None:
            raise ValueError("The D12 Ball game could not be found.")

        if game.status != GameStatus.IN_PROGRESS:
            raise ValueError("Only a game in progress can be finished.")

        await self.archive_game_channel(game)
        game.finish_game()
        save_games(self.games)
        return game

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # Games whose channel Discord says does not exist. Collected and
        # dropped after the sweep rather than during it, so the save
        # happens once and the dict is not mutated while it is walked.
        deleted_channels: list[str] = []

        for game in self.games.values():
            if game.status != GameStatus.FINISHED:
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

    @app_commands.command(
        name="create_game",
        description="Create a new D12 Ball game.",
    )
    @app_commands.describe(
        p1="Player 1. Leave blank to make yourself Player 1.",
        p2="Player 2. Leave blank to play against the AI.",
        test_game=(
            "Create a test game where you control Player 1 and Player 2."
        ),
        game_name=(
            "A fun name for this game, used in the channel name. Leave "
            "blank to name it after the players."
        ),
    )
    @app_commands.guild_only()
    async def create_game(
        self,
        interaction: discord.Interaction,
        p1: Optional[discord.Member] = None,
        p2: Optional[discord.Member] = None,
        test_game: bool = False,
        game_name: Optional[app_commands.Range[str, 1, 80]] = None,
    ) -> None:
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

        if test_game and (p1 is not None or p2 is not None):
            await interaction.response.send_message(
                "A test game cannot specify p1 or p2; you control both sides.",
                ephemeral=True,
            )
            return

        # Work out which members are Player 1 and Player 2.
        if test_game:
            player_1 = interaction.user
            player_2 = interaction.user
        elif p1 is None and p2 is None:
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

        if (
            not test_game
            and player_2 is not None
            and player_1.id == player_2.id
        ):
            await interaction.response.send_message(
                "Player 1 and Player 2 must be different people.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            game = await self.open_new_game(
                guild,
                player_1,
                player_2,
                test_game=test_game,
                created_by=interaction.user,
                game_name=game_name,
            )
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        await interaction.followup.send(
            f"Game created: <#{game.channel_id}>",
            ephemeral=True,
        )

    async def open_new_game(
        self,
        guild: discord.Guild,
        player_1: discord.Member,
        player_2: Optional[discord.Member],
        test_game: bool = False,
        created_by: Optional[discord.abc.User] = None,
        mode: GameMode = GameMode.BASIC,
        tie_mode: TieMode = TieMode.LEAGUE,
        board_size: int = 7,
        ai_opponent: Optional[AIOpponent] = None,
        game_name: Optional[str] = None,
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
        game_number = self.get_next_game_number(guild)
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
            game_name=game_name,
        )

        bot_member = guild.me

        if bot_member is None:
            raise ValueError("I could not find my server account.")

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

        game_id = uuid.uuid4().hex

        game = D12BallGame(
            game_id=game_id,
            game_number=game_number,
            guild_id=guild.id,
            channel_id=game_channel.id,
            message_id=None,
            player_1_id=player_1.id,
            player_2_id=player_2.id if player_2 else None,
            player_1_name=player_1_name,
            player_2_name=player_2_name,
            test_game=test_game,
            game_name=game_name,
            mode=mode,
            tie_mode=tie_mode,
            status=GameStatus.SETUP,
            board_size=board_size,
            ai_opponent=resolved_ai_opponent,
        )

        self.games[game_id] = game

        view = TeamSelectionView(
            cog=self,
            game_id=game_id,
        )

        message_text = view.build_team_message(game)

        message_text = (
            "Start playing in this channel.\n\n"
            f"{message_text}"
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
            self.games.pop(game_id, None)

            raise ValueError(
                f"The channel was created, but I could not send "
                f"the game message: {error}"
            )

        game.message_id = game_message.id
        save_games(self.games)
        return game

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
            tie_mode=game.tie_mode,
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

        setups = self.roster_setups_for_user(
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
                    match, setup, show_abilities=abilities,
                )
            )

    @app_commands.command(
        name="maneuver_reference",
        description=(
            "Post the maneuver reference image showing all six maneuvers."
        ),
    )
    @app_commands.guild_only()
    async def maneuver_reference(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.send_message(
            file=self.build_maneuver_reference_file(),
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

        if match.pending_action == "maneuver":
            await interaction.followup.send(
                "A maneuver challenge is already in progress for this "
                "turn.",
                ephemeral=True,
            )
            return

        if match.pending_action == "shoot":
            await interaction.followup.send(
                "A score attempt is already in progress for this turn.",
                ephemeral=True,
            )
            return

        # A ball handler or a maneuver choice may already be recorded
        # from a prior offensive choice whose effect was never resolved
        # into a state change (e.g. an uncontested maneuver). Nothing
        # else advances the match to its next turn, so this command
        # always starts fresh: clear that stale choice and re-derive the
        # ball handler from the board's current occupancy.
        match.reset_maneuver()
        game.match_state = match.to_dict()
        save_games(self.games)

        try:
            await self.send_turn_prompt(interaction, game)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)

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

        side = self.side_for_user(game, interaction.user.id)
        if game.test_game and interaction.user.id == game.player_1_id:
            for candidate_side in (TeamSide.HOME, TeamSide.VISITING):
                setup = match.setup_for_side(candidate_side)
                roster_ids = (
                    setup.field_players
                    + setup.player_board.bench
                    + setup.player_board.back_bench
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

        game.match_state = match.to_dict()
        save_games(self.games)

        player = self.get_player_definition(player_card)
        await self.announce_board_update(
            interaction,
            game,
            f"{format_role_bracket(player, self.team_emojis)} moved to "
            f"{destination_display_name(destination)}.",
        )

    @coach.autocomplete("player_card")
    async def coach_player_card_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            return []
        side = self.side_for_user(game, interaction.user.id)
        if side is None:
            return []
        match = self.load_match_state(game)
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
                + setup.player_board.bench
                + setup.player_board.back_bench
            )
        ]
        options = [
            (player_id, self.format_roster_player(player_id))
            for player_id in roster_ids
        ]
        return filter_choices(current, options)

    @coach.autocomplete("destination")
    async def coach_destination_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        options = [
            (value, destination_display_name(value))
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
            player = self.get_player_definition(player_card)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        card_side = (
            TeamSide.HOME
            if player.team == match.home.team
            else TeamSide.VISITING
        )

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

        game.match_state = match.to_dict()
        save_games(self.games)

        await self.announce_board_update(
            interaction,
            game,
            f"{format_role_bracket(player, self.team_emojis)} moved to "
            f"{destination_display_name(dest_target)}.",
        )

    @ref.autocomplete("player_card")
    async def ref_player_card_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            return []
        match = self.load_match_state(game)
        options = [
            (player_id, self.format_roster_player_with_team(player_id))
            for setup in (match.home, match.visiting)
            for player_id in (
                setup.field_players
                + setup.player_board.bench
                + setup.player_board.back_bench
            )
        ]
        return filter_choices(current, options)

    @ref.autocomplete("destination")
    async def ref_destination_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            return []
        match = self.load_match_state(game)
        options = [
            (
                f"{setup.side.value}:{target}",
                f"{format_team_side_label(setup)} - "
                f"{destination_display_name(target)}",
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
        destination="The board space to move them to, e.g. H1.",
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

        game.match_state = match.to_dict()
        save_games(self.games)

        player = self.get_player_definition(meeple)
        await self.announce_board_update(
            interaction,
            game,
            f"{format_role_bracket(player, self.team_emojis)} moved to "
            f"{space_label(zone, space_index)}.",
        )

    @meeple_move.autocomplete("meeple")
    async def meeple_move_meeple_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            return []
        match = self.load_match_state(game)
        options = [
            (player_id, self.format_roster_player_with_team(player_id))
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
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            return []
        match = self.load_match_state(game)
        return filter_choices(current, space_choices(match))

    @ball_group.command(
        name="move",
        description="Place the ball on any board space.",
    )
    @app_commands.describe(
        destination="The board space to move the ball to, e.g. H1.",
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

        game.match_state = match.to_dict()
        save_games(self.games)

        possession_team = match.setup_for_side(match.ball.possession).team
        await self.announce_board_update(
            interaction,
            game,
            f"The ball moved to {space_label(zone, space_index)}. "
            f"{possession_team.value.title()} has possession.",
        )

    @ball_move.autocomplete("destination")
    async def ball_move_destination_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            return []
        match = self.load_match_state(game)
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

        game.match_state = match.to_dict()
        save_games(self.games)

        await interaction.followup.send(
            f"{match.setup_for_side(side).team.value.title()} now has "
            "possession."
        )
        await self.refresh_match_image(interaction, game)

    @ball_possession.autocomplete("team")
    async def ball_possession_team_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            return []
        match = self.load_match_state(game)
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

        game.match_state = match.to_dict()
        save_games(self.games)

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
            side = self.side_for_user(game, interaction.user.id)
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

        game.match_state = match.to_dict()
        save_games(self.games)

        team_name = match.setup_for_side(side).team.value.title()
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
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            return []
        match = self.load_match_state(game)
        options = [
            (setup.side.value, format_team_side_label(setup))
            for setup in (match.home, match.visiting)
        ]
        return filter_choices(current, options)

    @app_commands.command(
        name="time",
        description="Set or adjust the game clock (00-15) and half.",
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
                value, match.scoreboard.time, 0, 15,
            )
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        if period is not None:
            match.scoreboard.period = MatchPeriod(period)

        game.match_state = match.to_dict()
        save_games(self.games)

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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(D12Ball(bot))

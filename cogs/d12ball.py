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
from d12ball.engine import (
    FULL_TIME_STAGES,
    HALFTIME_STAGES,
    LEGACY_HALFTIME_STAGES,
    SETUP_STAGES,
    RulesEngine,
)
from d12ball.components import (
    SETUP_PASS_CLOCK_COST,
    MANEUVER_TIER_ADVANCED,
    MANEUVER_TIER_BASIC,
    MIN_HIGH_PASS_DISTANCE,
    SECOND_HALF_START_MINUTE,
    SETUP_AREAS,
    CoachingOccasion,
    FormationShape,
    MatchPeriod,
    MatchState,
    PlayerDefinition,
    PlayerRole,
    ShotDefender,
    TeamSetup,
    TeamSide,
    Zone,
    formation_space_order,
    kickoff_space_index,
    legacy_maneuver_key,
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
    team_display_name,
)
from d12ball.cards import render_maneuver_hand
from d12ball import tutorial
from d12ball.render import (
    TEAM_COLORS,
    ZONE_LABELS,
    render_coaching_image,
    render_field_image,
    render_injury_test_die,
    render_maneuver_challenge,
    render_maneuver_reference_image,
    render_match_image,
    render_own_goal_dice,
    render_score_attempt,
)
from d12ball.rules_doc import (
    LIVING_RULES_PATH,
    RulesDocument,
    chunk_for_discord,
    load_rules_document,
)

from gamesaves.d12ball.storage import (
    load_games,
    save_games,
)

from discord_emoji_cache import ensure_cached_emojis

from cogs.d12ball_helpers import (
    BENCH_DESTINATIONS,
    COIN_EMOJI_NAMES,
    EMOJI_REFETCH_INTERVAL,
    ERROR_RECOVERY_ADVICE,
    FIELD_IMAGE_FILENAME,
    HIGH_PASS_CONTEST_HEADLINE,
    LOGGER,
    PBD_ARCHIVE_CATEGORY_NAME,
    PBD_GAMES_CATEGORY_NAME,
    add_full_image_button,
    add_full_image_button_to_response,
    ball_location_line,
    ball_space_label,
    board_image_filename,
    build_full_image_button,
    build_full_time_summary,
    build_game_channel_name,
    build_goal_log,
    contest_noun,
    destination_display_name,
    fetch_application_emojis,
    filter_choices,
    format_ai_name,
    format_goal_time,
    format_player_with_team,
    format_role_bracket,
    format_team_side_label,
    full_image_link_button,
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
    HighPassChoiceView,
    HomeAwaySelectionView,
    InjuryTestView,
    LooseBallChoiceView,
    LooseBallSkillTestView,
    LowPassChoiceView,
    ManeuverActionPromptView,
    ManeuverActionSelectView,
    ManeuverChallengeView,
    OwnGoalRollView,
    PlayerActionView,
    RematchView,
    RunBackChoiceView,
    RunBackPlayerChoiceView,
    ScoreAttemptView,
    SetUpAttemptChoiceView,
    SetupPassChoiceView,
    SetupPassPushBackView,
    ShooterChoiceView,
    ShootoutOrderPromptView,
    ShootoutOrderSelectView,
    ShootoutPickPromptView,
    ShootoutPickSelectView,
    ShootoutTestView,
    SkillTestView,
    SpeedDeltaChoiceView,
    CoachingHubView,
    CoachingOfferView,
    TeamSelectionView,
)


# HALFTIME_STAGES, SETUP_STAGES, FULL_TIME_STAGES and
# LEGACY_HALFTIME_STAGES now live in d12ball/engine.py, imported above
# -- RulesEngine.next_halftime_stage/next_setup_stage/
# next_full_time_stage/halftime_stage are the only readers left once
# the stage-advancing methods moved there with them.

# The most placements one run back may make before it is treated as
# stuck. Twelve players a side is the whole board several times over,
# so this only ever fires on a bug -- see continue_run_back.
MAX_RUN_BACK_PASSES = 60


# The highest the clock may be set to by hand. The clock itself has no
# ceiling -- it runs for as long as a last possession does -- so this is
# not a rule, only what two digits hold: everything that prints the
# clock does so as `{:02d}`, and `/d12ball time 100` would be the one
# state the scoreboard cannot draw.
MAX_DEBUG_CLOCK = 99


# How often one game's persistent board message may be refreshed.
#
# The arithmetic, because it is not obvious: `message_id` is not one of
# Discord's major rate-limit parameters, so every
# `PATCH /channels/{id}/messages/{id}` in a game's channel shares one
# bucket -- about five requests in five seconds. Holding refreshes more
# than five seconds apart is what keeps the board to one refresh per
# window, which leaves the rest of that budget for the prompts. See
# "The board message is one bucket" in CLAUDE.md.
#
# It is also how long the board goes without its full-image link: an
# interim write strips the link rather than paying a second edit to
# re-cut it, and the settling write scheduled at this interval is what
# puts it back. See write_board_message.
BOARD_REFRESH_INTERVAL = 6.0

# What the interval widens to while Discord is refusing board writes,
# doubling per consecutive refusal, and the ceiling it stops at.
#
# The interval above is a budget, and a budget is only ever a guess at
# somebody else's arithmetic. This is what happens when the guess is
# wrong: a refused write does not record its digest -- deliberately, so
# the board it failed to put up is not treated as the one on the
# message -- so the next refresh redraws the same board and asks again,
# six seconds later, for as long as anyone keeps playing. Nothing in
# the gate could ever end that, and one logged session spent
# three-quarters of an hour in it, 61 refused uploads, every request in
# the channel refused. Backing off is the only exit: discord.py retries
# a 429 five times *inside* the one await this code makes, so a write
# is up to five requests however careful the gate is, and `Client`
# clamps `max_ratelimit_timeout` to a 30-second floor, so there is no
# way to ask for fewer. What the bot can decide is when to ask next.
BOARD_REFRESH_BACKOFF_CEILING = 300.0

# What discord.py raises a refused request as, once it has given up.
# It sleeps the `retry_after` and retries five times first, so by the
# time this reaches the bot the channel has already had five uploads
# refused -- which is the other half of why the answer is to wait
# rather than to try again promptly.
TOO_MANY_REQUESTS = 429


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
        # Checked here, against the catalog as it is read: the
        # maneuvers are imported from a spreadsheet, so a rename
        # upstream would otherwise leave a tutorial beat railing a
        # coach onto a card that no longer exists -- and a rail that
        # matches nothing shows as three disabled buttons rather than
        # as an error. See d12ball/tutorial.py.
        tutorial.validate_script(self.maneuver_catalog)
        # One hexagon per tier: a basic-mode coach has no advanced
        # cards to read a matchup for, so its hexagon shows one box a
        # rank rather than the pair an advanced game's does -- see
        # render_maneuver_reference_image.
        self.maneuver_reference_image_bytes = {
            tier: render_maneuver_reference_image(
                self.maneuver_catalog, tier
            ).read()
            for tier in (MANEUVER_TIER_BASIC, MANEUVER_TIER_ADVANCED)
        }
        # A side's playable cards, which is what a coach is shown when
        # they open the pick. All of them are drawn here for the same
        # reason the reference image is: it is the one place a render
        # can block the loop harmlessly, and the alternative is drawing
        # up to seven cards on every click of a button pressed several
        # times a turn. They cannot go stale -- nothing about a maneuver
        # card depends on the match.
        #
        # **Three hands a side, not one**, keyed by the tiers a coach
        # may play: basic, and (in an advanced game) both. See
        # `RulesEngine.maneuver_tiers` for who gets which.
        self.maneuver_hand_image_bytes = {
            (side, tiers): render_maneuver_hand(
                self.maneuver_catalog, self.player_catalog, side, tiers
            ).read()
            for side in ("offense", "defense")
            for tiers in (
                (MANEUVER_TIER_BASIC,),
                (MANEUVER_TIER_BASIC, MANEUVER_TIER_ADVANCED),
            )
        }
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
        # The rules-only slice of this class -- see d12ball/engine.py.
        # Built from the same four catalogs/strategies above, which is
        # why it comes right after them rather than at the top or
        # bottom of __init__.
        self.engine = RulesEngine(
            self.player_catalog,
            self.basic_ruleset,
            self.maneuver_catalog,
            self.ai_strategies,
        )
        # Per game: when its board message was last edited -- the
        # moment the write *landed*, not the moment it was sent -- the
        # trailing refresh waiting to edit it again, and a digest of
        # the board already sitting on the message. See
        # refresh_match_image.
        self.board_refreshed_at: dict[str, float] = {}
        self.board_refresh_tasks: dict[str, "asyncio.Task[None]"] = {}
        self.board_png_digests: dict[str, bytes] = {}
        # The full-image URL an interim write took the link off and has
        # not put back yet, by game. A game is in here only while its
        # board message is carrying a board it has no link to, which is
        # what the settling write is for -- see settle_board_link.
        self.board_link_owed: dict[str, str] = {}
        # Held for the length of a board write, so two of them can
        # never be in flight on the same message at once, and the set
        # of games whose board has been asked for since the write
        # covering it began. See refresh_match_image.
        self.board_refresh_locks: dict[str, asyncio.Lock] = {}
        self.board_refresh_wanted: set[str] = set()
        # Board writes Discord has refused in a row, by game. Widens
        # that game's interval until one lands. See
        # board_refresh_interval.
        self.board_writes_refused: dict[str, int] = {}

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
                    match = self.engine.load_match_state(game)
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
                turn_view, _ = self.pending_turn_view(game.game_id, match)
                self.bot.add_view(
                    turn_view,
                    message_id=game.turn_message_id,
                )
                restored_views += 1

                if isinstance(
                    turn_view,
                    (ShootoutOrderPromptView, ShootoutPickPromptView),
                ):
                    # Same problem as the maneuver menu, same answer --
                    # see restore_shootout_menus.
                    restored_views += self.restore_shootout_menus(game, match)

                if isinstance(turn_view, ManeuverActionPromptView):
                    # The maneuver menu a coach may have open right
                    # now, which is ephemeral and so has no message to
                    # re-attach to. Only reachable from here: a
                    # maneuver under way always has its prompt on
                    # turn_message_id, since that is only cleared once
                    # both sides have picked and the menus are gone
                    # with it.
                    restored_views += self.restore_maneuver_menus(game, match)

        LOGGER.info(
            "Loaded %d saved D12 Ball games and restored %d button "
            "views.",
            len(self.games),
            restored_views,
        )

        # discord.py reports a 429 as a bare method and URL, and the
        # only thing in it that identifies the game is the channel and
        # message id. Three rounds of these warnings were read by
        # inferring which message that was; one line a live game at
        # startup makes it a lookup instead. See "Discord's rate
        # limits" in CLAUDE.md.
        for game in self.games.values():
            if game.status == GameStatus.FINISHED:
                continue
            LOGGER.info(
                "D12 Ball game %s (pbd%s): channel %s, board message %s, "
                "prompt message %s.",
                game.game_id,
                game.game_number,
                game.channel_id,
                game.message_id,
                game.turn_message_id,
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

        A board whose settling write is cancelled here keeps the board
        it has and loses its full-image link until the next write puts
        one back -- the same trade the link is under everywhere else.
        """
        for task in list(self.board_refresh_tasks.values()):
            task.cancel()

        self.board_refresh_wanted.clear()

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
            "Something went wrong running that command. "
            f"{ERROR_RECOVERY_ADVICE}",
        )

    async def ensure_coin_emojis(self) -> dict[CoinFace, str]:
        """
        The coin emoji, retrying the lookup while any are missing.

        Uploading the emoji to the application therefore takes effect
        without needing a restart -- but no more often than
        EMOJI_REFETCH_INTERVAL. An application that has never had them
        uploaded is short of them on every single toss, so the retry
        used to mean an HTTP request per coin flip, forever, for a
        lookup whose answer had not changed since startup. The cache-
        with-cooldown shape is `ensure_cached_emojis`, shared with
        cogs/coins.py; only the fetch itself -- one application-emoji
        list feeding three loaders, see cog_load -- is this cog's own.
        """

        async def loader() -> dict[CoinFace, str]:
            application_emojis = await fetch_application_emojis(self.bot)
            if application_emojis is None:
                return self.coin_emojis
            return await load_coin_emojis(self.bot, application_emojis)

        self.coin_emojis, self.coin_emojis_checked_at = (
            await ensure_cached_emojis(
                self.coin_emojis,
                self.coin_emojis_checked_at,
                len(COIN_EMOJI_NAMES),
                loader,
            )
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





    def game_for_channel(self, channel_id: int) -> Optional[D12BallGame]:
        for game in self.games.values():
            if game.channel_id == channel_id:
                return game
        return None


    def match_for_channel(
        self,
        channel_id: int,
    ) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        """
        `(game, match)` for the game running in `channel_id`, or
        `(None, None)` when there is none there yet or it has no match
        state -- the lookup `defer_and_get_match` and every autocomplete
        callback open with. Autocomplete has no interaction to reply
        through the way a command does, which is why this doesn't
        reply and each caller answers an empty list itself.
        """
        game = self.game_for_channel(channel_id)
        if game is None or game.match_state is None:
            return None, None
        return game, self.engine.load_match_state(game)

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

        game, match = self.match_for_channel(interaction.channel_id)
        if game is None:
            await interaction.followup.send(
                "There is no D12 Ball match in progress in this channel.",
                ephemeral=True,
            )
            return None

        return game, match









    def reference_tier(self, game: Optional[D12BallGame]) -> str:
        """
        Which hexagon to post: the advanced one for an advanced game,
        the basic one everywhere else -- including outside a game's
        channel, where there is nothing to ask.
        """
        if game is not None and game.mode == GameMode.ADVANCED:
            return MANEUVER_TIER_ADVANCED
        return MANEUVER_TIER_BASIC

    def build_maneuver_reference_file(
        self, tier: str = MANEUVER_TIER_BASIC,
    ) -> discord.File:
        return discord.File(
            io.BytesIO(self.maneuver_reference_image_bytes[tier]),
            filename=f"maneuver_reference_{tier}.png",
        )

    def build_maneuver_hand_file(
        self,
        side: str,
        tiers: tuple[str, ...] = (MANEUVER_TIER_BASIC,),
    ) -> discord.File:
        """
        The cards a coach may play, wrapped fresh each time: uploading a
        `discord.File` consumes the stream inside it, so the bytes are
        what is kept and the file is built per send -- the same reason
        `render_match_png` returns bytes rather than a File.
        """
        return discord.File(
            io.BytesIO(self.maneuver_hand_image_bytes[(side, tuple(tiers))]),
            filename=f"maneuver_hand_{side}.png",
        )


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

        Two ways to get here and they read differently, so the message
        asks the state which one it was rather than taking a flag:
        anyone still eligible means the defense was offered the
        challenge and sent nobody, since a defense with somebody to
        send is the only defense that gets the choice. Since 2026-08-16
        that is practically always the answer -- the other branch needs
        a side with nobody on the field.
        """
        handler = self.engine.get_player_definition(match.active_player_id)
        defense_setup = match.setup_for_side(match.defending_side())

        if match.eligible_challengers():
            reason = "have sent nobody in to challenge"
        else:
            reason = "have nobody left to challenge"

        await interaction.followup.send(
            f"**Unchallenged!** {format_team_side_label(defense_setup)} "
            f"{reason} "
            f"{format_role_bracket(handler, self.team_emojis, match.team_for_player(handler.player_id))}, "
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
            ai_strategy = self.engine.get_ai_strategy(game)
            # A tutorial beat names the card Dinky plays, and it is
            # written straight into the match here rather than through
            # the strategy: `choose_maneuver_action` takes a side and
            # nothing else, so it has no way to know which beat is
            # running, and changing its signature for one caller would
            # put the script inside the AI. Dinky's pick is made before
            # the coach's exactly as it always is -- the rails decide
            # what the coach may answer with, not the other way round.
            beat = self.tutorial_beat(game)

            if self.engine.possession_player_number(game, match) == 2:
                scripted = beat.dinky_maneuver_for("offense") if beat else None
                match.choose_offense_maneuver(
                    scripted
                    or ai_strategy.choose_maneuver_action(
                        "offense",
                        self.engine.maneuver_hand(game, match, "offense"),
                    )
                )
            if (
                not match.maneuver_uncontested
                and self.engine.defending_player_number(game, match) == 2
            ):
                scripted = beat.dinky_maneuver_for("defense") if beat else None
                match.choose_defense_maneuver(
                    scripted
                    or ai_strategy.choose_maneuver_action(
                        "defense",
                        self.engine.maneuver_hand(game, match, "defense"),
                    )
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
                    self.engine.possession_player_number(game, match),
                    mention=True,
                )
            )
        if not match.maneuver_uncontested and match.defense_maneuver is None:
            waiting_on.append(
                format_player_with_team(
                    game,
                    self.engine.defending_player_number(game, match),
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
        # The cards are what this beat is about, so its note goes in
        # front of the menu rather than with the lesson two messages
        # up: by the time a coach opens their hand they have watched a
        # challenger walk in and are looking at three buttons, which is
        # the moment the explanation is worth reading.
        tutorial_beat = self.tutorial_beat(game)
        if tutorial_beat is not None:
            await interaction.followup.send(tutorial_beat.maneuver_note)

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
        # Keys are what the match holds and what everything below
        # dispatches on; the names are only ever printed.
        offense_key = match.offense_maneuver
        defense_key = match.defense_maneuver
        offense_name = self.engine.maneuver_name(offense_key)
        defense_name = self.engine.maneuver_name(defense_key)
        offense_number = self.engine.possession_player_number(game, match)
        defense_number = self.engine.defending_player_number(game, match)
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
                interaction, game, match, offense_key,
            )
            return

        reveal = (
            f"{offense_display} chose **{offense_name}**.\n"
            f"{defense_display} chose **{defense_name}**."
        )

        # Who wins is settled_maneuver_winner's alone to say; what is
        # decided here is only how the four ways it can land are
        # worded. `outcome` is the ranking on its own, which is what
        # separates a win on the cards from a win handed over by the
        # other player's injury.
        outcome = self.maneuver_catalog.resolve(offense_key, defense_key)
        winner_key = self.engine.settled_maneuver_winner(match)
        winner_name = self.engine.maneuver_name(winner_key)
        defense_injured = match.challenger_id in match.injured

        if winner_key is not None:
            if outcome == "tie":
                # A tie with exactly one injured participant: they lose
                # it outright. Nothing is rolled, so neither side pays
                # the token a skill test would have cost them.
                injured_player = self.engine.get_player_definition(
                    match.challenger_id
                    if defense_injured
                    else match.active_player_id
                )
                await interaction.followup.send(
                    f"{reveal}\n\n"
                    f"**{offense_name}** ties with **{defense_name}**, but "
                    f"{format_role_bracket(injured_player, self.team_emojis, match.team_for_player(injured_player.player_id))}"
                    " is **injured** "
                    f"{get_injured_emoji(self.condition_emojis)} and "
                    "automatically loses the tie.\n\n"
                    f"## **{winner_name}** wins!"
                )
            else:
                # Headed the same way a won skill test is (see
                # SkillTestView.roll), so the two ways a maneuver can be
                # won read alike. Whoever resolves the effect isn't named
                # here: an effect with a choice in it prompts them by name
                # itself, and one without needs nobody to do anything.
                await interaction.followup.send(
                    f"{reveal}\n\n## **{winner_name}** wins!"
                )
            await self.begin_effect_resolution(
                interaction, game, match, winner_key,
            )
            return

        if outcome == "tie":
            # An ordinary tie -- both or neither participant is injured.
            headline = (
                f"{reveal}\n\n"
                f"**{offense_name}** ties with **{defense_name}** — skill "
                "test!\n\n"
            )
        else:
            # An injured player's maneuver never wins outright -- they
            # still have to win a skill test to make it stick.
            would_be_winner = (
                offense_name if outcome == "offense" else defense_name
            )
            injured_player = self.engine.get_player_definition(
                match.active_player_id
                if outcome == "offense"
                else match.challenger_id
            )
            headline = (
                f"{reveal}\n\n"
                f"**{would_be_winner}** would win, but "
                f"{format_role_bracket(injured_player, self.team_emojis, match.team_for_player(injured_player.player_id))} is "
                f"**injured** {get_injured_emoji(self.condition_emojis)} -- "
                "a skill test decides it instead!\n\n"
            )

        exhaustion_text = (
            self.apply_exhaustion(match, match.active_player_id, 1)
            + "\n"
            + self.apply_exhaustion(match, match.challenger_id, 1)
        )
        game.match_state = match.to_dict()
        save_games(self.games)

        offense_player = self.engine.get_player_definition(match.active_player_id)
        defense_player = self.engine.get_player_definition(match.challenger_id)
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
            f"{headline}"
            f"{format_role_bracket(offense_player, self.team_emojis, match.team_for_player(offense_player.player_id))}: offense skill "
            f"{offense_skill}\n"
            f"{format_role_bracket(defense_player, self.team_emojis, match.team_for_player(defense_player.player_id))}: defense skill "
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

    async def begin_injury_tests(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        players: list[PlayerDefinition],
        resume: dict,
    ) -> None:
        """
        Hand the injury tests a resolved contest owes to the coaches,
        one button each, and remember what the contest was going to do
        next.

        **A contest cannot simply carry on into its effect any more**:
        the tests are now clicks, and the last of them may be several
        minutes after the roll that owed them. `resume` is that
        continuation, persisted with the queue because a restart in
        between has nothing else to reconstruct it from -- the skill
        test's winner is not derivable once the roll has happened
        (`settled_maneuver_winner` answers None while a test is owed),
        and a loose ball's distance is gone with the state that
        cleared it. `dispatch_injury_resume` is the other half.

        A player already injured owes nothing, so the queue is
        filtered here rather than refused at the prompt -- an injured
        player gains no exhaustion tokens and can never be asked
        again.
        """
        owed = [
            player.player_id
            for player in players
            if player.player_id not in match.injured
        ]
        if not owed:
            # Nothing owed is the common case, and it writes nothing:
            # the contest carries straight on into its continuation,
            # exactly as it did before the tests became clicks.
            await self.dispatch_injury_resume(interaction, game, match, resume)
            return

        match.pending_injury_tests = owed
        match.pending_injury_resume = resume
        game.match_state = match.to_dict()
        save_games(self.games)

        await self.continue_injury_tests(interaction, game, match)

    async def continue_injury_tests(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Ask for the next injury test still owed, or -- when there are
        none left -- do what the contest that owed them was going to
        do. The one exit from the queue, so a test that is rolled and
        a test that turns out not to be owed leave by the same door.
        """
        while match.pending_injury_tests:
            player_id = match.pending_injury_tests[0]
            if player_id in match.injured:
                # Injured since the queue was built -- by the other
                # participant's test, which cannot happen today, but a
                # player who cannot be injured twice should never be
                # asked to roll for it.
                match.pending_injury_tests.pop(0)
                continue

            player = self.engine.get_player_definition(player_id)
            controller_id = self.engine.controlling_user_id(game, match, player_id)
            mention = f"<@{controller_id}>" if controller_id else "Someone"
            tokens = match.exhaustion.get(player_id, 0)
            prompt_message = await interaction.followup.send(
                f"{mention}, "
                f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} is "
                "exhausted and owes an injury test: a d12 that has to "
                f"beat their {tokens} exhaustion "
                f"{'token' if tokens == 1 else 'tokens'}.",
                view=InjuryTestView(self, game.game_id, player_id),
                wait=True,
                allowed_mentions=discord.AllowedMentions(
                    users=True, roles=False, everyone=False,
                ),
            )
            game.turn_message_id = prompt_message.id
            game.match_state = match.to_dict()
            save_games(self.games)
            return

        resume = match.pending_injury_resume
        match.pending_injury_resume = None
        game.match_state = match.to_dict()
        save_games(self.games)

        await self.dispatch_injury_resume(interaction, game, match, resume)

    async def dispatch_injury_resume(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        resume: Optional[dict],
    ) -> None:
        """
        Pick the turn back up where the injury tests interrupted it.
        The kinds are the contests that hand them out: a maneuver's
        skill test goes on to the winner's effect, a loose ball (or
        the long High Pass that borrows its machinery) goes on to its
        run back, and a shootout skill test goes on to the next one --
        or to the end of the game.
        """
        kind = (resume or {}).get("kind")
        if kind == "shootout_test":
            # Nothing writes this any more -- a shootout test stopped
            # owing injury checks on 2026-08-15 and goes straight to
            # `continue_shootout` itself. It is still read, because a
            # game saved between that roll and its tests outlives the
            # change: the same reason `TeamSetup.from_dict` still
            # answers to `player_board`. It dies out on its own.
            await self.continue_shootout(interaction, game, match)
            return
        if kind == "maneuver_effect":
            # `winner_name` is what this carried before maneuvers had
            # keys, and a game saved mid-injury-test outlives the
            # change -- so the old spelling is still read and never
            # written. Same tolerance as `legacy_maneuver_key`.
            await self.begin_effect_resolution(
                interaction,
                game,
                match,
                resume.get("winner_key")
                or legacy_maneuver_key(resume.get("winner_name")),
            )
            return
        if kind == "run_back":
            await self.begin_run_back(
                interaction,
                game,
                match,
                distance_moved=resume.get("distance_moved", 1),
                turnover_occurred=resume.get("turnover_occurred", True),
            )
            return
        LOGGER.error(
            "Game %s finished its injury tests with nothing to resume "
            "(%r); it needs /d12ball resume.",
            game.game_id,
            resume,
        )

    async def run_injury_test(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        player: PlayerDefinition,
    ) -> None:
        """
        One injury test, off the button `continue_injury_tests` posted
        for it: roll a d12, and if it doesn't beat the player's current
        exhaustion token count, they become injured.

        Exhausted is judged when the contest resolves, not when it
        started, and against every token they hold by then -- the one
        each participant pays to enter the test and one more each time
        a tie sends it back to be rolled again, all of which count. A
        player the test itself pushed over their defensive skill rolls
        this check for that same test.
        """
        if player.player_id in match.injured:
            # Nothing to roll, and nothing to announce either -- an
            # injured player cannot be injured again. Back to the queue
            # rather than out of it, so this can never be where a turn
            # stops.
            if player.player_id in match.pending_injury_tests:
                match.pending_injury_tests.remove(player.player_id)
                game.match_state = match.to_dict()
                save_games(self.games)
            await self.continue_injury_tests(interaction, game, match)
            return

        # The script fixes injury checks to pass for the whole
        # tutorial -- see BLANKET_ROLLS. The check still runs and the
        # coach still watches it.
        scripted = self.tutorial_dice(game, "injury", 1)
        roll = scripted[0] if scripted else random.randint(1, 12)
        current_tokens = match.exhaustion.get(player.player_id, 0)
        safe = roll > current_tokens
        player_team = match.team_for_player(player.player_id)
        dice_file = discord.File(
            await asyncio.to_thread(
                render_injury_test_die,
                roll,
                TEAM_COLORS[player_team],
                team_display_name(player_team),
                player.name,
                safe,
            ),
            filename="injury_test_die.png",
        )

        if player.player_id in match.pending_injury_tests:
            match.pending_injury_tests.remove(player.player_id)

        if safe:
            game.match_state = match.to_dict()
            save_games(self.games)

            content = (
                f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} is exhausted and rolls "
                f"an injury test: {roll} beats their {current_tokens} "
                "exhaustion tokens — safe."
            )
        else:
            match.mark_injured(player.player_id)
            game.match_state = match.to_dict()
            save_games(self.games)

            content = (
                f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} is exhausted and rolls "
                f"an injury test: {roll} does not beat their "
                f"{current_tokens} exhaustion tokens — injury! "
                f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} now has the condition "
                f"**injured** {get_injured_emoji(self.condition_emojis)}. "
                "Their exhaustion "
                "tokens are removed; they are no longer exhausted and "
                "cannot gain more exhaustion tokens or make another "
                "injury check."
            )

        # The prompt becomes the die, and what it says follows in its
        # own message rather than riding above it -- see
        # SkillTestView.roll for why every result is announced this way
        # round.
        await interaction.edit_original_response(
            content=None,
            attachments=[dice_file],
            view=None,
        )
        await interaction.followup.send(content)
        if not safe:
            await self.refresh_match_image(interaction, game)

        await self.continue_injury_tests(interaction, game, match)



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
        maneuver that needs no choice (Deflect, Pressure) or an
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
        # **An effect continuation is read first**, because it says the
        # effect is already past the prompt its winner would restore.
        # Setup Pass's speed choice has been answered by the time one
        # is set, and a beaten Precise Pass's Low Pass belongs to the
        # *defense* -- reading the winner there would put the steal's
        # speed choice back up and let a coach answer it twice. See
        # `continue_effect` for why the field outlives its dispatch.
        continuation = match.pending_effect_continuation or {}
        if continuation.get("kind") == "setup_pass_shot":
            return SetupPassChoiceView(self, game_id)
        if continuation.get("kind") == "free_low_pass":
            return LowPassChoiceView(self, game_id, key="low_pass", free=True)

        winner_key = self.engine.settled_maneuver_winner(match)
        if winner_key is None:
            # Still owed a skill test, so no effect is pending yet.
            return None
        # A tie a skill test settled resolves as the basic card, so the
        # prompt restored has to be that card's -- see
        # `RulesEngine.resolving_maneuver`.
        winner_key = self.engine.resolving_maneuver(match, winner_key)
        if winner_key in ("low_pass", "precise_pass"):
            return LowPassChoiceView(self, game_id, key=winner_key)
        if winner_key == "high_pass":
            return HighPassChoiceView(self, game_id)
        if winner_key == "setup_pass":
            return SpeedDeltaChoiceView(
                self, game_id, match.active_player_id, "offense",
            )
        if winner_key in ("dribble_advance", "dribble_burst"):
            handler = self.engine.get_player_definition(match.active_player_id)
            if winner_key == "dribble_advance" and (
                handler.role == PlayerRole.PLAYMAKER
            ):
                return DribbleAdvanceChoiceView(self, game_id)
            return SpeedDeltaChoiceView(
                self, game_id, match.active_player_id, "offense",
            )
        if winner_key in ("steal", "intercept"):
            return SpeedDeltaChoiceView(
                self, game_id, match.challenger_id, "defense",
            )
        return None

    def restore_maneuver_menus(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> int:
        """
        Bring an open maneuver menu back to life after a restart, and
        say how many were registered.

        **The maneuver pick is the one ephemeral view in the game**,
        and it has to be: a coach must not see the other side's choice
        before the reveal, and ephemeral is the only thing Discord
        offers that hides it. It is also therefore the one view that
        cannot be re-attached the ordinary way -- the bot never holds a
        durable handle to an ephemeral message, so there is no id to
        give `add_view`.

        `add_view` **without** a message_id is the way round it.
        discord.py looks a component interaction up by
        `(message_id, custom_id)` and then falls back to
        `(None, custom_id)`, so a view registered this way is
        dispatched for any message carrying its custom_ids -- the
        coach's already-open ephemeral menu included. Verified against
        `ViewStore.dispatch_view`; the fallback is deliberate and
        documented there.

        Two things make it safe rather than a scattergun:

        - **The custom_ids already carry the game and the side**
          (`d12ball:maneuver_pick:<game>:<side>:<maneuver>`), so
          nothing can be dispatched into the wrong game.
        - **A message_id match wins over the fallback**, so the next
          menu this game opens is dispatched to its own view as usual.
          This one only ever catches clicks nothing else claims.

        The registration outlives the maneuver -- there is no message
        to hang its removal on either -- but a stale click costs
        nothing: `pick` re-reads the match and answers "a maneuver has
        already been chosen for that side."
        """
        sides = []
        if match.offense_maneuver is None:
            sides.append("offense")
        if match.defense_maneuver is None and not match.maneuver_uncontested:
            sides.append("defense")

        for side in sides:
            # timeout=None because add_view refuses anything else: a
            # view it cannot see the message for has nothing to time
            # out against.
            self.bot.add_view(
                ManeuverActionSelectView(
                    self, game.game_id, side, timeout=None,
                ),
            )

        return len(sides)

    def restore_shootout_menus(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> int:
        """
        Bring an open shootout menu back to life after a restart, the
        way `restore_maneuver_menus` does for the maneuver pick, and
        for the same reason: a coach's shooting order and their
        sudden-death shooter are secret, so both menus are ephemeral
        and neither has a message id to re-attach to. `add_view`
        without one registers against `(None, custom_id)`, which is
        what the coach's already-open menu is dispatched by.

        The custom_ids carry the game and the side, so nothing can
        reach the wrong game, and a message_id match still wins -- the
        next menu the shootout opens is dispatched to its own view as
        usual. A stale click is answered rather than acted on: an
        order that is already set refuses to be reordered, and a pick
        that has already been made says so.

        Only the side that still owes something is registered, so a
        coach who has already answered has nothing left listening.
        """
        registered = 0
        for side in (TeamSide.HOME, TeamSide.VISITING):
            if self.engine.side_is_ai(game, side):
                continue
            if not match.shootout_orders_complete:
                if match.shootout_order_complete(side):
                    continue
                view = ShootoutOrderSelectView(
                    self, game.game_id, side, timeout=None,
                )
            elif match.shootout_shooter(side) is None:
                view = ShootoutPickSelectView(
                    self, game.game_id, side, timeout=None,
                )
            else:
                continue

            # timeout=None because add_view refuses anything else: a
            # view it cannot see the message for has nothing to time
            # out against.
            self.bot.add_view(view)
            registered += 1

        return registered

    def pending_turn_view(
        self,
        game_id: str,
        match: MatchState,
    ) -> tuple[discord.ui.View, str]:
        """
        The prompt a saved match still owes: the view to put in front
        of whoever it is waiting on, and a line asking for it.

        **This is the only reading of "what is this match waiting
        on?", and it has two callers that must not drift apart.**
        Startup re-attaches the view to the message the prompt was
        already posted on (`turn_message_id`); `/d12ball resume` posts
        a fresh message carrying the same one, for the games where
        that message is gone, was never recorded, or was left with
        nothing live on it. A second copy of this branch chain is how
        a resume ends up offering a different prompt from the one a
        restart restores.

        Ordering matters more than it looks:

        - Setup and halftime come first because both leave
          `active_player_id` None, and the "no ball handler yet"
          branch would otherwise misread either as the kickoff.
        - `challenger_id` (or `maneuver_uncontested`) is what says a
          maneuver is under way, not `pending_action`, which
          `choose_challenger` clears the moment a challenger is
          picked.
        - An owed injury test and an owed own-goal roll come next,
          ahead of everything else, because both are interruptions of
          a turn whose own state is still set underneath them and
          would otherwise answer first.

        The three `or PlayerActionView` fallbacks are states whose
        next step is the bot's, not a coach's -- a run back with only
        forced placements left, an effect with no choice in it. There
        is no button to restore for those, so startup falls back to
        the turn prompt; `resume_pending_prompt` re-drives the
        pipeline instead, which is the difference between the two
        callers and the reason this returns a view rather than doing
        the posting itself.
        """
        if match.pending_setup_stage is not None:
            # Before kickoff, so active_player_id is None and the "no
            # ball handler yet" branch below would otherwise misread
            # this as the kickoff prompt -- the same reason halftime is
            # checked ahead of it.
            return (
                CoachingHubView(self, game_id),
                "Coaching Choice, before kickoff:",
            )

        if match.pending_full_time_stage is not None:
            # Between the whistle and the shootout, so the turn is
            # already reset and every branch below would misread it.
            # Always the hub: the window is given rather than declared,
            # so there is no offer to come back to.
            return (
                CoachingHubView(self, game_id),
                "Coaching Choice, before the shootout:",
            )

        if match.pending_halftime_stage is not None:
            # Halftime resets active_player_id before its own stages
            # run, so it has to be checked ahead of the "no ball
            # handler yet" branch below, which would otherwise misread
            # halftime as kickoff.
            stage = self.engine.halftime_stage(match)
            if stage in ("extra_token_home", "extra_token_visiting"):
                side = (
                    TeamSide.HOME
                    if stage == "extra_token_home"
                    else TeamSide.VISITING
                )
                return (
                    HalftimeExtraTokenView(self, game_id, side),
                    "Halftime: choose a player to lose an extra "
                    "exhaustion token.",
                )
            # coaching_home / coaching_visiting. Always the hub:
            # halftime never asks whether to declare, so there is no
            # offer to come back to, unlike an ordinary turnover's
            # window below. A part-made pick inside the flow is not
            # persisted and restarts here, the same simplification a
            # run-back choice makes.
            return (
                CoachingHubView(self, game_id),
                "Halftime Coaching Choice:",
            )

        if match.pending_injury_tests:
            # Ahead of everything a contest leaves set, because that is
            # all still set: a maneuver's skill test comes back here
            # with its challenger and both picks in place, and a loose
            # ball with no active player at all, which the kickoff
            # branch below would misread.
            player = self.engine.get_player_definition(match.pending_injury_tests[0])
            return (
                InjuryTestView(self, game_id, player.player_id),
                f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} still "
                "owes an injury test:",
            )

        if match.pending_own_goal:
            # Same reason: the Pressure that risked it is still the
            # live maneuver, so the effect branch would otherwise offer
            # to resolve it a second time.
            return (
                OwnGoalRollView(self, game_id),
                "Either player can roll for the own goal.",
            )

        if match.pending_shootout:
            # The three shootout states, read off the same three
            # questions `advance_shootout` asks and in the same order.
            # It comes after the injury queue because a shootout skill
            # test owes its checks before the next one is set up, and
            # ahead of everything below because the match underneath a
            # shootout is still whatever full time left there.
            if not match.shootout_orders_complete:
                return (
                    ShootoutOrderPromptView(self, game_id),
                    "Extreme shootout — set your shooting order:",
                )
            if not match.shootout_shooters_complete:
                return (
                    ShootoutPickPromptView(self, game_id),
                    "Extreme shootout — choose who shoots next:",
                )
            return (
                ShootoutTestView(self, game_id),
                "Either player can roll the shootout skill test:",
            )

        if match.pending_cede:
            # A ceded ball resets the turn before either window opens,
            # so active_player_id is None and the kickoff branch below
            # would misread it -- the same reason setup and halftime
            # are checked ahead of that one. Always the hub: ceding is
            # what bought the window, so neither coach is ever asked
            # whether to take it. With no window open the cascade died
            # between the second one closing and the tail behind it,
            # which is resume's to re-drive rather than a click's.
            if match.pending_coaching_side is not None:
                return (
                    CoachingHubView(self, game_id),
                    "Coaching Choice, on the ceded ball:",
                )
            return (
                PlayerActionView(self, game_id),
                "Settle the ceded ball:",
            )

        if match.active_player_id is None:
            return (
                BallHandlerSelectionView(self, game_id),
                "Choose who takes the ball:",
            )

        if match.pending_coaching_side is not None:
            # A window mid-flight comes back as either the offer or the
            # menu. A part-made choice (picked who goes off, not yet
            # who comes on) is not persisted and restarts at the menu,
            # the same way a run-back choice does.
            if match.pending_coaching_declared:
                return (
                    CoachingHubView(self, game_id),
                    "Coaching Choice:",
                )
            return (
                CoachingOfferView(self, game_id),
                "Coaching Choice — coach, or pass?",
            )

        if match.pending_run_back:
            step = self.engine.next_run_back_step(match)
            return (
                self.build_run_back_view(game_id, match)
                or PlayerActionView(self, game_id),
                "Choose which of your doubled-up players runs back:"
                if step is not None and len(step[1]) > 1
                else "Choose where the next player runs back to:",
            )

        if match.pending_ball_recovery:
            # An out-of-bounds ball whose run back has already
            # finished, waiting on the winning side to send someone to
            # pick it up.
            return (
                BallRecoveryView(self, game_id),
                "Send the nearest player either side of the ball to "
                "pick it up at "
                f"{space_label(match.ball.zone, match.ball.space_index)}:",
            )

        if match.pending_loose_ball:
            if (
                match.loose_ball_offense_player is not None
                and match.loose_ball_defense_player is not None
            ):
                return (
                    LooseBallSkillTestView(self, game_id),
                    "Either player can roll for the loose ball:",
                )
            return (
                self.build_loose_ball_view(game_id, match)
                or PlayerActionView(self, game_id),
                "Choose who goes after the loose ball:",
            )

        if match.pending_action == "shoot":
            return (
                ScoreAttemptView(self, game_id),
                "Either player can roll for the score attempt.",
            )

        if match.pending_action == "maneuver" and match.challenger_id is None:
            return (
                ManeuverChallengeView(self, game_id),
                "Choose who challenges the maneuver:",
            )

        if match.challenger_id is not None or match.maneuver_uncontested:
            # challenger_id is only ever set while a maneuver is in
            # progress and cleared by reset_maneuver(), so it alone
            # disambiguates this from any other phase -- pending_action
            # itself is cleared to None by choose_challenger() right
            # when the challenger is picked, so it can't be relied on
            # from here on. maneuver_uncontested says the same thing
            # for a maneuver that never had a challenger, and is
            # cleared by the same reset.
            if not match.maneuver_selections_complete:
                return (
                    ManeuverActionPromptView(self, game_id),
                    "Choose your maneuver:",
                )
            if self.engine.settled_maneuver_winner(match) is None:
                # No winner yet means a skill test is owed -- a tie, or
                # a decisive maneuver an injured player still has to
                # roll for. Asking the ranking directly here would get
                # both wrong.
                return (
                    SkillTestView(self, game_id),
                    "Either player can roll:",
                )
            return (
                self.build_effect_choice_view(game_id, match)
                or PlayerActionView(self, game_id),
                "Resolve the maneuver:",
            )

        return (
            PlayerActionView(self, game_id),
            "Choose an action:",
        )

    def build_run_back_view(
        self,
        game_id: str,
        match: MatchState,
    ) -> Optional[discord.ui.View]:
        """
        Reconstruct the run-back prompt for whichever player still
        needs a real choice. Any forced placements are always applied
        immediately in continue_run_back, before a message is ever
        posted, so anything still outstanding by the time this is
        called is an actual choice.

        Which of the two prompts it is is read back off the position,
        exactly as the cascade reads it: a stack with more than one
        player to spare comes back as the question of who runs, and
        everything else as the question of where. A coach who had
        already answered the first when the bot went down is asked it
        again -- that pick lives on the view and nowhere else, the
        same as a part-made coaching choice.
        """
        step = self.engine.next_run_back_step(match)
        if step is None:
            return None
        _, candidates = step
        if len(candidates) == 1:
            return RunBackChoiceView(self, game_id, candidates[0])
        return RunBackPlayerChoiceView(self, game_id, candidates)

    async def begin_effect_resolution(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        winner_key: str,
    ) -> None:
        """
        Dispatch a decisively-won maneuver to its effect, by **key**.
        `offense_maneuver`/`defense_maneuver`/`active_player_id`/
        `challenger_id` all stay set until the whole pipeline (effect,
        any run-back, time) finishes -- reset_maneuver() only happens
        at the very end, in finish_maneuver_resolution -- so a bot
        restart mid-choice can still reconstruct exactly where things
        left off (see build_effect_choice_view).
        """
        handlers = {
            "low_pass": self.resolve_low_pass,
            "dribble_advance": self.resolve_dribble_advance,
            "high_pass": self.resolve_high_pass,
            "deflect": self.resolve_deflect,
            "steal": self.resolve_steal,
            "pressure": self.resolve_pressure,
            "precise_pass": self.resolve_precise_pass,
            "dribble_burst": self.resolve_dribble_burst,
            "setup_pass": self.resolve_setup_pass,
            "clear": self.resolve_clear,
            "intercept": self.resolve_intercept,
            "double_team": self.resolve_double_team,
        }
        # **A tie settled by a skill test resolves as the basic card.**
        # An advanced effect follows the cards, so a winner that only
        # won on the dice runs its counterpart's effect and the loser
        # pays nothing -- see `RulesEngine.advanced_effects_apply`.
        # Substituting the key here rather than branching inside six
        # handlers is what keeps that one rule in one place.
        handler = handlers.get(
            self.engine.resolving_maneuver(match, winner_key)
        )
        if handler is None:
            # Unrecognized maneuver name (future data) -- nothing to
            # automate; leave it to a human, same as before this pass.
            await self.finish_maneuver_resolution(interaction, game, match)
            return
        await handler(interaction, game, match)

    # -- Low Pass --------------------------------------------------



    async def resolve_precise_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Precise Pass is a Low Pass with the reach taken off and the
        speed bonus tripled: **any** teammate on the board rather than
        the nearest each way within two, and +3 instead of +1. Every
        other thing about it -- the receiver pick out of a stack, the
        passer's step forward across a shared space, the Winger's
        set-up -- is a Low Pass's, which is why the two share one
        function.
        """
        await self.resolve_low_pass(
            interaction, game, match, key="precise_pass",
        )

    async def resolve_low_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        key: str = "low_pass",
        free: bool = False,
    ) -> None:
        """
        `free` marks the unopposed Low Pass **Precise Pass's cost**
        hands the defense: it is not this side's maneuver, so it
        charges no further clock and cannot be a Precise Pass.
        """
        candidates = self.engine.pass_candidates(match, key)

        if not candidates:
            # A Low Pass has to reach a different player, so a handler
            # with no teammate within two spaces has won the maneuver
            # and has nowhere to put the ball. The ball goes a space
            # forward and is loose, and its speed still rises by 1
            # (2026-08-07) -- the maneuver's speed bonus doesn't depend
            # on the pass finding anyone.
            offense_side = match.ball.possession
            actual_distance = match.move_ball_relative(offense_side, 1)
            match.ball.speed = min(
                12, match.ball.speed + self.engine.pass_speed_bonus(key)
            )
            game.match_state = match.to_dict()
            save_games(self.games)

            # Nothing to move onto at the far end of the field: the
            # ball is loose where it already is.
            movement_note = (
                "the ball rolls a space forward"
                if actual_distance
                else "the ball stays where it is"
            )
            # No refresh here: begin_loose_ball draws this same board
            # under its own announcement and brings the persistent
            # message in line with it, so one here would be a second
            # write of an identical board (see "Discord's rate limits"
            # in CLAUDE.md).
            await self.begin_loose_ball(
                interaction,
                game,
                match,
                distance_moved=1,
                lead_in=(
                    f"**{self.engine.maneuver_name(key)}:** there is "
                    + (
                        "nobody on the field to receive it"
                        if key == "precise_pass"
                        else "no teammate within two spaces to receive it"
                    )
                    + ", and a pass can't be played to the passer -- "
                    f"{movement_note}. "
                    f"Ball speed is now {match.ball.speed}."
                ),
                headline=(
                    "**Loose ball!** Nobody is there to collect the "
                    "pass -- each side may send a nearby player to "
                    "contest it."
                ),
            )
            return

        if self.engine.side_controlled_by_ai(game, match, "offense"):
            strategy = self.engine.get_ai_strategy(game)
            distance = strategy.choose_low_pass(match, candidates)
            await self.apply_low_pass(
                interaction,
                game,
                match,
                distance,
                receiver_id=strategy.choose_low_pass_receiver(
                    match, self.engine.low_pass_receivers(match, distance),
                ),
                key=key,
                free=free,
            )
            return

        mention = format_player_with_team(
            game,
            self.engine.possession_player_number(game, match),
            mention=True,
        )
        prompt_message = await interaction.followup.send(
            f"{mention}, choose your "
            f"{self.engine.maneuver_name(key)}:",
            view=LowPassChoiceView(self, game.game_id, key=key, free=free),
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
        key: str = "low_pass",
        free: bool = False,
    ) -> None:
        name = self.engine.maneuver_name(key)
        # A pass granted by Precise Pass's cost is a continuation, and
        # applying it is what spends it -- see `continue_effect`.
        if free:
            match.pending_effect_continuation = None
        offense_side = match.ball.possession
        handler = self.engine.get_player_definition(match.active_player_id)
        # Read before the ball moves, because the receivers are
        # relative to where it is now. `receiver_id` is who the passer
        # picked out of a shared space; without one -- a single
        # occupant, so nothing was asked -- it is whoever is standing
        # there. Either way this is the player the pass was aimed at,
        # which is not always the same as whoever the landing space's
        # occupant list happens to start with -- see the Winger branch
        # below.
        receivers = self.engine.low_pass_receivers(match, distance)
        if receiver_id not in receivers:
            receiver_id = receivers[0] if receivers else None

        # Read before the ball moves too, and for the same reason a
        # won Double Team reads it before the push: "the closest
        # teammate" is measured from where the play started, which is
        # where the ball is standing right now. See
        # `pay_double_team_cost`.
        double_team_partner = (
            self.engine.double_team_partner(match)
            if self.engine.advanced_cost(match, key) == "double_team"
            else None
        )

        actual_distance = match.move_ball_relative(offense_side, distance)
        match.ball.speed = min(
            12, match.ball.speed + self.engine.pass_speed_bonus(key)
        )
        # A pass across a shared space sends the passer a space forward
        # (2026-08-07) -- the ball hasn't gone anywhere, so this is what
        # the maneuver buys. Clamped at the far end of the field, where
        # there is nowhere to run to.
        passer_advance = (
            match.move_player_relative(match.active_player_id, offense_side, 1)
            if distance == 0
            else 0
        )
        # The pass was aimed at somebody, and it is the same somebody a
        # Winger's set-up would hand the shot to -- so they receive it
        # and take the next turn. `receivers` is empty only when the
        # pass had no legal destination, which rolls the ball forward
        # loose instead of completing; nobody carries a loose ball.
        match.set_ball_carrier(receiver_id)
        game.match_state = match.to_dict()
        save_games(self.games)

        if distance == 0:
            movement_note = "goes to a teammate in the same space"
            if passer_advance:
                movement_note += (
                    f", and {format_role_bracket(handler, self.team_emojis, match.team_for_player(handler.player_id))} "
                    "moves a space forward"
                )
        else:
            direction = "forward" if distance > 0 else "backward"
            space_word = "space" if actual_distance == 1 else "spaces"
            movement_note = f"moves {actual_distance} {space_word} {direction}"
        content = (
            f"**{name}:** the ball {movement_note}. "
            f"Ball speed is now {match.ball.speed}."
        )

        # **Double Team's cost**: beaten by a pass, the defender who
        # played it and the teammate who would have joined them are
        # each shoved a space forward, away from their own goal.
        content += self.pay_double_team_cost(match, key, double_team_partner)
        # Low Pass's own cost is a flat 1 space minute regardless of
        # distance (2026-08-16), the same as every maneuver but High
        # Pass. A pass granted by Precise Pass's cost is not this
        # side's maneuver and charges nothing: the clock was already
        # spent on the steal that produced it.
        distance_moved = 0 if free else 1

        # Role ability -- Winger: the receiving player may attempt a
        # scoring opportunity right where the pass lands, whatever the
        # distance -- unlike High Pass's set-up, this doesn't require
        # reaching the space nearest the goal. It does require shooting
        # range, like any other shot: the ability frees the set-up from
        # a distance, not from where a goal can be scored from.
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
                f"{format_role_bracket(handler, self.team_emojis, match.team_for_player(handler.player_id))}'s Winger "
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
        handler = self.engine.get_player_definition(match.active_player_id)
        if handler.role != PlayerRole.PLAYMAKER:
            await self.apply_dribble_advance(interaction, game, match, 1)
            return

        if self.engine.side_controlled_by_ai(game, match, "offense"):
            distance = self.engine.get_ai_strategy(
                game
            ).choose_dribble_advance_distance(match)
            await self.apply_dribble_advance(
                interaction, game, match, distance
            )
            return

        mention = format_player_with_team(
            game,
            self.engine.possession_player_number(game, match),
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
        # They dribbled it there, so they still have it: the same
        # player takes the next turn rather than the coach choosing
        # again off the space they landed on.
        match.set_ball_carrier(match.active_player_id)
        game.match_state = match.to_dict()
        save_games(self.games)

        handler = self.engine.get_player_definition(match.active_player_id)
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
                f"{format_role_bracket(handler, self.team_emojis, match.team_for_player(handler.player_id))} and the "
                f"ball move forward {actual_distance} {space_word}"
                f"{ability_note}."
                + self.pay_clear_cost(match, "dribble_advance")
            ),
        )

    async def resolve_dribble_burst(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Dribble Burst: the handler carries the ball **all the way to
        the last space of the goal zone they attack**, defenders no
        obstacle, at a token a space -- then manipulates ball speed up
        to their offensive skill, exactly as a Dribble Advance does.

        There is no distance to choose: the run is to the end of the
        field or it is not a Dribble Burst. What it costs is the
        exhaustion, which is the first time a maneuver has charged by
        distance -- every other per-space charge in the game is a walk
        somebody was sent on.

        **The Playmaker pays one token fewer** (the author,
        2026-08-19). Its ability is an extra space on a Dribble
        Advance, which against a run to the end of the field is no
        bonus at all -- there is no distance left to add to. So the
        ability lands on the one thing this card does have that its
        counterpart does not: what the run costs. It is the only role
        ability that reads differently on the two cards of a rank.
        """
        offense_side = match.ball.possession
        handler = self.engine.get_player_definition(match.active_player_id)
        distance = match.spaces_to_attacking_end(
            match.active_player_id, offense_side,
        )

        actual_distance = match.move_player_relative(
            match.active_player_id, offense_side, distance,
        )
        match.set_ball_space(
            *match.board.meeple_position(match.active_player_id)
        )
        match.set_ball_carrier(match.active_player_id)
        playmaker_bonus = handler.role == PlayerRole.PLAYMAKER
        # Floored at 0 rather than allowed to go negative: a burst that
        # moved nowhere costs nothing, and a Playmaker's discount
        # cannot turn a run into a token back.
        tokens = max(0, actual_distance - (1 if playmaker_bonus else 0))
        exhaustion_text = self.apply_exhaustion(
            match, match.active_player_id, tokens,
        )
        game.match_state = match.to_dict()
        save_games(self.games)

        await self.refresh_match_image(interaction, game)

        space_word = "space" if actual_distance == 1 else "spaces"
        handler_label = format_role_bracket(
            handler, self.team_emojis, match.team_for_player(handler.player_id),
        )
        lead_in = (
            f"**Dribble Burst:** {handler_label} bursts "
            f"{actual_distance} {space_word} to the last space of the goal "
            "they attack, past everyone in the way."
        )
        if playmaker_bonus:
            lead_in += " That costs them a token less (Playmaker ability)."
        if exhaustion_text:
            lead_in += f"\n{exhaustion_text}"

        # **Clear's cost**: beaten by a dribble, the defender who
        # played it gains 2 exhaustion. It is a flat 2 rather than 2 on
        # top of a maneuver's own charge, because a maneuver charges
        # none -- only a skill test, a walk, a shot and a run back do.
        lead_in += self.pay_clear_cost(match, "dribble_burst")

        await self.offer_speed_choice(
            interaction,
            game,
            match,
            player_id=match.active_player_id,
            skill_type="offense",
            lead_in=lead_in,
        )

    def pay_double_team_cost(
        self,
        match: MatchState,
        winner_key: str,
        partner_id: Optional[str],
    ) -> str:
        """
        Double Team's cost, charged inside the pass that beat it: the
        defender who played it and the nearest teammate each move a
        space forward, away from their own goal.

        `partner_id` is passed rather than looked up, because by the
        time this runs the pass has already moved the ball and "the
        closest teammate" would be measured from the wrong space -- the
        card means the space the play started from. Its caller reads it
        before the ball moves, the same way a won Double Team does.

        No exhaustion -- nobody chose to go, and every per-space charge
        in the game is for a move somebody was sent on. Empty string
        when Double Team was not the card beaten, which is nearly
        always.
        """
        if self.engine.advanced_cost(match, winner_key) != "double_team":
            return ""
        defense_side = match.defending_side()
        moved = []
        for player_id in (match.challenger_id, partner_id):
            if player_id is None:
                continue
            match.move_player_relative(player_id, defense_side, 1)
            player = self.engine.get_player_definition(player_id)
            moved.append(
                format_role_bracket(
                    player,
                    self.team_emojis,
                    match.team_for_player(player_id),
                )
            )
        if not moved:
            return ""
        return (
            "\n\n**Double Team** was beaten -- "
            + " and ".join(moved)
            + " are each shoved a space forward, away from their own goal."
        )

    def pay_clear_cost(self, match: MatchState, winner_key: str) -> str:
        """
        Clear's cost, charged where it is due -- inside the dribble
        that beat it -- and worded for the message that dribble is
        already sending. Empty string when Clear was not the card
        beaten, which is nearly always.
        """
        if self.engine.advanced_cost(match, winner_key) != "clear":
            return ""
        defender_id = match.challenger_id
        if defender_id is None:
            return ""
        text = self.apply_exhaustion(match, defender_id, 2)
        return f"\n\n**Clear** was beaten -- 2 exhaustion.\n{text}"

    # -- High Pass -----------------------------------------------------



    async def resolve_high_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        # There is nothing to choose when even the shortest pass runs
        # out of field -- 2, 3 and 4 all land on the space closest to
        # the goal, so the pass is an overshoot before anyone picks
        # anything (2026-08-10). The prompt is skipped rather than
        # answered: asking would be putting one answer up three times,
        # and a Fullback's 4 is no less moot than the 2. The distance
        # handed on is the minimum, which is what the clock charges
        # once the clamp has had its say.
        distances = self.engine.high_pass_distance_options(match)
        if not distances:
            await self.apply_high_pass(
                interaction, game, match, MIN_HIGH_PASS_DISTANCE,
            )
            return

        if self.engine.side_controlled_by_ai(game, match, "offense"):
            distance = self.engine.get_ai_strategy(game).choose_high_pass_distance(
                match, distances,
            )
            await self.apply_high_pass(interaction, game, match, distance)
            return

        mention = format_player_with_team(
            game,
            self.engine.possession_player_number(game, match),
            mention=True,
        )
        # The field goes under the distances for the reason it goes
        # under the maneuver cards: how far to throw is a question about
        # where everybody is standing and where the end of the field is,
        # and by this point in a turn the board has scrolled away. It
        # rides on the prompt rather than on a message of its own so the
        # click can take it away again -- see `HighPassChoiceView`.
        prompt_view = HighPassChoiceView(self, game.game_id)
        prompt_message = await interaction.followup.send(
            f"{mention}, choose your High Pass distance:",
            file=await self.build_field_file(game),
            view=prompt_view,
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)
        # With the view handed over, or the edit that adds the link
        # drops the distances the prompt exists for. Webhook route, not
        # the channel's -- see "Discord's rate limits".
        await add_full_image_button(prompt_message, prompt_view)

    async def resolve_setup_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Setup Pass, the advanced High Pass: **adjust ball speed up to
        the passer's offensive skill, and then** set up a scoring
        opportunity at 0, 1 or 3 spaces, with the speed benefit
        counting toward the shot.

        The order is the card's and it is the reason this is two
        prompts rather than one. A speed choice has always been the
        *last* human step of an effect, leading straight into
        `finish_maneuver_resolution`; here it is the first, so what
        comes after it is recorded as an effect continuation and picked
        up by `continue_effect`. A restart between the two comes back
        to whichever prompt is up, and the continuation is persisted so
        the pass is not lost with it.
        """
        match.pending_effect_continuation = {"kind": "setup_pass_shot"}
        game.match_state = match.to_dict()
        save_games(self.games)

        passer = self.engine.get_player_definition(match.active_player_id)
        await self.offer_speed_choice(
            interaction,
            game,
            match,
            player_id=match.active_player_id,
            skill_type="offense",
            distance_moved=SETUP_PASS_CLOCK_COST,
            lead_in=(
                "**Setup Pass:** "
                f"{format_role_bracket(passer, self.team_emojis, match.team_for_player(passer.player_id))} "
                "sets the ball's speed before picking out the pass."
            ),
        )

    async def offer_setup_pass_distance(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The second half of Setup Pass: 0, 1 or 3 spaces, and the
        teammate it reaches takes a scoring opportunity.

        **0 is a teammate sharing the passer's own space**, which
        `high_pass_receiver_candidates` already computes -- it is
        `scoring_opportunity_candidates` less the passer, and the 2026-08-12
        rule that a passer never receives their own pass is what makes
        that the right list. A distance reaching nobody is not offered,
        for the reason `high_pass_distances` does not offer a clamped
        throw: it is a pass with no receiver, and the card is a set-up.
        """
        distances = self.engine.setup_pass_distances(match)

        if not distances:
            # **Setup Pass cannot overshoot**: from a space with no
            # teammate to reach, the pass goes out and the other team
            # gains possession. That is the existing out-of-bounds
            # outcome -- a new play, both sides reset, the gaining side
            # sends somebody to pick it up.
            await self.apply_setup_pass_out(interaction, game, match)
            return

        if self.engine.side_controlled_by_ai(game, match, "offense"):
            await self.apply_setup_pass(
                interaction, game, match, max(distances),
            )
            return

        mention = format_player_with_team(
            game,
            self.engine.possession_player_number(game, match),
            mention=True,
        )
        prompt_view = SetupPassChoiceView(self, game.game_id)
        prompt_message = await interaction.followup.send(
            f"{mention}, choose where your **Setup Pass** lands:",
            file=await self.build_field_file(game),
            view=prompt_view,
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)
        await add_full_image_button(prompt_message, prompt_view)

    async def apply_setup_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance: int,
    ) -> None:
        offense_side = match.ball.possession
        # Applied, so the continuation is spent -- see `continue_effect`
        # for why it survived until now.
        match.pending_effect_continuation = None
        actual_distance = match.move_ball_relative(offense_side, distance)
        receivers = self.engine.high_pass_receiver_candidates(
            match, offense_side,
        )
        if not receivers:
            # The board moved under a stale click -- the pass has
            # nobody to reach, which is the same "goes out" outcome the
            # menu would have refused to offer.
            await self.apply_setup_pass_out(interaction, game, match)
            return

        receiver_id = receivers[0]
        match.set_ball_carrier(receiver_id)
        game.match_state = match.to_dict()
        save_games(self.games)

        receiver = self.engine.get_player_definition(receiver_id)
        space_word = "space" if actual_distance == 1 else "spaces"
        movement = (
            "goes to a teammate in the same space"
            if distance == 0
            else f"moves {actual_distance} {space_word} forward"
        )
        await self.refresh_match_image(interaction, game)
        await self.offer_scoring_attempt_choice(
            interaction,
            game,
            match,
            shooter_id=receiver_id,
            distance_moved=SETUP_PASS_CLOCK_COST,
            lead_in=(
                f"**Setup Pass:** the ball {movement} to "
                f"{format_role_bracket(receiver, self.team_emojis, match.team_for_player(receiver.player_id))} "
                f"-- a scoring opportunity! Ball speed is {match.ball.speed}."
            ),
        )

    async def apply_setup_pass_out(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        **Setup Pass cannot overshoot.** With no teammate at 0, 1 or 3
        the pass runs out of play and the other team gains possession:
        a new play, both sides reset, and the gaining side sends the
        nearest player to fetch the ball -- the out-of-bounds outcome
        the game already has.

        That makes this a **fourth** `new_play=True` call site, where
        the other three are the score attempt, a conceded own goal and
        the out-of-bounds loose ball. It is one for the same reason
        those are: the ball went dead rather than being taken off
        anybody.
        """
        match.pending_effect_continuation = None
        match.ball.possession = match.defending_side()
        match.ball.speed = 1
        match.clear_ball_carrier()
        match.pending_ball_recovery = True
        game.match_state = match.to_dict()
        save_games(self.games)

        gaining = match.setup_for_side(match.ball.possession)
        await self.begin_run_back(
            interaction,
            game,
            match,
            new_play=True,
            distance_moved=SETUP_PASS_CLOCK_COST,
            lead_in=(
                "**Setup Pass:** there is nobody to pick the ball out to, "
                "so it runs out of play. "
                f"{format_team_side_label(gaining)} gain possession."
            ),
        )

    async def apply_high_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance: int,
    ) -> None:
        offense_side = match.ball.possession
        handler = self.engine.get_player_definition(match.active_player_id)
        # Role ability -- Fullback: can choose to pass up to 4 spaces
        # instead of the usual 2-3 max (see HighPassChoiceView).
        fullback_bonus = handler.role == PlayerRole.FULLBACK and distance == 4

        # Overshoot: the pass is clamped short of the distance asked
        # for, i.e. it ran out of field. Read before the ball moves,
        # the same way Deflect reads its own -- and by the same
        # test, so a pass that could not move the ball at all is an
        # overshoot like any other.
        overshot = match.high_pass_overshoots(offense_side, distance)

        actual_distance = match.move_ball_relative(offense_side, distance)
        game.match_state = match.to_dict()
        save_games(self.games)

        # High Pass's own cost is a flat 2 space minutes regardless of
        # distance (2026-08-16) -- the one maneuver that isn't 1. Kept
        # apart from `actual_distance`, which is what the pass actually
        # did and what the result says.
        distance_moved = 2

        ability_note = " (Fullback ability)" if fullback_bonus else ""
        if actual_distance:
            space_word = "space" if actual_distance == 1 else "spaces"
            content = (
                f"**High Pass:** the ball moves {actual_distance} "
                f"{space_word} forward{ability_note}."
            )
        else:
            # Thrown from the final space, so the clamp leaves the ball
            # exactly where it was. Worth saying in words rather than
            # as "moves 0 spaces forward", which reads as a bug -- and
            # a coach sees it now that the passer cannot shoot off it.
            content = (
                "**High Pass:** the ball is thrown up from the last space "
                "and comes straight back down on it."
            )

        # Who this pass reached, read once now the ball has landed and
        # asked by every branch below -- the passer is not among them,
        # whatever the distance. See high_pass_receiver_candidates.
        receiver_candidates = self.engine.high_pass_receiver_candidates(
            match, offense_side,
        )

        # An overshoot sets up a scoring opportunity whatever distance
        # was asked for (2026-08-10), on the space closest to the goal
        # -- which is where the clamp has just put the ball. The shot
        # is always legal there, as deep into the offense's own
        # shooting range as the field goes, so no range check: it could
        # never fail here, and a branch that cannot be taken reads as
        # if it could. Checked ahead of the ordinary 2-space set-up
        # below, which it subsumes -- the same shot is offered, but
        # with the modifier the other way round and a contest behind
        # it.
        if overshot and receiver_candidates:
            await self.offer_overshoot_set_up(
                interaction,
                game,
                match,
                shooter_id=receiver_candidates[0],
                distance_moved=distance_moved,
                lead_in=content,
            )
            return
        # Nobody the pass could reach on the landing space leaves
        # nothing to set up, so an overshoot falls through to the
        # ordinary paths below: a loose ball, a clean turnover, or --
        # the case the passer exclusion opened (2026-08-12) -- the
        # passer keeping a ball that never left them.

        # A pass of 2 is received cleanly: no contest at all
        # (2026-08-07), and it may set up a scoring opportunity for
        # whoever it lands on -- unlike the old fixed-2 High Pass,
        # this no longer requires overshooting the field. A longer
        # pass never offers it, whether or not it happens to overshoot.
        #
        # A set-up's shot is an ordinary score attempt and obeys the
        # same rule about where a shot may be taken from: what the
        # set-up buys is the shot out of turn, not a shot from
        # anywhere. Out of range the pass is still received, which the
        # branch below settles -- the range rule takes away the shot,
        # not the catch.
        setup_candidates = []
        if distance == 2 and match.can_attempt_score(offense_side):
            setup_candidates = receiver_candidates

        if setup_candidates:
            # Received, so the receiver carries it -- set before the
            # set-up is offered, because declining resolves this as an
            # ordinary completed pass and the carrier has to survive
            # that. Taking the shot makes it moot: a goal or a miss is
            # a new play, which clears the carrier.
            match.set_ball_carrier(setup_candidates[0])
            game.match_state = match.to_dict()
            save_games(self.games)
            await self.refresh_match_image(interaction, game)
            await self.offer_scoring_attempt_choice(
                interaction,
                game,
                match,
                shooter_id=setup_candidates[0],
                distance_moved=distance_moved,
                lead_in=f"{content} That reaches a teammate -- a scoring "
                "opportunity!",
            )
            return

        # No scoring-opportunity option (or the requested distance
        # wasn't a 2). If the pass reached nobody, this isn't the High
        # Pass "receiver must win a skill test" contest at all -- it's
        # a plain loose ball, exactly like any other maneuver that
        # overshoots into empty territory.

        # A 2-space pass that found its receiver but not shooting range
        # is just a pass: it was received cleanly, and the only thing
        # the range rule takes away is the shot. Falling through would
        # hand it to the long-pass contest below, which a pass of 2 has
        # never had to win.
        if distance == 2 and receiver_candidates:
            # Caught cleanly, just out of shooting range -- the range
            # rule takes away the shot, not the catch, so the receiver
            # still carries it.
            match.set_ball_carrier(receiver_candidates[0])
            game.match_state = match.to_dict()
            save_games(self.games)
            await self.refresh_match_image(interaction, game)
            await self.finish_maneuver_resolution(
                interaction, game, match, distance_moved=distance_moved,
                lead_in=content,
            )
            return

        if not receiver_candidates:
            # **A passer never receives their own pass, and since
            # 2026-08-24 that is no longer a free ride.** The exclusion
            # above can only bite when the field clamped the throw to 0
            # spaces -- a High Pass moves the ball, not the handler, so
            # that is the only way the passer is still standing where
            # it lands. With nobody else there either, this is a throw
            # with nowhere to go: there was no field left to put it on
            # and no teammate to put it to, so it goes out exactly as a
            # Setup Pass with no legal destination does, rather than
            # quietly staying with the passer. `actual_distance` (not
            # `distance`) is the test, because that's what tells the
            # ball genuinely didn't move from a real empty destination
            # elsewhere on the field -- which stays an ordinary loose
            # ball below.
            if actual_distance == 0:
                await self.apply_high_pass_out(
                    interaction, game, match,
                    distance_moved=distance_moved, lead_in=content,
                )
                return
            await self.refresh_match_image(interaction, game)
            await self.finish_maneuver_resolution(
                interaction, game, match, distance_moved=distance_moved,
                lead_in=content,
            )
            return

        # **Intercept's cost**: beaten by a High Pass, the reception is
        # not contested -- the receiver simply keeps it. It is the one
        # of the six costs that can be inert, and this is the only
        # branch it is not: a pass of 2, an overshoot's set-up and a
        # pass reaching nobody have all already returned above, and
        # none of them had a contest to skip.
        if self.engine.advanced_cost(match, "high_pass") == "intercept":
            match.set_ball_carrier(receiver_candidates[0])
            game.match_state = match.to_dict()
            save_games(self.games)
            receiver = self.engine.get_player_definition(
                receiver_candidates[0]
            )
            await self.refresh_match_image(interaction, game)
            await self.finish_maneuver_resolution(
                interaction, game, match, distance_moved=distance_moved,
                lead_in=(
                    f"{content}\n\n**Intercept** was beaten -- the "
                    "reception is not contested, and "
                    f"{format_role_bracket(receiver, self.team_emojis, match.team_for_player(receiver.player_id))} "
                    "keeps the ball."
                ),
            )
            return

        # A teammate is standing right where the pass landed, and the
        # pass went 3 or more -- a distance of 2 with a teammate there
        # took the set-up branch above, since both branches ask
        # high_pass_receiver_candidates the same question. A long
        # High Pass still forces a skill test to keep the ball, unlike
        # any other maneuver.
        await self.refresh_match_image(interaction, game)
        await self.begin_high_pass_contest(
            interaction, game, match, distance_moved, lead_in=content,
        )

    async def apply_high_pass_out(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int,
        lead_in: str,
    ) -> None:
        """
        A High Pass thrown with nowhere left to put it: the handler is
        already on the space closest to the opponents' goal, and
        nobody shares it with them. That is the one position a High
        Pass can be thrown from without moving the ball at all, so
        there is no field left to overshoot onto and no teammate to
        land beside -- the same dead end Setup Pass reaches whenever
        none of its own distances find anybody (`apply_setup_pass_out`,
        which this mirrors). The other team gains possession, a new
        play, and the gaining side sends the nearest player to fetch
        it -- the out-of-bounds outcome the game already has, rather
        than the passer quietly keeping a ball that never left them.
        """
        match.ball.possession = match.defending_side()
        match.ball.speed = 1
        match.clear_ball_carrier()
        match.pending_ball_recovery = True
        game.match_state = match.to_dict()
        save_games(self.games)

        gaining = match.setup_for_side(match.ball.possession)
        await self.begin_run_back(
            interaction,
            game,
            match,
            new_play=True,
            distance_moved=distance_moved,
            lead_in=(
                f"{lead_in} There is nowhere left to throw it and nobody "
                "to receive it there -- the ball goes out of play. "
                f"{format_team_side_label(gaining)} gain possession."
            ),
        )

    async def offer_overshoot_set_up(
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
        The scoring opportunity a High Pass that ran out of field sets
        up (2026-08-10) -- see "High Pass" in the living rules.

        The pass arrived faster than the receiver could settle it, so
        `pending_high_pass_overshoot` turns the ball speed modifier
        around for everything the overshoot leads to: this shot, and
        the long-pass contest behind it. It is set before either is
        offered, and cleared with the rest of the turn by
        reset_maneuver.

        **The two are one choice, not an offer and a fallback.** An
        overshoot is a shot at a disadvantage or a contest to keep the
        ball, both paying the modifier, so declining always lands in
        the contest -- there is no distance here that resolves as a
        settled pass. A distance of 2 could only overshoot from a
        position where no distance was ever offered (see
        resolve_high_pass), so the ordinary "a pass of 2 is received,
        full stop" rule and this one never meet.
        """
        match.pending_high_pass_overshoot = True
        # Received, so the receiver carries it -- set before the
        # set-up is offered, for the same reason the ordinary 2-space
        # set-up does it: declining can resolve this as a completed
        # pass, and the carrier has to survive that.
        match.set_ball_carrier(shooter_id)
        game.match_state = match.to_dict()
        save_games(self.games)

        penalty = match.ball_speed_modifier()
        speed_note = (
            " The ball comes in too fast to settle -- the ball speed "
            f"modifier counts **against** what follows ({penalty})."
            if penalty
            else ""
        )
        await self.refresh_match_image(interaction, game)
        await self.offer_scoring_attempt_choice(
            interaction,
            game,
            match,
            shooter_id=shooter_id,
            distance_moved=distance_moved,
            contest_on_decline=True,
            lead_in=(
                f"{lead_in} That overshoots the field -- a scoring "
                f"opportunity!{speed_note}"
            ),
        )

    async def begin_high_pass_contest(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int,
        lead_in: str = "",
    ) -> None:
        """
        The long-pass contest: the receiver standing where the pass
        landed still has to win a skill test to keep the ball.

        Since 2026-08-18 this is a loose ball and nothing else -- the
        receiver contests because they are standing on the ball, which
        is the ordinary rule, and so does a defender sharing the space.
        The one thing still peculiar to a High Pass is the ball speed
        modifier, which `is_high_pass` carries. So there is nothing here
        but the flag: the contestants are read off the position by
        loose_ball_candidates, and the passer is struck out of the
        offense's pool by MatchState.loose_ball_occupants.

        Two paths reach it, and callers of both have already found the
        receiver on the landing space: an unclamped pass of 3 or 4, and
        an overshoot whose set-up the coach declined (2026-08-10). The
        second still carries `pending_high_pass_overshoot`, so the
        contest is rolled with the ball speed modifier against the
        receiver rather than for them -- the same sign the declined
        shot would have paid.
        """
        await self.begin_loose_ball(
            interaction,
            game,
            match,
            distance_moved,
            lead_in=lead_in,
            headline=HIGH_PASS_CONTEST_HEADLINE,
            is_high_pass=True,
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
        contest_on_decline: bool = False,
    ) -> None:
        """
        Offer the offense a chance to attempt a scoring-opportunity
        shot instead of letting a maneuver resolve normally -- used by
        a High Pass's 2-space pass, a High Pass that overshoots, and a
        Winger's Low Pass.

        Declining nearly always resolves the maneuver as a normal pass;
        a 2-space High Pass stopped forcing a contest instead on
        2026-08-07. `contest_on_decline` is the one exception: an
        overshoot is a shot or a contest, both at the same
        disadvantage, so declining lands in the contest rather than
        settling the ball (2026-08-10). It is passed rather than
        derived because by the time this runs, an overshot pass and an
        ordinary 2-space one have left the match in the same state.
        """
        if self.engine.side_controlled_by_ai(game, match, "offense"):
            attempt = self.engine.get_ai_strategy(
                game
            ).choose_scoring_opportunity_attempt(match)
            if lead_in:
                await interaction.followup.send(lead_in)
            if attempt:
                await self.start_set_up_shot(
                    interaction, game, match, shooter_id,
                    maneuver_cost=distance_moved,
                )
            else:
                await self.decline_scoring_attempt(
                    interaction, game, match, distance_moved,
                    contest=contest_on_decline,
                )
            return

        shooter = self.engine.get_player_definition(shooter_id)
        prompt_message = await interaction.followup.send(
            f"{lead_in}\n\n"
            f"{format_role_bracket(shooter, self.team_emojis, match.team_for_player(shooter.player_id))} can attempt "
            "the scoring opportunity, or let it go:",
            view=SetUpAttemptChoiceView(
                self, game.game_id, shooter_id, distance_moved,
                contest_on_decline=contest_on_decline,
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
        contest: bool = False,
    ) -> None:
        """
        Let go of a scoring opportunity: the maneuver that offered it
        resolves as it otherwise would have.

        For an overshot High Pass that is the long-pass contest, not a
        settled ball -- the shot and the contest are the two halves of
        one choice. See offer_scoring_attempt_choice.
        """
        if contest:
            await self.begin_high_pass_contest(
                interaction,
                game,
                match,
                distance_moved,
                lead_in="The scoring opportunity is let go -- but the "
                "pass still has to be kept.",
            )
            return
        await self.finish_maneuver_resolution(
            interaction, game, match, distance_moved=distance_moved,
        )



    # -- Loose ball (a pass landing on an empty space) -----------------


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
        the loose ball instead of letting the turn proceed with nobody
        eligible to act -- returns True when it took that detour, so
        the caller stops instead of continuing.

        **There is one detour now, not two.** A ball landing where only
        the *other* side is standing used to be theirs outright: no
        movement, no roll, a clean steal. It is a loose ball like any
        other since 2026-08-18, and the side that lost it may send
        somebody to contest it -- the defender standing there is simply
        a contestant who costs their side nothing. See "The loose ball"
        in docs/living-rules.md.

        A Deflect does not come through here at all: it makes a
        loose ball whoever is standing on the landing space, so its own
        effect calls begin_loose_ball directly rather than answering a
        question whose answer would be "not loose".
        """
        if match.eligible_ball_handlers():
            return False

        await self.begin_loose_ball(
            interaction, game, match, distance_moved, lead_in=lead_in,
        )
        return True






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
        skill_type = self.engine.loose_ball_side_on_the_clock(match)
        if skill_type is None:
            return None
        side = self.engine.loose_ball_prompt_side(match)
        return LooseBallChoiceView(
            self,
            game_id,
            skill_type,
            self.engine.loose_ball_candidates(match, side),
            match,
        )


    async def begin_loose_ball(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int,
        lead_in: str = "",
        headline: Optional[str] = None,
        is_high_pass: bool = False,
        restrict_to_occupants: bool = False,
    ) -> None:
        """
        `distance_moved` (the pass's own clamped travel) is stashed on
        `match` by begin_loose_ball() -- the pick and, if it comes to
        one, the skill test both span later interactions that can't
        see a Python-level parameter from this call, so everything
        downstream reads it back from match state instead.

        `lead_in` is narration from the pass that hasn't been posted
        yet -- it rides along on this function's own first message.

        `headline` overrides the wording, which is otherwise built from
        the position by build_loose_ball_headline -- a loose ball may
        now land on an occupied space, so nothing may assume emptiness.

        **Nobody's contestant is forced from here any more.** A side
        with somebody standing on the ball puts them up, for nothing
        and without being asked, and that is one rule read off the
        position by loose_ball_candidates rather than two call sites
        passing players in. It used to be the High Pass's alone; it is
        now every loose ball's, so the High Pass had nothing left to
        pass.

        `restrict_to_occupants` is Deflect/Clear's own rule (and Setup
        Pass's cost, which lands the ball the same way): a side with
        nobody on the landing space may no longer send a player in to
        contest it against a side that already has one there -- only a
        landing space nobody occupies is a real loose ball. When it's
        set and exactly one side has somebody there, that side's
        opponent is pre-declined before either side is ever put on the
        clock, so they are never prompted and never get the chance. An
        empty space or a space both sides already share is unaffected
        -- those are exactly the ordinary "each side may send" and
        "forced contest" cases already.
        """
        match.begin_loose_ball(distance_moved, is_high_pass=is_high_pass)
        # The ball is free and about to be contested, so nobody is
        # carrying it -- including the long High Pass, where a receiver
        # who has to win a test to keep it is not yet in possession of
        # anything. Whoever comes out of the contest with it is chosen
        # off the ball's space in the ordinary way.
        match.clear_ball_carrier()

        single_side_note: Optional[str] = None
        if restrict_to_occupants:
            offense_side = match.ball.possession
            defense_side = match.defending_side()
            offense_occupied = bool(match.loose_ball_occupants(offense_side))
            defense_occupied = bool(match.loose_ball_occupants(defense_side))
            if offense_occupied != defense_occupied:
                empty_side, taking_side = (
                    (defense_side, offense_side)
                    if offense_occupied
                    else (offense_side, defense_side)
                )
                match.decline_loose_ball(empty_side)
                single_side_note = (
                    "**Loose ball!** Only "
                    f"{format_team_side_label(match.setup_for_side(taking_side))} "
                    "has anyone there -- they keep it, uncontested."
                )

        self.engine.auto_resolve_loose_ball_picks(game, match)
        game.match_state = match.to_dict()
        save_games(self.games)

        if headline is None:
            headline = single_side_note or self.engine.build_loose_ball_headline(match)
        prefix = f"{lead_in}\n\n" if lead_in else ""
        if is_high_pass:
            # A High Pass is not a loose ball: the ball is on a player
            # everyone can already see, and the board it is standing on
            # was posted by the pass itself.
            await interaction.followup.send(f"{prefix}{headline}")
        else:
            # A genuine loose ball is the one position nobody can read
            # off the last thing they were told -- the ball is lying in
            # an empty space some number of spaces from wherever the
            # pass started, and the very next question is who to send
            # after it. So it is named and drawn, together.
            await self.announce_board_update(
                interaction,
                game,
                f"{prefix}{headline}\n{ball_location_line(match)}",
            )

        if self.engine.loose_ball_side_on_the_clock(match) is None:
            await self.resolve_loose_ball(interaction, game, match)
            return

        prompt_message = await interaction.followup.send(
            self.engine.build_loose_ball_prompt(game, match),
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
                # Only a side with nobody fielded at all lands here now
                # -- distance replaced the zone as the measure on
                # 2026-08-16, so declining is otherwise the whole of
                # how a ball goes out.
                else "Neither side has anyone left to send"
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
            player = self.engine.get_player_definition(offense_player_id)
            recovery_distance = match.distance_to_ball(offense_player_id)
            match.move_meeple(
                offense_player_id, match.ball.zone, match.ball.space_index,
            )
            exhaustion_text = self.apply_exhaustion(
                match, offense_player_id, recovery_distance,
            )
            match.pending_loose_ball = False
            # They went after it and came away with it, so they are
            # holding it -- the same answer as a contested win below,
            # since an unopposed contest is still how they got it.
            match.set_ball_carrier(offense_player_id)
            game.match_state = match.to_dict()
            save_games(self.games)

            recovery_line = (
                f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} keeps "
                "possession after the high pass, uncontested."
                if is_high_pass
                else f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} "
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
            player = self.engine.get_player_definition(defense_player_id)
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
            match.set_ball_carrier(defense_player_id)
            game.match_state = match.to_dict()
            save_games(self.games)

            headline = (
                f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} "
                "picks off the high pass, uncontested."
                if is_high_pass
                else f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} "
                "recovers the loose ball uncontested."
            )
            await interaction.followup.send(
                "# Turnover!\n"
                f"{headline} "
                f"{format_team_side_label(match.setup_for_side(match.ball.possession))} "
                f"now has possession -- {format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} "
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

        offense_player = self.engine.get_player_definition(offense_player_id)
        defense_player = self.engine.get_player_definition(defense_player_id)
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
            f"{format_role_bracket(defense_player, self.team_emojis, match.team_for_player(defense_player.player_id))} "
            f"(defense skill {defense_skill}) challenges "
            f"{format_role_bracket(offense_player, self.team_emojis, match.team_for_player(offense_player.player_id))} "
            f"(offense skill {offense_skill}) for the high pass -- the "
            "receiver must win this skill test to keep possession!"
            if is_high_pass
            else f"{format_role_bracket(offense_player, self.team_emojis, match.team_for_player(offense_player.player_id))} "
            f"(offense skill {offense_skill}) and "
            f"{format_role_bracket(defense_player, self.team_emojis, match.team_for_player(defense_player.player_id))} "
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
        if len(candidates) == 1 or self.engine.side_controlled_by_ai(
            game, match, "offense",
        ):
            if len(candidates) == 1:
                shooter_id = candidates[0]
            else:
                shooter_id = self.engine.get_ai_strategy(game).choose_shooter(
                    candidates, match,
                )
            if lead_in:
                await interaction.followup.send(lead_in)
            await self.start_set_up_shot(interaction, game, match, shooter_id)
            return

        mention = format_player_with_team(
            game,
            self.engine.possession_player_number(game, match),
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
        maneuver_cost: int = 1,
    ) -> None:
        """
        `maneuver_cost` is the flat cost of the maneuver that offered
        this set-up -- 1 for everything but a High Pass, which is why
        it defaults to 1 and only a High Pass call site overrides it.
        Stored so ScoreAttemptView.roll can charge it on top of the
        shot's own extra minute (2026-08-16): the two stack now,
        instead of the shot's cost replacing the maneuver's.
        """
        match.active_player_id = shooter_id
        match.pending_action = "shoot"
        match.pending_shot_is_set_up = True
        match.pending_shot_setup_cost = maneuver_cost
        game.match_state = match.to_dict()
        save_games(self.games)

        shooter = self.engine.get_player_definition(shooter_id)
        await interaction.followup.send(
            f"{format_role_bracket(shooter, self.team_emojis, match.team_for_player(shooter.player_id))} takes the "
            "shot off the set-up."
        )
        await self.begin_score_attempt(interaction, game, match)

    # -- Deflect -------------------------------------------------

    async def resolve_deflect(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        await self.apply_deflection(interaction, game, match, "deflect")

    async def resolve_clear(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Clear is Deflect at three spaces: the ball goes back 3
        and ball speed drops by 3 rather than 1. Everything else about
        it -- the overshoot set-up, the loose ball it leaves behind --
        is the same, which is why the two share one function.

        **The Fullback's ability is +1 distance, so a Clear it plays
        goes back 4** (the author, 2026-08-19). Its sentence reads
        "Block deflect: ball goes back 2 spaces", which read as a
        number is a *reduction* against a 3-space clearance and read as
        the rule behind the number is the +1 that takes a basic
        deflection from 1 to 2. The rule is what carries.
        """
        await self.apply_deflection(interaction, game, match, "clear")

    async def apply_deflection(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        key: str,
    ) -> None:
        offense_side = match.ball.possession
        defense_side = match.defending_side()
        defender = self.engine.get_player_definition(match.challenger_id)
        name = self.engine.maneuver_name(key)

        # Role ability -- Fullback: +1 space on a deflection, which
        # takes a Deflect from 1 to 2 and a Clear from 3 to 4.
        fullback_bonus = defender.role == PlayerRole.FULLBACK
        base_distance = 3 if key == "clear" else 1
        deflect_distance = base_distance + (1 if fullback_bonus else 0)

        # **The speed drop is the card's, not the distance's.** A
        # Fullback's Deflect has always moved the ball 2 and
        # dropped the speed by 1, so the two are separate numbers that
        # happen to match on an ordinary deflection -- and a Clear's
        # -3 stays -3 when the Fullback pushes it to 4 spaces. Written
        # as `deflect_distance` this read correctly right up until the
        # Fullback was let near a Clear.
        speed_drop = base_distance

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
        match.ball.speed = max(1, match.ball.speed - speed_drop)
        game.match_state = match.to_dict()
        save_games(self.games)

        space_word = "space" if actual_distance == 1 else "spaces"
        ability_note = " (Fullback ability)" if fullback_bonus else ""
        content = (
            f"**{name}:** the ball moves {actual_distance} "
            f"{space_word} back{ability_note}. Ball speed is now "
            f"{match.ball.speed}."
        )

        # A shot has to be within shooting range, and this one always
        # is: an overshoot means the ball reached the space closest to
        # the offense's own goal, which is as deep into the deflecting
        # team's range as the field goes. So this asks
        # scoring_opportunity_candidates with no range check over it --
        # the check could never fail here, and a branch that cannot be
        # taken reads as if it could.
        candidates = []
        if overshot:
            candidates = self.engine.scoring_opportunity_candidates(
                match, defense_side,
            )

        if candidates:
            # A defender standing right where the ball ends up gets a
            # shot at the goal it's now next to -- that's a turnover
            # before the shot, same as any other change of possession,
            # so the score attempt reads the correct attacking and
            # defending sides.
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
            return

        # **Setup Pass's cost**: beaten by a deflection, the defending
        # coach drives the ball back a further 1, 2 or 3 spaces and it
        # is loose where it stops. It is asked here rather than as a
        # step after the maneuver because a deflection already ends in
        # a loose ball -- the cost only decides where it lies. Not
        # asked when the deflection overshot into a shot above: the
        # ball is already as far back as the field goes and the shot is
        # the bigger thing happening.
        if self.engine.advanced_cost(match, key) == "setup_pass":
            await self.offer_setup_pass_push_back(
                interaction, game, match, lead_in=content,
            )
            return

        # A deflection knocks the ball out of anybody's possession, so
        # it does not go through finish_maneuver_resolution's ordinary
        # loose-ball check: that check asks whether the possessing team
        # has somebody on the ball, and here the answer does not
        # matter -- either side's occupant is equally dispossessed.
        #
        # **Since 2026-08-24, occupancy still decides how it's won.**
        # An empty landing space is a real loose ball (each side may
        # send someone); a space only one side already occupies is
        # theirs outright, with no send offered to the other side; a
        # space both occupy is a forced contest. `restrict_to_occupants`
        # is that rule -- see begin_loose_ball.
        #
        # No refresh_match_image first: begin_loose_ball posts the
        # board with the announcement, and refreshing here would write
        # the same board twice (see "Discord's rate limits").
        #
        # A deflection's time cost is a fixed 1 space minute per the
        # rules table, not "distance traveled" like Low/High Pass, so
        # this doesn't shrink if the move was clamped at the edge (or
        # grow with the Fullback's extra distance, or Clear's).
        await self.begin_loose_ball(
            interaction, game, match, 1, lead_in=content,
            restrict_to_occupants=True,
        )

    async def offer_setup_pass_push_back(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str,
    ) -> None:
        """
        Setup Pass's cost: the coach who beat it chooses 1, 2 or 3
        further spaces to drive the ball back, where it is a loose
        ball.

        Distances that would run off the end of the field are not
        offered, for the reason `high_pass_distances` does not offer
        them: a longer push landing where a shorter one already would
        is the same push described twice. If none of the three fits,
        the ball is already at the end and the cost is spent -- the
        loose ball happens where the deflection left it.
        """
        defense_side = match.defending_side()
        offense_side = match.ball.possession
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        distances = [
            distance
            for distance in (1, 2, 3)
            if abs(
                match.relative_flat_index(origin_flat, offense_side, -distance)
                - origin_flat
            )
            == distance
        ]

        if not distances:
            await self.begin_loose_ball(
                interaction, game, match, 1, lead_in=lead_in,
                restrict_to_occupants=True,
            )
            return

        if self.engine.side_controlled_by_ai(game, match, "defense"):
            # Dinky drives it as far back as it can, the same
            # maximizing it brings to a speed choice.
            await self.apply_setup_pass_push_back(
                interaction, game, match, max(distances), lead_in=lead_in,
            )
            return

        mention = format_player_with_team(
            game,
            self.engine.defending_player_number(game, match),
            mention=True,
        )
        prompt_view = SetupPassPushBackView(self, game.game_id)
        prompt_message = await interaction.followup.send(
            f"{lead_in}\n\n{mention}, **Setup Pass** was beaten -- how far "
            "back does the ball go? It will be loose where it stops.",
            view=prompt_view,
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def apply_setup_pass_push_back(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance: int,
        lead_in: str = "",
    ) -> None:
        offense_side = match.ball.possession
        actual_distance = match.move_ball_relative(offense_side, -distance)
        game.match_state = match.to_dict()
        save_games(self.games)

        space_word = "space" if actual_distance == 1 else "spaces"
        prefix = f"{lead_in}\n\n" if lead_in else ""
        await self.begin_loose_ball(
            interaction,
            game,
            match,
            1,
            lead_in=(
                f"{prefix}**Setup Pass** was beaten: the ball is driven a "
                f"further {actual_distance} {space_word} back."
            ),
            restrict_to_occupants=True,
        )

    # -- Steal ----------------------------------------------------------

    async def resolve_steal(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        await self.apply_steal(interaction, game, match, "steal")

    async def resolve_intercept(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Intercept is the basic Steal with the sign flipped: the
        interceptor carries the ball **forward**, toward the goal they
        now attack, rather than falling back toward their own. It is
        the only card in the game that moves the ball against the way
        the offense was going.
        """
        await self.apply_steal(interaction, game, match, "intercept")

    async def apply_steal(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        key: str,
    ) -> None:
        new_possession_side = match.defending_side()
        challenger_id = match.challenger_id
        name = self.engine.maneuver_name(key)
        # Toward the new possessor's own goal for a Steal, toward the
        # goal they now attack for an Intercept -- so the two are one
        # function and a sign.
        direction = 1 if key == "intercept" else -1

        # The turnover happens first, then both the interceptor and the
        # ball move -- relative to the *new* possessing side, not the
        # old one. Moving the challenger's meeple (not just the ball)
        # and re-deriving the ball's space from it keeps the two in the
        # same space, so possession can be assigned directly without
        # set_possession's occupancy check.
        match.ball.possession = new_possession_side
        # Every turnover drops the ball's speed back to 1 -- the
        # defender's manipulate-speed choice below applies to that
        # reset value, not whatever the speed was before the steal.
        match.ball.speed = 1

        # Intercept moving forward can run out of field, which a Steal
        # falling back never can: the ball was in play, so there is
        # always a space behind it. Read before the move, the way every
        # other overshoot is.
        origin_flat = match.board.flat_index(
            *match.board.meeple_position(challenger_id)
        )
        target_flat = match.relative_flat_index(
            origin_flat, new_possession_side, direction,
        )
        overshot = abs(target_flat - origin_flat) < 1

        actual_distance = match.move_player_relative(
            challenger_id, new_possession_side, direction,
        )
        match.set_ball_space(*match.board.meeple_position(challenger_id))
        # The interceptor took the ball off someone and moved with it,
        # so they carry it into their side's next turn -- the same
        # player the run back exempts below.
        match.set_ball_carrier(challenger_id)
        game.match_state = match.to_dict()
        save_games(self.games)

        space_word = "space" if actual_distance == 1 else "spaces"
        challenger = self.engine.get_player_definition(challenger_id)
        challenger_label = format_role_bracket(
            challenger,
            self.team_emojis,
            match.team_for_player(challenger.player_id),
        )
        new_possession = match.setup_for_side(match.ball.possession)
        travel = (
            f"then carries it {actual_distance} {space_word} forward, "
            "toward the goal they now attack"
            if key == "intercept"
            else f"then falls back {actual_distance} {space_word} toward "
            "their own goal with the ball"
        )
        content = (
            f"**{name}:**\n"
            "# Turnover!\n"
            f"{challenger_label} steals the ball. "
            f"{format_team_side_label(new_possession)} now has possession, "
            f"{travel}."
        )

        if key == "intercept" and overshot:
            # **The interceptor was already on the last space toward
            # the goal they now attack, so there is nowhere to carry
            # it: it is a scoring opportunity instead** (the author,
            # 2026-08-19).
            #
            # Straight to the shot, the same as a deflection's
            # overshoot and for the same reason: the run back and the
            # speed step both belong after a turnover that left the
            # play running, and this one has not. That drops
            # Intercept's own speed-manipulation step, which is the one
            # thing about this branch worth watching -- a set-up shot
            # already reads the ball speed the turnover reset.
            await self.refresh_match_image(interaction, game)
            await self.begin_shooter_choice(
                interaction,
                game,
                match,
                [challenger_id],
                lead_in=(
                    f"{content}\n\nThere is no field left ahead of them -- "
                    "a scoring opportunity!"
                ),
            )
            return

        # **Precise Pass's cost**: beaten by a steal, the passing side
        # hands the defender an unopposed Low Pass once the steal has
        # settled. It is recorded rather than played here because the
        # steal is not finished: the run back and then the speed choice
        # both come first, and the pass is played from wherever that
        # leaves the interceptor. See `pending_effect_continuation`.
        if self.engine.advanced_cost(match, key) == "precise_pass":
            match.pending_effect_continuation = {
                "kind": "free_low_pass",
                "player_id": challenger_id,
            }
            content += (
                "\n\n**Precise Pass** was beaten -- the defense gets an "
                "unopposed Low Pass once everyone is back in position."
            )
            game.match_state = match.to_dict()
            save_games(self.games)

        await self.refresh_match_image(interaction, game)

        # Ball-speed manipulation is offered after run-back finishes,
        # not here -- see begin_run_back's speed_choice_after.
        # No stays_player_id: begin_run_back exempts the ball carrier,
        # which set_ball_carrier above has already made the interceptor.
        await self.begin_run_back(
            interaction,
            game,
            match,
            speed_choice_after=True,
            lead_in=content,
        )

    # -- Pressure --------------------------------------------------------

    async def resolve_pressure(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        await self.apply_pressure(interaction, game, match, "pressure")

    async def resolve_double_team(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Double Team is Pressure at two spaces, with a second defender
        brought in free of exhaustion -- and it is the one card whose
        effect lands on the *following* maneuver: so long as no new
        play intervenes, both defenders challenge the ball holder and
        both add their defensive skill.
        """
        await self.apply_pressure(interaction, game, match, "double_team")

    async def apply_pressure(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        key: str,
    ) -> None:
        offense_side = match.ball.possession
        defense_side = match.defending_side()
        name = self.engine.maneuver_name(key)
        push = 2 if key == "double_team" else 1

        # Own-goal risk: a pressure is the only thing that threatens
        # one, and only when the ball-holder is already at the space
        # closest to their own goal, i.e. pushing them back further
        # isn't possible.
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        target_flat = match.relative_flat_index(
            origin_flat, offense_side, -push,
        )
        overshot = abs(target_flat - origin_flat) < push

        # **Read before anything moves.** The card says "the teammate
        # closest to the space where the play started", and the play
        # started where the ball is standing now -- a moment later the
        # handler has been shoved back two and the ball with them, and
        # the nearest defender to *that* space can be somebody else
        # entirely. Asked here, so the answer is the one the card
        # describes.
        partner_id = (
            self.engine.double_team_partner(match)
            if key == "double_team"
            else None
        )

        actual_distance = match.move_player_relative(
            match.active_player_id, offense_side, -push,
        )
        match.set_ball_space(
            *match.board.meeple_position(match.active_player_id)
        )

        # The challenger advances onto the handler's space. A Double
        # Team brings that teammate onto it as well, free of
        # exhaustion -- so they are *placed* rather than run, which is
        # what "no exhaustion cost" means in a game where every other
        # way to reach a space charges a token a space.
        handler_zone, handler_space = match.board.meeple_position(
            match.active_player_id
        )
        match.move_meeple(match.challenger_id, handler_zone, handler_space)
        if partner_id is not None:
            match.move_meeple(partner_id, handler_zone, handler_space)

        # Losing to a pressure does not lose the ball: the handler was
        # shoved back still holding it, so they take the next turn.
        # Set before the overshoot branch, because an own goal avoided
        # is the same thing -- pressured, and still holding it. The
        # Defender's steal below moves the carry to the Defender, and a
        # conceded own goal is a new play, which clears it.
        match.set_ball_carrier(match.active_player_id)

        handler = self.engine.get_player_definition(match.active_player_id)
        defender = self.engine.get_player_definition(match.challenger_id)
        space_word = "space" if actual_distance == 1 else "spaces"
        content = (
            f"**{name}:** "
            f"{format_role_bracket(handler, self.team_emojis, match.team_for_player(handler.player_id))} and the "
            f"ball go back {actual_distance} {space_word}. "
            f"{format_role_bracket(defender, self.team_emojis, match.team_for_player(defender.player_id))} moves "
            "forward."
        )

        if key == "double_team" and partner_id is not None:
            partner = self.engine.get_player_definition(partner_id)
            # **The pair is recorded, not the fact that a Double Team
            # happened.** What the next maneuver needs is who
            # challenges it, and that is two named cards; a flag would
            # leave the following turn re-deriving "the nearest
            # teammate" off a board that has moved since.
            match.pending_double_team = [match.challenger_id, partner_id]
            content += (
                f" {format_role_bracket(partner, self.team_emojis, match.team_for_player(partner_id))} "
                "joins them, free of exhaustion -- and **both** will "
                "challenge on the next maneuver, each adding their "
                "defensive skill."
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
            await self.begin_own_goal_roll(
                interaction, game, match, distance_moved=1,
            )
            return

        # **Dribble Burst's cost**: beaten by a pressure, the offense
        # loses possession *and* the ball keeps whatever speed it was
        # carrying while the defense manipulates it. Neither of those
        # is something a pressure does on its own -- a turnover is the
        # steal's and so is the speed step -- which is what the matrix
        # means by the cost borrowing machinery its defeaters do not
        # have. It is also **the first exception to "every turnover
        # resets ball speed to 1"**, and the reason nothing here calls
        # `match.ball.speed = 1`.
        burst_cost = self.engine.advanced_cost(match, key) == "dribble_burst"
        if burst_cost:
            match.ball.possession = defense_side
            match.set_ball_carrier(match.challenger_id)
            content += (
                "\n\n# Turnover!\n"
                "**Dribble Burst** was beaten -- "
                f"{format_team_side_label(match.setup_for_side(defense_side))} "
                "take the ball, and it keeps the speed the burst put into "
                f"it ({match.ball.speed})."
            )

        # Role ability -- Defender: also steals the ball on a won
        # pressure, on top of the normal effect above.
        stolen = defender.role == PlayerRole.DEFENDER
        if stolen and not burst_cost:
            match.ball.possession = defense_side
            match.ball.speed = 1
            match.set_ball_carrier(match.challenger_id)
            content += (
                "\n\n# Turnover!\n"
                f"{format_role_bracket(defender, self.team_emojis, match.team_for_player(defender.player_id))} "
                "steals the ball (Defender ability)! "
                f"{format_team_side_label(match.setup_for_side(defense_side))} "
                "now has possession."
            )

        game.match_state = match.to_dict()
        save_games(self.games)

        await self.refresh_match_image(interaction, game)

        # Fixed 1 space minute per the rules table, independent of
        # clamping, same reasoning as a deflection above.
        if burst_cost:
            # The defense has the ball and the speed step the cost
            # granted them, which is the steal's shape: run everyone
            # back first, then let them set the speed.
            await self.begin_run_back(
                interaction,
                game,
                match,
                speed_choice_after=True,
                speed_reset=False,
                lead_in=content,
            )
        elif stolen:
            # The stealing player keeps the ball and stays put --
            # everyone else who's out of position runs back. Read off
            # the carrier set above, not passed in.
            await self.begin_run_back(
                interaction,
                game,
                match,
                lead_in=content,
            )
        else:
            await self.finish_maneuver_resolution(
                interaction, game, match, distance_moved=1, lead_in=content,
            )

    # -- Ball-speed manipulation (Dribble Advance / Steal) --

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
        manipulated after any run-back it caused (Steal), so
        this leads straight into finish_maneuver_resolution once
        chosen. `turnover_occurred`/`distance_moved` are just carried
        through to that call.

        `lead_in` is narration from the maneuver that led here -- it
        rides along on the speed-choice prompt when a human picks, or
        gets forwarded to apply_speed_choice to ride along on its own
        message when the pick is automatic.
        """
        skill = self.player_catalog.effective_profile(
            self.engine.get_player_definition(player_id),
        )
        skill_value = skill.offense if skill_type == "offense" else skill.defense

        controller_id = self.engine.controlling_user_id(game, match, player_id)
        is_ai = game.is_solo_game and controller_id == game.player_2_id

        if is_ai:
            delta = self.engine.get_ai_strategy(game).choose_speed_delta(skill_value)
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

        # An advanced effect can reach past its own maneuver, and a
        # speed choice is the last human step of the two that do -- see
        # `MatchState.pending_effect_continuation`.
        if match.pending_effect_continuation is not None:
            await self.continue_effect(
                interaction,
                game,
                match,
                distance_moved=distance_moved,
                turnover_occurred=turnover_occurred,
            )
            return

        await self.finish_maneuver_resolution(
            interaction,
            game,
            match,
            distance_moved=distance_moved,
            turnover_occurred=turnover_occurred,
        )

    async def continue_effect(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int = 1,
        turnover_occurred: bool = False,
    ) -> None:
        """
        Run whatever an advanced effect still owes once its last prompt
        has been answered.

        **The record is cleared by whatever applies the step, not
        here.** A continuation is one more prompt, and a coach may take
        hours over it -- so between dispatching and the click that
        answers, the only thing on the match saying what is owed is
        this field. Clearing it at dispatch (which is what
        `finish_cede` does with `pending_cede`, for a flow with no
        prompt left in it) would leave a restart in that window
        reading the maneuver's winner instead and re-offering the
        speed choice a coach had already answered.
        `build_effect_choice_view` reads this first for the same
        reason.

        An unrecognised kind falls through to the ordinary end of a
        maneuver rather than stranding the turn: a continuation written
        by a version of the bot this one does not have is a game to
        finish, not a game to lose. That branch *does* clear it, or the
        next speed choice in the game would find it still set.
        """
        continuation = match.pending_effect_continuation or {}

        if continuation.get("kind") == "free_low_pass":
            # **Precise Pass's cost.** The defense stole the ball and
            # now plays a Low Pass with it, unopposed. The passer is
            # whoever took it -- named when the cost was recorded, and
            # re-derived from the ball if a run back has moved things
            # since.
            passer_id = continuation.get("player_id")
            holders = match.eligible_ball_handlers()
            if passer_id not in holders:
                passer_id = holders[0] if holders else None
            if passer_id is not None:
                match.active_player_id = passer_id
                game.match_state = match.to_dict()
                save_games(self.games)
                await self.resolve_low_pass(
                    interaction, game, match, key="low_pass", free=True,
                )
                return

        if continuation.get("kind") == "setup_pass_shot":
            # **Setup Pass's benefit**, second half: the speed is set,
            # and now the scoring opportunity is set up.
            await self.offer_setup_pass_distance(interaction, game, match)
            return

        match.pending_effect_continuation = None
        game.match_state = match.to_dict()
        save_games(self.games)
        await self.finish_maneuver_resolution(
            interaction,
            game,
            match,
            distance_moved=distance_moved,
            turnover_occurred=turnover_occurred,
        )

    # -- Own goal ----------------------------------------------------

    async def begin_own_goal_roll(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int,
    ) -> None:
        """
        Put the own-goal roll behind a button, the way a score attempt
        is: the coach whose player is about to concede rolls it
        themselves rather than reading what the bot already rolled for
        them.

        Nothing is decided here, so everything the roll needs is
        persisted first -- `pending_own_goal` says one is owed and
        `pending_own_goal_distance` carries the clock cost of the
        maneuver that risked it, which the resolution spends whichever
        way the roll goes. A restart between the two comes back to this
        prompt through `pending_turn_view`.
        """
        match.pending_own_goal = True
        match.pending_own_goal_distance = distance_moved
        game.match_state = match.to_dict()
        save_games(self.games)

        offense_player = self.engine.get_player_definition(match.active_player_id)
        offense_skill = self.player_catalog.effective_profile(
            offense_player,
        ).offense
        controller_id = self.engine.controlling_user_id(
            game, match, offense_player.player_id,
        )
        mention = f"<@{controller_id}>" if controller_id else "Someone"

        prompt_message = await interaction.followup.send(
            f"**Own goal risk!** {mention}, "
            f"{format_role_bracket(offense_player, self.team_emojis, match.team_for_player(offense_player.player_id))} "
            "rolls two d12 at an advantage — the higher of the two, plus "
            f"their offensive skill ({offense_skill}). A total of 7 or "
            "more and the own goal is avoided.",
            view=OwnGoalRollView(self, game.game_id),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def run_own_goal_roll(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The roll itself, off the button `begin_own_goal_roll` posted:
        2d12 at an advantage (take the higher), plus the ball-handler's
        offensive skill, safe on 7+.

        Making the attempt costs the rolling player 1 exhaust token,
        win or lose, on top of whatever the maneuver that triggered the
        risk already charged. It is not a skill test, so it owes no
        injury check.
        """
        distance_moved = match.pending_own_goal_distance
        match.pending_own_goal = False

        offense_player = self.engine.get_player_definition(match.active_player_id)
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
            f"{format_role_bracket(offense_player, self.team_emojis, match.team_for_player(offense_player.player_id))} "
            f"rolls at an advantage: higher of {rolls[0]}/{rolls[1]} "
            f"is {taken}, + {offense_skill} (offensive skill) "
            f"= {total}"
        )

        if safe:
            # A new play resets speed same as any other -- see
            # begin_run_back below -- and nothing else on this path
            # would, since Pressure's overshoot branch never touches it.
            match.ball.speed = 1
            # The ball stays exactly where the overshot Pressure left
            # it, with no coverage guarantee at all -- not even the
            # standard deal's, since that position is wherever the play
            # happened to reach. So, since 2026-08-24, this owes the
            # same pickup an out-of-bounds ball does rather than a
            # two-sided loose ball: begin_ball_recovery checks
            # eligible_ball_handlers() first and asks nobody when the
            # reset already covers it.
            match.pending_ball_recovery = True
            verdict = f"## Own goal avoided!\n\n{exhaustion_text}"
        else:
            conceding_side = match.ball.possession
            # The goal is the other side's; the kick is this player's,
            # and the log says both -- see concede_own_goal.
            match.concede_own_goal(offense_player.player_id)
            match.restart_after_goal(conceding_side)
            match.pending_run_back = True
            match.pending_run_back_distance = distance_moved
            match.pending_run_back_turnover = True
            game.match_state = match.to_dict()
            save_games(self.games)
            verdict = (
                f"# Own goal!\n"
                f"{format_role_bracket(offense_player, self.team_emojis, match.team_for_player(offense_player.player_id))} "
                "puts it in their own net on "
                f"**{format_goal_time(match.goals[-1])}**.\n"
                f"{team_display_name(match.home.team)} {match.scoreboard.home_score}:"
                f"{match.scoreboard.visiting_score} "
                f"{team_display_name(match.visiting.team)}\n\n"
                f"{exhaustion_text}"
            )

        # The prompt becomes the dice, taking its own explanation with
        # it once the roll it was asking for has happened -- the same
        # trade a score attempt makes. The arithmetic rides above the
        # image because it is what built it; the verdict follows in a
        # message of its own, since a message's attachments render
        # below its content and a verdict written here would be read
        # before the roll that decided it. See SkillTestView.roll.
        await interaction.edit_original_response(
            content=breakdown,
            attachments=[dice_file],
            view=None,
        )
        await interaction.followup.send(verdict)
        await self.refresh_match_image(interaction, game)
        if safe:
            game.match_state = match.to_dict()
            save_games(self.games)
            # Avoiding it is a stoppage too, not a play that simply
            # carries on: both sides reset to their saved arrangement
            # and the side that kept the ball may declare, exactly like
            # any other new play -- and if this closes out last
            # possession, begin_run_back's own check ends the period
            # here instead. See "Own goal" in docs/living-rules.md.
            await self.begin_run_back(
                interaction,
                game,
                match,
                distance_moved=distance_moved,
                turnover_occurred=True,
                new_play=True,
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
            in match.setup_for_side(side).team_board.back_bench
        )
        occasion = match.coaching_occasion or CoachingOccasion.NEW_PLAY

        match.substitute(
            side,
            outgoing_player_id,
            incoming_player_id,
            retire_outgoing=occasion.retires_outgoing_players,
        )
        match.record_substitution(outgoing_player_id, incoming_player_id)

        outgoing = self.engine.get_player_definition(outgoing_player_id)
        incoming = self.engine.get_player_definition(incoming_player_id)
        text = (
            f"{format_role_bracket(incoming, self.team_emojis, match.team_for_player(incoming.player_id))} comes on "
            f"for {format_role_bracket(outgoing, self.team_emojis, match.team_for_player(outgoing.player_id))}"
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

        text += f"\n{self.engine.substitution_allowance_label(match)}."
        return text


    def apply_position_swap(
        self,
        match: MatchState,
        side: TeamSide,
        player_id: str,
        other_player_id: str,
    ) -> str:
        """
        The Coaching Choice's zone assignment: trade two players'
        zones, meeples included, and describe it.
        """
        match.exchange_field_players(side, player_id, other_player_id)

        setup = match.setup_for_side(side)
        first = self.engine.get_player_definition(player_id)
        second = self.engine.get_player_definition(other_player_id)
        return (
            f"{format_role_bracket(first, self.team_emojis, match.team_for_player(first.player_id))} and "
            f"{format_role_bracket(second, self.team_emojis, match.team_for_player(second.player_id))} change "
            "places: "
            f"{format_role_bracket(first, self.team_emojis, match.team_for_player(first.player_id))} to "
            f"{destination_display_name(setup.assigned_zone(player_id).value)}"
            f", {format_role_bracket(second, self.team_emojis, match.team_for_player(second.player_id))} to "
            f"{destination_display_name(setup.assigned_zone(other_player_id).value)}"
            ". No exhaustion cost."
        )





    def apply_reposition(
        self,
        match: MatchState,
        side: TeamSide,
        player_id: str,
        space_index: int,
        swap_with: Optional[str] = None,
    ) -> str:
        """
        The Coaching Choice's space positioning: move one meeple within
        its own zone, trading with whoever is already there when the
        rule says so, and describe what happened.
        """
        setup = match.setup_for_side(side)
        zone = setup.assigned_zone(player_id)
        partner = match.position_meeple(
            side, player_id, space_index, swap_with=swap_with,
        )

        player = self.engine.get_player_definition(player_id)
        if partner is None:
            return (
                f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} moves "
                f"to {space_label(zone, space_index)}. No exhaustion cost."
            )
        other = self.engine.get_player_definition(partner)
        return (
            f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} moves to "
            f"{space_label(zone, space_index)} and "
            f"{format_role_bracket(other, self.team_emojis, match.team_for_player(other.player_id))} takes their "
            "place. No exhaustion cost."
        )


    async def coaching_file(
        self,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
    ) -> discord.File:
        """
        The coach's own half of the field, as an attachment for their
        Coaching Choice message. Rendered in a worker thread like every
        other image: Pillow is pure CPU and the event loop is shared by
        every game at once.
        """
        png = await asyncio.to_thread(
            render_coaching_image,
            match,
            self.player_catalog,
            side,
            self.engine.coaching_title(match, side),
        )
        return discord.File(
            io.BytesIO(png.getvalue()),
            filename=f"d12ball-coaching-{game.game_number}.png",
        )

    async def begin_substitution_window(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
        occasion: CoachingOccasion = CoachingOccasion.NEW_PLAY,
        is_response: bool = False,
        lead_in: str = "",
    ) -> None:
        """
        Offer `side` the window. A declaration is once a half, so a
        side that has already spent theirs is never offered one. An
        injured player on the field is named in the heading but
        compels nothing -- leaving them on is the coach's call.

        `occasion` carries every difference between the five -- the
        substitution allowance, whether the declare-or-pass offer is
        put at all, where a player taken off goes, and whether the
        three positional actions are offered at all. Setup, halftime
        and full time are given rather than declared, so all three skip
        the offer and open the menu directly; a ceded ball skips it for
        the opposite reason, having already been paid for.

        **A window opens on the arrangement its coach last settled**,
        never on the scramble a run back left behind -- see
        MatchState.restore_assigned_positions. A new play resets both
        sides before offering the window, so this only ever does
        anything at halftime, where the first half ended wherever it
        ended; but it is the guarantee for every occasion rather than
        a halftime step, because a coach reading their half-field is
        reading the shape they set either way.

        Except full time, which has no positioning in it: nothing is
        played from a position after it, so restoring would rearrange
        the last board of the game to no purpose.
        """
        side = TeamSide(side)
        occasion = CoachingOccasion(occasion)

        # The tutorial's last lesson, and the one it cannot schedule:
        # a new play offers this window to the side *restarting* play,
        # which after the coach's goal is Dinky. So the note fires at
        # the first window this coach is ever offered, whenever the
        # game gets round to it -- which is why it reads `tutorial`
        # rather than `in_tutorial`, and usually lands a few turns
        # after the script has finished. `skip_tutorial` sets the flag
        # so a coach who opted out is not taught anyway.
        if (
            game.tutorial
            and not game.tutorial_coaching_explained
            and side == self.tutorial_player_side(game)
        ):
            game.tutorial_coaching_explained = True
            save_games(self.games)
            await interaction.followup.send(tutorial.COACHING_NOTE)

        restored = (
            match.restore_assigned_positions(side)
            if occasion.offers_positioning
            else False
        )
        shape = self.engine.current_formation(match, side)
        match.open_coaching_window(
            side,
            occasion,
            is_response=is_response,
            formation=shape.value if shape else None,
        )
        game.match_state = match.to_dict()
        save_games(self.games)

        # Only when the restore actually moved somebody, so the common
        # case -- setup, and a new play that has just reset both sides
        # -- costs nothing. Halftime does move them, and a coach whose
        # half-field disagrees with the board above it has no way to
        # tell which one the game thinks is true.
        if restored:
            await self.refresh_match_image(interaction, game)

        if self.engine.side_is_ai(game, side):
            await self.run_ai_substitution_window(
                interaction, game, match, lead_in=lead_in,
            )
            return

        if occasion.asks_declaration:
            note = (
                "Answering the other team, which leaves your own "
                "once-a-half Coaching Choice unspent."
                if is_response
                else "Calling one is once a half. Coach, or pass?"
            )
        elif occasion == CoachingOccasion.CEDED:
            note = (
                "The ball bought this, so there is nothing to decide "
                "-- it is open."
                if not is_response
                else "The other team gave the ball up to coach. Yours "
                "is open too, and leaves your own once-a-half Coaching "
                "Choice unspent."
            )
        else:
            note = "Take as long as you like; nothing here costs exhaustion."

        # Said only when it actually moved somebody, which is halftime
        # and nowhere else: a coach who left the first half with their
        # side scattered is looking at their own shape again and
        # should be told why.
        if restored:
            note += (
                "\nYour side is back on the arrangement you last set, "
                "free of exhaustion."
            )

        # An injured player is worth pointing out, but only as a
        # nudge: nothing compels a side to get them off, and a coach
        # may leave them on, disadvantaged, all game.
        injured_ids = match.injured_field_players(side)
        if injured_ids:
            injured = ", ".join(
                format_role_bracket(
                    self.engine.get_player_definition(player_id),
                    self.team_emojis,
                    match.team_for_player(player_id),
                )
                for player_id in injured_ids
            )
            verb = "is" if len(injured_ids) == 1 else "are"
            note += f"\n{injured} {verb} injured and still on the field."

        prompt = await interaction.followup.send(
            self.engine.coaching_prompt(game, match, side, note, lead_in=lead_in),
            file=await self.coaching_file(game, match, side),
            view=(
                CoachingOfferView(self, game.game_id)
                if occasion.asks_declaration
                else CoachingHubView(self, game.game_id)
            ),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt.id
        save_games(self.games)

    async def repost_coaching_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> str:
        """
        Put an already-open Coaching Choice back in front of its coach,
        image and all, without touching the window itself.

        Deliberately not `begin_substitution_window`, which is the
        *opening* of a window: that calls `open_coaching_window` and
        resets the substitution counter, so resuming through it would
        hand a coach back the swaps they had already spent. Everything
        here reads the window as saved.

        The image is re-sent because a Coaching Choice is unreadable
        without it -- exhaustion counts, the Exhausted and Injured
        badges and which bench a player sits on are drawn nowhere else
        (see "Working on the board image" in CLAUDE.md).
        """
        side = TeamSide(match.pending_coaching_side)

        if self.engine.side_is_ai(game, side):
            # No menu to put back up: the AI's window is a routine that
            # runs to completion, and a restart in the middle of one
            # leaves nobody to click anything. Run it, as
            # begin_substitution_window would have.
            await self.run_ai_substitution_window(interaction, game, match)
            return "the AI's Coaching Choice"

        view = (
            CoachingHubView(self, game.game_id)
            if match.pending_coaching_declared
            else CoachingOfferView(self, game.game_id)
        )
        prompt = await interaction.followup.send(
            self.engine.coaching_prompt(
                game,
                match,
                side,
                "Picking this up where it left off. Nothing you "
                "had already done has been undone.",
            ),
            file=await self.coaching_file(game, match, side),
            view=view,
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt.id
        save_games(self.games)
        return "the open Coaching Choice"

    async def resume_pending_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> str:
        """
        Put the game back in front of whoever it is waiting on, and say
        what that was. See `/d12ball resume`.

        A restart only ever re-arms **one** message per game, the one
        recorded in `turn_message_id`, so a game that lost that message
        -- deleted by `close_maneuver_prompt` once both sides had
        picked, or never recorded because the process died before the
        prompt was sent -- comes back with nothing live in its channel
        at all. This posts a new one.

        The states worth separating out are the ones whose next step
        was **the bot's**, not a coach's. A restart mid-cascade is what
        strands a game hardest: `continue_run_back`, the halftime
        sequence and the setup sequence are all driven from a live
        interaction, so a process that dies between two of their steps
        leaves state that nothing will ever pick up and no button to
        press. Each is handed back to the routine that drives it, which
        picks up exactly where it stopped. Everything else owes a
        click, and gets `pending_turn_view` on a fresh message -- the
        same view a restart would have re-attached.

        Nothing here changes the match. That is what `force` is for.
        """
        if match.pending_shootout and not match.pending_injury_tests:
            # Two of the shootout's four steps are the bot's own -- the
            # reveal, and setting the next test up -- so a process that
            # died between them leaves nothing to click. advance_shootout
            # picks up whichever it stopped on. An owed injury check is
            # the exception: that is a button, and it comes first.
            await self.advance_shootout(interaction, game, match)
            return "the extreme shootout"

        if match.pending_coaching_side is not None:
            # Ahead of the three stage checks below: setup, halftime
            # and full time all run their coaching through this same
            # window, and their own routines would re-open it.
            return await self.repost_coaching_prompt(interaction, game, match)

        if match.pending_setup_stage is not None:
            await self.advance_setup_stage(interaction, game, match)
            return "the pre-kickoff Coaching Choice"

        if match.pending_halftime_stage is not None:
            await self.advance_halftime_stage(interaction, game, match)
            return "halftime"

        if match.pending_full_time_stage is not None:
            # The other side's window, or the shootout itself: either
            # way the next step was the bot's, and a process that died
            # between the two coaches left nothing to click.
            await self.advance_full_time_stage(interaction, game, match)
            return "the Coaching Choice before the shootout"

        if match.pending_cede:
            # Both windows have closed -- the branch above would have
            # caught one still open -- so what is left is the tail, and
            # that was the bot's own next step.
            await self.finish_cede(interaction, game, match)
            return "the ceded ball"

        if match.pending_run_back:
            await self.continue_run_back(interaction, game, match)
            return "the run back"

        if match.pending_ball_recovery:
            await self.begin_ball_recovery(interaction, game, match)
            return "the out-of-bounds pickup"

        view, ask = self.pending_turn_view(game.game_id, match)
        prompt = await interaction.followup.send(
            ask,
            view=view,
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt.id
        save_games(self.games)
        return "a choice, re-posted above"




    def coaching_summary(
        self,
        match: MatchState,
        side: TeamSide,
    ) -> list[str]:
        """
        What the open window changed, a line each, for the message it
        closes with. Asked while the window is still open -- closing
        it clears what this reads.

        **Only the shape and the swaps.** Zone assignment and space
        positioning are on the board everyone can see, and the board
        is posted the moment coaching is over; a substitution changes
        who is playing, and a formation change is the shape those
        positions are read against, so both are worth saying in words.
        The substitution notes especially: each one is written over by
        the next step of the flow, so without this they are gone by
        the time the coach clicks Done.
        """
        side = TeamSide(side)
        lines: list[str] = []

        was = match.pending_coaching_formation
        now = self.engine.current_formation(match, side)
        if now is not None and now.value != was:
            lines.append(
                f"Formation: **{was} → {now.value}**."
                if was
                else f"Formation: **{now.value}**."
            )

        for outgoing_player_id, incoming_player_id in (
            match.pending_coaching_swaps
        ):
            outgoing = self.engine.get_player_definition(outgoing_player_id)
            incoming = self.engine.get_player_definition(incoming_player_id)
            lines.append(
                f"{format_role_bracket(incoming, self.team_emojis, match.team_for_player(incoming.player_id))} came "
                f"on for {format_role_bracket(outgoing, self.team_emojis, match.team_for_player(outgoing.player_id))}."
            )

        return lines

    async def run_ai_substitution_window(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        side = TeamSide(match.pending_coaching_side)
        occasion = match.coaching_occasion or CoachingOccasion.NEW_PLAY
        strategy = self.engine.get_ai_strategy(game)
        lines: list[str] = []

        while match.may_substitute():
            choice = strategy.choose_substitution(match, side)
            if choice is None:
                break
            if not match.pending_coaching_declared:
                match.declare_coaching()
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

        covered = self.cover_kickoff_space(match, side)
        if covered:
            lines.append(covered)

        game.match_state = match.to_dict()
        save_games(self.games)

        setup = match.setup_for_side(side)
        prefix = f"{lead_in}\n\n" if lead_in else ""
        if lines:
            body = "\n".join(lines)
            await interaction.followup.send(
                f"{prefix}# Coaching Choice\n"
                f"{format_team_side_label(setup)}:\n{body}"
            )
            # Before kickoff there is no board up yet, deliberately --
            # finish_setup_coaching posts it once both coaches are
            # done, and an AI window is not the moment to break that.
            if match.pending_setup_stage is None:
                await self.refresh_match_image(interaction, game)
        elif lead_in and occasion.spends_declaration:
            # A new play's lead-in is the announcement that opened the
            # window -- the goal, the miss -- and has to be posted
            # whatever the AI decided. Setup's and halftime's are
            # instructions to a coach, so an AI that changed nothing
            # says nothing rather than posting a menu heading with no
            # menu under it.
            await interaction.followup.send(lead_in)

        await self.finish_substitution_window(interaction, game, match)

    def cover_kickoff_space(
        self,
        match: MatchState,
        side: TeamSide,
    ) -> Optional[str]:
        """
        Put one of an AI side's meeples on their own kickoff space when
        nobody is standing on it, and describe the move -- or None when
        there is nothing to do.

        A human coach is refused the Done button until they have
        covered it (see coaching_finish_refusal); the AI has no menu to
        be held in, so it does the same thing here. The kickoff space
        is always in midfield and every basic shape puts at least two
        cards there, so the mover is always somebody whose own zone it
        is.
        """
        side = TeamSide(side)
        if self.engine.coaching_finish_refusal(match, side) is None:
            return None

        setup = match.setup_for_side(side)
        kickoff_index = match.kickoff_space_for(side)
        kickoff_flat = match.board.flat_index(Zone.MIDFIELD, kickoff_index)
        candidates = [
            player_id
            for player_id in setup.field_players
            if setup.assigned_zone(player_id) == Zone.MIDFIELD
        ]
        if not candidates:
            LOGGER.error(
                "No %s card is assigned to midfield, so nobody can take "
                "the kickoff space.",
                side.value,
            )
            return None

        def distance(player_id: str) -> int:
            position = match.board.meeple_position(player_id)
            if position is None:
                return 10**6
            return abs(match.board.flat_index(*position) - kickoff_flat)

        nearest = min(candidates, key=distance)
        match.position_meeple(side, nearest, kickoff_index)
        player = self.engine.get_player_definition(nearest)
        return (
            f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} takes the "
            f"kickoff spot at {space_label(Zone.MIDFIELD, kickoff_index)}."
        )

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
        declared = match.pending_coaching_declared
        was_response = match.pending_coaching_is_response
        occasion = match.coaching_occasion
        side = (
            TeamSide(match.pending_coaching_side)
            if match.pending_coaching_side
            else None
        )
        match.close_coaching_window()
        # Full time records nothing: the window it closes had no
        # positioning in it, and nothing is played from a position
        # again, so writing where the second half left the side would
        # overwrite the coach's arrangement with a scramble no new play
        # will ever restore.
        if (
            declared
            and side is not None
            and (occasion is None or occasion.offers_positioning)
        ):
            match.set_assigned_positions(side)
        game.match_state = match.to_dict()
        save_games(self.games)

        # Setup, halftime and full time give each side its own window
        # rather than a turnover's declare-then-respond pairing, so all
        # three move on to the next stage of their own sequence instead
        # of offering the other side a response.
        if match.pending_full_time_stage is not None:
            self.engine.next_full_time_stage(match)
            game.match_state = match.to_dict()
            save_games(self.games)
            await self.advance_full_time_stage(interaction, game, match)
            return

        if match.pending_setup_stage is not None:
            self.engine.next_setup_stage(match)
            game.match_state = match.to_dict()
            save_games(self.games)
            await self.advance_setup_stage(interaction, game, match)
            return

        if self.engine.halftime_stage(match) in (
            "coaching_home", "coaching_visiting",
        ):
            self.engine.next_halftime_stage(match)
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
            # The reply is the same occasion as the declaration it
            # answers -- a ceded ball opens the other coach's window
            # already declared too, since there is nothing for them to
            # pass on: they have been handed the ball and the window
            # both, and neither costs them anything.
            await self.begin_substitution_window(
                interaction,
                game,
                match,
                other_side,
                occasion=occasion or CoachingOccasion.NEW_PLAY,
                is_response=True,
            )
            return

        if match.pending_cede:
            # Nobody ran anywhere and nothing is displaced: both sides
            # took the field on their own arrangement as their windows
            # opened. So this skips the run back entirely rather than
            # letting it charge for a scramble that never happened.
            await self.finish_cede(interaction, game, match)
            return

        await self.announce_run_back(interaction, game, match)

    # -- Ceding the ball to coach --------------------------------------


    async def begin_cede(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The offense gives the ball up to coach -- see "Ceding the ball"
        in docs/living-rules.md, and `MatchState.may_cede_possession`
        for when it is on offer at all. The caller has acknowledged the
        interaction and is responsible for the prompt the click came
        from.

        It is a turnover with none of a turnover's machinery: the ball
        does not move and nobody runs back, but it costs its flat space
        minute like any other maneuver (2026-08-16) -- charged in
        `finish_cede`, once its tail (a ball recovery may span a
        restart) is settled. What the ceding side is buying is the
        window, so this opens it for them at once, and
        `finish_substitution_window` hands the other coach theirs
        exactly as a declaration's reply -- which is what it is.

        **Under last possession it ends the period instead.** A
        turnover then is the end of the half either way, and ceding is
        a turnover; the window would be a coach rearranging a side that
        has no possession left to play. `pending_cede` is cleared with
        it, or the flag would follow the game into the second half.
        That branch charges the minute itself, since it bypasses
        `finish_cede` entirely -- every turn of last possession is
        charged as usual, this included.
        """
        ceding_side = match.ball.possession
        ceding_label = format_team_side_label(
            match.setup_for_side(ceding_side)
        )
        receiving_side = match.cede_possession()
        receiving_label = format_team_side_label(
            match.setup_for_side(receiving_side)
        )
        game.match_state = match.to_dict()
        save_games(self.games)

        await self.drop_turn_prompt(interaction, game)

        lead_in = (
            f"# {ceding_label} cede the ball\n"
            f"{receiving_label} take possession at "
            f"{space_label(match.ball.zone, match.ball.space_index)}, "
            "where it was given up. The ball speed goes down to **1**."
        )

        if match.scoreboard.last_possession:
            match.pending_cede = False
            match.advance_time(1)
            game.match_state = match.to_dict()
            save_games(self.games)
            await self.end_period(interaction, game, match, lead_in=lead_in)
            return

        await self.refresh_match_image(interaction, game)
        await self.begin_substitution_window(
            interaction,
            game,
            match,
            ceding_side,
            occasion=CoachingOccasion.CEDED,
            lead_in=lead_in,
        )

    async def finish_cede(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The tail of a cede, once both coaches have closed their
        windows. There is no run back to run, and none is owed: each
        window opened on its own coach's arrangement, so by here both
        sides are standing exactly where a new play's reset would have
        put them. That is why the living rules call a cede a new play
        in everything but how it was bought -- it arrives at the same
        board by a different road, and nothing has to re-run the reset
        to make it true.

        What is left is whether anybody is standing on the ball. A
        ceded ball is handed over where it lies, and the side receiving
        it may have nobody there -- their arrangement covers their
        zones, not wherever open play left the ball -- so they send the
        nearest player either side of it, at the usual token a space.
        That is the same thing an out-of-bounds ball asks of the side
        that wins it, for the same reason, so it is the same step.

        `pending_cede` is cleared before either branch: from here on
        the state says what is owed on its own, and leaving it set
        would have `pending_turn_view` answering for a window that has
        closed.
        """
        match.pending_cede = False
        needs_recovery = not match.eligible_ball_handlers()
        match.pending_ball_recovery = needs_recovery
        game.match_state = match.to_dict()
        save_games(self.games)

        if needs_recovery:
            await self.begin_ball_recovery(interaction, game, match)
            return

        # Ceding costs its flat space minute like any other maneuver
        # (2026-08-16). turnover_occurred is true because it is one --
        # it is what makes this the end of the period when last
        # possession was already in force, which begin_cede has caught
        # already and this keeps honest.
        await self.finish_maneuver_resolution(
            interaction,
            game,
            match,
            distance_moved=1,
            turnover_occurred=True,
        )

    async def begin_run_back(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int = 1,
        turnover_occurred: bool = True,
        new_play: bool = False,
        speed_choice_after: bool = False,
        speed_reset: bool = True,
        lead_in: str = "",
    ) -> None:
        """
        `distance_moved`/`turnover_occurred` describe the maneuver that
        triggered this run-back, stashed on `match` so they survive the
        multi-turn choice flow and reach finish_maneuver_resolution
        correctly once run-back itself (which only ever costs
        exhaustion, never time) is done.

        `speed_reset` is announce_run_back's own note, and only ever
        False for Dribble Burst's cost: every caller here has already
        set `match.ball.speed` to whatever it should read by the time
        this runs, so this is wording, not state -- it says whether
        that was a reset to 1 (every other turnover) or the burst's
        speed carrying over (see the comment on `advanced_cost`).

        `new_play` says the ball changed hands because play stopped and
        is restarting -- a goal, an own goal, a missed attempt, a ball
        out of bounds -- rather than because the other team took it off
        them. Only a new play opens a substitution window; a steal
        (Steal, a Defender's Pressure steal, a loose ball or
        a long High Pass the other side wins) runs everyone back and
        plays straight on. See "Steals and new plays",
        docs/living-rules.md. It is not persisted: it is consumed here,
        and by the time anything is saved the state already says which
        of the two happened -- a window open, or a run back pending.

        **The player holding the ball does not run back**, whoever they
        are -- see "Choosing the handler" and "Running back after a
        steal"
        in docs/living-rules.md. The exemption is read off
        `ball_carrier_id` rather than passed in, because the two are
        the same fact: a run back that moved the ball's holder would
        run them off the ball and charge them for it. It used to be a
        `stays_player_id` argument that only Steal and a
        Defender's Pressure steal passed, which left a loose-ball or
        High Pass winner -- equally the holder -- being run back off
        the ball they had just won.

        A new play exempts nobody: the ball went dead, so nobody is
        carrying it, and the reset that follows moves both sides
        whatever they were doing.

        `speed_choice_after` is set only for Steal -- once
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
        own state change (e.g. Steal's turnover and 1-space
        fallback) has already been applied and saved by the caller,
        this just skips everything downstream of that. The maneuver
        that *declares* last possession is not that turnover and isn't
        caught here: its own clock advance happens later, in
        finish_maneuver_resolution, so it runs back like any other.

        A resolution that left possession where it was doesn't run a
        run-back at all: "every time there's a turnover for any
        reason (steal, goal etc.) players have to run back" is the
        whole of when one happens ("Turnovers, resets, and running back",
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

        if new_play:
            # The ball is dead. Clearing here as well as in
            # announce_new_play_reset is what keeps the exemption below
            # honest: a goal scored off a High Pass set-up leaves the
            # receiver still recorded as carrying it, and they are not
            # -- the ball is on its way back to the kickoff space.
            match.clear_ball_carrier()

        match.pending_run_back = True
        match.pending_run_back_distance = distance_moved
        match.pending_run_back_turnover = turnover_occurred
        match.pending_run_back_stays_player_id = match.ball_carrier_id
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
            if match.may_declare_coaching(winning_side):
                await self.begin_substitution_window(
                    interaction, game, match, winning_side,
                )
                return

        await self.announce_run_back(
            interaction, game, match, lead_in, speed_reset=speed_reset,
        )

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
        # The ball went dead and is being brought back into play, so
        # nobody is carrying it -- whoever ends up on it chooses.
        match.clear_ball_carrier()
        # **A new play is the one thing that ends a Double Team**, and
        # the card says so outright: "so long as it's not a new play,
        # on their next maneuver, both defending players challenge".
        # Cleared here rather than in `reset_maneuver`, which runs at
        # the end of every turn -- including the turn that set it.
        match.pending_double_team = []
        moved: list[str] = []
        for side in (TeamSide.HOME, TeamSide.VISITING):
            for player_id, zone, space_index in (
                match.restore_assigned_positions(side)
            ):
                player = self.engine.get_player_definition(player_id)
                moved.append(
                    f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} to "
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
        speed_reset: bool = True,
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
        # Speed manipulation (Steal) always happens after
        # run-back now, so a turnover's ball speed is still at its
        # reset value of 1 here -- except Dribble Burst's cost, whose
        # caller passes speed_reset=False because the ball kept the
        # burst's own speed instead, and that is already said in the
        # lead-in this note would otherwise contradict.
        speed_note = (
            "The ball speed goes down to **1**."
            if turnover_occurred and speed_reset
            else ""
        )
        displaced = any(
            self.engine.run_back_movers(match, side)
            for side in (TeamSide.HOME, TeamSide.VISITING)
        )
        if displaced:
            await interaction.followup.send(
                f"{prefix}# Players run back!\n"
                "Players return to an open space in their assigned zone and "
                "gain 1 exhaustion token for every space traveled. Forced "
                "moves are handled automatically; where there is a choice — "
                "which space, or which of two teammates sharing one — the "
                f"coach is asked. {speed_note}"
            )
        elif prefix or speed_note:
            await interaction.followup.send(f"{prefix}{speed_note}".strip())
        await self.continue_run_back(interaction, game, match)





    def run_back_space_prompt(
        self,
        match: MatchState,
        side: TeamSide,
        player_id: str,
        mention: str,
    ) -> str:
        """
        Where does this player run back to -- the question every run
        back ends on, whether the player was displaced or has just been
        picked out of a stack. It is a function rather than a string at
        the call site because those are two different places now: the
        cascade asks it directly, and RunBackPlayerChoiceView asks it
        again over the top of its own answer, and the two have to word
        it identically.
        """
        player = self.engine.get_player_definition(player_id)
        return (
            f"{mention}, choose where "
            f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} runs back "
            f"to:\n{self.engine.describe_run_back_options(match, side, player_id)}"
        )

    def run_back_player_prompt(
        self,
        match: MatchState,
        side: TeamSide,
        candidates: list[str],
        mention: str,
    ) -> str:
        """
        Which of a stack runs back, and where each of them is standing
        -- a coach choosing between two teammates on one space is
        choosing which of them pays for the walk, so the prompt says
        who they are rather than leaving it to the buttons alone.
        """
        lines = []
        for player_id in candidates:
            player = self.engine.get_player_definition(player_id)
            position = match.board.meeple_position(player_id)
            lines.append(
                f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} on "
                f"{space_label(*position)}"
                if position is not None
                else format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))
            )
        return (
            f"{mention}, your players are doubled up while their zone "
            "still has a space with nobody on it — choose which of them "
            "runs back:\n" + "\n".join(lines)
        )



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

        async def flush(png: Optional[bytes] = None) -> bool:
            """
            Post the automatic placements so far, with the board they
            produced. True when there was something to post.

            `png` is an already-rendered board, for the caller that is
            about to upload the same one onto the prompt below.
            """
            nonlocal lead_in, notes

            if not notes:
                return False

            prefix = f"{lead_in}\n\n" if lead_in else ""
            body = "\n".join(notes)
            notes = []
            lead_in = ""
            await interaction.followup.send(f"{prefix}{body}")
            await self.refresh_match_image(interaction, game, png=png)
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

            self.engine.apply_forced_run_backs(match)
            game.match_state = match.to_dict()
            save_games(self.games)

            step = self.engine.next_run_back_step(match)

            if step is not None:
                side, candidates = step

                if self.engine.side_is_ai(game, side):
                    # One candidate is a settled player and only the
                    # space is open; several is a stack Dinky picks out
                    # of, the same call a coach is given below.
                    player_id = (
                        candidates[0]
                        if len(candidates) == 1
                        else self.engine.get_ai_strategy(
                            game
                        ).choose_run_back_player(match, candidates)
                    )
                    zone = match.setup_for_side(side).assigned_zone(player_id)
                    player = self.engine.get_player_definition(player_id)
                    space_index = self.engine.get_ai_strategy(
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
                        f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} "
                        f"runs back to {space_label(zone, space_index)}."
                        f"\n{exhaustion_text}"
                    )
                    continue

                # A coach's choice ends the cascade here: say what has
                # happened so far, show the board it left, and ask --
                # with the board on the prompt itself, because both
                # questions a run back asks (which of these players
                # goes, and which space they go to) are questions about
                # where everybody is standing, and the persistent
                # message has scrolled away up the channel by the time
                # a turn has resolved. It goes with the prompt: the
                # click edits both away together, so the board a coach
                # is reading is never one of a position that has moved
                # on.
                #
                # One render, two uploads -- the same board settles the
                # persistent message, exactly as announce_board_update
                # does. See "Discord's rate limits" in CLAUDE.md.
                png = await self.render_match_png(game)
                if not await flush(png):
                    await self.refresh_match_image(interaction, game, png=png)

                controller_id = self.engine.side_controller_id(game, side)
                mention = f"<@{controller_id}>" if controller_id else "Someone"
                prefix = f"{lead_in}\n\n" if lead_in else ""

                # A stack asks who before it asks where, and the two
                # share one message: the second question is an edit of
                # the first, which keeps the board that was uploaded
                # for it rather than paying for a second one. See
                # RunBackPlayerChoiceView.
                if len(candidates) == 1:
                    prompt_view = RunBackChoiceView(
                        self, game.game_id, candidates[0],
                    )
                    body = self.run_back_space_prompt(
                        match, side, candidates[0], mention,
                    )
                else:
                    prompt_view = RunBackPlayerChoiceView(
                        self, game.game_id, candidates,
                    )
                    body = self.run_back_player_prompt(
                        match, side, candidates, mention,
                    )

                prompt_message = await interaction.followup.send(
                    f"{prefix}{body}",
                    file=self.match_file_from_png(game, png),
                    view=prompt_view,
                    wait=True,
                    allowed_mentions=discord.AllowedMentions(
                        users=True, roles=False, everyone=False,
                    ),
                )
                # The view has to be handed over with the link, or the
                # edit that adds it drops the buttons this prompt is
                # for -- see add_full_image_button. Both go when the
                # choice is made.
                await add_full_image_button(prompt_message, prompt_view)
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
                    player = self.engine.get_player_definition(player_id)
                    distance = match.fill_kickoff(player_id)
                    exhaustion_text = self.apply_exhaustion(
                        match, player_id, distance,
                    )
                    game.match_state = match.to_dict()
                    save_games(self.games)

                    notes.append(
                        f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} "
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
            # that won it sends the nearest player either side of it,
            # at the usual per-space cost.
            await self.begin_ball_recovery(
                interaction, game, match, lead_in=lead_in,
            )
            return

        if speed_choice_after:
            # Steal: the defender who stole the ball still
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
        Ask the side that won an out-of-bounds or ceded ball which of
        their players goes and stands on it: the nearest either side of
        it, from any zone, at one exhaustion token per space traveled.
        It is the same choice a loose ball and a challenge put, and
        since 2026-08-16 it is the same pool -- it used to offer the
        whole field, which is a distance sum the coach had to do off
        the board.

        Deliberately the last thing that happens: both callers reset
        everyone to their arrangement first, so this player is placed
        once and stays, where placing them before it would only have
        them run back off the ball and leave it loose all over again.

        **Which is also why it asks whether there is anything to do.**
        A reset can perfectly well put one of the gaining side on the
        ball's space by itself -- that is the arrangement's own doing,
        and the rules ask for a pickup "unless one of theirs is
        already on it". `finish_cede` decides this before it sets the
        flag, because it has a second branch to run either way; the
        out-of-bounds path sets the flag before the reset, so the
        question can only be asked here.
        """
        side = match.ball.possession
        candidates = (
            [] if match.eligible_ball_handlers()
            else match.contest_candidates(side)
        )
        if not candidates:
            # Somebody of theirs is already standing on it, or nobody
            # is fielded at all. Either way nothing is placed: let the
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

        if self.engine.side_is_ai(game, side):
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
            f"{prefix}{mention}, everyone is back in position -- send "
            "the nearest player either side of the ball to pick it up "
            f"at {space_label(match.ball.zone, match.ball.space_index)}:",
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
        player = self.engine.get_player_definition(player_id)
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
            f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} picks the "
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

        The maneuver that reaches the period's last minute never ends it,
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
            # The minute is the period's own, and the clock does not
            # stop on it: from here every turn is charged as usual and
            # only the turnover ends the period.
            await interaction.followup.send(
                f"{prefix}The clock reaches "
                f"{match.scoreboard.last_minute:02d} -- this is now "
                f"**last possession**. {body} The clock keeps running."
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
        # Every maneuver costs at least its flat space minute
        # (2026-08-16), ceding included, so there is no longer a
        # zero-cost turn to word specially here.
        clock = (
            f"Time has advanced {distance_moved}, now "
            f"at {match.scoreboard.time:02d}."
        )
        snapshot = await interaction.followup.send(
            content=(
                f"{prefix}Ball is now "
                f"{space_label(match.ball.zone, match.ball.space_index)}, "
                f"{format_team_side_label(match.setup_for_side(match.ball.possession))} "
                f"has possession. {clock}"
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
        second half, or end the game at full time -- which, on a level
        score, means opening the [extreme shootout](begin_shootout)
        rather than finishing anything.
        """
        prefix = f"{lead_in}\n\n" if lead_in else ""

        # The turnover that ends a period is the one carry that must
        # not survive it: a Steal under last possession names
        # a carrier, and the second half kicks off from the coaches'
        # arrangement with nobody holding anything.
        match.clear_ball_carrier()

        if match.scoreboard.period == MatchPeriod.FIRST_HALF:
            first_half_ended_at = match.scoreboard.time
            match.scoreboard.period = MatchPeriod.SECOND_HALF
            # The second half starts at 16 however far past 15 the
            # first half ran, so the number on the clock means the same
            # thing in every game. It is set here rather than at the
            # kickoff for the reason everything else in this branch is:
            # halftime is played with the second half's board already
            # on the scoreboard.
            match.scoreboard.time = SECOND_HALF_START_MINUTE
            match.scoreboard.last_possession = False
            # A declaration is once every half, so both sides get
            # theirs back -- including a side that had to spend the
            # first half's on an injury. Their two substitutions for
            # the half come back with it; halftime's own two are
            # counted separately and are not touched here.
            match.declared_substitution.clear()
            match.half_substitutions_used.clear()
            match.close_coaching_window()
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
                f"{prefix}**End of the first half!** The ball turns over "
                f"at {first_half_ended_at:02d} under last possession -- "
                "the period ends. The second half starts at "
                f"{SECOND_HALF_START_MINUTE:02d}."
            )
            await self.refresh_match_image(interaction, game)
            await self.begin_halftime(interaction, game, match)
            return

        match.reset_maneuver()
        game.match_state = match.to_dict()
        save_games(self.games)

        whistle = (
            f"{prefix}**Full time!** The ball turns over at "
            f"{match.scoreboard.time:02d} under last possession -- the "
            "game ends.\n\n"
            f"{build_full_time_summary(game, match)}"
        )

        if match.scoreboard.home_score == match.scoreboard.visiting_score:
            # Level, so nothing is finished: the summary above says the
            # game goes to the shootout, and the shootout is what ends
            # it -- the game record stays in progress until then, so a
            # restart mid-shootout comes back to a live game. One
            # substitution a side comes first.
            await interaction.followup.send(whistle)
            await self.refresh_match_image(interaction, game)
            await self.begin_full_time_coaching(interaction, game, match)
            return

        game.finish_game()
        save_games(self.games)

        # No refresh of its own: announce_game_over settles the
        # persistent message from the board it posts.
        await self.announce_game_over(
            interaction, game, f"{whistle}\n\n{self.build_goal_log(match)}"
        )

    def build_goal_log(self, match: MatchState) -> str:
        """
        The scoresheet, with this cog's roster and emoji behind it.

        It is built by the callers of announce_game_over rather than
        inside it, because that function is handed a string and has no
        match: the whistle and the shootout each already hold one, and
        passing it in would be for this alone.
        """
        return build_goal_log(match, self.player_catalog, self.team_emojis)

    async def announce_game_over(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        content: str,
    ) -> None:
        """
        The last message of a game: the result, the board the game
        ended on, and the rematch and archive buttons under it. Both
        endings post it -- the whistle when full time settles the game,
        and the shootout when it does not.

        The final board rides on this message rather than being left to
        the persistent one, for the reason a loose ball's does (see
        announce_board_update): by full time the persistent message has
        scrolled hours up the channel, and the result is exactly the
        thing nobody should have to go looking for the position of. It
        is the same render-once-upload-twice -- the persistent message
        is settled from these bytes -- so the callers no longer refresh
        it themselves. It is deliberately *not* pinned: pinning stays
        the new play's alone, and a pin here would be the one at the
        very bottom of a channel nobody is playing in any more.
        """
        view = RematchView(self, game.game_id)
        png = await self.render_match_png(game)
        final = await interaction.followup.send(
            content,
            file=self.match_file_from_png(game, png),
            view=view,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
            wait=True,
        )
        # Handed the view, or the edit that adds the link drops the two
        # buttons this message exists for.
        await add_full_image_button(final, view)
        # Remembered so the buttons come back after a restart: the
        # channel stays where it is until someone clicks one, which can
        # be days later.
        game.rematch_message_id = final.id
        save_games(self.games)
        await self.refresh_match_image(interaction, game, png=png)

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
                player = self.engine.get_player_definition(player_id)
                defense_skill = self.player_catalog.effective_profile(
                    player
                ).defense
                removed = match.recover_exhaustion(player_id, 1, defense_skill)
                if removed:
                    remaining = match.exhaustion.get(player_id, 0)
                    recovery_lines.append(
                        f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} "
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

    async def begin_setup_coaching(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        """
        Offer both coaches a Coaching Choice before kickoff, home
        first -- see "Setup" in docs/living-rules.md. Both
        teams are dealt the standard 2-2-2 and, in basic mode, dealt
        identically; this is where a coach may change any of it rather
        than waiting for their first window.

        Substitutions here are unlimited and a player taken off goes
        back to the bench: nobody has played, so nothing is used up.
        A coach happy with the deal finishes without changing anything.
        """
        match = self.engine.load_match_state(game)

        # A tutorial kicks off on the standard deal. The Coaching
        # Choice is the most involved menu in the game and the script
        # explains it at beat 6, on the window a real new play offers;
        # putting a coach through it before they have seen a turn is
        # asking them to rearrange a board they cannot read yet. It
        # costs them nothing -- both sides are dealt the same 2-2-2,
        # and the tutorial re-deals both of them every beat anyway.
        if game.tutorial:
            match.pending_setup_stage = None
            game.match_state = match.to_dict()
            save_games(self.games)
            await self.finish_setup_coaching(interaction, game, match)
            return

        match.pending_setup_stage = SETUP_STAGES[0]
        game.match_state = match.to_dict()
        save_games(self.games)
        await self.advance_setup_stage(interaction, game, match)


    async def advance_setup_stage(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """Hand the next coach their pre-kickoff Coaching Choice, or
        kick off."""
        stage = match.pending_setup_stage
        if stage in ("coaching_home", "coaching_visiting"):
            side = (
                TeamSide.HOME
                if stage == "coaching_home"
                else TeamSide.VISITING
            )
            setup = match.setup_for_side(side)
            await self.begin_substitution_window(
                interaction,
                game,
                match,
                side,
                occasion=CoachingOccasion.SETUP,
                lead_in=(
                    f"## Before kickoff\n{format_team_side_label(setup)} "
                    "set their line-up. Substitutions are unlimited here "
                    "and anyone taken off goes back to the bench -- the "
                    "game has not started, so nothing is used up."
                ),
            )
            return

        await self.finish_setup_coaching(interaction, game, match)

    async def finish_setup_coaching(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Both coaches are done, so the game can start -- and this is
        where the board first goes up. Nothing has been played yet, so
        a board posted before the windows would show a deal neither
        coach had finished with, and be redrawn twice over before
        anyone acted on it; the one worth looking at is the line-up the
        game actually kicks off from.

        A kickoff is a new play, so it posts its board the way every
        other one does: as its own message, under the coaching it came
        out of. It used to attach the board to the persistent message
        instead, which is a message near the top of the channel -- and
        Discord leaves an edited message where it was, so the board a
        coach had just finished setting appeared *above* the windows
        that set it, looking for all the world like the board had gone
        up before kickoff coaching rather than after it.
        """
        match.pending_setup_stage = None
        game.match_state = match.to_dict()
        save_games(self.games)

        kicking_off = match.setup_for_side(match.ball.possession)
        await self.post_new_play_board(
            interaction,
            game,
            (
                "**The teams are dealt.** The game kicks off with "
                f"{format_team_side_label(kicking_off)} in possession."
                if game.tutorial
                else "**Both coaches are set.** The game kicks off with "
                f"{format_team_side_label(kicking_off)} in possession."
            ),
        )

        # The script arms here rather than at creation, so everything
        # up to the kickoff -- teams, the toss, home or visiting -- is
        # played exactly as an ordinary game plays it. The welcome goes
        # under the board it describes; the first beat is staged by the
        # send_turn_prompt below.
        if game.tutorial:
            game.tutorial_step = tutorial.FIRST_STEP
            game.tutorial_staged = False
            save_games(self.games)
            await interaction.followup.send(tutorial.WELCOME)

        try:
            await self.send_turn_prompt(interaction, game)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)

    async def advance_halftime_stage(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """Dispatch to whichever halftime stage comes next, or finish."""
        stage = self.engine.halftime_stage(match)
        if stage == "extra_token_home":
            await self.begin_halftime_extra_token(
                interaction, game, match, TeamSide.HOME,
            )
        elif stage == "extra_token_visiting":
            await self.begin_halftime_extra_token(
                interaction, game, match, TeamSide.VISITING,
            )
        elif stage == "coaching_home":
            await self.begin_halftime_substitutions(
                interaction, game, match, TeamSide.HOME,
            )
        elif stage == "coaching_visiting":
            await self.begin_halftime_substitutions(
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
            self.engine.next_halftime_stage(match)
            game.match_state = match.to_dict()
            save_games(self.games)
            await self.advance_halftime_stage(interaction, game, match)
            return

        if self.engine.side_is_ai(game, side):
            player_id = max(
                eligible, key=lambda pid: match.exhaustion.get(pid, 0),
            )
            defense_skill = self.player_catalog.effective_profile(
                self.engine.get_player_definition(player_id)
            ).defense
            removed = match.recover_exhaustion(player_id, 1, defense_skill)
            self.engine.next_halftime_stage(match)
            game.match_state = match.to_dict()
            save_games(self.games)

            if removed:
                player = self.engine.get_player_definition(player_id)
                remaining = match.exhaustion.get(player_id, 0)
                await interaction.followup.send(
                    f"{format_team_side_label(setup)} removes an extra "
                    "exhaustion token from "
                    f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} "
                    f"(now {remaining})."
                )
                await self.refresh_match_image(interaction, game)
            await self.advance_halftime_stage(interaction, game, match)
            return

        controller_id = self.engine.side_controller_id(game, side)
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
            occasion=CoachingOccasion.HALFTIME,
            lead_in=(
                f"## Halftime\n{format_team_side_label(setup)} set up for "
                "the second half. Halftime is free: it leaves their "
                "own once-a-half Coaching Choice unspent, and its two "
                "substitutions are its own rather than either half's."
            ),
        )

    async def finish_halftime(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The last step of halftime -- the visiting kickoff-space
        guarantee is already enforced before this is reached (see
        coaching_finish_refusal), so this just clears the halftime flag
        and hands play to the second half.
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

    # -- The window before the shootout --------------------------------

    async def begin_full_time_coaching(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The last Coaching Choice of a level game, one to each coach
        before the shootout opens -- see "Full time" in
        docs/living-rules.md. **One substitution and nothing else**: a
        shootout is played by who is on the field and by nothing about
        where they stand, so the three positional actions would
        rearrange a side that never plays from a position again.

        Home go first, which is the author's call rather than anything
        the position decides: nobody kicks off here, so the reason
        setup and halftime have an order does not apply.

        It runs as a stage sequence for the same reason halftime does:
        two windows one after the other are two live interactions with
        the bot's own step between them, and a restart in the middle
        has nothing to click. `pending_full_time_stage` is what a
        restart reads.
        """
        match.pending_full_time_stage = FULL_TIME_STAGES[0]
        game.match_state = match.to_dict()
        save_games(self.games)
        await self.advance_full_time_stage(interaction, game, match)


    async def advance_full_time_stage(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """Hand the next coach their one substitution, or shoot out."""
        stage = match.pending_full_time_stage
        if stage in ("coaching_home", "coaching_visiting"):
            side = (
                TeamSide.HOME
                if stage == "coaching_home"
                else TeamSide.VISITING
            )
            # A menu whose only action is disabled is a Done button
            # with extra steps, and this window has no other action to
            # fall back on -- so a side with nobody it could bring on
            # is passed over in silence, the way halftime passes over a
            # side with nobody to take an extra token off. It takes
            # both benches spent: three substitutions to drain the
            # bench, and every one of the three who came off injured.
            if not match.substitution_pool(side):
                self.engine.next_full_time_stage(match)
                game.match_state = match.to_dict()
                save_games(self.games)
                await self.advance_full_time_stage(interaction, game, match)
                return

            setup = match.setup_for_side(side)
            await self.begin_substitution_window(
                interaction,
                game,
                match,
                side,
                occasion=CoachingOccasion.FULL_TIME,
                lead_in=(
                    f"## Before the shootout\n{format_team_side_label(setup)} "
                    "may make **one substitution** -- the last change "
                    "either side gets. Nothing else is offered: the "
                    "shootout is played by whoever is on the field, and "
                    "not by where they are standing."
                ),
            )
            return

        await self.finish_full_time_coaching(interaction, game, match)

    async def finish_full_time_coaching(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """Both coaches are done, so the shooting can start."""
        match.pending_full_time_stage = None
        game.match_state = match.to_dict()
        save_games(self.games)
        await self.begin_shootout(interaction, game, match)

    # -- The extreme shootout ------------------------------------------

    async def begin_shootout(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Open the shootout that settles a game level at full time. See
        "Extreme shootout" in docs/living-rules.md.

        The shootout is **four steps that hand back to each other**,
        and `advance_shootout` is the single reading of which one a
        saved game is on -- the same job `pending_turn_view` does for
        a turn, and for the same reason: two of the four are the
        bot's own move, so a restart between them has no button
        anywhere to press.
        """
        match.begin_shootout()
        game.match_state = match.to_dict()
        save_games(self.games)

        await interaction.followup.send(
            "# Extreme shootout\n"
            "The scores are level, so the game is settled on the "
            "extreme shootout.\n\n"
            "Each coach secretly puts their **six field players** in "
            "the order they will shoot. Both sides then reveal their "
            "top card together and those two players roll a **skill "
            "test**, each adding their offensive skill -- an injured "
            "player adds none and rolls the bare d12. The winner "
            "scores a goal; a tie scores for nobody. Six skill tests "
            "is a **round**, and a level round goes to sudden death."
        )
        await self.advance_shootout(interaction, game, match)

    async def advance_shootout(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Put the shootout's next step in front of whoever owes it.

        Everything routes through here -- opening the shootout, the
        end of a skill test, and `/d12ball resume` -- so there is one
        answer to "what is this shootout waiting on?" and no way for
        the resume to offer a different step from the one a restart
        restores. `pending_turn_view` reads the same three states off
        the same three questions.
        """
        if not match.shootout_orders_complete:
            await self.ask_shootout_orders(interaction, game, match)
            return

        if not match.shootout_shooters_complete:
            await self.ask_shootout_shooters(interaction, game, match)
            return

        await self.reveal_shootout_test(interaction, game, match)

    async def ask_shootout_orders(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The secret ordering both coaches do before the first test. An
        AI side sets its own here and now, so a solo game only ever
        waits on the one coach who has a choice to make.
        """
        for side in (TeamSide.HOME, TeamSide.VISITING):
            if match.shootout_order_complete(side):
                continue
            if not self.engine.side_is_ai(game, side):
                continue
            match.set_shootout_order(
                side,
                self.engine.get_ai_strategy(game).choose_shootout_order(
                    match.shootout_squad(side),
                ),
            )

        game.match_state = match.to_dict()
        save_games(self.games)

        if match.shootout_orders_complete:
            await self.reveal_shootout_test(interaction, game, match)
            return

        owing = [
            side
            for side in (TeamSide.HOME, TeamSide.VISITING)
            if not match.shootout_order_complete(side)
        ]
        await self.post_shootout_prompt(
            interaction,
            game,
            match,
            f"{self.engine.shootout_mentions(game, match, owing)}: set the "
            "order your six players shoot in. Nobody else sees it.",
            ShootoutOrderPromptView(self, game.game_id),
            # Nobody has shot, so the usual "skill test 1 of 6, 0 — 0"
            # is a scoreline with nothing in it yet.
            heading="### Extreme shootout",
        )

    async def ask_shootout_shooters(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Sudden death's pick. Only ever reached in a round past the
        first: the first round's shooter is read off the order, so
        there is nothing to ask for and nothing to lose in a restart.
        """
        for side in (TeamSide.HOME, TeamSide.VISITING):
            if match.shootout_shooter(side) is not None:
                continue
            if not self.engine.side_is_ai(game, side):
                continue
            match.set_shootout_shooter(
                side,
                self.engine.get_ai_strategy(game).choose_shootout_shooter(
                    match.shootout_eligible(side),
                ),
            )

        game.match_state = match.to_dict()
        save_games(self.games)

        if match.shootout_shooters_complete:
            await self.reveal_shootout_test(interaction, game, match)
            return

        owing = [
            side
            for side in (TeamSide.HOME, TeamSide.VISITING)
            if match.shootout_shooter(side) is None
        ]
        await self.post_shootout_prompt(
            interaction,
            game,
            match,
            f"{self.engine.shootout_mentions(game, match, owing)}: choose who "
            "goes out next, from the players who have not shot yet "
            "this round. Nobody else sees it until the reveal.",
            ShootoutPickPromptView(self, game.game_id),
        )

    async def post_shootout_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        content: str,
        view: discord.ui.View,
        heading: Optional[str] = None,
    ) -> None:
        prompt = await interaction.followup.send(
            f"{heading or self.engine.shootout_heading(match)}\n{content}",
            view=view,
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt.id
        save_games(self.games)





    def shootout_order_text(
        self,
        match: MatchState,
        side: TeamSide,
    ) -> str:
        """The order a coach has built so far, on their own menu."""
        lines = []
        for position, player_id in enumerate(
            match.shootout_order(side), start=1,
        ):
            player = self.engine.get_player_definition(player_id)
            note = " — injured" if player_id in match.injured else ""
            lines.append(
                f"{position}. "
                f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))}{note}"
            )

        if match.shootout_order_complete(side):
            header = (
                "**Your shooting order is set.** You may look at it, "
                "but not reorder it."
            )
        elif lines:
            header = "Keep going -- click the next player to shoot."
        else:
            header = (
                "Click your six players in the order they shoot. Only "
                "you can see this."
            )

        return "\n".join([header, *lines])

    async def reveal_shootout_test(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Both top cards, turned over together, and the button that
        rolls them against each other. Either coach may press it, like
        every other roll in the game.
        """
        lines = []
        for side in (TeamSide.HOME, TeamSide.VISITING):
            shooter_id = match.shootout_shooter(side)
            if shooter_id is None:
                # Nothing to reveal means the state moved under us --
                # advance_shootout is the only way back in.
                await self.advance_shootout(interaction, game, match)
                return
            player = self.engine.get_player_definition(shooter_id)
            note = (
                " — injured, no skill modifier"
                if shooter_id in match.injured
                else ""
            )
            lines.append(
                f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))}{note}"
            )

        prompt = await interaction.followup.send(
            f"{self.engine.shootout_heading(match)}\n"
            f"{lines[0]}\nversus\n{lines[1]}\n\nEither player can roll:",
            view=ShootoutTestView(self, game.game_id),
            wait=True,
        )
        game.turn_message_id = prompt.id
        save_games(self.games)

    async def close_shootout_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        """
        Drop the "set your order" or "choose your shooter" prompt once
        both sides have answered it. Its button has nothing left to
        open, and the reveal posted underneath it is what the channel
        should end on -- the same reasoning as close_maneuver_prompt,
        including clearing `turn_message_id` so nothing re-attaches a
        view to a message that is gone.
        """
        if game.turn_message_id is None or interaction.channel is None:
            return

        try:
            await interaction.channel.get_partial_message(
                game.turn_message_id,
            ).delete()
        except (discord.NotFound, discord.HTTPException):
            pass

        game.turn_message_id = None
        save_games(self.games)

    async def continue_shootout(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        What a settled skill test hands back to: end the shootout, or
        set the next test up.

        The test has already retired its two shooters by the time this
        runs (`finish_shootout_test`, in the same save as the goal),
        which is what lets `shootout_winner` count the tests still to
        come simply by asking who is left.
        """
        winner = match.shootout_winner()
        if winner is None:
            await self.advance_shootout(interaction, game, match)
            return

        match.pending_shootout = False
        game.match_state = match.to_dict()
        save_games(self.games)
        game.finish_game()
        save_games(self.games)

        home = match.shootout_goals_for(TeamSide.HOME)
        visiting = match.shootout_goals_for(TeamSide.VISITING)
        await self.announce_game_over(
            interaction,
            game,
            f"**The extreme shootout is settled, {home}-{visiting}.**"
            f"\n\n{build_full_time_summary(game, match)}"
            f"\n\n{self.build_goal_log(match)}",
        )

    async def close_maneuver_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Delete the public "choose your maneuver" prompt once every
        side it was waiting on has picked: its button has nothing left
        to open, and the resolution posted underneath it is what the
        channel should end on. An uncontested maneuver is waiting on
        the offense alone, so its prompt goes on that one pick.

        Until then it is left alone. It used to be re-edited with a
        fresh `ManeuverActionPromptView` on each pick, which changed
        nothing a coach could see -- the message says who it is waiting
        on and both sides share one button, so the prompt reads the
        same after one pick as before it, and the view is built from
        the game id alone. That edit was a request out of the tightest
        bucket in the game (see "Discord's rate limits" in CLAUDE.md),
        spent once a maneuver, immediately before the resolution's own
        board refresh, for nothing. Who has picked is announced in its
        own message.

        Deleting clears `turn_message_id` with it, so nothing tries to
        edit or re-attach a view to a message that is gone; whatever
        prompt the resolution posts next sets its own.
        """
        if game.turn_message_id is None or interaction.channel is None:
            return

        if not match.maneuver_selections_complete:
            return

        try:
            await interaction.channel.get_partial_message(
                game.turn_message_id,
            ).delete()
        except (discord.NotFound, discord.HTTPException):
            pass

        game.turn_message_id = None
        save_games(self.games)


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
        player = self.engine.get_player_definition(player_id)
        if player_id in match.injured:
            return (
                f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} is injured "
                f"{get_injured_emoji(self.condition_emojis)} and gains no "
                "exhaustion tokens."
            )
        if amount <= 0:
            return (
                f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} was "
                "already there -- no exhaustion cost."
            )

        exhaust_emoji = get_exhaust_emoji(self.condition_emojis)
        total = match.exhaustion.get(player_id, 0)
        token_word = "token" if amount == 1 else "tokens"
        text = (
            f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} gains {amount} exhaustion "
            f"{token_word} {exhaust_emoji * amount} (now {total} total)."
        )

        defense_skill = self.player_catalog.effective_profile(player).defense
        if self.engine.retest_exhausted(match, player_id):
            exhausted_emoji = get_exhausted_emoji(self.condition_emojis)
            text += (
                f"\n{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} now has the condition "
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

        defender = self.engine.get_player_definition(defender_id)
        space_word = "space" if distance == 1 else "spaces"
        return (
            f"{defender.name} has moved {distance} {space_word}."
            f"\n{self.describe_exhaustion_gain(match, defender_id, distance)}"
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
                self.engine.challenge_side(
                    match.active_player_id,
                    match.team_for_player(match.active_player_id),
                    attacking=True,
                ),
                self.engine.challenge_side(
                    defender_id,
                    match.team_for_player(defender_id),
                    attacking=False,
                ),
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

        The defenders are the other way round: what each one adds is
        folded in, as their `contribution`, because a coach counting
        the wall is asking what it comes to and not what it would come
        to somewhere else on the field.
        """
        shooter = self.engine.get_player_definition(match.active_player_id)
        speed_modifier = match.ball_speed_modifier()
        defenders = self.engine.intervening_defenders(match)
        defending_setup = match.setup_for_side(match.defending_side())

        modifiers = []
        if speed_modifier:
            modifiers.append(
                f"{speed_modifier:+d} ball speed ({match.ball.speed})"
            )
        if match.pending_shot_is_set_up and shooter.role == PlayerRole.STRIKER:
            modifiers.append("+3 Striker ability")

        return discord.File(
            await asyncio.to_thread(
                render_score_attempt,
                self.engine.challenge_side(
                    shooter.player_id,
                    match.team_for_player(shooter.player_id),
                    attacking=True,
                    modifiers=tuple(modifiers),
                ),
                [
                    self.engine.challenge_side(
                        defender.player.player_id,
                        match.team_for_player(defender.player.player_id),
                        attacking=False,
                        contribution=defender.value,
                        halved=not defender.on_ball,
                    )
                    for defender in defenders
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
        close_maneuver_prompt drops the maneuver prompt once both
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

        A write already in flight does not stand in for a request that
        arrives during it. Drawing and uploading a board is most of a
        second, and the state the caller wants on the message changed
        after that render began -- so this asks for a trailing pass
        rather than assuming it is covered, and takes
        `board_refresh_locks` for the write itself so two edits can
        never be in the air on one message at once. That is the pair of
        holes the interval alone left: a board left showing a state a
        click had already moved on from, and two PATCHes landing in the
        same instant against a bucket that allows about five in five
        seconds.

        The interval runs from the moment a write **lands**, which is
        the whole of what makes it an interval. Timed from when a write
        was sent it measures nothing: a board is nearly a megabyte of
        PNG, so the request itself is seconds long on an ordinary
        connection and twenty-odd when discord.py is sleeping off a 429
        inside it -- and for all of that time the window reads as
        having been open for ages. The next write then goes out the
        instant the lock frees, into the bucket that was refusing the
        last one. The lock stopped two writes being *concurrent*; only
        this stops them being *consecutive*, which is the same feedback
        loop one step along. See "Discord's rate limits" in CLAUDE.md.

        `png` is an already-rendered board, for a caller that is
        posting the same one somewhere else in the same breath and
        should not pay to draw it twice. It is only used when the
        refresh happens now; a deferred one re-draws, because the
        board it was handed will be stale by the time it runs.
        """
        if game.message_id is None or interaction.channel is None:
            return

        lock = self.board_refresh_locks.setdefault(
            game.game_id, asyncio.Lock(),
        )

        interval = self.board_refresh_interval(game)

        if lock.locked():
            self.schedule_board_refresh(interaction.channel, game, interval)
            return

        now = time.monotonic()
        last = self.board_refreshed_at.get(game.game_id)

        if last is not None and now - last < interval:
            self.schedule_board_refresh(
                interaction.channel, game, last + interval - now,
            )
            return

        async with lock:
            self.board_refresh_wanted.discard(game.game_id)
            try:
                await self.write_board_message(
                    interaction.channel, game, png, relink=False,
                )
            finally:
                self.board_refreshed_at[game.game_id] = time.monotonic()

        # That write left the board without its full-image link, so a
        # settling pass is owed whether or not anything else asks for
        # one -- and it is the same pass that draws whatever the rest
        # of this click still has to move.
        if game.game_id in self.board_link_owed:
            self.schedule_board_refresh(
                interaction.channel, game, self.board_refresh_interval(game),
            )

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
        scheduled but before it fired is already covered by it. What is
        *not* covered is a request that arrives while that refresh is
        drawing and uploading -- the board it is putting up predates the
        request -- so the want is recorded rather than the task counted,
        and a pass that finds the flag set again when it lands waits out
        another interval and goes round once more. Without that the
        request was dropped on the floor: the task was still in
        `board_refresh_tasks` and nothing rescheduled it, so the board
        kept a state the click had already moved past until somebody
        clicked again.

        `delay` is when to *look*, not when to write. This pass is
        usually queued behind a write that is still going, and its
        sleep runs alongside that write rather than after it -- so by
        the time the lock frees, the wait is already spent and the
        board would be written twice in the same instant. What the
        interval is owed is settled once the lock is held, against the
        moment the last write landed.
        """
        self.board_refresh_wanted.add(game.game_id)

        if game.game_id in self.board_refresh_tasks:
            return

        async def run() -> None:
            try:
                await asyncio.sleep(delay)

                while True:
                    lock = self.board_refresh_locks.setdefault(
                        game.game_id, asyncio.Lock(),
                    )
                    async with lock:
                        await self.wait_out_board_interval(game)
                        # Discarded after the wait and before the write,
                        # so this pass covers everything asked for up to
                        # the moment it starts drawing, and anything
                        # asked for during the write is left to the next.
                        self.board_refresh_wanted.discard(game.game_id)
                        try:
                            await self.write_board_message(channel, game)
                        finally:
                            self.board_refreshed_at[game.game_id] = (
                                time.monotonic()
                            )

                    # Nothing awaits between the check and the `finally`
                    # below, so a want recorded after this reads False
                    # cannot be lost -- it arrives to find the task gone
                    # and schedules its own.
                    if game.game_id not in self.board_refresh_wanted:
                        return

                    await asyncio.sleep(self.board_refresh_interval(game))
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
                self.board_refresh_wanted.discard(game.game_id)

        # The loop keeps only a weak reference to a task, so the handle
        # is held here to keep this one from being collected mid-sleep.
        self.board_refresh_tasks[game.game_id] = asyncio.create_task(run())

    def board_refresh_interval(self, game: D12BallGame) -> float:
        """
        How long this game's board waits between writes: the ordinary
        interval, doubled once per board write Discord has refused in a
        row, up to BOARD_REFRESH_BACKOFF_CEILING.

        Every other lever in this file decides *how many* writes a turn
        asks for. This is the one that decides what to do when the
        answer turns out to be too many anyway -- and without it there
        is no answer at all, because a refused write leaves its digest
        unrecorded and so is retried, identically, at the next window,
        for as long as the game goes on.
        """
        refused = self.board_writes_refused.get(game.game_id, 0)

        if not refused:
            return BOARD_REFRESH_INTERVAL

        return min(
            BOARD_REFRESH_INTERVAL * 2 ** refused,
            BOARD_REFRESH_BACKOFF_CEILING,
        )

    def note_board_write_refused(self, game: D12BallGame) -> None:
        """
        Record that Discord refused a board write, widening the window
        before the next one.

        Logged at WARNING rather than ERROR: it is console-only, and
        nobody can act on it in the moment -- but it is the one line
        that attributes a run of `discord.http` 429s to a game rather
        than leaving a channel id to be looked up. It is logged per
        refusal, and there are at most a handful of those now where the
        unbacked-off gate produced sixty.
        """
        self.board_writes_refused[game.game_id] = (
            self.board_writes_refused.get(game.game_id, 0) + 1
        )

        LOGGER.warning(
            "Discord refused the board write for D12 Ball game %s "
            "(%d in a row); next attempt in %.0fs.",
            game.game_id,
            self.board_writes_refused[game.game_id],
            self.board_refresh_interval(game),
        )

    async def wait_out_board_interval(self, game: D12BallGame) -> None:
        """
        Sleep whatever is left of this game's window, measured from the
        moment its last board write landed.

        The caller holds `board_refresh_locks`, so nothing else can
        write or restamp the clock while this waits -- and a refresh
        arriving meanwhile finds the lock held and books itself in
        rather than going out alongside.

        This is the only place the bot sleeps *before* a request, and
        it is not the pacing "fewer requests, never slower ones" rules
        out: nobody is waiting on the board this pass is going to draw,
        because it has not been drawn yet. Every other write it might
        stand in for is one it is about to make unnecessary.
        """
        last = self.board_refreshed_at.get(game.game_id)

        if last is None:
            return

        remaining = (
            last + self.board_refresh_interval(game) - time.monotonic()
        )

        if remaining > 0:
            await asyncio.sleep(remaining)

    async def write_board_message(
        self,
        channel: discord.TextChannel,
        game: D12BallGame,
        png: Optional[bytes] = None,
        *,
        relink: bool = True,
    ) -> None:
        """
        Put a board on the persistent message.

        The full-image link is what makes this expensive. Its URL only
        exists once Discord has stored the upload, so re-cutting it is
        always a second edit -- and the upload above it has already
        invalidated the link the message is carrying, so the choice is
        not "one edit or two", it is "two edits or no link". At two a
        turn's worth of refreshes on its own comes to about what the
        bucket has, which is what the 429s were.

        So `relink` splits it. An interim write says False: it strips
        the dead link in the edit it was already paying for, and
        records the URL as owed. The settling write -- the trailing
        refresh, once the state has stopped moving -- says True and
        pays for the live link once, however many boards went past in
        between. The board is linkless for BOARD_REFRESH_INTERVAL
        rather than dead-linked for it, which is the honest of the two.

        A board identical to the one already on the message is not
        written at all. Plenty of steps refresh without moving anything
        a coach can see -- picking a receiver, choosing a maneuver --
        and the render is deterministic, so byte-equality is the whole
        test. A settling write still has its link to pay, though, since
        the board it is settling is the one an interim write stripped.

        This is a nicety layered on top of state that has already been
        saved, not the thing carrying the turn forward -- a dropped
        connection here (aiohttp.ClientError, e.g. a reset or a bad SSL
        record on a flaky link) shouldn't abort the caller and strand
        the turn before it reaches the next prompt, any more than a 404
        or a Discord-side HTTP error already doesn't.

        A write Discord *refused* is a different kind of failure from
        the rest, and the only one this counts: the others are one-offs
        and the next window is the right time to try again, whereas a
        429 says the next window is precisely what is too soon. See
        board_refresh_interval.
        """
        if game.message_id is None:
            return

        if png is None:
            png = await self.render_match_png(game)

        digest = hashlib.sha256(png).digest()
        if self.board_png_digests.get(game.game_id) == digest:
            if relink:
                await self.settle_board_link(channel, game)
            return

        # Setting a view replaces the one already there, so the
        # message's own home/visiting buttons get rebuilt with it.
        # Those are inert once the assignment is made, which is the
        # only state a board refresh runs in; before it, this message
        # is still the team/coin prompt, its buttons are live, and it
        # has no link on it to go stale -- so it is left alone.
        strip_link = not relink and game.home_and_visiting_selected

        try:
            board_message = channel.get_partial_message(game.message_id)
            updated_message = await board_message.edit(
                attachments=[self.match_file_from_png(game, png)],
                view=(
                    HomeAwaySelectionView(cog=self, game_id=game.game_id)
                    if strip_link
                    else discord.utils.MISSING
                ),
            )
        except (
            discord.NotFound, discord.HTTPException, aiohttp.ClientError,
        ) as error:
            if getattr(error, "status", None) == TOO_MANY_REQUESTS:
                self.note_board_write_refused(game)
            return

        # Recorded only once the upload has landed, so a failed edit
        # leaves the next refresh believing it still has work to do.
        self.board_png_digests[game.game_id] = digest
        # One landing is the whole of the recovery: the window goes
        # straight back to its ordinary width rather than stepping down
        # through the backoff, because what the backoff was waiting for
        # has just happened.
        self.board_writes_refused.pop(game.game_id, None)
        # Whatever was owed was owed against the upload this one just
        # replaced, so it dies with it either way.
        self.board_link_owed.pop(game.game_id, None)

        if not game.home_and_visiting_selected:
            return

        if relink:
            await add_full_image_button(
                updated_message,
                HomeAwaySelectionView(cog=self, game_id=game.game_id),
            )
            return

        button = build_full_image_button(updated_message)
        if button is not None:
            self.board_link_owed[game.game_id] = button.url

    async def settle_board_link(
        self,
        channel: discord.TextChannel,
        game: D12BallGame,
    ) -> None:
        """
        Put the full-image link back on a board an interim write took
        it off, when there is no new board to carry it.

        The URL was read off the upload at the time, so this needs
        neither a fresh render nor the message back -- one edit, and
        only when something is actually owed.
        """
        url = self.board_link_owed.pop(game.game_id, None)

        if url is None or game.message_id is None:
            return

        view = HomeAwaySelectionView(cog=self, game_id=game.game_id)
        view.add_item(full_image_link_button(url))

        try:
            await channel.get_partial_message(game.message_id).edit(view=view)
        except (discord.NotFound, discord.HTTPException, aiohttp.ClientError):
            # As everywhere else the link is concerned: the board is
            # already up, and a missing link is worth less than
            # anything it would take down with it.
            pass



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
        player = self.engine.get_player_definition(player_id)
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

        entry = format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))
        if location is not None:
            entry += f" — {location}"
        entry += f" — {tokens} {get_exhaust_emoji(self.condition_emojis)}"
        if conditions:
            entry += f" — {', '.join(conditions)}"
        if show_abilities:
            ability = self.player_catalog.effective_profile(player).ability
            entry += f"\n     *{ability}*"
        return entry



    def build_team_roster_section(
        self,
        match: MatchState,
        setup: TeamSetup,
        show_abilities: bool = False,
    ) -> str:
        lines = [f"**{format_team_side_label(setup)}**"]
        for heading, members in self.engine.roster_places(match, setup):
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
        ai_strategy = self.engine.get_ai_strategy(game)
        handler_id = ai_strategy.choose_ball_handler(match)
        match.select_ball_handler(handler_id)
        handler = self.engine.get_player_definition(handler_id)
        action = ai_strategy.choose_action(match)

        if action == "shoot":
            match.pending_action = "shoot"
            game.match_state = match.to_dict()
            save_games(self.games)

            await interaction.followup.send(
                f"{ai_name} has chosen to shoot to score with "
                f"{format_role_bracket(handler, self.team_emojis, match.team_for_player(handler.player_id))}.",
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
                f"{format_role_bracket(handler, self.team_emojis, match.team_for_player(handler.player_id))}."
            )
            await self.announce_uncontested_maneuver(
                interaction, game, match,
            )
            return

        match.pending_action = "maneuver"

        # A defender already sharing the ball's exact space leaves
        # nothing to choose -- see PlayerActionView.choose_action.
        on_ball_space = match.automatic_challengers()
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

        defender_number = self.engine.defending_player_number(game, match)
        defender_mention = format_player_with_team(
            game,
            defender_number,
            mention=True,
        )

        challenge_view = ManeuverChallengeView(self, game.game_id)
        challenge_message = await interaction.followup.send(
            f"{ai_name} will maneuver with "
            f"{format_role_bracket(handler, self.team_emojis, match.team_for_player(handler.player_id))}.\n\n"
            f"{defender_mention}, choose which player will maneuver "
            "to challenge for the ball, or send nobody and let the "
            "maneuver through.",
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

    def tutorial_player_side(self, game: D12BallGame) -> TeamSide:
        """
        Which side of the board the coach being taught is playing.

        Player 1 is always the human in a tutorial -- it is refused any
        other shape (see `create_game`) -- so this is whichever side the
        coin toss put them on. Nothing forces that toss, which is why
        every beat's position is written from a side's own goal forward
        and mirrored on the way in. See `d12ball/tutorial.py`.
        """
        return (
            TeamSide.HOME
            if game.home_player_number == 1
            else TeamSide.VISITING
        )

    def tutorial_beat(self, game: D12BallGame):
        """
        The beat now in progress, or None when no rail applies -- an
        ordinary game, or a tutorial whose script has run out or been
        skipped. Every rail in the views comes through here, so there
        is one answer to "is this coach being taught right now".
        """
        if not game.in_tutorial:
            return None
        return tutorial.beat_for_step(game.tutorial_step)

    def tutorial_railed_option(
        self,
        game: Optional[D12BallGame],
        key: str,
        options,
    ) -> Optional[object]:
        """
        The one option the beat now running allows out of `options`, or
        None when nothing is railed.

        One question for every sub-choice a beat pins down -- the
        dribble distance, the ball speed, the pass distance, the set-up
        shot, whether a loose ball may be waved through -- so a view
        adds a rail with one call rather than a branch of its own. See
        `d12ball/tutorial.py` for why those are railed and a run-back
        space is not.

        It takes the options rather than a single value because one of
        the rails cannot name its value up front: the ball speed a
        steal may set is capped by the stealer's own defensive skill.
        """
        if game is None:
            return None
        return tutorial.resolve_choice(
            self.tutorial_beat(game), key, options,
        )

    def tutorial_dice(
        self,
        game: D12BallGame,
        kind: str,
        count: int,
    ) -> Optional[list[int]]:
        """
        The die values the script fixes for this contest, or None to
        roll for real.

        Every `random.randint(1, 12)` in a contest a tutorial can reach
        asks this first. What it answers for, and what it deliberately
        leaves to the dice, is in `d12ball/tutorial.py` -- the short of
        it is that a beat only scripts a roll the *next* beat depends
        on, and the score attempt at the end is not one of them.
        """
        return tutorial.scripted_dice(
            self.tutorial_beat(game), kind, count,
        )

    async def stage_tutorial_beat(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        """
        Advance the script to the turn about to be played and post its
        lesson.

        **It moves nothing.** The board is set once, at kickoff, and
        every beat after that is played from wherever the previous
        turn left it -- see the module docstring in
        `d12ball/tutorial.py`. This used to re-deal both sides before
        each beat, which put a seam in the middle of the story; if a
        beat ever needs a position again, the fix is to change the
        script so the play arrives there.

        Called at the top of every `send_turn_prompt` for a tutorial
        game, which is once a turn -- so the *advance* is what counts
        the beats. `tutorial_staged` is what keeps that honest: the
        recovery commands (`/d12ball offensive_choice` and `resume
        force:true`) also send a turn prompt without a turn having been
        played, and re-entering a beat must not silently skip the next
        one.
        """
        if not game.in_tutorial:
            return

        if game.tutorial_staged:
            game.tutorial_step = (game.tutorial_step or 0) + 1
            game.tutorial_staged = False

        beat = tutorial.beat_for_step(game.tutorial_step)

        if beat is None:
            # Past the last beat: the script is over. The flag is
            # cleared before anything else, so the prompt this turn
            # puts up is built with no rails on it at all.
            game.tutorial_step = None
            game.tutorial_staged = False
            save_games(self.games)
            await interaction.followup.send(tutorial.HANDOVER)
            return

        game.tutorial_staged = True
        save_games(self.games)
        await interaction.followup.send(beat.lesson)

    async def send_turn_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        # Ahead of everything, including the AI branch below: a beat
        # the coach is *defending* is still a beat, and its position
        # has to be down before Dinky takes a turn on it.
        if game.in_tutorial:
            await self.stage_tutorial_beat(interaction, game)

        refresh_player_names(game, interaction.guild)
        match = self.engine.load_match_state(game)
        # The carrier, when the last resolution left the ball with
        # somebody; everyone on the ball's space otherwise. Either way
        # a single candidate is selected below without asking, so the
        # rule costs a coach a click rather than adding one.
        eligible_handlers = match.turn_handler_candidates()
        if not eligible_handlers:
            raise ValueError(
                "The team in possession has no player in the ball's space."
            )
        carrying = match.ball_carrier_id in eligible_handlers

        offense_number = self.engine.possession_player_number(game, match)
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
            self.engine.build_turn_prompt(game, match, carrying=carrying),
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
        match = self.engine.load_match_state(game)
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

    async def build_field_file(self, game: D12BallGame) -> discord.File:
        """
        The field on its own -- where everybody is standing and where
        the ball is, with nothing else on it -- which is what a coach
        gets under their maneuver cards. See
        `ManeuverActionPromptView.open_action_menu`.

        Unlike the maneuver hand, this cannot be drawn once at startup:
        it is the position, so it is different on every pick. Bytes are
        not kept for the same reason -- the render is uploaded once and
        is stale immediately -- so it goes straight into a File rather
        than through the `render_match_png` / `match_file_from_png`
        pair, which exists for the board that is put in two places at
        once.
        """
        image = await asyncio.to_thread(
            render_field_image,
            self.engine.load_match_state(game),
            self.player_catalog,
        )
        return discord.File(image, filename=FIELD_IMAGE_FILENAME)

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
        A message a coach cannot read without seeing the board, with a
        fresh snapshot attached directly to it, in addition to keeping
        the persistent board message in sync.

        Two kinds of message qualify. A manual board correction
        (/coach, /ref, /meeple move, /ball move/possession/speed,
        /score, /time) is confirmed by showing what it did. A loose
        ball is announced by showing where it is: the ball is lying in
        a space nothing else in the channel names, and the question
        that follows -- who to send after it -- is a question about how
        far away everybody is.

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

    def game_channel_is_archived(self, game: D12BallGame) -> bool:
        """
        Whether this game's channel is already filed away, read out of
        the client's cache so a view can ask it while it is being
        built.

        The same test `move_channel_to_archive` makes before it moves
        anything, which is why an unknown channel answers False: the
        move is idempotent, so a button offered when it need not have
        been costs one no-op, where a button withheld leaves a pair
        with no way to archive.
        """
        channel = self.bot.get_channel(game.channel_id)
        category = getattr(channel, "category", None)
        return bool(
            category is not None
            and category.name.casefold()
            == PBD_ARCHIVE_CATEGORY_NAME.casefold()
        )

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

        # The tutorial is a scripted warm-up against Dinky and nothing
        # else -- see d12ball/tutorial.py. Its five beats set a position
        # a side at a time and rail one coach onto one card, neither of
        # which means anything with a second human in the game or with
        # one person holding both sides' menus. Refused rather than
        # quietly ignored: a coach who asked for a tutorial and got an
        # ordinary game would have no way to tell.
        if tutorial and (p1 is not None or p2 is not None or test_game):
            await interaction.response.send_message(
                "A tutorial game is played against Dinky on your own, so "
                "it cannot take p1, p2 or test_game.",
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
                tutorial=tutorial,
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
            status=GameStatus.SETUP,
            board_size=board_size,
            ai_opponent=resolved_ai_opponent,
            tutorial=tutorial,
            # The step is set at kickoff, not here: setup is played
            # exactly as an ordinary game plays it -- teams, the coin
            # toss, home or visiting -- and the script starts with the
            # first turn. `in_tutorial` is False until then, so nothing
            # in setup is on rails.
            tutorial_step=None,
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
                    match, setup, show_abilities=abilities,
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
        #logs channel" in CLAUDE.md. Both commands ask before they answer
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
        # rate limits" in CLAUDE.md. A command run inside a thread
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

        # The shootout is not a turn and has no offensive choice in it,
        # so this would reset a maneuver that is not being played and
        # then prompt for a ball nobody is holding. The window between
        # the whistle and the shootout is the same: the second half is
        # over, and there is no turn under it either.
        if match.pending_shootout or match.pending_full_time_stage:
            await interaction.followup.send(
                "This game is in the extreme shootout, or the Coaching "
                "Choice before it. Use `/d12ball resume` to put its "
                "prompt back up.",
                ephemeral=True,
            )
            return

        # A ceded ball is the same again: the turn was reset before
        # either window opened, so nothing below would notice, and the
        # reset would drop a coach's open Coaching Choice on the floor
        # along with the pick-up the ball may still owe.
        if match.pending_cede:
            await interaction.followup.send(
                "The ball has been ceded and the Coaching Choice it "
                "bought is still running. Use `/d12ball resume` to put "
                "its prompt back up.",
                ephemeral=True,
            )
            return

        # Both refusals point at /d12ball resume, which is what these
        # two states actually want: it re-posts the maneuver or score
        # attempt prompt this turn is still owed rather than throwing
        # the turn away. A turn that is genuinely wedged wants
        # `resume force:true`.
        if match.pending_action == "maneuver":
            await interaction.followup.send(
                "A maneuver challenge is already in progress for this "
                "turn. Use `/d12ball resume` to put its prompt back up, "
                "or `/d12ball resume force:true` to abandon the turn and "
                "start the offensive choice over.",
                ephemeral=True,
            )
            return

        if match.pending_action == "shoot":
            await interaction.followup.send(
                "A score attempt is already in progress for this turn. "
                "Use `/d12ball resume` to put its prompt back up, or "
                "`/d12ball resume force:true` to abandon the turn and "
                "start the offensive choice over.",
                ephemeral=True,
            )
            return

        # A third of the same: an owed roll leaves `pending_action`
        # clear (`choose_challenger` cleared it when the maneuver
        # started), so without this the turn's reset below would throw
        # the roll away without saying so.
        owed_roll = (
            "an own goal roll"
            if match.pending_own_goal
            else "an injury test" if match.pending_injury_tests else None
        )
        if owed_roll is not None:
            await interaction.followup.send(
                f"This turn is still waiting on {owed_roll}. Use "
                "`/d12ball resume` to put its button back up, or "
                "`/d12ball resume force:true` to abandon the turn and "
                "start the offensive choice over.",
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

    def may_administer_game(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> bool:
        """
        Whether this person may run a recovery command on this game:
        either of its two players, or anyone the server trusts with
        `manage_channels`.

        A test game has both players set to the same person, so the
        player check covers it. `manage_channels` is the same
        permission `/debug reset_channels` is gated on, which is the
        blunter version of the same job.
        """
        if interaction.user.id in (game.player_1_id, game.player_2_id):
            return True
        permissions = getattr(interaction.user, "guild_permissions", None)
        return bool(permissions is not None and permissions.manage_channels)

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

        Deliberately **not** gated on `may_administer_game`: a tutorial
        is one human against Dinky, so its only player is the only
        person this could mean anything to, and a moderator ending
        somebody else's lesson is not a thing worth building.
        """
        game = self.game_for_channel(interaction.channel_id)

        if game is None:
            await interaction.response.send_message(
                "This channel does not have a D12 Ball game in it.",
                ephemeral=True,
            )
            return

        if interaction.user.id != game.player_1_id:
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
        `resume_pending_prompt`.

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
            # reset_maneuver clears the whole turn -- ball handler,
            # maneuver picks, run back, loose ball, kickoff fill,
            # out-of-bounds pickup -- and the coaching window is closed
            # separately because it is not part of a turn. Setup,
            # halftime, a ceded ball and the shootout -- the window
            # before it included -- are left alone on purpose: those
            # are real positions in the game rather than a turn gone
            # wrong, and a plain resume walks them on. The shootout
            # most of all -- there is no turn under it to clear, and
            # clearing one would throw away orders both coaches have
            # already set. A cede has already turned the ball over, so
            # clearing it would also leave the turn prompt asking the
            # receiving side to act with nobody on the ball.
            if (
                match.pending_setup_stage is not None
                or match.pending_halftime_stage is not None
                or match.pending_full_time_stage is not None
                or match.pending_shootout
                or match.pending_cede
            ):
                await interaction.followup.send(
                    "This game is in setup, at halftime, in the extreme "
                    "shootout, or on a ceded ball -- none of which "
                    "`force` can skip past. Run `/d12ball resume` "
                    "without it.",
                    ephemeral=True,
                )
                return

            match.reset_maneuver()
            match.close_coaching_window()
            game.match_state = match.to_dict()
            save_games(self.games)

            try:
                await self.send_turn_prompt(interaction, game)
            except ValueError as error:
                await interaction.followup.send(str(error), ephemeral=True)
                return

            await self.refresh_match_image(interaction, game)
            await interaction.followup.send(
                "Turn cleared and the offensive choice re-posted.",
                ephemeral=True,
            )
            return

        try:
            waiting_on = await self.resume_pending_prompt(
                interaction, game, match,
            )
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
        (see "Discord's rate limits" in CLAUDE.md), and the saved game
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

        # A board refresh still waiting on its window would write to a
        # channel that has just been archived, so drop it the same way
        # cog_unload does.
        task = self.board_refresh_tasks.pop(game.game_id, None)
        if task is not None:
            task.cancel()
        self.board_refreshed_at.pop(game.game_id, None)
        self.board_png_digests.pop(game.game_id, None)
        self.board_refresh_wanted.discard(game.game_id)
        self.board_refresh_locks.pop(game.game_id, None)
        self.board_link_owed.pop(game.game_id, None)
        self.board_writes_refused.pop(game.game_id, None)

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

        game.match_state = match.to_dict()
        save_games(self.games)

        player = self.engine.get_player_definition(player_card)
        await self.announce_board_update(
            interaction,
            game,
            f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} moved to "
            f"{destination_display_name(destination)}.",
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

        game.match_state = match.to_dict()
        save_games(self.games)

        await self.announce_board_update(
            interaction,
            game,
            f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} moved to "
            f"{destination_display_name(dest_target)}.",
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

        player = self.engine.get_player_definition(meeple)
        await self.announce_board_update(
            interaction,
            game,
            f"{format_role_bracket(player, self.team_emojis, match.team_for_player(player.player_id))} moved to "
            f"{space_label(zone, space_index)}.",
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

        game.match_state = match.to_dict()
        save_games(self.games)

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

        game.match_state = match.to_dict()
        save_games(self.games)

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

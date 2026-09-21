"""
The cog's own machinery, and the spine of a turn.

Lifecycle and startup, the game/match lookups every command opens
with, `persist`, the two player-label helpers, and the run from a
maneuver being picked to its effect being dispatched -- the challenge,
the skill test, the injury queue, and `pending_turn_view`.
"""

import asyncio
import discord
import io
import time
from typing import Optional, Sequence

from discord import app_commands
from discord.ext import commands
from d12ball.ai import build_ai_strategies
from d12ball.engine import RulesEngine
from d12ball.components import (
    MANEUVER_TIER_BASIC,
    MANEUVER_TIER_GAMBIT,
    MANEUVER_TIER_WORDS,
    MatchState,
    PlayerDefinition,
    PlayerRole,
    TeamSetup,
    TeamSide,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import (
    CoinFace,
    D12BallGame,
    GameStatus,
    Team,
    team_display_name,
)
from d12ball.cards import (
    maneuver_hand_combinations,
    render_maneuver_hands,
)
from d12ball.flow import FollowOn, FollowOnStep, StepResult
from d12ball.flow import driver
from d12ball.flow.turn import (
    announce_uncontested_maneuver,
    injured_word_and_emoji,
    record_turn_action,
)
from d12ball.flow.injuries import (
    begin_injury_tests,
    continue_injury_tests,
    injury_test_step,
)
from d12ball.prompts import (
    SCORE_ATTEMPT_ASK,
    PendingPrompt,
    PromptKind,
    effect_choice_prompt,
    maneuver_prompt_wording,
    pending_prompt,
    run_back_prompt,
)
from d12ball import tutorial
from d12ball.render import (
    TEAM_COLORS,
    render_injury_test_die,
    render_maneuver_reference_image,
)
from gamesaves.d12ball.storage import (
    load_games,
    save_games,
)
from gamesaves.d12ball.hub import load_hubs
from discord_emoji_cache import ensure_cached_emojis
from cogs.d12ball_helpers import (
    COIN_EMOJI_NAMES,
    EMOJI_REFETCH_INTERVAL,
    ERROR_RECOVERY_ADVICE,
    LOGGER,
    add_full_image_button,
    fetch_application_emojis,
    format_player_with_team,
    format_team_side_label,
    get_damaged_emoji,
    get_injured_emoji,
    load_coin_emojis,
    load_condition_emojis,
    load_d12_emoji,
    load_d12_button_emoji,
    load_role_emojis,
    load_species_ability_emojis,
    load_team_emojis,
    refresh_player_names,
    send_error_fallback,
    send_new_prompt,
)
from cogs.d12ball_views import (
    BallHandlerSelectionView,
    BallRecoveryView,
    CoachingHubView,
    HubRolesView,
    CoachingOfferView,
    CoinFlipView,
    DribbleAdvanceChoiceView,
    DribbleBurstChoiceView,
    HalftimeExtraTokenView,
    HighPassChoiceView,
    HomeAwaySelectionView,
    InjuryTestView,
    MindPullView,
    SmoothView,
    LobbyView,
    LooseBallChoiceView,
    LooseBallSkillTestView,
    LowPassChoiceView,
    ManeuverActionPromptView,
    ManeuverChallengeView,
    NewGameHubView,
    OwnGoalRollView,
    PlayerActionView,
    RematchView,
    RunBackChoiceView,
    RunBackPlayerChoiceView,
    ScoreAttemptView,
    SetUpAttemptChoiceView,
    ShooterChoiceView,
    SetupPassChoiceView,
    SetupPassPushBackView,
    ShootoutOrderPromptView,
    ShootoutOrderSelectView,
    ShootoutPickPromptView,
    ShootoutPickSelectView,
    ShootoutTestView,
    SkillTestView,
    SpeedDeltaChoiceView,
    TeamSelectionView,
    TutorialContinueView,
)
from cogs.d12ball_boards import BoardRefresher


#: Every prompt whose message carries **the field strip** -- the six
#: distance questions and the run back's two. Every one of them is
#: answered by reading where everybody is standing relative to the
#: ball, and by the time a maneuver has resolved the persistent board
#: has scrolled away up the channel. See `D12Ball.send_field_prompt`.
FIELD_PROMPT_KINDS = frozenset({
    PromptKind.LOW_PASS_CHOICE,
    PromptKind.HIGH_PASS_CHOICE,
    PromptKind.SETUP_PASS_CHOICE,
    PromptKind.DRIBBLE_ADVANCE_CHOICE,
    PromptKind.DRIBBLE_BURST_CHOICE,
    PromptKind.RUN_BACK_SPACE,
    PromptKind.RUN_BACK_PLAYER,
})


#: The two prompt kinds whose message carries **the coach's own
#: half-field** -- the one picture in the game that is not the board,
#: the field strip or a hand of cards. See `D12Ball.coaching_file`, and
#: "Working on the board image" in docs/design/board-image.md.
COACHING_PROMPT_KINDS = frozenset({
    PromptKind.COACHING_HUB,
    PromptKind.COACHING_OFFER,
})


#: Prompts the board is **not** written in front of, because the
#: answer draws it a moment later. Setup Pass's push back ends in a
#: loose ball on every branch -- the fallback where no distance fits,
#: Dinky's maximum, and the coach's own answer -- and a loose ball is
#: announced with the board under it. So the board a deflection moved
#: reaches the channel either way; what this decides is only that it
#: is not *also* drawn in front of a question whose answer moves the
#: ball again. Rank D1's economy, keyed on the prompt now that the
#: offer is a step the driver runs. See "Discord's rate limits" in
#: docs/design/rate-limits.md.
PROMPTS_DRAWN_LATER = frozenset({
    PromptKind.SETUP_PASS_PUSH_BACK,
})


#: Every follow-on whose own message **is** the lines handed to it, so
#: a run must carry them into it rather than post them above it.
#:
#: One member. `announce_game_over` is handed the whistle and the
#: scoresheet and puts the final board and the rematch buttons on the
#: message it makes of them -- so those lines are its content, not a
#: message above it. It earns the set rather than an `is` check
#: because the answer is the step's.
FOLLOW_ONS_THAT_SPEAK_THE_LINES = frozenset({
    FollowOnStep.ANNOUNCE_GAME_OVER,
})


#: Where the frontend has a picture of the position to put up, so the
#: driver must not run on past it.
#:
#: `driver.advance` stops after a step named here and
#: `D12Ball.post_stop` takes the picture. It is the frontend's half of
#: principle 8: "do not let the position move on behind a picture I
#: am about to take". A loose ball is announced by showing where it
#: is, and the tail of a maneuver shows the board the offensive choice
#: is handed back over -- the next step is a whole AI turn, which
#: walks a challenger in. A new play's board is the third picture and
#: is the model's own stop (`StepResult.new_play`).
DRIVER_STOPS = frozenset({
    FollowOnStep.BEGIN_LOOSE_BALL,
    FollowOnStep.FINISH_MANEUVER_RESOLUTION,
})


#: Every step the driver runs whose lines are **a message of their
#: own**, so the loop must stop carrying them forward once it has run.
#:
#: This is the old `post_then_dispatch` and `post_blocks_then_dispatch`
#: as a set rather than as two methods: the choice of dispatcher used
#: to be the cog calling a different method, so a step whose lines
#: were an event in their own right could not be run by anything but
#: the cog. `driver.advance` closes a `NarrationGroup` after each of
#: these and `post_narration_group` posts it -- which keeps the
#: decision exactly where principle 8 puts it, and stops it being a
#: flag on `StepResult`.
DRIVER_OWN_MESSAGE = frozenset({
    # The reveal; the effect that follows posts its own.
    FollowOnStep.RESOLVE_MANEUVER,
    # The skill test's reveal is a permanent message, separate from
    # the roll prompt, so it survives every re-roll intact.
    FollowOnStep.BEGIN_MANEUVER_SKILL_TEST,
    # The walk-in, over the challenge image.
    FollowOnStep.AUTO_RESOLVE_CHALLENGER,
    # Who came away with the ball is a different event from where it
    # came down, and the run back that follows is a third.
    FollowOnStep.RESOLVE_LOOSE_BALL,
    FollowOnStep.ANNOUNCE_RUN_BACK,
    # The cascade's automatic placements, batched into one message.
    FollowOnStep.CONTINUE_RUN_BACK,
    # The pickup is an event, and the maneuver's tail behind it is
    # the next one.
    FollowOnStep.APPLY_BALL_RECOVERY,
    # The new speed is the answer to the question this was, and what
    # follows it is the next event.
    FollowOnStep.OFFER_SPEED_CHOICE,
    # The whistle and the runs of separate events behind it.
    FollowOnStep.END_PERIOD,
    FollowOnStep.CONTINUE_SHOOTOUT,
    FollowOnStep.FINISH_SUBSTITUTION_WINDOW,
    # A window's lead-in is a message above the menu, and an AI side's
    # window is a run of separate events.
    FollowOnStep.BEGIN_SUBSTITUTION_WINDOW,
    # The lines a turn opens with -- "Dinky has chosen to maneuver",
    # then "Unchallenged!" -- each a message, as the AI's turn always
    # read; a human's turn says nothing here.
    FollowOnStep.START_TURN,
    # "X takes the shot off the set-up", above the composition.
    FollowOnStep.START_SET_UP_SHOT,
})


#: The groups posted **one message per block** rather than joined.
#:
#: A period transition is a cascade of separate events -- the whistle,
#: the halftime recovery, an AI side's extra token, the shootout's
#: explainer -- and a coach reads them as the several they are. Every
#: other group in the set above is one message. Keyed on the step
#: because the answer is the step's, not the card's that reached it.
DRIVER_BLOCKS_PER_MESSAGE = frozenset({
    FollowOnStep.END_PERIOD,
    # The shootout's own transitions, for the whistle's reason: the
    # settled score, the summary and the goal log are separate events.
    FollowOnStep.CONTINUE_SHOOTOUT,
    # The junction the five coaching occasions come back through, for
    # the same reason: a window closing can hand out the next side's,
    # or open a kickoff, or let a run back go ahead.
    FollowOnStep.FINISH_SUBSTITUTION_WINDOW,
    # An AI side's whole window is a routine, and each thing it did is
    # its own line.
    FollowOnStep.BEGIN_SUBSTITUTION_WINDOW,
    # The AI's turn, a message per thing it says.
    FollowOnStep.START_TURN,
    FollowOnStep.START_SET_UP_SHOT,
})


#: Every prompt kind whose view is built from the cog and the game id
#: alone. The eight that carry something else are branches in
#: `view_for_prompt`, and `PARAMETERISED_PROMPT_KINDS` names them so
#: the two together can be checked against `PromptKind` -- a kind with
#: no view is a prompt the bot cannot put up.
PLAIN_PROMPT_VIEWS = {
    PromptKind.COACHING_HUB: CoachingHubView,
    PromptKind.COACHING_OFFER: CoachingOfferView,
    PromptKind.OWN_GOAL_ROLL: OwnGoalRollView,
    PromptKind.SHOOTOUT_ORDER: ShootoutOrderPromptView,
    PromptKind.SHOOTOUT_PICK: ShootoutPickPromptView,
    PromptKind.SHOOTOUT_TEST: ShootoutTestView,
    PromptKind.PLAYER_ACTION: PlayerActionView,
    PromptKind.BALL_HANDLER_SELECTION: BallHandlerSelectionView,
    PromptKind.BALL_RECOVERY: BallRecoveryView,
    PromptKind.LOOSE_BALL_SKILL_TEST: LooseBallSkillTestView,
    PromptKind.SCORE_ATTEMPT: ScoreAttemptView,
    PromptKind.MANEUVER_CHALLENGE: ManeuverChallengeView,
    PromptKind.MANEUVER_ACTION: ManeuverActionPromptView,
    PromptKind.SKILL_TEST: SkillTestView,
    PromptKind.HIGH_PASS_CHOICE: HighPassChoiceView,
    PromptKind.SETUP_PASS_CHOICE: SetupPassChoiceView,
    PromptKind.DRIBBLE_ADVANCE_CHOICE: DribbleAdvanceChoiceView,
    PromptKind.DRIBBLE_BURST_CHOICE: DribbleBurstChoiceView,
    PromptKind.SETUP_PASS_PUSH_BACK: SetupPassPushBackView,
}

#: The kinds carrying a parameter their view needs -- and the two
#: whose view is built from the game id alone but is not a prompt's
#: buttons in the ordinary sense: the tutorial's Continue, and the
#: rematch under a finished game.
PARAMETERISED_PROMPT_KINDS = frozenset({
    PromptKind.TUTORIAL_CONTINUE,
    PromptKind.GAME_OVER,
    PromptKind.HALFTIME_EXTRA_TOKEN,
    PromptKind.MIND_PULL,
    PromptKind.SMOOTH,
    PromptKind.INJURY_TEST,
    PromptKind.RUN_BACK_SPACE,
    PromptKind.RUN_BACK_PLAYER,
    PromptKind.LOOSE_BALL_PICK,
    PromptKind.LOW_PASS_CHOICE,
    PromptKind.SPEED_DELTA_CHOICE,
    PromptKind.SET_UP_ATTEMPT,
    PromptKind.SHOOTER_CHOICE,
})


class CoreMixin:
    """
    The cog's own machinery, and the spine of a turn.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.games = load_games()
        # `{guild_id: {"channel_id", "message_id"}}` for each server's
        # game-creation hub message -- see gamesaves/d12ball/hub.py and
        # "The game-creation hub and the lobby" in docs/design/hub-and-lobby.md.
        self.hubs = load_hubs()
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
        self.prerender_maneuver_images()

        self.coin_emojis: dict[CoinFace, str] = {}
        # When the coin emoji were last asked after, on the monotonic
        # clock -- see ensure_coin_emojis. None, not 0.0: monotonic
        # counts from boot on Linux, so on a host that starts the bot
        # as it comes up, 0.0 reads as "asked a moment ago" and skips
        # the first retry.
        self.coin_emojis_checked_at: Optional[float] = None
        # The condition, team, role and species-ability emoji all live
        # on the engine -- see `condition_emojis`, `team_emojis`,
        # `role_emojis` and `species_ability_emojis` below. The
        # engine's `__init__` starts each of the four at `{}`, so there
        # is nothing to initialise here.
        # The `<:d12dice:id>` string for the hub message and the lobby
        # heading, and the lighter `<:d12dicecream:id>` for the hub
        # button (its blue fill swallowed the darker die) -- both None
        # until cog_load, and re-fetched by `/d12ball setup_hub` so a
        # fresh upload takes without a restart.
        self.d12_emoji: Optional[str] = None
        self.d12_button_emoji: Optional[str] = None
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
        # The board message's write gate, and the seven maps of
        # per-game state behind it. See cogs/d12ball_boards.py.
        self.boards = BoardRefresher(self)

        self.restore_saved_views()
        self.log_live_games()

    def prerender_maneuver_images(self) -> None:
        """
        Draw every maneuver image the bot will ever send, once.

        Startup is the one place a render can block the loop
        harmlessly, and the alternative is drawing up to thirteen cards
        on every maneuver. Nothing about a maneuver card or the
        reference hexagon depends on the match, so none of these can go
        stale.
        """
        # One hexagon per tier: a basic-mode coach has no gambits
        # to read a matchup for, so its hexagon shows one box a
        # rank rather than the pair an advanced game's does -- see
        # render_maneuver_reference_image.
        self.maneuver_reference_image_bytes = {
            tier: render_maneuver_reference_image(
                self.maneuver_catalog, tier
            ).read()
            for tier in (MANEUVER_TIER_BASIC, MANEUVER_TIER_GAMBIT)
        }
        # The cards the maneuver prompt carries.
        #
        # **Keyed by the hands on the prompt: one `(side, tiers)` pair
        # per hand.** The prompt is public and carries a hand for every
        # side that still has a human pick to make, so the sides are the
        # two of them, or one alone when the maneuver is unchallenged or
        # the other side is Dinky's -- see
        # `RulesEngine.maneuver_pick_sides`.
        #
        # **The tiers are per side**, which is what makes this eight
        # images rather than six: since 2026-09-20 a gambit is held only
        # by a coach whose team is behind, so a contested prompt can
        # carry six cards for one side and three for the other -- see
        # `RulesEngine.maneuver_tiers`.
        self.maneuver_hand_image_bytes = {
            hands: render_maneuver_hands(
                self.maneuver_catalog, self.player_catalog, hands
            ).read()
            for hands in maneuver_hand_combinations()
        }

    def restore_saved_views(self) -> None:
        """
        Re-arm one message per saved game: whichever setup prompt it
        stopped at, a finished game's rematch message, and the prompt
        its turn is waiting on.

        A restart re-arms exactly one turn message per game, which is
        why a game can still come back with no working button anywhere
        -- see "Recovering a stuck game" in docs/design/recovery.md.
        """
        restored_views = 0

        for entry in self.hubs.values():
            # The hub buttons have no game to lose and stay live for the
            # life of their messages. A stale entry (a message deleted by
            # hand) just registers a view nothing will ever dispatch to.
            self.bot.add_view(
                NewGameHubView(self),
                message_id=entry["message_id"],
            )
            restored_views += 1
            # Absent from an entry written before the roles message
            # existed; `/d12ball setup_hub` fills it in.
            roles_message_id = entry.get("roles_message_id")
            if roles_message_id is not None:
                self.bot.add_view(
                    HubRolesView(self),
                    message_id=roles_message_id,
                )
                restored_views += 1

        for game in self.games.values():
            if game.in_lobby:
                # A lobby is a SETUP game with no teams picked yet, so
                # without this branch it would restore the team picker
                # instead of the lobby's own Join/Leave/Start view.
                if game.message_id is not None:
                    self.bot.add_view(
                        LobbyView(self, game.game_id),
                        message_id=game.message_id,
                    )
                    restored_views += 1
                continue

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
                and not game.is_finished
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

        LOGGER.info(
            "Loaded %d saved D12 Ball games and restored %d button "
            "views.",
            len(self.games),
            restored_views,
        )

    def log_live_games(self) -> None:
        """
        One line per unfinished game, naming its channel and its two
        message ids.

        discord.py reports a 429 as a bare method and URL, and the only
        thing in it that identifies the game is the channel and message
        id. Three rounds of those warnings were read by inferring which
        message that was, wrongly; this makes it a lookup instead. See
        "Discord's rate limits" in docs/design/rate-limits.md.
        """
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
        self.species_ability_emojis = await load_species_ability_emojis(
            self.bot, application_emojis,
        )
        self.team_emojis = await load_team_emojis(
            self.bot, application_emojis,
        )
        self.role_emojis = await load_role_emojis(
            self.bot, application_emojis,
        )
        self.d12_emoji = await load_d12_emoji(self.bot, application_emojis)
        self.d12_button_emoji = await load_d12_button_emoji(
            self.bot, application_emojis,
        )

    async def cog_unload(self) -> None:
        """
        Drop any board refresh still waiting on its window -- see
        `BoardRefresher.shutdown` for what that costs a board.
        """
        self.boards.shutdown()

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

    def persist(self, game: D12BallGame, match: MatchState) -> None:
        """
        Write the match back onto its game record and save.

        **The two halves are one step and must not be separated.** A
        turn resolves through a dozen of these, and a `save_games`
        without the `to_dict` above it writes whatever the record was
        already carrying -- so the file keeps a state the game has
        already moved past, silently, until a restart reads it back.
        Nothing about that failure is visible while the bot is up.

        `save_games` never raises (see "Gotchas" in docs/design/gotchas.md), which
        is what lets this be called mid-resolution without a save
        failure taking the turn down with it.

        A caller that has only a game to save -- a message id, a
        tutorial flag, the finished status -- calls `save_games`
        directly, and there are around forty of those. This is for the
        match.
        """
        game.match_state = match.to_dict()
        save_games(self.games)

    def record_turn_action(
        self,
        match: MatchState,
        action: str,
        by_ai: bool = False,
    ) -> None:
        """
        Open a turn in the event log.

        A forwarding method over `d12ball.flow.turn.record_turn_action`
        since Phase 6, which is where it belongs: a step that takes a
        turn has to open one, and a step cannot call a cog method. The
        reasoning is in the model's copy; this is kept so none of the
        call sites moved -- the shape `team_emojis` took in Phase 1a.
        """
        record_turn_action(match, action, by_ai)

    @property
    def condition_emojis(self) -> dict[str, str]:
        """
        The condition emoji, `"exhaust" -> "<:exhaust:id>"` and the
        four conditions beside it, once cog_load has fetched them and
        `{}` before -- read by `RulesEngine.describe_exhaustion_gain`
        and by the roster and coaching lines that show a player's
        state.

        On the engine for the same reason as `team_emojis` and
        `role_emojis` below, and arrived there for a sharper one: the
        sentence an exhaustion charge writes is narration, narration
        is the model's, and a flow step charging a token cannot ask a
        cog what an exhaustion token looks like. This is a view of
        that one copy, not a second dict -- cog_load *replaces* the
        dict on every fetch.
        """
        return self.engine.condition_emojis

    @condition_emojis.setter
    def condition_emojis(self, condition_emojis: dict[str, str]) -> None:
        self.engine.condition_emojis = condition_emojis

    @property
    def team_emojis(self) -> dict[Team, str]:
        """
        The team emoji, `Team -> "<:team_orange:id>"`, once cog_load
        has fetched them and `{}` before -- read by
        `format_player_with_team` and `format_player_label` (see
        `role_emojis` just below, for why this lives on the engine
        rather than being a second dict assigned beside it).
        """
        return self.engine.team_emojis

    @team_emojis.setter
    def team_emojis(self, team_emojis: dict[Team, str]) -> None:
        self.engine.team_emojis = team_emojis

    @property
    def role_emojis(self) -> dict[tuple[PlayerRole, Optional[Team]], str]:
        """
        The role emoji, `(PlayerRole, Team | None) ->
        "<:role_fullback_orange:id>"`, once cog_load has fetched them
        and `{}` before -- the badge in a side's own colour, with the
        plain cut filed under a team of None (see `load_role_emojis`).

        The dict itself lives on the engine, whose two message builders
        name a player with it (`format_roster_player_for_message`), and
        this is a view of that one copy rather than a second dict
        assigned beside it -- cog_load *replaces* the dict, so a
        reference handed to the engine at construction would go stale
        the moment the fetch landed.
        """
        return self.engine.role_emojis

    @role_emojis.setter
    def role_emojis(
        self, role_emojis: dict[tuple[PlayerRole, Optional[Team]], str],
    ) -> None:
        self.engine.role_emojis = role_emojis

    @property
    def species_ability_emojis(self) -> dict[str, str]:
        """
        The species-ability emoji, `"telekinetic" -> "<:telekinetic_
        color:id>"`, once cog_load has fetched them and `{}` before --
        the mark at the head of Mind Pull's and Smooth's own banners.
        On the engine with `team_emojis`, `role_emojis` and
        `condition_emojis` rather than a second dict assigned beside
        it, so the wording still has them once those steps lift into
        `d12ball/flow/` -- see "Application emoji for the four
        abilities" in docs/design/species-abilities.md.
        """
        return self.engine.species_ability_emojis

    @species_ability_emojis.setter
    def species_ability_emojis(
        self, species_ability_emojis: dict[str, str],
    ) -> None:
        self.engine.species_ability_emojis = species_ability_emojis

    def player_label(
        self,
        match: MatchState,
        player: PlayerDefinition,
    ) -> str:
        """
        "🟠 Hellguard [FB]" -- a player named the way every message in
        the game names them, with the role badge emoji in place of the
        brackets once they are uploaded (see `role_emojis`), drawn
        with that side's own colour on its edge.

        A forwarding method over `RulesEngine.format_player_label`,
        which reads both emoji dicts off the engine itself now that
        they live there -- see `team_emojis` and `role_emojis` above.
        Kept here so no call site moved: ninety-odd sites already read
        this rather than spelling out `format_role_bracket` and its
        three arguments for themselves.
        """
        return self.engine.format_player_label(match, player)

    def player_id_label(
        self,
        match: MatchState,
        player_id: str,
    ) -> str:
        """
        `player_label` for a caller holding a card id rather than a
        definition -- a run-back candidate, a shootout order, the
        injured list on a coaching prompt.
        """
        return self.player_label(
            match, self.engine.get_player_definition(player_id),
        )

    def reference_tier(self, game: Optional[D12BallGame]) -> str:
        """
        Which hexagon to post: the one with the gambits on it for a
        game actually playing them, the basic one everywhere else
        -- including outside a game's channel, where there is nothing
        to ask. Through `gambits_apply` rather than off
        `game.mode`, or an advanced game that opted the maneuvers out
        would be handed a reference to six cards it will never hold.

        **The game's, deliberately, rather than the asking coach's.**
        A coach the 2026-09-20 gate has closed this turn still needs to
        read what the *other* side may be about to play, and the
        hexagon is the twelve relations rather than a hand -- so it
        asks the module and not `may_play_gambits`.
        """
        if game is not None and self.engine.gambits_apply(game):
            return MANEUVER_TIER_GAMBIT
        return MANEUVER_TIER_BASIC

    def build_maneuver_reference_file(
        self, tier: str = MANEUVER_TIER_BASIC,
    ) -> discord.File:
        return discord.File(
            io.BytesIO(self.maneuver_reference_image_bytes[tier]),
            filename=(
                f"maneuver_reference_{MANEUVER_TIER_WORDS[tier]}.png"
            ),
        )

    def build_maneuver_hand_file(
        self,
        hands: Sequence[tuple[str, Sequence[str]]] = (
            ("offense", (MANEUVER_TIER_BASIC,)),
        ),
    ) -> discord.File:
        """
        The cards on offer this maneuver, wrapped fresh each time:
        uploading a `discord.File` consumes the stream inside it, so the
        bytes are what is kept and the file is built per send -- the
        same reason `render_match_png` returns bytes rather than a File.

        `hands` is one `(side, tiers)` pair per hand on the prompt, as
        `maneuver_hand_combinations` keys them -- the tiers are each
        side's own, since a gambit is held one coach at a time.
        """
        key = tuple((side, tuple(tiers)) for side, tiers in hands)
        return discord.File(
            io.BytesIO(self.maneuver_hand_image_bytes[key]),
            filename=(
                f"maneuver_hand_{'_'.join(side for side, _ in key)}.png"
            ),
        )


    async def begin_score_attempt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        ask: str = SCORE_ATTEMPT_ASK,
    ) -> None:
        """
        Post what the score attempt is made of, then the roll prompt.
        The composition is a message of its own, and an image for the
        same reason the maneuver challenge is one (see
        build_maneuver_challenge_file): a shot is decided by skills and
        abilities that a line of prose lists without showing.

        `ask` is the prompt's line -- the model's, through
        `render_prompt`; the default is the same line for the two
        callers that reach here without a prompt in hand.
        """
        composition_message = await send_new_prompt(
            interaction,
            file=await self.build_score_attempt_file(match),
        )

        # The one thing the image doesn't show is how the two rolls are
        # read against each other, so it rides on the prompt -- which
        # becomes the dice image the moment it is answered, taking the
        # explanation with it once it is no longer needed.
        prompt_message = await send_new_prompt(
            interaction,
            ask,
            view=ScoreAttemptView(
                self, game.game_id,
                composition_message_id=composition_message.id,
            ),
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
        An already-decided challenger pick, as an entry point:
        `d12ball.flow.turn.auto_resolve_challenger` through the
        dispatcher, which posts the walk-in over the challenge image
        (`post_narration_group`) and carries on to the maneuver pick.
        """
        await self.dispatch_step_result(
            interaction,
            game,
            match,
            StepResult(
                next=FollowOn(
                    FollowOnStep.AUTO_RESOLVE_CHALLENGER,
                    {"challenger_id": challenger_id},
                ),
            ),
        )

    async def announce_uncontested_maneuver(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """"There is nobody to challenge", as an entry point -- its own
        message, then the offense's pick."""
        await self.post_then_dispatch(
            interaction,
            game,
            match,
            announce_uncontested_maneuver(self.engine, game, match),
        )

    async def begin_maneuver_action_selection(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """The simultaneous maneuver pick, as an entry point."""
        await self.run_step(
            interaction,
            game,
            match,
            FollowOnStep.BEGIN_MANEUVER_ACTION_SELECTION,
            lead_in=lead_in,
        )

    async def resolve_maneuver(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """The reveal, as an entry point -- `d12ball.flow.turn.resolve_maneuver`."""
        await self.run_step(
            interaction, game, match, FollowOnStep.RESOLVE_MANEUVER,
            lead_in=lead_in,
        )

    async def begin_maneuver_skill_test(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        headline: str,
        lead_in: str = "",
    ) -> None:
        """The skill test's reveal and prompt, as an entry point."""
        await self.run_step(
            interaction,
            game,
            match,
            FollowOnStep.BEGIN_MANEUVER_SKILL_TEST,
            lead_in=lead_in,
            headline=headline,
        )

    async def begin_effect_resolution(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        winner_key: str,
        lead_in: str = "",
    ) -> None:
        """
        A settled maneuver's effect, as an entry point --
        `d12ball.flow.effects.begin_effect_resolution`, which logs the
        maneuver and runs the won card by key.
        """
        await self.run_step(
            interaction,
            game,
            match,
            FollowOnStep.BEGIN_EFFECT_RESOLUTION,
            lead_in=lead_in,
            winner_key=winner_key,
        )

    async def send_maneuver_action_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        content: str,
    ) -> None:
        """
        Put the maneuver hands up on **one public prompt** -- see
        `ManeuverActionPromptView` for why the cards can be public
        while the pick stays secret.

        Everything here is a picture: the hand image, the link to the
        full-size version, and the field strip under it. Who is being
        asked and what they are told arrives in `content`, which is
        the prompt's own ask (`maneuver_action_ask`); a tutorial's note
        has already been shown and clicked through by the time this is
        reached (`d12ball.flow.gates`).
        """
        prompt_view = ManeuverActionPromptView(self, game.game_id)
        sides = self.engine.maneuver_pick_sides(game, match)
        # The cards ride on the prompt itself. One image, not one per
        # side: Discord lays two attachments out side by side, which
        # would halve the width of both hands. See render_maneuver_hands
        # for why showing both gives nothing away.
        prompt_message = await send_new_prompt(
            interaction,
            content,
            file=self.build_maneuver_hand_file(
                tuple(
                    (side, self.engine.maneuver_tiers(game, match, side))
                    for side in sides
                ),
            ),
            view=prompt_view,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

        # The abilities are small print at the size Discord shows an
        # image inline, so the link is worth the extra round trip. It
        # is the webhook route, not the channel's edit bucket -- see
        # "Discord's rate limits". Adding it re-sends the view, or the
        # edit would drop the buttons the prompt exists for.
        await add_full_image_button(
            prompt_message,
            view=prompt_view,
            row=prompt_view.full_image_row,
        )
        await self.post_field_image(interaction, game)

    def injured_word_and_emoji(
        self,
        game: D12BallGame,
        player_id: str,
    ) -> tuple[str, str]:
        """
        What a player out of the contest is called, and the mark for
        it -- a forwarding method over
        `d12ball.flow.turn.injured_word_and_emoji`.

        Kept here so none of its four call sites moved: a coaching
        prompt, a shootout, and the injury test itself all name the
        condition, and only one of the four is in the flow.
        """
        return injured_word_and_emoji(self.engine, game, player_id)

    def maneuver_prompt_wording(
        self,
        game: D12BallGame,
        match: MatchState,
        sides: list[str],
    ) -> tuple[list[str], str]:
        """
        Who is mentioned above the maneuver prompt, and what they are
        told to do -- a forwarding method over
        `d12ball.flow.turn.maneuver_prompt_wording`.
        """
        return maneuver_prompt_wording(self.engine, game, match, sides)

    async def begin_injury_tests(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        players: list[PlayerDefinition],
        resume: dict,
    ) -> None:
        """
        The Discord half of the injury tests a resolved contest owes:
        run the step, save what it did, then ask what it asks or run
        what it names.

        The queue, the filter and the continuation are all
        `d12ball.flow.injuries.begin_injury_tests`'s since Phase 4 --
        see it for why `resume` is persisted alongside the queue. What
        is left here is the persist, which the step no longer does
        (principle 9), and which is an **added** line rather than a
        moved one: the wrapper was not saving before, it relied on the
        step to.
        """
        result = begin_injury_tests(self.engine, game, match, players, resume)
        await self.dispatch_step_result(interaction, game, match, result)

    async def continue_injury_tests(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Ask for the next injury test still owed, or -- when there are
        none left -- do what the contest that owed them was going to
        do. The Discord half of
        `d12ball.flow.injuries.continue_injury_tests`, and the one
        exit from the queue.
        """
        result = continue_injury_tests(self.engine, game, match)
        await self.dispatch_step_result(interaction, game, match, result)

    async def post_injury_die(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        roll,
        result: StepResult,
    ) -> None:
        """
        One injury test's die, where the prompt was, and then what it
        says.

        The prompt becomes the die, and the verdict follows in its own
        message rather than riding above it -- see SkillTestView.roll
        for why every result is announced this way round. An
        already-injured player rolls nothing and the step says so by
        handing back no roll at all (`roll` is None): nothing to draw
        and nothing to announce, so the queue simply carries on.
        """
        if roll is None:
            await self.dispatch_step_result(interaction, game, match, result)
            return

        player = self.engine.get_player_definition(roll.player_id)
        player_team = match.team_for_player(roll.player_id)
        dice_file = discord.File(
            await asyncio.to_thread(
                render_injury_test_die,
                roll.roll,
                TEAM_COLORS[player_team],
                team_display_name(player_team),
                player.name,
                roll.safe,
                bool(roll.overdrive),
            ),
            filename="injury_test_die.png",
        )
        await interaction.edit_original_response(
            content=None,
            attachments=[dice_file],
            view=None,
        )
        # The second die between the check and its verdict. It matters
        # more here than anywhere: a backfire is the one thing in the
        # game that injures the player who rolled well.
        await self.post_volatile_ignition(
            interaction, match, (roll.player_id, roll.ignite),
        )
        await send_new_prompt(interaction, result.narration[0])

        await self.dispatch_step_result(
            interaction,
            game,
            match,
            StepResult(
                narration=result.narration[1:],
                board_changed=result.board_changed,
                next=result.next,
            ),
        )

    async def run_injury_test(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        player: PlayerDefinition,
    ) -> None:
        """
        One injury test, as an entry point --
        `d12ball.flow.injuries.injury_test_step` and the die.
        """
        roll, result = injury_test_step(
            self.engine, game, match, player.player_id,
        )
        self.persist(game, match)
        await self.post_injury_die(interaction, game, match, roll, result)

    def build_effect_choice_view(
        self,
        game_id: str,
        match: MatchState,
    ) -> Optional[discord.ui.View]:
        """
        Whichever initial effect-choice prompt is pending for a
        decisively-won maneuver, as a view -- used both to restore it
        on a bot restart and (implicitly, by the same logic) to post it
        the first time.

        The reading is `d12ball.prompts.effect_choice_prompt`, which
        holds what this used to decide and why; None here is None
        there, which is a maneuver needing no choice (Deflect,
        Pressure) or one still owed a skill test.
        """
        prompt = effect_choice_prompt(self.engine, self.games[game_id], match)
        if prompt is None:
            return None
        return self.view_for_prompt(game_id, match, prompt)

    def restore_shootout_menus(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> int:
        """
        Bring an open shootout menu back to life after a restart, the
        way the maneuver pick used to be restored before its menu
        went public, and for the same reason: a coach's shooting
        order and their
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
        of whoever it is waiting on, and the line asking for it.

        **The reading is the model's** --
        `d12ball.prompts.pending_prompt` is the branch chain that used
        to be this method's body, ordering comments and all, so a web
        app can ask the same question rather than growing a second copy
        of it (see "The model and the Discord layer" in CLAUDE.md).
        What is left here is the rendering, and the `ask` passes
        through untouched.

        Its two callers must not drift apart: `restore_saved_views`
        re-attaches what this returns to the message the prompt is
        already on, and `resume_pending_prompt` posts it on a fresh
        one. That is also why this returns a view rather than sending
        it -- see "Recovering a stuck game" in docs/design/recovery.md.
        """
        prompt = pending_prompt(self.engine, self.games[game_id], match)
        return self.view_for_prompt(game_id, match, prompt), prompt.ask

    def view_for_prompt(
        self,
        game_id: str,
        match: MatchState,
        prompt: PendingPrompt,
    ) -> discord.ui.View:
        """
        The view a `PendingPrompt` is shown as.

        **This is the only place a `PromptKind` becomes a
        `discord.ui.View`.** Later phases render a step's next prompt
        through here rather than growing a second table -- two tables
        is the same failure as two copies of the chain, one step
        further down.

        Most kinds are a constructor taking the cog and the game id,
        and those are `PLAIN_PROMPT_VIEWS`; the eight that carry a
        parameter are the branches below. `match` is here for the one
        whose view is built from a candidate list rather than from the
        prompt alone -- the loose ball's pick reads its buttons off the
        board, and a prompt is what to ask rather than a rendering
        brief.
        """
        kind = prompt.kind
        if kind is PromptKind.TUTORIAL_CONTINUE:
            return TutorialContinueView(self, game_id)
        if kind is PromptKind.GAME_OVER:
            return RematchView(self, game_id)
        if kind is PromptKind.HALFTIME_EXTRA_TOKEN:
            return HalftimeExtraTokenView(self, game_id, prompt.side)
        if kind is PromptKind.MIND_PULL:
            return MindPullView(self, game_id, prompt.player_id)
        if kind is PromptKind.SMOOTH:
            return SmoothView(self, game_id, prompt.player_id)
        if kind is PromptKind.INJURY_TEST:
            return InjuryTestView(self, game_id, prompt.player_id)
        if kind is PromptKind.RUN_BACK_SPACE:
            return RunBackChoiceView(self, game_id, prompt.player_id)
        if kind is PromptKind.RUN_BACK_PLAYER:
            return RunBackPlayerChoiceView(self, game_id, prompt.player_ids)
        if kind is PromptKind.LOOSE_BALL_PICK:
            return LooseBallChoiceView(
                self,
                game_id,
                prompt.skill_type,
                self.engine.loose_ball_candidates(match, prompt.side),
                match,
            )
        if kind is PromptKind.LOW_PASS_CHOICE:
            return LowPassChoiceView(
                self, game_id, key=prompt.maneuver_key, free=prompt.free,
            )
        if kind is PromptKind.SPEED_DELTA_CHOICE:
            return SpeedDeltaChoiceView(
                self, game_id, prompt.player_id, prompt.skill_type,
            )
        if kind is PromptKind.SET_UP_ATTEMPT:
            return SetUpAttemptChoiceView(
                self,
                game_id,
                prompt.player_id,
                prompt.distance_moved,
                contest_on_decline=prompt.contest_on_decline,
            )
        if kind is PromptKind.SHOOTER_CHOICE:
            return ShooterChoiceView(self, game_id, prompt.player_ids)
        return PLAIN_PROMPT_VIEWS[kind](self, game_id)

    async def post_then_dispatch(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        result: StepResult,
        with_board: bool = False,
    ) -> None:
        """
        Post this step's own lines as their own message, then run what
        comes next with **nothing carried forward**.

        `dispatch_step_result` does the opposite: it hands the lines to
        the next step as its `lead_in`, so a cascade of the bot's own
        steps reads as one message. That is right for a maneuver
        resolving into its effect and wrong for the handful of places
        where the line is an event in its own right -- where the ball
        came down, that a new play has started, that everybody is
        running back. Those were separate messages before the lift and
        a coach reads the channel expecting them to be.

        **Which of the two a step gets is the frontend's decision**,
        which is why it is a second method here rather than a flag on
        `StepResult`: principle 8 puts batching on this side of the
        seam, and the model says only what was said and in what order.

        `with_board` puts the message up with a snapshot attached (see
        `announce_board_update`) rather than merely keeping the
        persistent board in sync -- a loose ball is announced by
        showing where it is.
        """
        lines = " ".join(result.narration)
        if lines:
            if with_board:
                await self.announce_board_update(interaction, game, lines)
            else:
                await send_new_prompt(interaction, lines)
                if result.board_changed:
                    await self.refresh_match_image(interaction, game)
        elif result.board_changed:
            await self.refresh_match_image(interaction, game)

        await self.dispatch_step_result(
            interaction, game, match, StepResult(next=result.next),
        )

    async def post_blocks_then_dispatch(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        result: StepResult,
    ) -> None:
        """
        Post this step's narration **one message per block**, then run
        what comes next with nothing carried forward.

        The third dispatcher, and the one the periods need.
        `dispatch_step_result` joins the blocks and hands them to the
        next step as its lead-in; `post_then_dispatch` joins them into
        one message of their own; this posts each block separately.
        A period's whistle is a cascade of the bot's own steps that
        were **several messages each** before the lift -- the whistle,
        the halftime recovery, an AI side's extra token, the shootout's
        explainer -- and a coach reads them as the separate events they
        are.

        `StepResult.narration` is already "the blocks in the order they
        were said" (see `StepResult`); which of the three dispatchers a
        step gets is the frontend's decision, which is why this is a
        third method here rather than a flag on the result. See
        principle 8 in CLAUDE.md.

        **One board refresh for the cascade, not one per block.** The
        model reports that the board moved; how many writes that costs
        is this side's, and the whole of a period transition is one
        position settling. It is written first, so the board is right
        by the time the first line naming it is read.

        A follow-on in `FOLLOW_ONS_THAT_SPEAK_THE_LINES` is handed the
        blocks instead of having them posted above it.
        """
        following = result.next
        if result.board_changed:
            await self.refresh_match_image(interaction, game)

        lines = ""
        if (
            isinstance(following, FollowOn)
            and following.step in FOLLOW_ONS_THAT_SPEAK_THE_LINES
        ):
            lines = " ".join(result.narration)
        else:
            for block in result.narration:
                await send_new_prompt(interaction, block)

        await self.dispatch_step_result(
            interaction,
            game,
            match,
            StepResult(narration=[lines] if lines else [], next=following),
        )

    # -- The dispatcher -----------------------------------------------

    async def run_step(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        step: FollowOnStep,
        lead_in: str = "",
        **kwargs: object,
    ) -> None:
        """
        Run one step of the flow by name, and everything it starts --
        the entry point every cog wrapper that names a step is one
        line over. `lead_in` is the narration the step opens with,
        which is how every step is called.
        """
        await self.dispatch_step_result(
            interaction,
            game,
            match,
            StepResult(
                narration=[lead_in] if lead_in else [],
                next=FollowOn(step, kwargs),
            ),
        )

    async def dispatch_step_result(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        result: StepResult,
    ) -> None:
        """
        Turn a `StepResult` into Discord: run the chain it starts,
        save once, redraw the board if anything moved, post what was
        said, and put up what is asked.

        **The loop is the driver's** (`d12ball.flow.driver.advance`),
        and it runs every step in the game. What is here is the whole
        of the Discord side, and it is rendering: which of a run's
        narration groups becomes one message and which several, where
        a picture goes and which picture, and the one write of the
        persistent board. Three things make the loop hand control
        back here before it has finished, and each is a picture this
        side has to take of the position *as it stands* before the
        next step moves it:

        - **a snapshot** under a line -- a loose ball is announced by
          showing where it is, and the tail of a maneuver shows the
          board the offensive choice is handed back over
          (`DRIVER_STOPS`);
        - **a new play's board**, posted and pinned with the reset's
          lines as its caption -- the model's own stop, on
          `StepResult.new_play`;
        - **a prompt**, which is where the run ends by definition.

        After a stop the loop is re-entered with whatever the stopped
        step named, so a click still runs to its prompt in one call
        of this method.

        **The one save is here** -- principle 9. Every step of a run
        has mutated the match and none of them has written it; the
        dispatcher writes once per run, after everything that moves
        has moved and before anything is posted, which is the
        ordering the whole principle is about: a prompt hands the
        turn to a click that reloads the match out of the save file,
        so the file has to be right first. It is unconditional rather
        than `if run.ran`, because the caller's own step has almost
        always changed something and the dispatcher cannot see that
        from here.

        **`board_changed` is the model's answer and the write is this
        method's decision.** A run says the board moved; whether that
        costs a request is read here. A stop that draws the board
        under its own line writes the persistent message from the
        same render (`announce_board_update`, `post_new_play_board`),
        so the ordinary write is skipped in front of it; and a prompt
        whose answer draws the board a moment later
        (`PROMPTS_DRAWN_LATER`) is not drawn in front of either.

        A `PendingPrompt` goes through `render_prompt` and so through
        `view_for_prompt`, the same table a restart restores through.
        Two tables is how the live flow and the resume come to offer
        different questions -- see "d12ball/prompts.py" in
        docs/design/model-discord-split.md.
        """
        while True:
            try:
                run = driver.advance(
                    self.engine,
                    game,
                    match,
                    result,
                    stop_after=DRIVER_STOPS,
                    own_message=DRIVER_OWN_MESSAGE,
                    speaks_lines=FOLLOW_ONS_THAT_SPEAK_THE_LINES,
                )
            except ValueError as error:
                # A step refusing a position it should never have
                # been handed -- the side in possession with nobody on
                # the ball. Whatever ran before it is written down, and
                # the refusal is reported rather than acted on.
                self.persist(game, match)
                await send_error_fallback(interaction, str(error))
                return
            self.persist(game, match)

            following = run.result.next
            stopped = run.stopped_on
            draws_own_board = stopped is not None and (
                run.result.new_play
                or self.stop_draws_the_board(stopped, run.result, following)
            )
            if (
                run.board_changed
                and not draws_own_board
                and not (
                    isinstance(following, PendingPrompt)
                    and following.kind in PROMPTS_DRAWN_LATER
                )
            ):
                await self.refresh_match_image(interaction, game)

            # **The closed groups, before anything the run is still
            # carrying.** Each is a step whose lines are an event of
            # their own -- the reveal, the settled loose ball, "Players
            # run back!", the whistle -- and the step it is tagged with
            # is what picks how it is posted. The board is already
            # written above, so the position is right by the time the
            # first line naming it is read.
            for group in run.groups:
                await self.post_narration_group(interaction, game, match, group)

            if stopped is not None:
                carried = await self.post_stop(
                    interaction, game, match, stopped, run.result,
                )
                result = StepResult(
                    narration=list(run.result.narration) if carried else [],
                    next=following,
                )
                if following is None:
                    return
                continue

            lead_in = " ".join(run.result.narration)
            if isinstance(following, PendingPrompt):
                await self.render_prompt(
                    interaction, game, match, following, lead_in,
                )
                return

            if lead_in:
                await send_new_prompt(interaction, lead_in)
            return

    def stop_draws_the_board(
        self,
        stopped: FollowOn,
        result: StepResult,
        following: object,
    ) -> bool:
        """
        Whether the step the loop stopped on is about to put the board
        up under its own line, so the ordinary write is skipped in
        front of it -- render once, upload twice.

        The loose ball draws for a genuine loose ball and not for a
        long High Pass (the ball is on a receiver both coaches watched
        catch it, and the board the pass moved is written in front of
        the contest instead) -- which is the step's own `board_changed`.
        The tail of a maneuver draws when it hands the offensive choice
        back, and not when it hands to the whistle or a gate, where its
        lines carry on into whatever comes next.
        """
        if stopped.step is FollowOnStep.BEGIN_LOOSE_BALL:
            return bool(result.narration) and result.board_changed
        if stopped.step is FollowOnStep.FINISH_MANEUVER_RESOLUTION:
            return (
                isinstance(following, FollowOn)
                and following.step is FollowOnStep.SEND_TURN_PROMPT
            )
        return False

    async def post_stop(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        stopped: FollowOn,
        result: StepResult,
    ) -> bool:
        """
        Put up the picture the loop stopped for, with the stopped
        step's lines. Returns True when the lines were **not** posted
        and should carry on into the next step as its lead-in.

        - A new play: the board, posted and pinned, captioned by the
          last line; any earlier lines are a message above it (the
          setup and halftime steps take a lead-in that was its own
          message before the lift).
        - A loose ball: named and drawn together where it is genuine;
          the High Pass contest's announcement is a plain message over
          the board the pass already wrote. Nothing at all where the
          arrival gate took over -- the offer is an ordinary prompt and
          carries its lines forward.
        - The tail of a maneuver, handing the offensive choice back:
          one last board with everything settled, drawn once and
          uploaded twice -- onto the persistent message and under the
          closing line. Two messages where there are two lines, because
          the last-possession announcement is its own beat. Handing to
          anything else, the lines carry.
        """
        lines = list(result.narration)

        if result.new_play:
            if len(lines) > 1:
                await send_new_prompt(interaction, " ".join(lines[:-1]))
            await self.post_new_play_board(
                interaction, game, lines[-1] if lines else "",
            )
            return False

        if stopped.step is FollowOnStep.BEGIN_LOOSE_BALL:
            if not lines:
                return False
            if result.board_changed:
                await self.announce_board_update(
                    interaction, game, " ".join(lines),
                )
            else:
                await send_new_prompt(interaction, " ".join(lines))
            return False

        if stopped.step is FollowOnStep.FINISH_MANEUVER_RESOLUTION:
            if not self.stop_draws_the_board(stopped, result, result.next):
                return True
            png = await self.render_match_png(game)
            await self.refresh_match_image(interaction, game, png=png)
            if len(lines) > 1:
                await send_new_prompt(interaction, " ".join(lines[:-1]))
            snapshot = await send_new_prompt(
                interaction,
                lines[-1],
                file=self.match_file_from_png(game, png),
            )
            await add_full_image_button(snapshot)
            return False

        return True

    async def post_narration_group(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        group: driver.NarrationGroup,
    ) -> None:
        """
        One closed group, as the messages the step it came from earns:
        one message per block for a period transition and the other
        runs of separate events (`DRIVER_BLOCKS_PER_MESSAGE`), the
        challenge image under the walk-in for a challenger nobody was
        asked for, and one message for everything else.
        """
        if (
            group.step is FollowOnStep.AUTO_RESOLVE_CHALLENGER
            and match.challenger_id is not None
        ):
            await self.announce_maneuver_challenge(
                interaction,
                match,
                match.challenger_id,
                " ".join(group.narration),
            )
            return
        if group.step in DRIVER_BLOCKS_PER_MESSAGE:
            for block in group.narration:
                if block:
                    await send_new_prompt(interaction, block)
            return
        block = " ".join(group.narration)
        if block:
            await send_new_prompt(interaction, block)

    async def render_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        prompt: PendingPrompt,
        lead_in: str = "",
    ) -> None:
        """
        Put a `PendingPrompt` in front of whoever it is waiting on,
        **with its picture**, keyed on the kind.

        This is the frontend's half of principle 2: the model says
        what is asked and of whom, and this says how that reaches a
        person. Every picture in the game that rides on a question is
        decided here and nowhere else -- the field strip under the six
        distance questions and the run back, the hand of cards under
        the maneuver pick, the composition in front of the shot, the
        coach's own half-field on a Coaching Choice, the final board
        and the rematch buttons on a finished game. A kind not named
        below is a message with buttons on it and nothing else.

        `lead_in` is whatever the run was still carrying, and it opens
        the prompt's message -- except in front of the shot, where it
        is a message of its own above the composition, which is how
        "X has chosen to shoot" always read.

        **The message a restart re-attaches the view to** is recorded
        on the way out (`turn_message_id`), whichever branch posted it.
        A prompt that is not recorded is one `on_ready` cannot put live
        buttons back on. It is the game record rather than the match,
        so it is `save_games` and not `persist`: the match was written
        before anything was posted (principle 9), and this is the id
        of the message that write led to.
        """
        kind = prompt.kind
        content = " ".join(filter(None, (lead_in, prompt.ask)))
        mentions = discord.AllowedMentions(
            users=True, roles=False, everyone=False,
        )

        if kind is PromptKind.GAME_OVER:
            await self.announce_game_over(interaction, game, content)
            return

        if kind is PromptKind.SCORE_ATTEMPT:
            if lead_in:
                await send_new_prompt(interaction, lead_in)
            await self.begin_score_attempt(
                interaction, game, match, ask=prompt.ask,
            )
            return

        if kind is PromptKind.MANEUVER_ACTION:
            await self.send_maneuver_action_prompt(
                interaction, game, match, content,
            )
            return

        view = self.view_for_prompt(game.game_id, match, prompt)

        if kind in FIELD_PROMPT_KINDS:
            # Over the field: every one of these is answered by reading
            # where everybody is standing relative to the ball, and by
            # the time a maneuver has resolved the persistent board has
            # scrolled away up the channel. See `send_field_prompt`.
            await self.send_field_prompt(
                interaction, game, match, content, view,
            )
            return

        file = None
        if kind in COACHING_PROMPT_KINDS:
            # The one picture in the game that is not the board, the
            # field strip or a hand of cards: the coach's own half of
            # the field, with play stopped.
            file = await self.coaching_file(
                game, match, TeamSide(prompt.side or match.pending_coaching_side),
            )

        if kind in (PromptKind.PLAYER_ACTION, PromptKind.BALL_HANDLER_SELECTION):
            # The turn prompt names both coaches, and a coach may have
            # renamed themselves since the last one.
            refresh_player_names(game, getattr(interaction, "guild", None))

        prompt_message = await send_new_prompt(
            interaction,
            content,
            file=file,
            view=view,
            # **Every prompt this posts may name a coach**, and most of
            # them do -- an injury test, a run-back choice and a
            # loose-ball pick all open with a mention. Ping the user
            # asked, never a role and never the channel.
            allowed_mentions=mentions,
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    def build_run_back_view(
        self,
        game_id: str,
        match: MatchState,
    ) -> Optional[discord.ui.View]:
        """
        The run-back prompt for whichever player still needs a real
        choice, as a view -- `d12ball.prompts.run_back_prompt`'s answer
        through `view_for_prompt`, and None where there is no choice
        left to make.
        """
        prompt = run_back_prompt(self.engine, self.games[game_id], match)
        if prompt is None:
            return None
        return self.view_for_prompt(game_id, match, prompt)


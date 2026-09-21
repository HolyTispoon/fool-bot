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
from typing import Callable, Optional, Sequence

from discord import app_commands
from discord.ext import commands
from d12ball.ai import build_ai_strategies
from d12ball.engine import RulesEngine
from d12ball.components import (
    DECISION_CARDS,
    DECISION_INJURY_FORFEIT,
    DECISION_SKILL_TEST,
    DECISION_UNCONTESTED,
    CoachingOccasion,
    EVENT_MANEUVER,
    EVENT_SKILL_TEST,
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
    auto_resolve_challenger,
    begin_maneuver_action_selection,
    injured_word_and_emoji,
    maneuver_prompt_wording,
    resolve_maneuver,
)
from d12ball.flow.arrivals import take_scoring_opportunity
from d12ball.flow.turn import record_turn_action
from d12ball.flow.injuries import (
    begin_injury_tests,
    continue_injury_tests,
    injury_test_step,
)
from d12ball.prompts import (
    PendingPrompt,
    PromptKind,
    effect_choice_prompt,
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
    MANEUVER_ROW_COLOURS,
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
    ShootoutOrderPromptView,
    ShootoutOrderSelectView,
    ShootoutPickPromptView,
    ShootoutPickSelectView,
    ShootoutTestView,
    SkillTestView,
    SpeedDeltaChoiceView,
    TeamSelectionView,
)
from cogs.d12ball_boards import BoardRefresher


#: The follow-on steps that put the board up themselves, so
#: `dispatch_step_result` does not write it a second time in front of
#: them.
#:
#: **This is a Discord economy, not a fact about the position.** A step
#: reports `board_changed` honestly -- the ball moved -- and the
#: frontend decides what that costs: here, every edit to any message in
#: a channel shares one five-in-five bucket, so a refresh in front of a
#: step that is about to draw the same board writes the same bytes
#: twice for one click. See "Discord's rate limits" in
#: docs/design/rate-limits.md, and principle 8 in CLAUDE.md for why the
#: suppression lives here rather than in the step. A web app reading
#: the same `StepResult` has no such bucket and should redraw.
#:
#: Both members reach it by the same route, one of them a beat later.
#: `begin_loose_ball` announces the position with the board under it --
#: the ball is lying somewhere nothing in the channel has named, and
#: the very next question is who to send after it. And every branch of
#: `offer_setup_pass_push_back` ends in `begin_loose_ball`: the
#: fallback where no distance fits, Dinky's maximum, and the coach's
#: own answer. So the board a deflection moved reaches the channel
#: either way; what this decides is only that it is not *also* drawn in
#: front of a question whose answer moves the ball again.
#:
#: A set rather than a check on one member, because the answer is the
#: **step's** and not the calling card's: rank D1 lifted the first two
#: callers of `begin_loose_ball`, Phase 4 lifted the rest, and every one
#: of them gets this without deciding it again.
FOLLOW_ONS_THAT_DRAW_THE_BOARD = frozenset({
    FollowOnStep.BEGIN_LOOSE_BALL,
    FollowOnStep.OFFER_SETUP_PASS_PUSH_BACK,
})


#: The two prompt kinds whose message carries **the coach's own
#: half-field** -- the one picture in the game that is not the board,
#: the field strip or a hand of cards. `D12Ball.begin_substitution_window`
#: posts these itself rather than letting `dispatch_step_result` do it,
#: because the file has to be rendered and attached; see
#: "Working on the board image" in docs/design/board-image.md.
COACHING_PROMPT_KINDS = frozenset({
    PromptKind.COACHING_HUB,
    PromptKind.COACHING_OFFER,
})


#: Every follow-on whose own message **is** the lines handed to it, so
#: a caller posting a step's narration block by block must not post
#: them and then run it.
#:
#: One member, and it earns the set rather than an `is` check for
#: `FOLLOW_ONS_THAT_DRAW_THE_BOARD`'s reason: the answer is the step's.
#: `announce_game_over` is handed a string and puts the final board and
#: the rematch buttons on the message it makes of it -- so the whistle
#: and the scoresheet are its content, not a message above it. See
#: `D12Ball.post_blocks_then_dispatch`.
FOLLOW_ONS_THAT_SPEAK_THE_LINES = frozenset({
    FollowOnStep.ANNOUNCE_GAME_OVER,
})


#: Where the frontend has a picture of the position to put up, so the
#: driver must not run on past it.
#:
#: `driver.advance` stops after a step named here. It is the frontend's
#: half of principle 8 and the mirror of `FOLLOW_ONS_THAT_DRAW_THE_BOARD`:
#: that set says "do not write a board in front of this step", this one
#: says "do not let the position move on behind a picture I am about to
#: take". Empty while every step the driver runs carries its lines
#: forward rather than showing them over a snapshot -- a step that
#: announces the board under its own line (`begin_loose_ball`) is not in
#: the driver's table at all yet, so it stops the loop by being absent.
DRIVER_STOPS: frozenset = frozenset()


#: Every step the driver runs whose lines are **a message of their
#: own**, so the loop must stop carrying them forward once it has run.
#:
#: This is `post_then_dispatch` and `post_blocks_then_dispatch` as a
#: set rather than as two methods, and it is what let those four steps
#: into the loop at all: before Phase 6's second increment the choice
#: of dispatcher *was* the cog calling a different method, so a step
#: whose lines were an event in their own right could not be run by
#: anything but the cog. `driver.advance` closes a `NarrationGroup`
#: after each of these and the rendering below picks a dispatcher per
#: group -- which keeps the decision exactly where principle 8 puts
#: it, and stops it being a flag on `StepResult`.
DRIVER_OWN_MESSAGE = frozenset({
    FollowOnStep.RESOLVE_MANEUVER,
    FollowOnStep.RESOLVE_LOOSE_BALL,
    FollowOnStep.ANNOUNCE_RUN_BACK,
    FollowOnStep.END_PERIOD,
    FollowOnStep.CONTINUE_SHOOTOUT,
    FollowOnStep.FINISH_SUBSTITUTION_WINDOW,
})


#: The groups posted **one message per block** rather than joined.
#:
#: A period transition is a cascade of separate events -- the whistle,
#: the halftime recovery, an AI side's extra token, the shootout's
#: explainer -- and a coach reads them as the several they are. Every
#: other group in the set above is one message. Keyed on the step for
#: `FOLLOW_ONS_THAT_DRAW_THE_BOARD`'s reason: the answer is the step's,
#: not the card's that reached it.
DRIVER_BLOCKS_PER_MESSAGE = frozenset({
    FollowOnStep.END_PERIOD,
    # The shootout's own transitions, for the whistle's reason:
    # the settled score, the summary and the goal log are separate
    # events, and `D12Ball.continue_shootout` posted them a message
    # apiece through `post_blocks_then_dispatch` before the test
    # that reaches it became a step.
    FollowOnStep.CONTINUE_SHOOTOUT,
    # The junction the five coaching occasions come back through,
    # for the same reason: a window closing can hand out the next
    # side's, or open a kickoff, or let a run back go ahead, and
    # those are separate events.
    FollowOnStep.FINISH_SUBSTITUTION_WINDOW,
})


def follow_on_draws_the_board(following: FollowOn) -> bool:
    """
    Whether the step a result hands to is about to put the board up
    itself, so the frontend should not write one in front of it.

    The set above is the whole of it for a step that always draws.
    **`begin_run_back` is the first that draws only sometimes**, and
    rank O3 is what met it: a run back after a steal redraws nothing
    of its own, but a run back opening a *new play* posts and pins a
    board -- both passes that go out of play reach it that way, and
    the old cog wrote no board in front of either. So the argument
    that decides it is read here, beside the set, rather than the
    model being asked to report a board that did not move.

    **`is_high_pass` is the second argument that decides it**, and
    Phase 6 is what made it matter. `begin_loose_ball` draws the board
    under its own announcement for a genuine loose ball -- nothing in
    the channel names the space the ball is lying in -- and
    deliberately does not for a long High Pass, where the ball is on a
    receiver both coaches watched catch it and the board the pass
    moved is written in front of the contest instead. While
    `BEGIN_HIGH_PASS_CONTEST` was the cog's, that write came from the
    dispatch above it and this set never saw the difference; now that
    the loop runs the contest, the run ends on `BEGIN_LOOSE_BALL`
    itself and suppressing here would lose the pass's board
    altogether. Read off the step's own arguments, like `new_play`
    beside it.

    Still keyed to the step and its own arguments rather than to the
    card that named it, which is rank D1's rule and the reason every
    caller of `begin_loose_ball` Phase 4 lifted inherited this without
    deciding it again.
    """
    if following.step in FOLLOW_ONS_THAT_DRAW_THE_BOARD:
        return not following.kwargs.get("is_high_pass")
    return (
        following.step is FollowOnStep.BEGIN_RUN_BACK
        and bool(following.kwargs.get("new_play"))
    )


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
}

#: The kinds carrying a parameter their view needs.
PARAMETERISED_PROMPT_KINDS = frozenset({
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
    ) -> None:
        """
        Post what the score attempt is made of, then the roll prompt.
        The composition is a message of its own, and an image for the
        same reason the maneuver challenge is one (see
        build_maneuver_challenge_file): a shot is decided by skills and
        abilities that a line of prose lists without showing.
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
            "Either player can roll. Both sides roll one d12; the "
            "attacker scores on a total equal to or higher than the "
            "defence.",
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
        The Discord half of an already-decided challenger pick --
        `d12ball.flow.turn.auto_resolve_challenger`.

        **A bespoke wrapper rather than `dispatch_step_result`**,
        because the walk-in line is not a message of its own: it rides
        above the matchup image, which is meant to sit directly on top
        of the maneuver prompt a coach is reading it for. See
        `announce_maneuver_challenge`.
        """
        result = auto_resolve_challenger(
            self.engine, game, match, challenger_id,
        )
        self.persist(game, match)

        await self.announce_maneuver_challenge(
            interaction, match, challenger_id, " ".join(result.narration),
        )
        if result.board_changed:
            await self.refresh_match_image(interaction, game)
        await self.dispatch_step_result(
            interaction, game, match, StepResult(next=result.next),
        )

    async def auto_resolve_challenger_step(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        *,
        challenger_id: str,
        lead_in: str = "",
    ) -> None:
        """`auto_resolve_challenger` as a follow-on."""
        if lead_in:
            await send_new_prompt(interaction, lead_in)
        await self.auto_resolve_challenger(
            interaction, game, match, challenger_id,
        )

    async def announce_uncontested_maneuver(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The Discord half of "there is nobody to challenge" --
        `d12ball.flow.turn.announce_uncontested_maneuver`. Its own
        message: the pick that follows is a prompt of its own.
        """
        result = announce_uncontested_maneuver(self.engine, game, match)
        await self.post_then_dispatch(interaction, game, match, result)

    async def begin_maneuver_action_selection(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        The Discord half of the simultaneous maneuver-action choice --
        `d12ball.flow.turn.begin_maneuver_action_selection`, which
        writes the AI's pick and says whether anybody is still owed
        one.

        `lead_in` is always "" -- both steps that hand here post their
        own line first (the challenge image, the unchallenged notice)
        -- and is carried into whatever comes next rather than dropped.
        """
        result = begin_maneuver_action_selection(self.engine, game, match)
        if lead_in:
            result.narration.insert(0, lead_in)
        await self.dispatch_step_result(interaction, game, match, result)

    async def send_maneuver_action_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        *,
        sides: list[str],
        ask: str,
        lead_in: str = "",
    ) -> None:
        """
        Put the maneuver hands up on **one public prompt** -- see
        `ManeuverActionPromptView` for why the cards can be public
        while the pick stays secret.

        Everything here is a picture or a gate: the hand image, the
        link to the full-size version, the field strip, and (in a
        tutorial) the note held behind Continue. Who is being asked
        and what they are told arrives in `ask`.
        """

        async def show_prompt(
            inner_interaction: discord.Interaction,
        ) -> None:
            prompt_view = ManeuverActionPromptView(self, game.game_id)
            # The cards ride on the prompt itself. One image, not one
            # per side: Discord lays two attachments out side by side,
            # which would halve the width of both hands. See
            # render_maneuver_hands for why showing both gives nothing
            # away.
            # Who holds their gambits, under the instruction and above
            # the cards. It is public knowledge either coach could work
            # out from the scoreboard and the board (see
            # `RulesEngine.may_play_gambits`), and `""` in the games
            # and positions where the question does not arise -- so
            # this adds a paragraph to an advanced prompt and nothing
            # at all to a basic one.
            gambit_access = self.engine.describe_gambit_access(game, match)
            prompt_text = " ".join(filter(None, (lead_in, ask)))
            if gambit_access:
                prompt_text = f"{prompt_text}\n\n{gambit_access}"

            prompt_message = await send_new_prompt(
                inner_interaction,
                prompt_text,
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
            # image inline, so the link is worth the extra round trip.
            # It is the webhook route, not the channel's edit bucket --
            # see "Discord's rate limits". Adding it re-sends the view,
            # or the edit would drop the buttons the prompt exists for.
            await add_full_image_button(
                prompt_message,
                view=prompt_view,
                row=prompt_view.full_image_row,
            )
            await self.post_field_image(inner_interaction, game)

        # The cards are what this beat is about, so its note goes in
        # front of the prompt rather than with the lesson two messages
        # up: by the time the hands are in front of a coach they have
        # watched a challenger walk in and are looking at three
        # buttons, which is the moment the explanation is worth
        # reading. It is held behind Continue rather than posted right
        # alongside the prompt -- see post_tutorial_note -- since
        # nothing forces a coach to read it before live buttons draw
        # their eye.
        tutorial_beat = self.tutorial_beat(game)
        if tutorial_beat is not None:
            await self.post_tutorial_note(
                interaction, game, tutorial_beat.maneuver_note, show_prompt,
            )
            return

        await show_prompt(interaction)

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

    async def begin_maneuver_skill_test(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        headline: str,
        lead_in: str = "",
    ) -> None:
        """
        Charge both participants their token, post what is at stake,
        and put the roll behind a button -- every roll is a coach's.

        `lead_in` is here because every follow-on is called with one.
        It is always "" for this step: `resolve_maneuver` hands the
        reveal over as `headline`, which the message below embeds,
        rather than as narration that would have been posted above it.
        """
        if lead_in:
            await send_new_prompt(interaction, lead_in)
        exhaustion_text = (
            self.apply_exhaustion(game, match, match.active_player_id, 1)
            + "\n"
            + self.apply_exhaustion(game, match, match.challenger_id, 1)
        )
        self.persist(game, match)

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
        await send_new_prompt(
            interaction,
            f"{headline}"
            f"{self.player_label(match, offense_player)}: offense skill "
            f"{offense_skill}\n"
            f"{self.player_label(match, defense_player)}: defense skill "
            f"{defense_skill}\n\n"
            + exhaustion_text,
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=False,
                everyone=False,
            ),
        )
        await self.refresh_match_image(interaction, game)

        test_message = await send_new_prompt(
            interaction,
            "Either player can roll:",
            view=SkillTestView(self, game.game_id),
        )
        game.turn_message_id = test_message.id
        save_games(self.games)

    async def resolve_maneuver(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        The Discord half of the reveal -- `d12ball.flow.turn.resolve_maneuver`.

        Its own message, because the effect that follows posts its own:
        a coach reads "X wins!" and then watches the card resolve.
        """
        result = resolve_maneuver(self.engine, game, match)
        if lead_in:
            result.narration.insert(0, lead_in)
        await self.post_then_dispatch(interaction, game, match, result)

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

    async def run_injury_test(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        player: PlayerDefinition,
    ) -> None:
        """
        One injury test, off the button `continue_injury_tests` posted
        for it.

        **The rule is `d12ball.flow.injuries.injury_test_step`** since
        Phase 6: the roll, what Volatile and Overdrive do to it, the
        threshold it has to beat, the event and the verdict are all the
        model's. What is left here is the die, and that it goes between
        the two things said about it.

        An already-injured player rolls nothing and the step says so by
        handing back no roll at all -- nothing to draw and nothing to
        announce, so the queue simply carries on.
        """
        roll, result = injury_test_step(
            self.engine, game, match, player.player_id,
        )
        if roll is None:
            await self.dispatch_step_result(interaction, game, match, result)
            return

        player_team = match.team_for_player(player.player_id)
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
        self.persist(game, match)

        # The prompt becomes the die, and what it says follows in its
        # own message rather than riding above it -- see
        # SkillTestView.roll for why every result is announced this way
        # round.
        await interaction.edit_original_response(
            content=None,
            attachments=[dice_file],
            view=None,
        )
        # The second die between the check and its verdict. It matters
        # more here than anywhere: a backfire is the one thing in the
        # game that injures the player who rolled well.
        await self.post_volatile_ignition(
            interaction, match, (player.player_id, roll.ignite),
        )
        await send_new_prompt(interaction, result.narration[0])
        if not roll.safe:
            await self.refresh_match_image(interaction, game)

        await self.dispatch_step_result(
            interaction,
            game,
            match,
            StepResult(narration=result.narration[1:], next=result.next),
        )

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
        prompt = effect_choice_prompt(self.engine, match)
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

    # -- Follow-on adapters ------------------------------------------
    #
    # Every follow-on is called as
    # `(interaction, game, match, lead_in=..., **kwargs)`, and three of
    # the steps the model now names predate that shape: `send_turn_prompt`
    # takes no match, `begin_substitution_window` no lead-in, and
    # `start_set_up_shot` neither. Each is called from elsewhere with its
    # own signature, so the adapter is here rather than a signature change
    # rippling through their other callers. They go with the table in
    # Phase 6.

    async def send_turn_prompt_step(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        `send_turn_prompt` as a follow-on.

        `finish_maneuver_resolution` handles this member itself, to
        draw the board once and upload it twice; this is the row that
        keeps the table total over the enum, and the path any later
        caller of `SEND_TURN_PROMPT` would take.
        """
        if lead_in:
            await send_new_prompt(interaction, lead_in)
        try:
            await self.send_turn_prompt(interaction, game)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)

    async def begin_substitution_window_step(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        *,
        side: TeamSide,
        occasion: CoachingOccasion = CoachingOccasion.NEW_PLAY,
        is_response: bool = False,
        heading: str = "",
        lead_in: str = "",
    ) -> None:
        """
        `begin_substitution_window` as a follow-on.

        **`heading` and `lead_in` are two different things and both are
        here.** `lead_in` is the narration of whatever step named this
        one -- a new play's reset, the full-time whistle -- and is its
        own message above the menu. `heading` is the window's own
        opening line, which goes *inside* the prompt above the
        allowance; see `d12ball.flow.windows.open_substitution_window`.
        """
        if lead_in:
            await send_new_prompt(interaction, lead_in)
        await self.begin_substitution_window(
            interaction,
            game,
            match,
            side,
            occasion=occasion,
            is_response=is_response,
            lead_in=heading,
        )

    async def finish_setup_coaching_step(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """`finish_setup_coaching` as a follow-on: the kickoff board's
        caption is the step's own line, so it rides in rather than
        being posted above it."""
        await self.finish_setup_coaching(
            interaction, game, match, lead_in=lead_in,
        )

    async def finish_halftime_step(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """`finish_halftime` as a follow-on -- the same, for the second
        half's kickoff board."""
        await self.finish_halftime(interaction, game, match, lead_in=lead_in)

    async def announce_game_over_step(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        `announce_game_over` as a follow-on.

        **The game record is saved here rather than in the step.** The
        step that named this one called `game.finish_game()`, which is
        the record and not the match, so `persist` did not write it --
        and a process that died between the two would come back to a
        finished game that still reads as in progress. See principle 9
        in CLAUDE.md for why the match's own save is the caller's.
        """
        save_games(self.games)
        await self.announce_game_over(interaction, game, lead_in)

    async def start_set_up_shot_step(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        *,
        shooter_id: str,
        maneuver_cost: int = 1,
        lead_in: str = "",
    ) -> None:
        """
        The shot a set-up leads into, as a follow-on.

        **The rule is `arrivals.take_scoring_opportunity`** since Phase
        6 -- spending the offer, pointing the turn at the shooter and
        arming the shot -- and what is left under this member is the
        two uploads: the composition image and the roll prompt. Both
        callers come through here, the AI's own attempt and a coach's
        button, so the step runs once whichever asked for it.
        """
        if lead_in:
            await send_new_prompt(interaction, lead_in)
        result = take_scoring_opportunity(
            self.engine,
            game,
            match,
            shooter_id=shooter_id,
            maneuver_cost=maneuver_cost,
        )
        self.persist(game, match)
        await send_new_prompt(interaction, " ".join(result.narration))
        await self.begin_score_attempt(interaction, game, match)

    async def apply_ball_recovery_step(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        *,
        player_id: str,
        lead_in: str = "",
    ) -> None:
        """`apply_ball_recovery` as a follow-on."""
        await self.apply_ball_recovery(
            interaction, game, match, player_id, lead_in=lead_in,
        )

    def follow_on_methods(self) -> dict[FollowOnStep, Callable]:
        """
        Which method each `FollowOnStep` names.

        **A table, not a `getattr` on the member's name.** The model
        hands back a member of a closed enum and this is the only
        thing that turns one into a call, so nothing on the model's
        side can reach a cog method by spelling it. It is transitional
        and dies with `FollowOnStep` in Phase 6 of
        docs/model-discord-split.md, when the driver runs follow-ons
        itself.

        Built per call rather than at startup because the values are
        bound methods of a mixin assembled at import time; there is
        one dispatch per resolved maneuver, so the dictionary is not
        worth caching.
        """
        return {
            FollowOnStep.FINISH_MANEUVER_RESOLUTION:
                self.finish_maneuver_resolution,
            FollowOnStep.OFFER_SPEED_CHOICE: self.offer_speed_choice,
            FollowOnStep.BEGIN_RUN_BACK: self.begin_run_back,
            FollowOnStep.BEGIN_LOOSE_BALL: self.begin_loose_ball,
            FollowOnStep.OFFER_SETUP_PASS_PUSH_BACK:
                self.offer_setup_pass_push_back,
            FollowOnStep.FINISH_SETUP_COACHING:
                self.finish_setup_coaching_step,
            FollowOnStep.FINISH_HALFTIME: self.finish_halftime_step,
            FollowOnStep.ANNOUNCE_GAME_OVER: self.announce_game_over_step,
            FollowOnStep.SEND_TURN_PROMPT: self.send_turn_prompt_step,
            FollowOnStep.BEGIN_SUBSTITUTION_WINDOW:
                self.begin_substitution_window_step,
            FollowOnStep.START_SET_UP_SHOT: self.start_set_up_shot_step,
            FollowOnStep.CONTINUE_RUN_BACK: self.continue_run_back,
            FollowOnStep.APPLY_BALL_RECOVERY: self.apply_ball_recovery_step,
            FollowOnStep.SEND_MANEUVER_ACTION_PROMPT:
                self.send_maneuver_action_prompt,
            FollowOnStep.BEGIN_EFFECT_RESOLUTION:
                self.begin_effect_resolution,
            FollowOnStep.CONTINUE_EFFECT: self.continue_effect_step,
            FollowOnStep.BEGIN_MANEUVER_SKILL_TEST:
                self.begin_maneuver_skill_test,
            FollowOnStep.AUTO_RESOLVE_CHALLENGER:
                self.auto_resolve_challenger_step,
        }

    async def dispatch_step_result(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        result: StepResult,
    ) -> None:
        """
        Turn a `StepResult` into Discord: redraw the board if anything
        moved, then ask what it asks or run what it names.

        **The caller persists before calling this**, and that ordering
        is the transition rule for Phases 2 to 5 -- a lifted step no
        longer saves itself, and everything below is still the cog's,
        so a dispatch that ends in a prompt hands the turn to a click
        that reloads the match out of the save file. See
        `D12Ball.apply_low_pass` and principle 9 in CLAUDE.md.

        The narration is joined on a single space and carried into
        whatever comes next rather than posted on its own: a cascade of
        the bot's own steps is one message and one board refresh (see
        "Discord's rate limits" in docs/design/rate-limits.md), and the
        batching is the frontend's to decide -- which is what principle
        8 means. A result that neither asks nor continues has nobody to
        hand its lines to, so those it posts.

        **`board_changed` is the model's answer and the write is
        this method's decision.** A step says the board moved; whether
        that costs a request is read here, against
        `FOLLOW_ONS_THAT_DRAW_THE_BOARD` -- a step about to draw the
        same board under its own announcement is not drawn in front of.
        That is rank D1's answer and it is the step's rather than the
        calling card's, so every caller of `begin_loose_ball` gets it.

        A `PendingPrompt` goes through `view_for_prompt`, the same
        table a restart restores through. Two tables is how the live
        flow and the resume come to offer different questions -- see
        "d12ball/prompts.py" in docs/design/model-discord-split.md.
        """
        # **The loop is the driver's.** This used to walk the chain
        # itself -- look the member up in `follow_on_methods`, await
        # the cog wrapper, which called the flow function, saved, and
        # came back in here. `d12ball.flow.driver.advance` is that
        # walk with the Discord taken out, so the sequencing of a turn
        # is a rule a web app runs rather than one it would have to
        # copy (principle 10 in CLAUDE.md). What is left below is the
        # rendering: what becomes a message, what becomes a board
        # write, and which of the steps the driver cannot run comes
        # next.
        run = driver.advance(
            self.engine,
            game,
            match,
            result,
            stop_after=DRIVER_STOPS,
            own_message=DRIVER_OWN_MESSAGE,
            speaks_lines=FOLLOW_ONS_THAT_SPEAK_THE_LINES,
        )
        # **The one save, and it is here** -- principle 9. Every step
        # of the run has mutated the match and none of them has
        # written it: the wrappers that used to save between their own
        # step and this call no longer do (41 of them went), and the
        # steps the driver ran never did. So one write, after
        # everything that moves has moved and before anything is
        # posted, which is the ordering the whole principle is about:
        # a prompt hands the turn to a click that reloads the match
        # out of the save file, so the file has to be right first.
        #
        # It is unconditional rather than `if run.ran`, because the
        # caller's own step has almost always changed something and
        # the dispatcher cannot see that from here. One write per
        # click is what it was before; what has gone is the second,
        # third and fourth write of the same file inside one cascade.
        self.persist(game, match)
        result = run.result

        lead_in = " ".join(result.narration)
        following = result.next

        if result.board_changed and not (
            isinstance(following, FollowOn)
            and follow_on_draws_the_board(following)
        ):
            await self.refresh_match_image(interaction, game)

        # **The closed groups, before anything the run is still
        # carrying.** Each is a step whose lines are an event of their
        # own -- the reveal, the settled loose ball, "Players run
        # back!", the whistle -- and the step it is tagged with is what
        # picks its dispatcher. The board is already written above, so
        # the position is right by the time the first line naming it is
        # read, which is the ordering `post_blocks_then_dispatch` had
        # and the one the whistle depends on.
        for group in run.groups:
            if group.step in DRIVER_BLOCKS_PER_MESSAGE:
                for block in group.narration:
                    await send_new_prompt(interaction, block)
            else:
                block = " ".join(group.narration)
                if block:
                    await send_new_prompt(interaction, block)

        if isinstance(following, FollowOn):
            await self.follow_on_methods()[following.step](
                interaction, game, match, lead_in=lead_in, **following.kwargs,
            )
            return

        if isinstance(following, PendingPrompt):
            prompt_message = await send_new_prompt(
                interaction,
                " ".join(filter(None, (lead_in, following.ask))),
                view=self.view_for_prompt(game.game_id, match, following),
                # **Every prompt this posts may name a coach**, and
                # from Phase 4 most of them do -- an injury test, a
                # run-back choice and a loose-ball pick all open with a
                # mention. The settings are the ones all twenty-odd
                # hand-written prompt sites already pass: ping the user
                # asked, never a role and never the channel. Passing
                # them here rather than per prompt is what stops a
                # lifted prompt quietly picking up the library default,
                # which allows all three.
                allowed_mentions=discord.AllowedMentions(
                    users=True, roles=False, everyone=False,
                ),
            )
            # **The message a restart re-attaches the view to.** The
            # sites this method is absorbing each recorded it, and a
            # prompt that does not is one `on_ready` cannot put live
            # buttons back on -- the game falls back to
            # `/d12ball resume`. It is the game record rather than the
            # match, so it is `save_games` and not `persist`: the
            # caller has already written the match (principle 9), and
            # this is the id of the message that write led to. See
            # `restore_saved_views`.
            game.turn_message_id = prompt_message.id
            save_games(self.games)
            return

        if lead_in:
            await send_new_prompt(interaction, lead_in)

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

    def record_maneuver(
        self,
        game: D12BallGame,
        match: MatchState,
        winner_key: str,
    ) -> None:
        """
        Log the maneuver that has just been settled -- both picks, the
        winner, and how it was won.

        Called from `begin_effect_resolution`, which every maneuver in
        the game reaches **exactly once**: a decisive win and an
        unchallenged one go straight there from `resolve_maneuver`, and
        a tie goes there through the skill test and whatever injury
        tests it owed. A skill-test tie re-rolls without passing
        through, which is right -- nothing has been settled yet, and
        the re-roll logs a `skill_test` event of its own.

        **How it was won is read off the log, not off the match.** The
        obvious test -- ask `settled_maneuver_winner` whether the cards
        decided it -- is wrong here by a hair: the injury tests run
        between the roll and this call, so a skill test whose loser
        went down injured would come back reading as a win on the
        cards. The log cannot move under it that way: a `skill_test`
        event in this turn means the dice settled it, full stop.
        """
        decision = DECISION_UNCONTESTED
        if not match.maneuver_uncontested:
            rolled = any(
                event.kind == EVENT_SKILL_TEST
                for event in match.events_this_turn()
            )
            if rolled:
                decision = DECISION_SKILL_TEST
            elif self.maneuver_catalog.resolve(
                match.offense_maneuver, match.defense_maneuver,
            ) == "tie":
                # A tie nothing was rolled for is the one an injured
                # participant forfeits outright.
                decision = DECISION_INJURY_FORFEIT
            else:
                decision = DECISION_CARDS

        match.record_event(
            EVENT_MANEUVER,
            side=match.ball.possession,
            player_id=match.active_player_id,
            offense_key=match.offense_maneuver,
            defense_key=match.defense_maneuver,
            winner_key=winner_key,
            decision=decision,
            challenger_id=match.challenger_id,
        )
        # **Saved here, and this is not optional.** An effect that
        # ends in a prompt hands the turn to a click that will load
        # the match back out of the save file, so an event written and
        # not persisted is an event the next interaction never sees --
        # which is exactly what a Dribble Advance did, since its own
        # prompt saves the game record without rewriting the match
        # (correctly: nothing on the match had changed until now).
        # Anything that records has to save in the same breath.
        self.persist(game, match)

    async def begin_effect_resolution(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        winner_key: str,
        lead_in: str = "",
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
        # Always "" today: `resolve_maneuver` posts its reveal before
        # handing over, so nothing is waiting. Accepted and posted
        # rather than dropped, because every follow-on is called with
        # one.
        if lead_in:
            await send_new_prompt(interaction, lead_in)
        self.record_maneuver(game, match, winner_key)

        handlers = {
            "low_pass": self.resolve_low_pass,
            "dribble_advance": self.resolve_dribble_advance,
            "high_pass": self.resolve_high_pass,
            "deflect": self.resolve_deflect,
            "steal": self.resolve_steal,
            "pressure": self.resolve_pressure,
            "skilled_pass": self.resolve_skilled_pass,
            "dribble_burst": self.resolve_dribble_burst,
            "setup_pass": self.resolve_setup_pass,
            "clear": self.resolve_clear,
            "intercept": self.resolve_intercept,
            "double_team": self.resolve_double_team,
        }
        # **A tie settled by a skill test resolves as the basic card.**
        # A gambit's effect follows the cards, so a winner that only
        # won on the dice runs its counterpart's effect and the loser
        # pays nothing -- see `RulesEngine.gambit_cost_applies`.
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

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
from dataclasses import replace
from types import MappingProxyType
from typing import Mapping, Optional, Sequence

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
    RuleRefusal,
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
from d12ball.flow.turn import injured_word_and_emoji
from d12ball.prompts import (
    OPTIONS,
    SCORE_ATTEMPT_ASK,
    PendingPrompt,
    PromptKind,
    owed_step,
    pending_prompt,
    with_options,
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
from gamesaves.d12ball.service import (
    Batching,
    CarryFrom,
    GameResult,
    GameService,
    Narration,
    StopHandling,
)
from discord_emoji_cache import ensure_cached_emojis
from gamelocks import GameLocks
from cogs.d12ball_helpers import (
    COIN_EMOJI_NAMES,
    DiscordTokens,
    build_maneuver_action_caption,
    ERROR_RECOVERY_ADVICE,
    LOGGER,
    add_full_image_button,
    fetch_application_emojis,
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
#: message above it.
FOLLOW_ONS_THAT_SPEAK_THE_LINES = frozenset({
    FollowOnStep.ANNOUNCE_GAME_OVER,
})


#: Where the frontend has a picture of the position to put up, so the
#: driver must not run on past it: a loose ball is announced by
#: showing where it is, and the tail of a maneuver shows the board the
#: offensive choice is handed back over -- the next step is a whole AI
#: turn, which walks a challenger in. A new play's board is the third
#: picture and is the model's own stop (`StepResult.new_play`).
DRIVER_STOPS = frozenset({
    FollowOnStep.BEGIN_LOOSE_BALL,
    FollowOnStep.FINISH_MANEUVER_RESOLUTION,
})


#: Every step the driver runs whose lines are **a message of their
#: own**, so the loop must stop carrying them forward once it has run.
#: `driver.advance` closes a group after each of these and `present`
#: posts it -- which keeps the decision exactly where principle 8 puts
#: it, and stops it being a flag on `StepResult`.
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
    # The whistle and the runs of separate events behind it.
    FollowOnStep.END_PERIOD,
    FollowOnStep.CONTINUE_SHOOTOUT,
    FollowOnStep.FINISH_SUBSTITUTION_WINDOW,
    # A window's lead-in is a message above the menu, and an AI side's
    # window is a run of separate events.
    FollowOnStep.BEGIN_SUBSTITUTION_WINDOW,
    # The lines a turn opens with, each a message above the turn
    # prompt; the turn itself says nothing here.
    FollowOnStep.START_TURN,
    # "X takes the shot off the set-up", above the composition.
    FollowOnStep.START_SET_UP_SHOT,
    # A resumed halftime's stages are each a message, as they are
    # when the whistle reaches them in one run.
    FollowOnStep.ADVANCE_HALFTIME_STAGE,
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
    # The lines a turn opens with, a message per thing said.
    FollowOnStep.START_TURN,
    FollowOnStep.START_SET_UP_SHOT,
    # Resumed, for the whistle's reason.
    FollowOnStep.ADVANCE_HALFTIME_STAGE,
})


#: How much of an AI answer's lines are a message of their own, by
#: the kind answered -- **the same split each kind's view passes as
#: `carry_from`** when a coach answers it, so an AI answer reads as a
#: coach's: the distance menus' answers open the effect's own message
#: (0), a declined offer's first line replaces the offer and the rest
#: carries (1), and everything else is posted as the view would have
#: posted it. A kind not listed keeps every line.
AI_ANSWER_CARRY: Mapping[PromptKind, CarryFrom] = {
    # A challenger nobody was asked for walks in over the challenge
    # image, and the answer's own line opens it (`PlayerActionView`).
    PromptKind.PLAYER_ACTION: lambda answered: (
        0
        if isinstance(answered.result.next, FollowOn)
        and answered.result.next.step is FollowOnStep.AUTO_RESOLVE_CHALLENGER
        else None
    ),
    # A placement is part of the cascade's one message
    # (`CONTINUE_RUN_BACK` composes it), not a message of its own.
    PromptKind.RUN_BACK_PLAYER: 0,
    PromptKind.RUN_BACK_SPACE: 0,
    PromptKind.LOW_PASS_CHOICE: 0,
    PromptKind.HIGH_PASS_CHOICE: 0,
    PromptKind.SETUP_PASS_CHOICE: 0,
    PromptKind.SETUP_PASS_PUSH_BACK: 0,
    PromptKind.SET_UP_ATTEMPT: 0,
    PromptKind.DRIBBLE_ADVANCE_CHOICE: 0,
    PromptKind.DRIBBLE_BURST_CHOICE: 0,
    PromptKind.SHOOTER_CHOICE: 0,
    # A pull that lands opens what follows; one that misses, or is
    # let go, is a line of its own (`MindPullView`). The Smooth's two
    # answers split the same way, on the choice -- see `carry_answer`.
    PromptKind.MIND_PULL: lambda answered: (
        1 if answered.detail is None or not answered.detail.pulled else 0
    ),
}


class DiscordBatching(Batching):
    """
    The Discord frontend's batching, handed to `GameService` once.

    The three sets above are its fields; `at_stop` is what the cog
    does where the loop stopped for it, and `carry_answer` how an AI
    answer's lines split, by `AI_ANSWER_CARRY`. This is the whole of
    principle 8's "the frontend owns batching" in one object: the
    service never reads a step's name to decide anything, it asks
    this.
    """

    def __init__(self) -> None:
        super().__init__(
            stop_after=DRIVER_STOPS,
            own_message=DRIVER_OWN_MESSAGE,
            speaks_lines=FOLLOW_ONS_THAT_SPEAK_THE_LINES,
        )

    def at_stop(self, stopped, result, following) -> StopHandling:
        """
        A new play is drawn, posted and pinned. A loose ball is drawn
        where it is genuine (the step moved the ball and has something
        to say); a long High Pass's contest is a plain message over
        the board the pass already wrote. The tail of a maneuver draws
        when it hands the offensive choice back, and carries its lines
        on into whatever else it hands to -- the whistle, a gate.
        """
        if result.new_play:
            return StopHandling.DRAW
        if stopped.step is FollowOnStep.BEGIN_LOOSE_BALL:
            if result.narration and result.board_changed:
                return StopHandling.DRAW
            return StopHandling.POST
        if stopped.step is FollowOnStep.FINISH_MANEUVER_RESOLUTION:
            if (
                isinstance(following, FollowOn)
                and following.step is FollowOnStep.SEND_TURN_PROMPT
            ):
                return StopHandling.DRAW
            return StopHandling.CARRY
        return StopHandling.DRAW

    def carry_answer(self, action, answered) -> CarryFrom:
        if action.kind is PromptKind.SMOOTH:
            # Taking the ball over opens what follows; letting it pass
            # is a line of its own (`SmoothView`).
            return 1 if action.choice == "decline" else 0
        return AI_ANSWER_CARRY.get(action.kind)


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

    # The condition, team, role and species-ability emoji, each empty
    # until `cog_load` has fetched them and replaced whole on every
    # fetch. They are the frontend's: the model names a team, a
    # badge, a condition or a species with a token
    # (`d12ball/tokens.py`) and `render_text` below draws it from
    # these four -- see `DiscordTokens`. They lived on the engine
    # until step 9 of docs/architecture-migration.md. The defaults are
    # read-only class attributes rather than dicts made in `__init__`
    # so a cog built without it (every test's) reads "nothing fetched"
    # and cannot mutate a dict shared by every instance.
    condition_emojis: Mapping[str, str] = MappingProxyType({})
    team_emojis: Mapping[Team, str] = MappingProxyType({})
    role_emojis: Mapping[tuple[PlayerRole, Optional[Team]], str] = (
        MappingProxyType({})
    )
    species_ability_emojis: Mapping[str, str] = MappingProxyType({})

    #: The web frontend, where the environment asked for one -- see
    #: `start_web_app`. `None` in every test and in any checkout that
    #: has not set `FOOLBOT_WEB_PORT`.
    web_app = None

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
        # The four emoji mappings are class defaults above, until
        # cog_load replaces them.
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
                restored = self.pending_turn_view(game.game_id, match)
                if restored is None:
                    # Nobody is asked anything here: the bot owes a step
                    # of its own, or the AI owes an answer, and nothing
                    # will run either until somebody asks for it -- the
                    # message this would have re-armed is a prompt the
                    # position has moved past. An ERROR because
                    # somebody has to act, and the sweep runs once per
                    # process, so it will not repeat on every
                    # reconnect.
                    owed = owed_step(self.engine, game, match)
                    LOGGER.error(
                        "D12 Ball game %s owes %s and has no prompt to "
                        "re-arm; `/d12ball resume` in its channel runs "
                        "it.",
                        game.game_id,
                        f"a step of the bot's own ({owed.step.name})"
                        if owed is not None else "the AI's answer",
                    )
                    continue
                turn_view, _ = restored
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
        await self.start_web_app()

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

    async def start_web_app(self) -> None:
        """
        Put the web frontend up over this cog's service, where the
        environment has asked for one (`FOOLBOT_WEB_PORT`; see
        docs/design/web-app.md).

        **The same service and the same locks**, because there is one
        process and one `games` dict (decision 5 of docs/web-app.md):
        the web app is a second frontend over the bot's own game, not
        a second copy of it. The import is here rather than at the top
        of the module so a checkout with no web app configured pays
        nothing for it, and a failure to bind is an ERROR -- the port
        is somebody's to free, and the bot carries on playing on
        Discord either way.
        """
        from webapp.server import configured_port, start_web_app

        if configured_port() is None:
            # Nothing is asked for, so nothing is built -- not even the
            # service, which a cog a test assembles without `__init__`
            # has no games to make one over.
            return
        try:
            self.web_app = await start_web_app(self.service, self.locks)
        except OSError as error:
            self.web_app = None
            LOGGER.error("The web app could not start: %r", error)

    async def cog_unload(self) -> None:
        """
        Drop any board refresh still waiting on its window -- see
        `BoardRefresher.shutdown` for what that costs a board -- and
        take the web frontend down with the cog it was serving.
        """
        self.boards.shutdown()
        if self.web_app is not None:
            await self.web_app.stop()
            self.web_app = None

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

    def game_for_channel(self, channel_id: int) -> Optional[D12BallGame]:
        for game in self.games.values():
            if game.channel_id is not None and game.channel_id == channel_id:
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

    def render_text(
        self,
        text: str,
        game: Optional[D12BallGame] = None,
    ) -> str:
        """
        Every token the model left in `text`, drawn the way Discord
        draws it: the team rings, the role badges, the condition and
        species marks from the four dicts above, and `{coach:n}` as a
        mention of the account -- which needs the `game`, so a caller
        rendering a sentence that may address a coach passes it. See
        `DiscordTokens`, and "Tokens" in docs/design/model-discord-split.md.
        """
        return self.tokens(game).render(text)

    def tokens(self, game: Optional[D12BallGame] = None) -> DiscordTokens:
        """The resolver over this cog's four emoji dicts and, with the
        `game`, its coaches -- built here and nowhere else."""
        return DiscordTokens(
            self.team_emojis,
            self.role_emojis,
            self.condition_emojis,
            self.species_ability_emojis,
            game,
        )

    def rendered(self, game: D12BallGame, result: GameResult) -> GameResult:
        """
        A `GameResult` with every sentence in it rendered for Discord
        -- the answer's lines, each group's, the narration still
        carried, the prompt's ask and a refusal's reason. **The one
        place a result is rendered**, at the door the service hands
        it back through (`apply_action` for a click, `present_result`
        for everything the bot runs itself), so a view and the
        presenter read Discord text and never a token; the frontend
        renders once, the way a `PromptKind` becomes a view once.
        """
        render = self.tokens(game).render

        def prompt(pending: Optional[PendingPrompt]) -> Optional[PendingPrompt]:
            if pending is None:
                return None
            return replace(pending, ask=render(pending.ask))

        return replace(
            result,
            answer=tuple(render(line) for line in result.answer),
            groups=tuple(
                replace(group, lines=tuple(render(line) for line in group.lines))
                for group in result.groups
            ),
            narration=tuple(render(line) for line in result.narration),
            prompt=prompt(result.prompt),
            refusal=None if result.refusal is None else render(result.refusal),
            waiting_on=prompt(result.waiting_on),
        )

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

        `RulesEngine.format_player_label` names the player with
        tokens, and this renders them (`render_text`). Kept here so no
        call site moved: ninety-odd sites already read this rather
        than spelling out the label and its arguments for themselves.
        """
        return self.render_text(self.engine.format_player_label(match, player))

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
        this frontend's caption over the prompt's own ask
        (`build_maneuver_action_caption`); a tutorial's note
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
        it: `d12ball.flow.turn.injured_word_and_emoji`, with the mark
        rendered here since the flow hands back a token.
        """
        word, mark = injured_word_and_emoji(self.engine, game, player_id)
        return word, self.render_text(mark)

    def exhausted_word_and_emoji(
        self,
        game: D12BallGame,
        player_id: str,
    ) -> tuple[str, str]:
        """
        What a player over their token threshold is called, and the
        mark for it: `RulesEngine.exhausted_word_and_mark`, rendered
        here.
        """
        word, mark = self.engine.exhausted_word_and_mark(game, player_id)
        return word, self.render_text(mark)

    def token_word_and_emoji(
        self,
        game: D12BallGame,
        player_id: str,
    ) -> tuple[str, str]:
        """
        What a player's exhaustion tokens are called, and the mark they
        are counted out in: `RulesEngine.token_word_and_mark`, rendered
        here.
        """
        word, mark = self.engine.token_word_and_mark(game, player_id)
        return word, self.render_text(mark)


    async def post_injury_die(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        result: GameResult,
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
        roll = result.detail
        if roll is None:
            await self.present(interaction, game, result)
            return

        player = self.engine.get_player_definition(roll.player_id)
        player_team = match.team_for_player(roll.player_id)
        injured_word, _ = injured_word_and_emoji(
            self.engine, game, roll.player_id,
        )
        dice_file = discord.File(
            await asyncio.to_thread(
                render_injury_test_die,
                roll.roll,
                TEAM_COLORS[player_team],
                team_display_name(player_team),
                player.name,
                roll.safe,
                bool(roll.overdrive),
                injured_word,
                self.engine.injury_test_name(game, roll.player_id).upper(),
            ),
            filename="injury_test_die.png",
        )
        await interaction.edit_original_response(
            content=None,
            attachments=[dice_file],
            view=None,
        )
        # The second die between the check and its verdict. It matters
        # more here than anywhere: a burn is the one thing in the
        # game that injures the player who rolled well.
        await self.post_volatile_ignition(
            interaction, match, (roll.player_id, roll.ignite),
        )
        await send_new_prompt(interaction, result.answer[0])
        await self.present(interaction, game, result)


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
        # Which sides still owe an answer, and to which of the two
        # questions, is the prompt's (`ShootoutOptions.owed`) -- the
        # same reading the menus themselves open by.
        prompt = pending_prompt(self.engine, game, match)
        menus = {
            PromptKind.SHOOTOUT_ORDER: ShootoutOrderSelectView,
            PromptKind.SHOOTOUT_PICK: ShootoutPickSelectView,
        }
        if prompt is None or prompt.kind not in menus:
            return 0
        registered = 0
        for side in prompt.options.owed():
            if self.engine.side_is_ai(game, side):
                continue
            # timeout=None because add_view refuses anything else: a
            # view it cannot see the message for has nothing to time
            # out against.
            self.bot.add_view(
                menus[prompt.kind](self, game.game_id, side, timeout=None),
            )
            registered += 1

        return registered

    def pending_turn_view(
        self,
        game_id: str,
        match: MatchState,
    ) -> Optional[tuple[discord.ui.View, str]]:
        """
        The prompt a saved match still owes: the view to put in front
        of whoever it is waiting on, and the line asking for it -- or
        `None` where nobody is asked, because the bot owes a step of
        its own (`d12ball.prompts.owed_step`). There is no button to
        restore for one of those; `/d12ball resume` runs the step.

        **The reading is the model's** --
        `d12ball.prompts.pending_prompt` is the branch chain that used
        to be this method's body, ordering comments and all, so a web
        app can ask the same question rather than growing a second copy
        of it (see "The model and the Discord layer" in CLAUDE.md).
        What is left here is the rendering: the view, and the `ask`
        with its tokens drawn (`render_text`).

        `restore_saved_views` re-attaches what this returns to the
        message the prompt is already on, which is why it returns a
        view rather than sending it; a resume posts a fresh one through
        `GameService.resume` and `render_prompt` -- see "Recovering a
        stuck game" in docs/design/recovery.md.
        """
        game = self.games[game_id]
        prompt = pending_prompt(self.engine, game, match)
        if prompt is None or driver.ai_action(
            self.engine, game, match, prompt,
        ) is not None:
            # The AI's question is nobody's button: the service
            # answers it (`GameService.run`), and a save waiting on one
            # is a run that never finished -- `/d12ball resume` runs
            # it on.
            return None
        return (
            self.view_for_prompt(game_id, match, prompt),
            self.render_text(prompt.ask, game),
        )

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
        parameter are the branches below. Every view builds its
        buttons from the prompt's `options` (`SafeView.prompt_options`,
        which re-reads the chain), and the three handed a list here
        read the prompt's own; a prompt built without them -- by hand,
        in a test or a command -- gets them off `match` first, so this
        stays the one place a kind becomes a view whatever built the
        prompt.
        """
        if prompt.options is None and prompt.kind in OPTIONS:
            prompt = with_options(
                self.engine, self.games[game_id], match, prompt,
            )
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
            return SmoothView(
                self, game_id, prompt.player_id, prompt.options.keeper_id,
            )
        if kind is PromptKind.INJURY_TEST:
            return InjuryTestView(self, game_id, prompt.player_id)
        if kind is PromptKind.RUN_BACK_SPACE:
            return RunBackChoiceView(self, game_id, prompt.player_id)
        if kind is PromptKind.RUN_BACK_PLAYER:
            return RunBackPlayerChoiceView(
                self, game_id, list(prompt.options.player_ids),
            )
        if kind is PromptKind.LOOSE_BALL_PICK:
            return LooseBallChoiceView(
                self, game_id, prompt.skill_type, prompt.options, match,
            )
        if kind is PromptKind.LOW_PASS_CHOICE:
            return LowPassChoiceView(self, game_id)
        if kind is PromptKind.SPEED_DELTA_CHOICE:
            return SpeedDeltaChoiceView(self, game_id, prompt.player_id)
        if kind is PromptKind.SET_UP_ATTEMPT:
            return SetUpAttemptChoiceView(
                self,
                game_id,
                prompt.player_id,
                contest_on_decline=prompt.contest_on_decline,
            )

        if kind is PromptKind.SHOOTER_CHOICE:
            return ShooterChoiceView(
                self, game_id, list(prompt.options.player_ids),
            )
        return PLAIN_PROMPT_VIEWS[kind](self, game_id)

    # -- The service and the presenter -----------------------------------

    @property
    def locks(self) -> GameLocks:
        """
        **One lock per game, held around a click's whole answer** --
        the apply *and* what it puts in the channel -- so two answers
        cannot be presented in the other order from the one they were
        applied in. See `gamelocks.py` for why that, and not the apply
        alone, is what needs holding; `SafeView._scheduled_task` is
        where every click takes it, and the web app takes the same one
        over the same games (decision 5 of docs/web-app.md).

        Built on first use, like `service`, so a cog a test assembles
        without `__init__` has one.
        """
        locks = self.__dict__.get("_locks")
        if locks is None:
            locks = GameLocks()
            self.__dict__["_locks"] = locks
        return locks

    @property
    def service(self) -> GameService:
        """
        **The one door for a change to a game** -- ARCHITECTURE.md,
        part 2 -- over this cog's engine and the games it loaded, with
        the Discord batching. Every click and command goes through it:
        it runs the driver, saves once, and hands back a `GameResult`
        that `present` renders.

        Built on first use rather than in `__init__`, and rebuilt if
        the engine or the games dict it was built over is replaced --
        which is what a test builder does when it assembles a cog
        without `__init__` and hands it its own.
        """
        service = self.__dict__.get("_service")
        if (
            service is None
            or service.engine is not self.engine
            or service.games is not self.games
        ):
            service = GameService(self.engine, self.games, DiscordBatching())
            self.__dict__["_service"] = service
        return service


    def apply_action(
        self,
        game: D12BallGame,
        action: driver.Action,
        *,
        carry_from: CarryFrom = None,
    ) -> GameResult:
        """
        One click, applied and rendered: `GameService.apply_action` --
        load, apply, save once, return -- with the result's tokens
        drawn for Discord at the door (`rendered`). A view renders the
        answer's own lines and hands the rest to `present`.
        """
        return self.rendered(
            game,
            self.service.apply_action(
                game.game_id, action, carry_from=carry_from,
            ),
        )

    async def dispatch_step_result(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        result: StepResult,
        *,
        carry: bool = True,
    ) -> None:
        """
        Run what a step handed back, save once, and present it -- the
        entry point for the bot's own steps (a command that names a
        step, a gate skipped, the tests' `run_step`).

        A step refusing a position it should never have been handed
        raises `RuleRefusal`; whatever ran before it is written down by
        the service, and the refusal is reported rather than acted on.
        Any other error out of a step is a bug and propagates.
        """
        try:
            outcome = self.service.run(game, match, result, carry=carry)
        except RuleRefusal as error:
            await send_error_fallback(interaction, str(error))
            return
        await self.present_result(interaction, game, outcome)

    async def present_result(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        result: GameResult,
    ) -> None:
        """
        A result straight from the service, rendered and presented --
        the one line every entry point the bot runs itself ends on
        (`begin_setup_coaching`, `resume_game`, `send_turn_prompt`,
        `dispatch_step_result`). A click's result goes through
        `apply_action` instead, since its view renders the answer's
        own lines first.
        """
        await self.present(interaction, game, self.rendered(game, result))

    async def present(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        result: GameResult,
    ) -> None:
        """
        Turn a `GameResult` into Discord: write the board once if it
        moved, post each group as the messages its step earns, draw
        each picture from the position the service took at that stop,
        and put up what is asked through `render_prompt`.

        **It saves nothing.** The service wrote the match once, before
        this was called, which is the ordering principle 9 is about: a
        prompt hands the turn to a click that reloads the match out of
        the save file, so the file has to be right first.

        **`board_changed` is the model's answer and the write is this
        method's decision.** A drawn group writes the persistent board
        from the same render (render once, upload twice), so the plain
        write is owed only for what moved after the last picture, and
        it goes in front of the first thing posted after it. A prompt
        whose answer draws the board a moment later
        (`PROMPTS_DRAWN_LATER`) is not drawn in front of.
        """
        groups = result.groups
        prompt = result.prompt
        last_drawn = max(
            (index for index, group in enumerate(groups) if group.drawn),
            default=-1,
        )
        write_owed = result.board_changed and not (
            prompt is not None and prompt.kind in PROMPTS_DRAWN_LATER
        )

        for index, group in enumerate(groups):
            if write_owed and index == last_drawn + 1:
                await self.refresh_match_image(interaction, game)
            await self.post_group(
                interaction, game, result.match, group, list(group.lines),
            )

        if write_owed and len(groups) == last_drawn + 1:
            await self.refresh_match_image(interaction, game)

        lines = list(result.narration)
        if prompt is not None:
            await self.render_prompt(
                interaction, game, result.match, prompt, " ".join(lines),
            )
            return
        if lines:
            await send_new_prompt(interaction, " ".join(lines))

    async def post_group(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        group: Narration,
        lines: list[str],
    ) -> None:
        """
        One group, as the messages the step it came from earns.

        - A drawn group is a picture of the position: a new play's
          board, posted and pinned with the last line as its caption
          and any earlier lines a message above it; the tail of a
          maneuver, one last board with everything settled, drawn once
          and uploaded twice; a loose ball, named and drawn together.
        - The caller's own lines (no step) and a period transition's
          are one message per block; the walk-in for a challenger
          nobody was asked for rides on the challenge image; everything
          else is one message.
        """
        if group.drawn:
            snapshot = group.board
            if group.new_play:
                if len(lines) > 1:
                    await send_new_prompt(interaction, " ".join(lines[:-1]))
                await self.post_new_play_board(
                    interaction, game, lines[-1] if lines else "",
                    snapshot=snapshot,
                )
                return
            if group.step is FollowOnStep.FINISH_MANEUVER_RESOLUTION:
                png = await self.render_match_png(game, snapshot=snapshot)
                await self.refresh_match_image(interaction, game, png=png)
                if len(lines) > 1:
                    await send_new_prompt(interaction, " ".join(lines[:-1]))
                posted = await send_new_prompt(
                    interaction,
                    lines[-1] if lines else "",
                    file=self.match_file_from_png(game, png),
                )
                await add_full_image_button(posted)
                return
            await self.announce_board_update(
                interaction, game, " ".join(lines), snapshot=snapshot,
            )
            return

        if group.step is FollowOnStep.AUTO_RESOLVE_CHALLENGER:
            # The challenger the walk-in named, read off the group
            # rather than off the match: the match has moved on by
            # now, and reading it there drew the image of whoever the
            # position happened to hold.
            await self.announce_maneuver_challenge(
                interaction,
                match,
                group.arguments["challenger_id"],
                " ".join(lines),
            )
            return
        if group.action is not None:
            await self.post_ai_answer(interaction, group, lines)
            return
        if group.prompt is not None:
            # What a coach's prompt message would have opened with,
            # for a question the AI answered before anybody saw it:
            # one message, joined the way `render_prompt` joins it.
            await self.post_blocks(interaction, lines)
            return
        await self.post_blocks(
            interaction,
            lines,
            per_message=(
                group.step is None or group.step in DRIVER_BLOCKS_PER_MESSAGE
            ),
        )

    async def post_blocks(
        self,
        interaction: discord.Interaction,
        lines: list[str],
        *,
        per_message: bool = False,
    ) -> None:
        """The lines as one message joined on a space, or one message
        per non-empty block; nothing at all for nothing to say."""
        blocks = lines if per_message else [" ".join(lines)]
        for block in blocks:
            if block:
                await send_new_prompt(interaction, block)

    async def post_ai_answer(
        self,
        interaction: discord.Interaction,
        group: Narration,
        lines: list[str],
    ) -> None:
        """
        An AI answer's own lines, posted the way the kind's view posts
        a coach's -- the frontend's half of "the human's exact voice"
        (step 7 of docs/architecture-migration.md), keyed on the
        action the way a prompt's picture is keyed on the kind.

        - A hub note is the text above the hub's own buttons and is
          never a message; only "done" says anything the channel reads.
        - The shootout's first block is the coach's own secret (the
          order so far, "you send out"), shown on their ephemeral menu;
          the public line and the reveal behind it are the rest.
        - The maneuver pick and the halftime token post a message per
          block, as their views do; everything else is one message.
        """
        kind = group.action.kind
        if kind is PromptKind.COACHING_HUB and group.action.choice != "done":
            return
        if kind in (PromptKind.SHOOTOUT_ORDER, PromptKind.SHOOTOUT_PICK):
            lines = lines[1:]
        await self.post_blocks(
            interaction,
            lines,
            per_message=kind in (
                PromptKind.MANEUVER_ACTION,
                PromptKind.HALFTIME_EXTRA_TOKEN,
                PromptKind.SHOOTOUT_ORDER,
                PromptKind.SHOOTOUT_PICK,
            ),
        )

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
        the prompt's message as its own paragraph -- except in front
        of the shot, where it is a message of its own above the
        composition, which is how "X has chosen to shoot" always read.

        **The message a restart re-attaches the view to** is recorded
        on the way out (`turn_message_id`), whichever branch posted it.
        A prompt that is not recorded is one `on_ready` cannot put live
        buttons back on. It is the game record rather than the match,
        so it is `save_games` and not `persist`: the match was written
        before anything was posted (principle 9), and this is the id
        of the message that write led to.
        """
        kind = prompt.kind
        content = "\n\n".join(filter(None, (lead_in, prompt.ask)))
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
            # The one ask this frontend words for itself: the model
            # says who picks and that the pick is secret, and Discord
            # adds which row is theirs (`build_maneuver_action_caption`).
            caption = self.render_text(
                build_maneuver_action_caption(self.engine, game, match), game,
            )
            await self.send_maneuver_action_prompt(
                interaction, game, match,
                "\n\n".join(filter(None, (lead_in, caption))),
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



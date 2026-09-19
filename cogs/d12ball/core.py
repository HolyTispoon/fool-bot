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
import random
import time
from typing import Optional, Sequence

from discord import app_commands
from discord.ext import commands
from d12ball.ai import build_ai_strategies
from d12ball.engine import RulesEngine
from d12ball.components import (
    DECISION_CARDS,
    DECISION_INJURY_FORFEIT,
    DECISION_SKILL_TEST,
    DECISION_UNCONTESTED,
    EVENT_INJURY_TEST,
    EVENT_MANEUVER,
    EVENT_SKILL_TEST,
    EVENT_TURN_ACTION,
    MANEUVER_TIER_ADVANCED,
    MANEUVER_TIER_BASIC,
    MatchState,
    PlayerDefinition,
    PlayerRole,
    TeamSetup,
    TeamSide,
    legacy_maneuver_key,
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
from d12ball.cards import render_maneuver_hands
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
    contest_noun,
    fetch_application_emojis,
    format_player_with_team,
    format_role_bracket,
    format_team_side_label,
    get_injured_emoji,
    load_coin_emojis,
    load_condition_emojis,
    load_d12_emoji,
    load_d12_button_emoji,
    load_role_emojis,
    load_team_emojis,
    send_error_fallback,
    send_new_prompt,
    space_label,
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
    LobbyView,
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
        self.condition_emojis: dict[str, str] = {}
        self.team_emojis: dict[Team, str] = {}
        # The role emoji live on the engine -- see `role_emojis` below.
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
        # The cards the maneuver prompt carries.
        #
        # **Keyed by the sides on the prompt and the tiers they may
        # play.** The prompt is public and carries a hand for every side
        # that still has a human pick to make, so the sides are the two
        # of them, or one alone when the maneuver is unchallenged or the
        # other side is Dinky's -- see `RulesEngine.maneuver_pick_sides`
        # and `maneuver_tiers`.
        self.maneuver_hand_image_bytes = {
            (sides, tiers): render_maneuver_hands(
                self.maneuver_catalog, self.player_catalog, sides, tiers
            ).read()
            for sides in (
                ("offense",),
                ("defense",),
                ("offense", "defense"),
            )
            for tiers in (
                (MANEUVER_TIER_BASIC,),
                (MANEUVER_TIER_BASIC, MANEUVER_TIER_ADVANCED),
            )
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
        Open a turn in the event log -- see MatchEvent.

        **Every event in a turn belongs to the `turn_action` that
        opened it**, and belongs to it by being logged after it, so
        this has to be called before anything the turn does.

        `action` is the button's own value -- `maneuver` or `shoot`
        -- so the share of each in the statistics is the share of the
        choice a coach actually made, not of what it led to. **A time
        out is not one of them**: it is a pause inside a possession
        rather than a turn, and it records its own event kind instead
        -- see EVENT_TIME_OUT and `begin_time_out`.

        The three callers are `play_ai_turn` and the two turn
        actions, each at the point the action is **taken**: the shot
        and the maneuver at their button, past its own stale-view
        guard.
        """
        match.record_event(
            EVENT_TURN_ACTION,
            side=match.ball.possession,
            player_id=match.active_player_id,
            action=action,
            by_ai=by_ai,
        )

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

        This is `format_role_bracket` with the two arguments that are
        the same at every call site already filled in. The emoji dict
        is the cog's, and the team is **always** the one the match is
        fielding this card as: a player belongs to two rosters, so
        their definition cannot answer it and `match.team_for_player`
        has to (see "One player, both sides" in docs/design/teams-and-players.md). Ninety-odd
        sites wrote out all three, which put the same forty characters
        of lookup in front of every player's name in the codebase.

        `format_role_bracket` itself is still the right call for the
        few places that have a `TeamSetup` rather than a match, and
        so already know the side without asking.
        """
        return format_role_bracket(
            player,
            self.team_emojis,
            match.team_for_player(player.player_id),
            self.role_emojis,
        )

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
        Which hexagon to post: the advanced one for a game actually
        playing the advanced maneuvers, the basic one everywhere else
        -- including outside a game's channel, where there is nothing
        to ask. Through `advanced_maneuvers_apply` rather than off
        `game.mode`, or an advanced game that opted the maneuvers out
        would be handed a reference to six cards it will never hold.
        """
        if game is not None and self.engine.advanced_maneuvers_apply(game):
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
        sides: Sequence[str],
        tiers: tuple[str, ...] = (MANEUVER_TIER_BASIC,),
    ) -> discord.File:
        """
        The cards on offer this maneuver, wrapped fresh each time:
        uploading a `discord.File` consumes the stream inside it, so the
        bytes are what is kept and the file is built per send -- the
        same reason `render_match_png` returns bytes rather than a File.
        """
        sides = tuple(sides)
        return discord.File(
            io.BytesIO(self.maneuver_hand_image_bytes[(sides, tuple(tiers))]),
            filename=f"maneuver_hand_{'_'.join(sides)}.png",
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
        await send_new_prompt(
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
            view=ScoreAttemptView(self, game.game_id),
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
            game, match, challenger_id, distance,
        )
        self.persist(game, match)

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

        await send_new_prompt(
            interaction,
            f"**Unchallenged!** {format_team_side_label(defense_setup)} "
            f"{reason} "
            f"{self.player_label(match, handler)}, "
            "so whichever maneuver the offense picks succeeds."
        )
        await self.begin_maneuver_action_selection(interaction, game, match)

    def write_ai_maneuver_picks(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Dinky answers before the prompt is built, which is what makes a
        solo game's prompt one hand and one row --
        `RulesEngine.maneuver_pick_sides` is read afterwards, so it
        already knows the AI has picked.

        A tutorial beat names the card Dinky plays, and it is written
        straight into the match here rather than through the strategy:
        `choose_maneuver_action` takes a side and nothing else, so it
        has no way to know which beat is running, and changing its
        signature for one caller would put the script inside the AI.
        Dinky's pick is made before the coach's exactly as it always is
        -- the rails decide what the coach may answer with, not the
        other way round.
        """
        if not game.is_solo_game:
            return

        ai_strategy = self.engine.get_ai_strategy(game)
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

    def maneuver_prompt_wording(
        self,
        game: D12BallGame,
        match: MatchState,
        sides: list[str],
    ) -> tuple[list[str], str]:
        """
        Who is mentioned above the prompt, and what they are told to do.

        Both come off the same `sides` list the buttons are built from,
        which is the point: a coach named here and given no row to
        press would stall a game, and nothing else would catch it.
        """
        waiting_on = [
            format_player_with_team(
                game,
                self.engine.possession_player_number(game, match)
                if side == "offense"
                else self.engine.defending_player_number(game, match),
                self.team_emojis,
                mention=True,
            )
            for side in sides
        ]

        # The buttons are on the message, so there is nothing to tell a
        # coach to open. What the wording has to do instead is say which
        # row is theirs, since a contested prompt carries both.
        #
        # A lone side is not always the offense: a solo game's prompt
        # is one row, and it is the *defense's* whenever Dinky has the
        # ball. So the colour is read off the side rather than written
        # down -- it is the row's own colour either way (offense red,
        # defense green; see ManeuverActionPromptView).
        instruction = (
            "choose a maneuver from the "
            f"{MANEUVER_ROW_COLOURS[sides[0]]} row -- only you can "
            "see what you picked."
            if len(sides) == 1
            else (
                "both sides pick privately from the same message: red "
                "for the offense, green for the defense. Only you can "
                "see what you picked."
            )
        )

        return waiting_on, instruction

    async def begin_maneuver_action_selection(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Kick off the simultaneous maneuver-action choice once a
        challenger has been chosen: the AI opponent picks immediately,
        and every human side gets its own row of buttons on **one
        public prompt** -- see `ManeuverActionPromptView` for why the
        cards can be public while the pick stays secret.

        An uncontested maneuver comes through here too, and waits on
        the offense alone -- there is no defender to pick a defensive
        maneuver, and nothing secret about a pick with nobody to
        conceal it from, but the prompt is the same one so the coach
        reads the same cards they always do.
        """
        self.write_ai_maneuver_picks(game, match)

        self.persist(game, match)

        if match.maneuver_selections_complete:
            await self.resolve_maneuver(interaction, game, match)
            return

        sides = self.engine.maneuver_pick_sides(game, match)
        waiting_on, instruction = self.maneuver_prompt_wording(
            game, match, sides,
        )

        async def show_prompt(inner_interaction: discord.Interaction) -> None:
            prompt_view = ManeuverActionPromptView(self, game.game_id)
            # The cards ride on the prompt itself. One image, not one
            # per side: Discord lays two attachments out side by side,
            # which would halve the width of both hands. See
            # render_maneuver_hands for why showing both gives nothing
            # away.
            prompt_message = await send_new_prompt(
                inner_interaction,
                f"{' and '.join(waiting_on)}, {instruction}",
                file=self.build_maneuver_hand_file(
                    sides, self.engine.maneuver_tiers(game, match),
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


    def maneuver_winner_text(
        self,
        match: MatchState,
        reveal: str,
        outcome: str,
        winner_name: str,
        offense_name: str,
        defense_name: str,
    ) -> str:
        """
        How a maneuver settled on the cards reads. Two wordings: an
        ordinary decisive win, and a tie one injured participant loses
        outright.
        """
        if outcome != "tie":
            # Headed the same way a won skill test is (see
            # SkillTestView.roll), so the two ways a maneuver can be
            # won read alike. Whoever resolves the effect isn't named
            # here: an effect with a choice in it prompts them by name
            # itself, and one without needs nobody to do anything.
            return f"{reveal}\n\n## **{winner_name}** wins!"

        # A tie with exactly one injured participant: they lose it
        # outright. Nothing is rolled, so neither side pays the token a
        # skill test would have cost them.
        injured_player = self.engine.get_player_definition(
            match.challenger_id
            if match.challenger_id in match.injured
            else match.active_player_id
        )
        return (
            f"{reveal}\n\n"
            f"**{offense_name}** ties with **{defense_name}**, but "
            f"{self.player_label(match, injured_player)}"
            " is **injured** "
            f"{get_injured_emoji(self.condition_emojis)} and "
            "automatically loses the tie.\n\n"
            f"## **{winner_name}** wins!"
        )

    def skill_test_headline(
        self,
        match: MatchState,
        reveal: str,
        outcome: str,
        offense_name: str,
        defense_name: str,
    ) -> str:
        """
        Why a maneuver the cards did not settle is going to a skill
        test: the two ranked the same, or the one that would have won
        is owed to an injured player.
        """
        if outcome == "tie":
            # An ordinary tie -- both or neither participant is injured.
            return (
                f"{reveal}\n\n"
                f"**{offense_name}** ties with **{defense_name}** — skill "
                "test!\n\n"
            )

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
        return (
            f"{reveal}\n\n"
            f"**{would_be_winner}** would win, but "
            f"{self.player_label(match, injured_player)} is "
            f"**injured** {get_injured_emoji(self.condition_emojis)} -- "
            "a skill test decides it instead!\n\n"
        )

    async def begin_maneuver_skill_test(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        headline: str,
    ) -> None:
        """
        Charge both participants their token, post what is at stake,
        and put the roll behind a button -- every roll is a coach's.
        """
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
    ) -> None:
        # Keys are what the match holds and what everything below
        # dispatches on; the names are only ever printed.
        offense_key = match.offense_maneuver
        defense_key = match.defense_maneuver
        offense_name = self.engine.maneuver_name(offense_key)
        defense_name = self.engine.maneuver_name(defense_key)
        offense_number = self.engine.possession_player_number(game, match)
        defense_number = self.engine.defending_player_number(game, match)
        offense_display = format_player_with_team(
            game, offense_number, self.team_emojis,
        )
        defense_display = format_player_with_team(
            game, defense_number, self.team_emojis,
        )

        if match.maneuver_uncontested:
            # Nothing to reveal against and nothing to rank: the
            # offense's pick is the winner, and its effect runs the
            # same pipeline a decisive win always does.
            await send_new_prompt(
                interaction,
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

        if winner_key is not None:
            await send_new_prompt(
                interaction,
                self.maneuver_winner_text(
                    match,
                    reveal,
                    outcome,
                    self.engine.maneuver_name(winner_key),
                    offense_name,
                    defense_name,
                )
            )
            await self.begin_effect_resolution(
                interaction, game, match, winner_key,
            )
            return

        await self.begin_maneuver_skill_test(
            interaction,
            game,
            match,
            self.skill_test_headline(
                match, reveal, outcome, offense_name, defense_name,
            ),
        )

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
        self.persist(game, match)

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
            prompt_message = await send_new_prompt(
                interaction,
                f"{mention}, "
                f"{self.player_label(match, player)} is "
                "exhausted and owes an injury test: a d12 that has to "
                f"beat their {tokens} exhaustion "
                f"{'token' if tokens == 1 else 'tokens'}.",
                view=InjuryTestView(self, game.game_id, player_id),
                allowed_mentions=discord.AllowedMentions(
                    users=True, roles=False, everyone=False,
                ),
            )
            game.turn_message_id = prompt_message.id
            self.persist(game, match)
            return

        resume = match.pending_injury_resume
        match.pending_injury_resume = None
        self.persist(game, match)

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
                self.persist(game, match)
            await self.continue_injury_tests(interaction, game, match)
            return

        # The script fixes injury checks to pass for the whole
        # tutorial -- see BLANKET_ROLLS. The check still runs and the
        # coach still watches it.
        scripted = self.tutorial_dice(game, "injury", 1)
        roll = scripted[0] if scripted else random.randint(1, 12)
        # Volatile fires on an injury check like any other d12 -- so a
        # backfire that drops the check below the token count injures
        # the Fire Demon who rolled it, which the living rules say
        # outright rather than leaving to be inferred.
        ignite = self.engine.ignite(game, player.player_id, roll)
        overdrive = match.overdrive_modifier(player.player_id)
        match.consume_overdrive()
        check = roll + ignite.modifier + overdrive
        current_tokens = match.exhaustion.get(player.player_id, 0)
        safe = check > current_tokens
        # The die image draws the natural face, so an ignite has to be
        # said in words or the number a coach reads and the verdict
        # they are given would not add up.
        modifiers = ", ".join(
            part for part in (
                ignite.detail,
                f"+{overdrive} Overdrive" if overdrive else "",
            ) if part
        )
        ignite_note = f" ({modifiers}, {check})" if modifiers else ""
        player_team = match.team_for_player(player.player_id)
        dice_file = discord.File(
            await asyncio.to_thread(
                render_injury_test_die,
                roll,
                TEAM_COLORS[player_team],
                team_display_name(player_team),
                player.name,
                safe,
                bool(overdrive),
            ),
            filename="injury_test_die.png",
        )

        if player.player_id in match.pending_injury_tests:
            match.pending_injury_tests.remove(player.player_id)

        # Both outcomes, not only the injury. What a coach wants from
        # this is the *rate* -- how often playing a card that ties
        # actually costs a player -- and a log holding only the
        # failures has no denominator. `mark_injured` deliberately
        # logs nothing for the same reason.
        match.record_event(
            EVENT_INJURY_TEST,
            side=match.side_for_player(player.player_id),
            player_id=player.player_id,
            roll=roll,
            tokens=current_tokens,
            injured=not safe,
        )

        if safe:
            self.persist(game, match)

            content = (
                f"{self.player_label(match, player)} is exhausted and rolls "
                f"an injury test: {roll}{ignite_note} beats their "
                f"{current_tokens} exhaustion tokens — safe."
            )
        else:
            match.mark_injured(player.player_id)
            self.persist(game, match)

            # What happened, and nothing about what it means from
            # here. The rest of the rule -- tokens removed, no longer
            # exhausted, no further tokens and no further checks -- was
            # recited on every injury in the game, and the board says
            # all of it a moment later: the tokens come off the card
            # and the badge goes on.
            content = (
                f"{self.player_label(match, player)} is exhausted and rolls "
                f"an injury test: {roll}{ignite_note} does not beat their "
                f"{current_tokens} exhaustion tokens — injury! They are "
                f"**injured** {get_injured_emoji(self.condition_emojis)}."
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
        # The second die between the check and its verdict. It matters
        # more here than anywhere: a backfire is the one thing in the
        # game that injures the player who rolled well.
        await self.post_volatile_ignition(
            interaction, match, (player.player_id, ignite),
        )
        await send_new_prompt(interaction, content)
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
        # is set, and a beaten Skilled Pass's Low Pass belongs to the
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
        if winner_key in ("low_pass", "skilled_pass"):
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
            # A Dribble Burst asks a distance of everybody, not only a
            # Playmaker -- unless the handler is already on the last
            # space of the field, which is the one position with
            # nothing to ask and so the one that restores straight to
            # the speed choice.
            if winner_key == "dribble_burst" and (
                self.engine.dribble_burst_distances(match)
            ):
                return DribbleBurstChoiceView(self, game_id)
            return SpeedDeltaChoiceView(
                self, game_id, match.active_player_id, "offense",
            )
        if winner_key in ("steal", "intercept"):
            return SpeedDeltaChoiceView(
                self, game_id, match.challenger_id, "defense",
            )
        return None

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

        if match.pending_mind_pull:
            # Ahead of the injury tests and of everything a maneuver
            # leaves set, for a stronger version of their reason: a
            # pull interrupts an arrival that has *not happened yet*,
            # so the maneuver's own state is still exactly as it was
            # and every branch below would resolve the arrival this is
            # holding back. It is also the one interrupt that can
            # change who has the ball, so answering it first is what
            # keeps the rest of the chain reading a settled position.
            player = self.engine.get_player_definition(
                match.pending_mind_pull[0],
            )
            return (
                MindPullView(self, game_id, player.player_id),
                f"{self.player_label(match, player)} can still reach "
                "for the ball:",
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
                f"{self.player_label(match, player)} still "
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

        if match.pending_time_out:
            # A time out resets the turn before either window opens,
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
                    "Coaching Choice, on the time out:",
                )
            return (
                PlayerActionView(self, game_id),
                "Settle the time out:",
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
            step = self.engine.next_run_back_step(
                self.games[game_id], match,
            )
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
            # Named off the position like every other message on this
            # path: only a ball lying where nobody stands is loose, and
            # a resume that calls a contest -- or a High Pass -- a
            # loose ball misreads it in front of the coach about to
            # act on it. See contest_noun.
            noun = contest_noun(match)
            if (
                match.loose_ball_offense_player is not None
                and match.loose_ball_defense_player is not None
            ):
                return (
                    LooseBallSkillTestView(self, game_id),
                    f"Either player can roll for the {noun}:",
                )
            return (
                self.build_loose_ball_view(game_id, match)
                or PlayerActionView(self, game_id),
                f"Choose who goes after the {noun}:",
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
        step = self.engine.next_run_back_step(self.games[game_id], match)
        if step is None:
            return None
        _, candidates = step
        if len(candidates) == 1:
            return RunBackChoiceView(self, game_id, candidates[0])
        return RunBackPlayerChoiceView(self, game_id, candidates)

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
        # An advanced effect follows the cards, so a winner that only
        # won on the dice runs its counterpart's effect and the loser
        # pays nothing -- see `RulesEngine.advanced_cost_applies`.
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

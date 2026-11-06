"""
The TNP cog's own machinery: its games, engine, service and locks, the
tokens rendered at its door, and the startup sweep that re-arms the
persistent views (docs/design/tnp.md, "The lobby, the channel and the
table"). Copied from `cogs/codex/core.py`'s shape, cut to what step 5
needs.

**An exception here stays here** (decision 2): `cog_load` reads the data
and the games file and re-arms each game's views, logging and going on
wherever one fails, so nothing in it can stop fool-bot loading D12 Ball.
Nothing here decides a rule.
"""

from __future__ import annotations

import logging
from typing import Optional

from cogs.d12ball_boards import BoardRefresher
from cogs.tnp_helpers import TnpTokens
from cogs.tnp_views import LobbyView, RematchView, TableView
from gamelocks import GameLocks
from gamesaves.tnp.service import Batching, GameService
from gamesaves.tnp.storage import load_games
from tnp.catalog import Catalog, CatalogError, load
from tnp.components import MatchState
from tnp.engine import RulesEngine
from tnp.flow.result import FollowOnStep
from tnp.game import GameStatus, TnpGame

LOGGER = logging.getLogger(__name__)

#: Where a run stops for a picture (`Batching.stop_after`): after each
#: March attack, so each attack spot's lines are posted with the map as
#: that spot left it (docs/design/tnp.md, "The turn on Discord"), and
#: after each battle round's end, so a round is its own record with the
#: battle as the round left it ("Battles on Discord").
STOPS = frozenset({FollowOnStep.MARCH, FollowOnStep.END_ROUND})

#: The steps whose lines are their own group (`Batching.own_message`):
#: a battle's outcome put on the map, which closes the battle's last
#: round rather than leading into the next attack.
OWN_MESSAGE = frozenset({FollowOnStep.SETTLE_BATTLE})


class CoreMixin:
    def setup_state(self) -> None:
        """What `__init__` sets up: nothing read yet. `cog_load` reads."""
        #: None until `cog_load` reads the data, and after it if the
        #: data could not be read.
        self.catalog: Optional[Catalog] = None
        self.engine: Optional[RulesEngine] = None
        self.games: dict[str, TnpGame] = {}
        self.tokens = TnpTokens(None)
        # The table's write gate (docs/design/rate-limits.md), shared
        # with D12 Ball and Codex: the table message, its view and its
        # text. No full-image link -- the map opens by a click on it, and
        # a link is a second request after every upload.
        self.boards = BoardRefresher(
            self,
            keep_view=lambda game: self.table_view(game),
            links=lambda game: False,
            message_of=lambda game: game.table_message_id,
            text_for=self.table_text_or_none,
            label="TNP",
        )

    async def cog_unload(self) -> None:
        """A trailing table write still waiting holds this cog's games:
        dropped, as D12 Ball's and Codex's are."""
        self.boards.shutdown()

    async def cog_load(self) -> None:
        try:
            self.catalog = load()
        except (CatalogError, OSError) as error:
            # ERROR: somebody has to put the data back. Never raised,
            # so fool-bot's other cogs load regardless.
            LOGGER.error("TNP's data did not load; /tnp answers that it is unavailable: %s", error)
            self.catalog = None
        except Exception:
            LOGGER.exception("TNP's data did not load; /tnp answers that it is unavailable.")
            self.catalog = None
        self.tokens = TnpTokens(self.catalog)
        self.engine = RulesEngine(self.catalog) if self.catalog is not None else None
        try:
            # `load_games` logs and skips a game it cannot read, and
            # never raises; the guard is for what nobody foresaw.
            self.games = load_games()
        except Exception:
            LOGGER.exception("The TNP games file could not be read; TNP starts with no games.")
            self.games = {}
        self.restore_saved_views()

    # -- The service --------------------------------------------------------

    @property
    def locks(self) -> GameLocks:
        """One lock per game, held around a click's whole answer."""
        locks = self.__dict__.get("_locks")
        if locks is None:
            locks = GameLocks()
            self.__dict__["_locks"] = locks
        return locks

    @property
    def service(self) -> Optional[GameService]:
        """**The one door for a change to a game**, over this cog's engine
        and games, rebuilt if either is replaced; `None` while the data
        has not loaded."""
        if self.engine is None:
            return None
        service = self.__dict__.get("_service")
        if service is None or service.engine is not self.engine or service.games is not self.games:
            service = GameService(
                self.engine, self.games,
                Batching(stop_after=STOPS, own_message=OWN_MESSAGE, picture=self.position_picture),
            )
            self.__dict__["_service"] = service
        return service

    def render_text(self, text: str, game: Optional[TnpGame] = None) -> str:
        """The model's tokens as words, once, at the door."""
        return self.tokens.render(text, game)

    def game_for_channel(self, channel_id: Optional[int]) -> Optional[TnpGame]:
        """The TNP game open in a channel -- a lobby or a game being
        played -- or `None`. A channel holds one game at a time."""
        for game in self.games.values():
            if game.channel_id == channel_id and game.status in (GameStatus.LOBBY, GameStatus.PLAYING):
                return game
        return None

    # -- Startup ---------------------------------------------------------

    def restore_saved_views(self) -> None:
        """
        Re-arm every persistent view: each open lobby's `LobbyView` and
        each playing game's `TableView`. **A game that cannot be read is
        logged and skipped**, and the others are re-armed: one bad save
        stops nothing else (decision 2). A playing game with no table
        message is logged at ERROR: somebody has to run `/tnp resume`.
        """
        for game in list(self.games.values()):
            try:
                self.restore_game(game)
            except Exception:
                LOGGER.exception("TNP game %s could not be re-armed; it is skipped.", game.game_id)

    def restore_game(self, game: TnpGame) -> None:
        if game.status is GameStatus.LOBBY:
            if game.message_id is not None:
                self.bot.add_view(LobbyView(self, game.game_id), message_id=game.message_id)
            return
        if game.status is GameStatus.FINISHED:
            # **Rematch** on its table, until a rematch is opened from it.
            if game.table_message_id is not None and game.rematch_game_id is None:
                self.bot.add_view(RematchView(self, game.game_id), message_id=game.table_message_id)
            return
        if game.status is not GameStatus.PLAYING:
            return
        if game.match_state is None:
            LOGGER.error("TNP game %s (#%s) is being played and holds no match; it is skipped.",
                         game.game_id, game.game_number)
            return
        # The match is read once here, so a save that no longer loads is
        # logged as the game's, not found by the first click on it.
        MatchState.from_dict(game.match_state)
        if game.table_message_id is None:
            LOGGER.error(
                "TNP game %s (#%s) is being played and has no table message to re-arm; "
                "it needs /tnp resume.", game.game_id, game.game_number,
            )
            return
        self.bot.add_view(TableView(self, game.game_id), message_id=game.table_message_id)
        self.restore_battle_view(game)

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

from cogs.tnp_helpers import TnpTokens
from cogs.tnp_views import LobbyView, TableView
from gamelocks import GameLocks
from gamesaves.tnp.service import Batching, GameService
from gamesaves.tnp.storage import load_games
from tnp.catalog import Catalog, CatalogError, load
from tnp.components import MatchState
from tnp.engine import RulesEngine
from tnp.game import GameStatus, TnpGame

LOGGER = logging.getLogger(__name__)

class CoreMixin:
    def setup_state(self) -> None:
        """What `__init__` sets up: nothing read yet. `cog_load` reads."""
        #: None until `cog_load` reads the data, and after it if the
        #: data could not be read.
        self.catalog: Optional[Catalog] = None
        self.engine: Optional[RulesEngine] = None
        self.games: dict[str, TnpGame] = {}
        self.tokens = TnpTokens(None)

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
            service = GameService(self.engine, self.games, Batching())
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

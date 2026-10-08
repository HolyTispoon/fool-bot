"""
Discord faked for the Codex cog's turn tests (docs/codex-bot.md, step 4):
a server, a lobby channel and a game channel whose every request is
logged by route, and interactions whose responses are logged the same
way -- so a test can count what one click spends from **the channel's
bucket** (a send, an edit, a pin, an unpin, a delete) against what goes
through **the interaction's own webhook** (a response, a follow-up),
which spends nothing from it (docs/design/rate-limits.md).

`Table.started()` reaches the opening position through the real lobby;
`Table.panel()` opens the active player's panel from **My hand**; and
`press` / `choose` click a panel's button or menu by its label, the
way a person does, reading the view the last response put up.

Named `codex_<thing>` because `tests/` is flat and its helpers are
imported by bare name.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from contextlib import ExitStack
from types import SimpleNamespace
from typing import Optional
from unittest import mock

import discord

from codex.engine import RulesEngine
from cogs import d12ball_boards
from cogs.codex import Codex
from cogs.codex import core as codex_core
from cogs.codex_views import LobbyView, TurnMessageView
from save_patches import suppressed_cog_saves

GUILD, LOBBY_CHANNEL, GAME_CHANNEL = 1, 10, 20
LOBBY_MESSAGE = 100


def user(user_id: int, name: str, helper: bool = False):
    member = mock.MagicMock(spec=discord.Member)
    member.id, member.display_name = user_id, name
    member.guild_permissions = SimpleNamespace(manage_channels=helper)
    return member


class FakePartial:
    """A message by id, as `get_partial_message` hands one back."""

    def __init__(self, channel: "FakeChannel", message_id: int) -> None:
        self.channel = channel
        self.id = message_id

    async def edit(self, **kwargs):
        self.channel.log("edit", self.id, kwargs)
        if "content" in kwargs:
            self.channel.texts[self.id] = kwargs["content"]
        if "view" in kwargs:
            self.channel.views[self.id] = kwargs["view"]
        # No attachments, so the gate owes no full-image link and every
        # request counted here is the board's own.
        return SimpleNamespace(id=self.id, attachments=[])

    async def pin(self, **kwargs):
        self.channel.log("pin", self.id, kwargs)
        self.channel.pinned.add(self.id)

    async def unpin(self, **kwargs):
        self.channel.log("unpin", self.id, kwargs)
        self.channel.pinned.discard(self.id)

    async def delete(self, **kwargs):
        self.channel.log("delete", self.id, kwargs)
        self.channel.deleted.add(self.id)


class FakeChannel:
    """A channel whose every request is one row of `requests`."""

    def __init__(self, channel_id: int) -> None:
        self.id = channel_id
        self.mention = f"<#{channel_id}>"
        self.requests: list[tuple[str, int, dict]] = []
        self.texts: dict[int, Optional[str]] = {}
        self.views: dict[int, object] = {}
        self.pinned: set[int] = set()
        self.deleted: set[int] = set()
        self.ids = itertools.count(1000)

    async def edit(self, **kwargs):
        """The channel itself renamed and locked at Start
        (`lock_game_channel`): a request of the channel's own."""
        self.log("channel.edit", self.id, kwargs)

    def log(self, kind: str, message_id: int, kwargs: dict) -> None:
        self.requests.append((kind, message_id, kwargs))

    async def send(self, content=None, **kwargs):
        message_id = next(self.ids)
        self.log("send", message_id, {"content": content, **kwargs})
        self.texts[message_id] = content
        self.views[message_id] = kwargs.get("view")
        return FakeMessage(self, message_id)

    def get_partial_message(self, message_id: int) -> FakePartial:
        return FakePartial(self, message_id)

    def since(self, mark: int) -> list[tuple[str, int, dict]]:
        return self.requests[mark:]

    def public_texts(self) -> list[str]:
        """Every text the channel was sent or edited to, in order."""
        return [
            kwargs["content"] for kind, _, kwargs in self.requests
            if kind in ("send", "edit") and kwargs.get("content")
        ]


class FakeMessage(FakePartial):
    async def pin(self, **kwargs):
        await FakePartial.pin(self, **kwargs)


class FakeResponse:
    def __init__(self, log: list) -> None:
        self._log = log
        self.done = False

    def is_done(self) -> bool:
        return self.done

    async def send_message(self, *args, **kwargs):
        self.done = True
        self._log.append(("response.send", args, kwargs))

    async def edit_message(self, **kwargs):
        self.done = True
        self._log.append(("response.edit", (), kwargs))

    async def defer(self, **kwargs):
        self.done = True
        self._log.append(("response.defer", (), kwargs))


class FakeFollowup:
    def __init__(self, log: list) -> None:
        self._log = log

    async def send(self, *args, **kwargs):
        self._log.append(("followup.send", args, kwargs))


class FakeInteraction:
    """One click or command, its answers logged in `answers`."""

    def __init__(self, who, channel, guild=None) -> None:
        self.user = who
        self.channel = channel
        self.channel_id = channel.id
        self.guild = guild
        self.extras: dict = {}
        #: What Discord sends with a component click; `choose` fills in
        #: a menu's values here, as Discord does.
        self.data: dict = {}
        self.message = SimpleNamespace(id=0)
        self.answers: list = []
        self.response = FakeResponse(self.answers)
        self.followup = FakeFollowup(self.answers)

    async def original_response(self):
        return SimpleNamespace(id=LOBBY_MESSAGE)

    def last(self, kind: Optional[str] = None):
        """The last answer, or the last of `kind` -- `(kind, args, kwargs)`."""
        for answer in reversed(self.answers):
            if kind is None or answer[0] == kind:
                return answer
        raise AssertionError(f"no {kind or 'answer'} among {[a[0] for a in self.answers]}")

    def view(self):
        """The view the last response or follow-up put up."""
        for _, _, kwargs in reversed(self.answers):
            if kwargs.get("view") is not None:
                return kwargs["view"]
        return None

    def text(self) -> str:
        _, args, kwargs = self.last()
        return kwargs.get("content") or (args[0] if args else "") or ""


def find_button(view, label: str) -> discord.ui.Button:
    for item in view.children:
        if isinstance(item, discord.ui.Button) and (item.label or "").startswith(label):
            return item
    raise AssertionError(f"no button {label!r} among {[getattr(i, 'label', None) for i in view.children]}")


def find_select(view, placeholder: str) -> discord.ui.Select:
    for item in view.children:
        if isinstance(item, discord.ui.Select) and (item.placeholder or "").startswith(placeholder):
            return item
    raise AssertionError(
        f"no menu {placeholder!r} among {[getattr(i, 'placeholder', None) for i in view.children]}"
    )


class Table:
    """
    The fakes one test plays through. Saves are suppressed and the
    gate's interval is zero for the table's life (`ExitStack`), so every
    write the gate is asked for lands at once and can be counted --
    the interval decides *when*, never *how many*.
    """

    def __init__(self, seed: int = 7) -> None:
        self.stack = ExitStack()
        self.stack.enter_context(suppressed_cog_saves())
        self.stack.enter_context(mock.patch.object(d12ball_boards, "BOARD_REFRESH_INTERVAL", 0))
        self.bot = mock.MagicMock()
        self.lobby_channel = FakeChannel(LOBBY_CHANNEL)
        self.game_channel = FakeChannel(GAME_CHANNEL)
        self.game_channel.guild = None  # set below, once the guild is
        channels = {LOBBY_CHANNEL: self.lobby_channel, GAME_CHANNEL: self.game_channel}
        self.bot.get_channel.side_effect = channels.get
        self.guild = mock.MagicMock(id=GUILD)
        self.guild.categories = []
        self.guild.create_category = mock.AsyncMock(return_value=mock.MagicMock())
        self.guild.create_text_channel = mock.AsyncMock(return_value=self.game_channel)
        self.game_channel.guild = self.guild
        self.basher, self.fencer = user(101, "basher"), user(202, "fencer")
        self.said: list[str] = []
        self.build({}, seed)

    def build(self, games: dict, seed: int = 7) -> None:
        with mock.patch.object(codex_core, "load_games", return_value=games):
            self.cog = Codex(self.bot)
        self.cog.engine = RulesEngine(seed=seed)
        self.cog.tokens.refresh = mock.AsyncMock()
        self.cog.render_match_png = self.board_png
        self.cog.service.listeners.append(lambda game, result: self.said.extend(result.lines))

    def restart(self) -> None:
        """A bot restart: a new cog over the records as saved, with
        nothing in memory -- no panel, no turn's lines."""
        from codex.game import CodexGame

        self.cog.boards.shutdown()
        saved = {
            game_id: CodexGame.from_dict(json.loads(json.dumps(game.to_dict())))
            for game_id, game in self.cog.games.items()
        }
        self.build(saved)
        self.game = self.cog.games[self.game.game_id]

    def close(self) -> None:
        self.stack.close()

    async def board_png(self, game, match=None) -> bytes:
        """
        A stand-in for the board's PNG that changes exactly when what the
        board draws does -- the position and the layout -- so the gate's
        skip of an unchanged board counts as it would, without drawing
        two megabytes a click. The board itself is `test_codex_render`'s
        and the sample script's to look at.
        """
        if match is None:
            match = self.cog.service.load(game)
        position = json.dumps([match.to_dict(), game.board_layout], sort_keys=True, default=str)
        return hashlib.sha256(position.encode()).digest()

    def interaction(self, who, channel=None) -> FakeInteraction:
        return FakeInteraction(who, channel or self.game_channel, self.guild)

    async def started(self):
        """The real lobby -- opened in the game's own channel -- two seats,
        Start: the opening position."""
        call = self.interaction(self.basher, self.lobby_channel)
        await self.cog.lobby.callback(self.cog, call)
        (game,) = self.cog.games.values()
        lobby = LobbyView(self.cog, game.game_id)
        for who, action in ((self.basher, "bashing"), (self.fencer, "finesse"), (self.fencer, "start")):
            click = self.interaction(who)
            await next(item for item in lobby.children if f":{action}:" in item.custom_id).callback(click)
        self.game = game
        return game

    @property
    def match(self):
        return self.cog.service.load(self.game)

    def seated(self, seat: int):
        return self.basher if seat == 1 else self.fencer

    @property
    def active(self):
        return self.seated(self.match.active)

    @property
    def waiting(self):
        return self.seated(2 if self.match.active == 1 else 1)

    async def turn_button(self, action: str, who) -> FakeInteraction:
        """A button on the current turn message: hand, tech, codex, swap."""
        view = TurnMessageView(self.cog, self.game.game_id)
        call = self.interaction(who)
        await next(item for item in view.children if f":{action}:" in item.custom_id).callback(call)
        return call

    async def panel(self, who=None) -> tuple[FakeInteraction, object]:
        call = await self.turn_button("hand", who or self.active)
        return call, call.view()

    async def press(self, view, label: str, who=None) -> FakeInteraction:
        button = find_button(view, label)
        call = self.interaction(who or self.seated(view.seat))
        call.data = {"custom_id": button.custom_id, "component_type": 2}
        await view._scheduled_task(button, call)
        return call

    async def choose(self, view, placeholder: str, *values: str, who=None) -> FakeInteraction:
        select = find_select(view, placeholder)
        call = self.interaction(who or self.seated(view.seat))
        call.data = {"custom_id": select.custom_id, "component_type": 3, "values": list(values)}
        await view._scheduled_task(select, call)
        return call

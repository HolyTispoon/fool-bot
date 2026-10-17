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

import asyncio
import hashlib
import itertools
import json
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional
from unittest import mock

import discord

from codex.cards import catalog
from codex.engine import RulesEngine
from cogs import d12ball_boards
from cogs.codex import Codex
from cogs.codex import core as codex_core
from cogs.codex_views import LobbyView, TurnMessageView
from cogs.codex_views import base as codex_views_base
from save_patches import suppressed_cog_saves

GUILD, LOBBY_CHANNEL, GAME_CHANNEL = 1, 10, 20
LOBBY_MESSAGE = 100
#: The Codex bot's own user, the author of everything a channel is sent.
BOT_USER = 9


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
        self.channel.pin_order = [one for one in self.channel.pin_order if one != self.id] + [self.id]

    async def unpin(self, **kwargs):
        self.channel.log("unpin", self.id, kwargs)
        self.channel.pinned.discard(self.id)

    async def delete(self, **kwargs):
        self.channel.log("delete", self.id, kwargs)
        self.channel.deleted.add(self.id)
        # A deleted message's pin goes with it.
        self.channel.pinned.discard(self.id)


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
        #: The pinned messages' ids, oldest pin first.
        self.pin_order: list[int] = []
        #: Pinned messages of somebody else's, as `pins` hands them back.
        self.foreign_pins: list[SimpleNamespace] = []
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

    def pinned_message(self, message_id: int, pinned_at: datetime) -> SimpleNamespace:
        """A pinned message as `pins` hands it back: its text and the
        files its last send or edit carried, by the bot."""
        files = []
        for kind, one, kwargs in self.requests:
            if one != message_id:
                continue
            if kind == "send" and kwargs.get("file") is not None:
                files = [kwargs["file"]]
            elif kind == "edit" and kwargs.get("attachments"):
                files = list(kwargs["attachments"])
        return SimpleNamespace(
            id=message_id, author=SimpleNamespace(id=BOT_USER), content=self.texts.get(message_id),
            pinned_at=pinned_at, attachments=[fake_attachment(one) for one in files],
        )

    def pins(self, *, limit: int = 50, before: Optional[datetime] = None):
        """The pins newest first, one request a call; a call spends
        nothing from the messages' edit bucket."""
        self.log("pins", self.id, {"limit": limit, "before": before})
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        pinned = [self.pinned_message(message_id, start + timedelta(minutes=index))
                  for index, message_id in enumerate(self.pin_order) if message_id in self.pinned]
        pinned = sorted([*pinned, *self.foreign_pins], key=lambda one: one.pinned_at, reverse=True)
        if before is not None:
            pinned = [one for one in pinned if one.pinned_at < before]

        async def listed():
            for one in pinned[:limit]:
                yield one

        return listed()

    def since(self, mark: int) -> list[tuple[str, int, dict]]:
        return self.requests[mark:]

    def public_texts(self) -> list[str]:
        """Every text the channel was sent or edited to, in order."""
        return [
            kwargs["content"] for kind, _, kwargs in self.requests
            if kind in ("send", "edit") and kwargs.get("content")
        ]


def fake_attachment(file: discord.File) -> SimpleNamespace:
    """An uploaded file as a message's attachment, its bytes downloaded
    by `read`."""
    body = file.fp.getvalue()

    async def read():
        return body

    return SimpleNamespace(filename=file.filename, body=body, read=read)


class FakeMessage(FakePartial):
    #: Nothing uploaded, so the gate owes no full-image link for a post.
    attachments: list = []

    async def pin(self, **kwargs):
        await FakePartial.pin(self, **kwargs)


#: The ids of the messages a click's webhook makes -- its response, its
#: follow-ups -- apart from the channel's.
WEBHOOK_MESSAGE_IDS = itertools.count(5000)


def webhook_message(message_id: int, ephemeral: bool, fields: dict,
                    content: str = "") -> SimpleNamespace:
    """
    A message as a response, an edit or a follow-up hands it back: its
    id, whether it is ephemeral -- which is what puts a new picture's
    redraw in motion (`cogs.codex_views.base.redraw_pictures`) -- the
    words the write gave it, or `content` where it gave none, and the
    pictures.
    """
    if "attachments" in fields:
        shown = list(fields["attachments"])
    else:
        shown = list(fields.get("files") or ([fields["file"]] if fields.get("file") else []))
    return SimpleNamespace(
        id=message_id,
        flags=SimpleNamespace(ephemeral=ephemeral),
        content=fields.get("content") or content or "",
        attachments=[SimpleNamespace(filename=item.filename) if isinstance(item, discord.File) else item
                     for item in shown],
    )


def clicked_message(message_id: int = 0, ephemeral: bool = False, attachments=()) -> SimpleNamespace:
    """The message a click is on, as Discord sends it with the click."""
    return SimpleNamespace(id=message_id, flags=SimpleNamespace(ephemeral=ephemeral),
                           attachments=list(attachments))


class FakeResponse:
    def __init__(self, owner: "FakeInteraction") -> None:
        self._owner = owner
        self._log = owner.answers
        self.done = False

    def is_done(self) -> bool:
        return self.done

    async def send_message(self, *args, **kwargs):
        self.done = True
        self._log.append(("response.send", args, kwargs))
        message = webhook_message(next(WEBHOOK_MESSAGE_IDS), kwargs.get("ephemeral") is True, kwargs,
                                  args[0] if args and args[0] else "")
        return self._owner.wrote(message)

    async def edit_message(self, **kwargs):
        self.done = True
        self._log.append(("response.edit", (), kwargs))
        clicked = self._owner.message
        return self._owner.wrote(webhook_message(clicked.id, clicked.flags.ephemeral, kwargs,
                                                 getattr(clicked, "content", "")))

    async def defer(self, **kwargs):
        self.done = True
        self._log.append(("response.defer", (), kwargs))
        self._owner.original = self._owner.message


class FakeFollowup:
    def __init__(self, owner: "FakeInteraction") -> None:
        self._owner = owner
        self._log = owner.answers

    async def send(self, *args, **kwargs):
        self._log.append(("followup.send", args, kwargs))
        message = webhook_message(next(WEBHOOK_MESSAGE_IDS), kwargs.get("ephemeral") is True, kwargs,
                                  args[0] if args and args[0] else "")
        self._owner.messages[len(self._log) - 1] = message
        return message

    async def edit_message(self, message_id, **kwargs):
        """A follow-up edited -- a new picture's redraw."""
        self._owner.log_write(("followup.edit", (message_id,), kwargs))


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
        #: The message clicked, carrying what it was put up with --
        #: `Table` fills in the id, the attachments and whether it is
        #: ephemeral, for the message a view sits on.
        self.message = clicked_message()
        self.answers: list = []
        #: The edits a new picture's redraw made after the click.
        self.redraws: list = []
        #: The message each answer wrote, by its place in `answers`.
        self.messages: dict[int, SimpleNamespace] = {}
        #: The click's original message: the one its response sent, or
        #: the message clicked, edited or deferred.
        self.original: Optional[SimpleNamespace] = None
        self.response = FakeResponse(self)
        self.followup = FakeFollowup(self)

    def log_write(self, answer: tuple) -> None:
        """An edit through the click's webhook: one of its answers, or,
        made by a new picture's redraw (`cogs.codex_views.base._redraw`),
        one of `redraws` -- a request the click spends all the same, kept
        apart so what it answered reads as it did."""
        if asyncio.current_task() in codex_views_base._PENDING.values():
            self.redraws.append(answer)
        else:
            self.answers.append(answer)

    def wrote(self, message: SimpleNamespace) -> SimpleNamespace:
        """A response's message: the click's original from now on, and
        handed back as discord.py does, on the callback's `resource`."""
        self.original = message
        self.messages[len(self.answers) - 1] = message
        return SimpleNamespace(resource=message)

    async def original_response(self):
        return SimpleNamespace(id=LOBBY_MESSAGE)

    async def edit_original_response(self, **kwargs):
        """The message clicked edited on a click answered already --
        deferred while its game was busy -- or the click's own message
        drawn again, through the click's webhook."""
        self.log_write(("original.edit", (), kwargs))
        base = self.original or self.message
        message = webhook_message(base.id, base.flags.ephemeral, kwargs, getattr(base, "content", ""))
        self.messages[len(self.answers) - 1] = message
        return message

    async def delete_original_response(self):
        """The message clicked deleted -- a panel replaced by the one
        sent under the turn message -- through the click's webhook."""
        self.answers.append(("original.delete", (), {}))

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
        """The text of the last message the click put up -- its answer,
        an edit or a follow-up; a defer or a deletion carries none."""
        for kind, args, kwargs in reversed(self.answers):
            if kind not in ("response.defer", "original.delete"):
                return kwargs.get("content") or (args[0] if args else "") or ""
        return ""


def labels(view) -> list[str]:
    """A view's buttons by label, in order."""
    return [item.label for item in view.children if isinstance(item, discord.ui.Button)]


async def end_main_and_lock(table, who) -> None:
    """`who`'s acting seat ends its main phase and locks no patrollers,
    from **My hand**: a free-for-all's turn, or one teammate's half of a
    dragon's."""
    call = await table.turn_button("hand", who)
    view = (await table.press(call.view(), "End main phase", who=who)).view()
    await table.press(view, "Lock patrol", who=who)


def find_button(view, which) -> discord.ui.Button:
    """A button by the start of its label, or -- a tuple -- by the choice
    it answers with (`PanelButton.choice`): `("play", slug)`,
    `("build", building)`, `("repair",)`, `("attack", ref)`, `("ability", effect,
    source)`, `("summon", hero)`, `("level", hero)`, `("hire", slug)`, `("defend", ref)`,
    `("target", key)`, `("detect", ref)`, `("obliterate", ref)`,
    `("sparkshot", ref)`, `("overpower", ref)`."""
    for item in view.children:
        if not isinstance(item, discord.ui.Button):
            continue
        if isinstance(which, tuple):
            if getattr(item, "choice", None) == which:
                return item
        elif (item.label or "").startswith(which):
            return item
    raise AssertionError(
        f"no button {which!r} among "
        f"{[getattr(i, 'choice', None) or getattr(i, 'label', None) for i in view.children]}"
    )


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
        # A new picture's redraw at once, awaited by every click below,
        # so a click's answers count it.
        self.stack.enter_context(mock.patch.object(codex_views_base, "PICTURE_REDRAW_DELAY", 0))
        self.bot = mock.MagicMock()
        self.bot.user.id = BOT_USER
        self.bot.wait_until_ready = mock.AsyncMock()
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
        #: The seats' people: a free-for-all's third and later seats are
        #: `players[3]`..., added by `started_free_for_all`.
        self.players = {1: self.basher, 2: self.fencer}
        #: What the message each view sits on carries, as Discord hands
        #: it back on a click: an uploaded file as an attachment by its
        #: name, a kept one as it was.
        self.carried: dict = {}
        #: The message each view sits on: its id, and whether it is
        #: ephemeral.
        self.sits_on: dict = {}
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

    async def started(self, teams=(("bashing",), ("finesse",))):
        """The real lobby -- opened in the game's own channel -- two seats,
        Start: the opening position. `teams` are the two seats' heroes, as
        specs; three each plays the standard game the lobby opens on, a
        colour's deck button or **Mixed colors** (`pick_team`) -- the
        first hero's colour the deck -- and one the basic game, chosen
        with the lobby's **Basic game** first."""
        call = self.interaction(self.basher, self.lobby_channel)
        await self.cog.lobby.callback(self.cog, call)
        (game,) = self.cog.games.values()
        lobby = LobbyView(self.cog, game.game_id)
        if len(teams[0]) == 1:
            await self.choose_mode(game, "basic")
            lobby = LobbyView(self.cog, game.game_id)
        pick = self.pick_team if len(teams[0]) == 3 else self.pick_heroes
        await pick(lobby, self.basher, *teams[0])
        await pick(lobby, self.fencer, *teams[1])
        click = self.interaction(self.fencer)
        await next(item for item in lobby.children if ":start:" in item.custom_id).callback(click)
        self.game = game
        return game

    async def started_free_for_all(self, specs=("bashing", "finesse", "anarchy"), *, mode_click=None):
        """The real lobby, **Free-for-all**, one person a seat -- `specs`
        their heroes, three to five -- and Start: the opening position."""
        call = self.interaction(self.basher, self.lobby_channel)
        await self.cog.lobby.callback(self.cog, call)
        (game,) = self.cog.games.values()
        lobby = LobbyView(self.cog, game.game_id)
        await next(item for item in lobby.children
                   if ":variant_free_for_all:" in item.custom_id).callback(self.interaction(self.basher))
        await self.choose_mode(game, "basic")
        names = ("basher", "fencer", "dee", "eli", "fay")
        for seat, spec in enumerate(specs, start=1):
            who = self.players.setdefault(seat, user(100 * seat + seat, names[seat - 1]))
            await self.pick_heroes(LobbyView(self.cog, game.game_id), who, spec)
        click = self.interaction(self.fencer)
        await next(item for item in LobbyView(self.cog, game.game_id).children
                   if ":start:" in item.custom_id).callback(click)
        self.game = game
        return game

    async def choose_mode(self, game, mode: str) -> None:
        """The lobby's **Basic game** or **Standard game**, clicked while
        nobody sits."""
        lobby = LobbyView(self.cog, game.game_id)
        await next(item for item in lobby.children
                   if f":mode_{mode}:" in item.custom_id).callback(self.interaction(self.basher))

    async def started_dragon(self, specs=("bashing", "finesse", "anarchy", "feral"), *,
                             test_game: bool = False):
        """The real lobby, **Two-headed dragon**, one person a seat --
        seats 1 and 2 one team, 3 and 4 the other, `specs` their heroes --
        and Start: the opening position. `test_game` sits `basher` on all
        four, the lobby's per-seat menus picking each."""
        call = self.interaction(self.basher, self.lobby_channel)
        await self.cog.lobby.callback(self.cog, call, test_game=test_game)
        (game,) = self.cog.games.values()
        await self.choose_mode(game, "basic")
        lobby = LobbyView(self.cog, game.game_id)
        await next(item for item in lobby.children
                   if ":variant_two_headed_dragon:" in item.custom_id).callback(self.interaction(self.basher))
        names = ("basher", "fencer", "dee", "eli")
        for seat, spec in enumerate(specs, start=1):
            if test_game:
                self.players[seat] = self.basher
                await self.pick_heroes(LobbyView(self.cog, game.game_id), self.basher, spec,
                                       menu=f"heroes{seat}")
                continue
            who = self.players.setdefault(seat, user(100 * seat + seat, names[seat - 1]))
            await self.pick_heroes(LobbyView(self.cog, game.game_id), who, spec)
        if test_game:
            self.fencer = self.basher
        click = self.interaction(self.basher)
        await next(item for item in LobbyView(self.cog, game.game_id).children
                   if ":start:" in item.custom_id).callback(click)
        self.game = game
        return game

    async def pick_heroes(self, lobby, who, *specs: str, menu: str = "heroes") -> FakeInteraction:
        """The lobby's hero menu -- `menu` is "heroes1" or "heroes2" for a
        test game's two -- answered with `specs`, as Discord sends it."""
        select = next(item for item in lobby.children if f":{menu}:" in (item.custom_id or ""))
        call = self.interaction(who)
        call.data = {"custom_id": select.custom_id, "component_type": 3, "values": list(specs)}
        await lobby._scheduled_task(select, call)
        return call

    async def pick_team(self, lobby, who, *specs: str, seat: Optional[int] = None) -> FakeInteraction:
        """A standard game's team, as a player picks it: a colour's deck
        button where `specs` are its three heroes, otherwise **Mixed
        colors** and its two menus -- `specs[0]` first, the deck's.
        `seat` names a test game's side."""
        suffix = "" if seat is None else str(seat)
        color = catalog().color_deck_of(specs)
        call = self.interaction(who)
        if color is not None:
            button = next(item for item in lobby.children
                          if f":team{suffix}_{color}:" in (item.custom_id or ""))
            await button.callback(call)
            return call
        button = next(item for item in lobby.children
                      if f":mixed{suffix}:" in (item.custom_id or ""))
        await button.callback(call)
        picker = call.view()
        for select, values in ((picker.first_menu, [specs[0]]), (picker.others_menu, list(specs[1:]))):
            call = self.interaction(who)
            call.data = {"custom_id": select.custom_id, "component_type": 3, "values": values}
            await picker._scheduled_task(select, call)
        return call

    @property
    def match(self):
        return self.cog.service.load(self.game)

    def seated(self, seat: int):
        # The first two are the table's own attributes, which a test game
        # points at one person.
        return {1: self.basher, 2: self.fencer}.get(seat) or self.players[seat]

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
        await self.redrawn()
        self.remember(call)
        return call

    def message_of(self, view) -> SimpleNamespace:
        """The message `view` sits on, as a click on it carries it."""
        message_id, ephemeral = self.sits_on.get(view, (0, False))
        return clicked_message(message_id, ephemeral, self.carried.get(view, []))

    @staticmethod
    async def redrawn() -> None:
        """Every redraw a click put in motion, done: its edit is one of
        the click's answers."""
        while codex_views_base._PENDING:
            await asyncio.gather(*list(codex_views_base._PENDING.values()), return_exceptions=True)

    def remember(self, call: FakeInteraction) -> None:
        """What each view `call` put up sits beside: the files sent with
        it, the attachments an edit gave it, or -- an edit that named
        none -- what the message clicked already carried."""
        for index, (kind, _, kwargs) in enumerate(call.answers):
            view = kwargs.get("view")
            if view is None:
                continue
            written = call.messages.get(index) or call.message
            self.sits_on[view] = (written.id, written.flags.ephemeral)
            if "attachments" in kwargs:
                shown = kwargs["attachments"]
            elif "files" in kwargs or "file" in kwargs:
                shown = kwargs.get("files") or [kwargs["file"]]
            else:
                shown = call.message.attachments if kind in ("response.edit", "original.edit") else []
            self.carried[view] = [
                SimpleNamespace(filename=item.filename) if isinstance(item, discord.File) else item
                for item in shown
            ]

    async def panel(self, who=None) -> tuple[FakeInteraction, object]:
        call = await self.turn_button("hand", who or self.active)
        return call, call.view()

    async def press(self, view, which, who=None) -> FakeInteraction:
        """A button, by its label's start or by its choice (`find_button`)."""
        button = find_button(view, which)
        call = self.interaction(who or self.seated(view.seat))
        call.data = {"custom_id": button.custom_id, "component_type": 2}
        call.message = self.message_of(view)
        await view._scheduled_task(button, call)
        await self.redrawn()
        self.remember(call)
        return call

    async def press_while_busy(self, view, which, who=None) -> tuple[list[str], FakeInteraction]:
        """
        A button pressed while the click ahead of it still holds the
        game's lock -- putting its pictures up, as far as this click
        knows. What the click had answered by the time the lock came
        free, and the click.
        """
        button = find_button(view, which)
        call = self.interaction(who or self.seated(view.seat))
        call.data = {"custom_id": button.custom_id, "component_type": 2}
        call.message = self.message_of(view)
        async with self.cog.locks.hold(self.game.game_id):
            pressed = asyncio.create_task(view._scheduled_task(button, call))
            for _ in range(5):
                await asyncio.sleep(0)
            before = [answer[0] for answer in call.answers]
        await pressed
        await self.redrawn()
        self.remember(call)
        return before, call

    async def choose(self, view, placeholder: str, *values: str, who=None) -> FakeInteraction:
        select = find_select(view, placeholder)
        call = self.interaction(who or self.seated(view.seat))
        call.data = {"custom_id": select.custom_id, "component_type": 3, "values": list(values)}
        call.message = self.message_of(view)
        await view._scheduled_task(select, call)
        await self.redrawn()
        self.remember(call)
        return call

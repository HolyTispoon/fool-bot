"""
The write gate on a game's persistent board message.

Every 429 in two logged sessions of play was a `PATCH` on
`/channels/{id}/messages/{id}`, and `message_id` is not one of
Discord's major rate-limit parameters -- so every edit to every message
in a game's channel shares one bucket of roughly five requests in five
seconds. After the second round of those, the board message is the only
thing in this bot that edits through the channel at all, which makes
this module the whole of that bucket's spending.

What lives here is `BoardRefreshState` -- when a write landed, the pass
waiting to write again, the board already on the message, the link owed
for it, the lock over the message, the wants arriving mid-write, and the
refusals -- and the methods that read it. On the cog those were
seven parallel dicts keyed by game id, and the invariant that actually
had to hold was that all seven agreed about one game: expressed nowhere,
kept by hand at each of the eleven sites that wrote them. They were
touched by nothing but each other, which on a cog of two hundred-odd
methods made them read as ordinary surface.

`D12Ball.refresh_match_image` is the one forwarder left over it, the
way in for every call site that puts a board up. See "Discord's rate limits" in
docs/design/rate-limits.md for the measurements every decision here rests on.
"""

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

import aiohttp
import discord

from cogs.d12ball_helpers import (
    build_full_image_button,
    full_image_link_button,
)
from cogs.d12ball_views import HomeAwaySelectionView
from d12ball.game import D12BallGame

if TYPE_CHECKING:
    from cogs.d12ball import D12Ball


LOGGER = logging.getLogger(__name__)


# How long a game's board waits between writes.
#
# It must stay above Discord's own five-second window, or two refreshes
# fall inside one of them: at three seconds a turn spent exactly five
# requests and was still earning 429s, measured. Six leaves a turn at
# three requests over three passes -- the immediate board, the settling
# board, and the link the second of those owes. See "The board message
# is one bucket" in docs/design/rate-limits.md.
#
# Nothing spends two requests inside one of these windows any more,
# which is what the last batch of 429s turned out to be: see
# BoardRefresher.write.
#
# It is also how long the board goes without its full-image link, and
# since the link stopped riding along with the upload that killed it,
# up to two of these: a write strips the link in the edit it is already
# paying for, and a later pass with nothing new to draw puts one back.
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


@dataclass
class BoardRefreshState:
    """
    Everything one game's board message is carrying between writes.

    These were seven parallel dicts keyed by game id, and every one of
    the six methods below reached into several of them for the same
    game in the same breath -- so the invariant that actually had to
    hold was that all seven agreed about one game, expressed nowhere
    and enforced by hand at each site. Ten of the eleven places that
    wrote them wrote two or more.

    Each field is what its dict held for that game, with the dict's
    "missing" as the default -- `None` for the three that were read
    with `.get`, False for the membership set, 0 for the counter.
    """

    # When the last write to this board **landed**. Not when it was
    # sent: a board is nearly a megabyte, so the request itself is
    # seconds long and twenty-odd when discord.py is sleeping off a
    # 429 inside it, and timed from the send the window reads as
    # having been open for ages exactly when it has not. See refresh.
    refreshed_at: "float | None" = None
    # The trailing pass waiting to write again, if one is booked.
    task: "asyncio.Task[None] | None" = None
    # A digest of the board already on the message, recorded only once
    # an upload has landed -- so a write Discord refused leaves the
    # next refresh believing it still has work to do, which is what
    # makes the backoff the only exit from a refusal.
    png_digest: "bytes | None" = None
    # The full-image URL the last write took the link off and has not
    # put back. Set only while the board is carrying an image it has no
    # link to, and what keeps a trailing pass going when nothing else
    # wants one -- the link is the one thing left undone that no call
    # site will ever come back and ask for.
    link_owed: "str | None" = None
    # Held for the length of a write, so two can never be in the air
    # on one message at once. The lock stops writes being *concurrent*
    # and the interval stops them being *consecutive*; both are needed,
    # and neither is a shorter interval.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Whether the board has been asked for since the write covering it
    # began. A write in flight does not stand in for a request that
    # arrives during it -- the board it is putting up predates the
    # request -- so the want is recorded rather than the task counted.
    wanted: bool = False
    # Board writes Discord has refused in a row. Widens this game's
    # interval until one lands. See interval.
    writes_refused: int = 0


class BoardRefresher:
    """
    One game's board is written through one of these per cog.

    It holds the cog rather than the pieces it needs from it, because
    two of them -- `render_match_png` and `match_file_from_png` -- are
    read at call time and are mocked over in the tests after the
    refresher has been built.
    """

    def __init__(self, cog: "D12Ball") -> None:
        self.cog = cog
        self.states: dict[str, BoardRefreshState] = {}

    def state(self, game_id: str) -> BoardRefreshState:
        """
        This game's board state, started if it has none yet.

        For a caller about to *write* one of the fields. A caller only
        reading asks `self.states.get` instead, so that asking after a
        finished game does not quietly file a new entry for it.
        """
        return self.states.setdefault(game_id, BoardRefreshState())

    def pending_tasks(self) -> list["asyncio.Task[None]"]:
        """Every trailing write currently booked, across all games."""
        return [
            state.task for state in self.states.values()
            if state.task is not None
        ]

    async def refresh(
        self,
        channel: discord.TextChannel,
        game: D12BallGame,
        png: Optional[bytes] = None,
    ) -> None:
        """
        Bring the persistent board message up to date, at most once
        every BOARD_REFRESH_INTERVAL for a given game.

        Discord buckets message edits per message, and this one message
        is edited from fifty-odd places -- a single click walks through
        several of them. That is what was earning the 429s, and the
        intermediate boards are worth nothing: a coach reads the board
        once everything has finished moving. So a refresh that arrives
        inside the window does not queue behind the last one, it
        *replaces* it -- one trailing refresh is scheduled, and by the
        time it runs it draws whatever the state has become.

        A write already in flight does not stand in for a request that
        arrives during it. Drawing and uploading a board is most of a
        second, and the state the caller wants on the message changed
        after that render began -- so this asks for a trailing pass
        rather than assuming it is covered, and takes the game's `lock` for the
        write itself so two edits can never be in the air on one
        message at once. That is the pair of holes the interval alone
        left: a board left showing a state a click had already moved on
        from, and two PATCHes landing in the same instant against a
        bucket that allows about five in five seconds.

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
        loop one step along. See "Discord's rate limits" in docs/design/rate-limits.md.

        `png` is an already-rendered board, for a caller that is
        posting the same one somewhere else in the same breath and
        should not pay to draw it twice. It is only used when the
        refresh happens now; a deferred one re-draws, because the
        board it was handed will be stale by the time it runs.
        """
        if game.message_id is None:
            return

        state = self.state(game.game_id)

        window = self.interval(game)

        if state.lock.locked():
            self.schedule(channel, game, window)
            return

        now = time.monotonic()
        last = state.refreshed_at

        if last is not None and now - last < window:
            self.schedule(channel, game, last + window - now)
            return

        async with state.lock:
            state.wanted = False
            try:
                await self.write(channel, game, png, relink=False)
            finally:
                # In a `finally`: a write that raised still spent its
                # place in the bucket, and a window left open by the
                # failure is one more request into a channel that is
                # already unhappy.
                state.refreshed_at = time.monotonic()

        # That write left the board without its full-image link, so a
        # settling pass is owed whether or not anything else asks for
        # one -- and it is the same pass that draws whatever the rest
        # of this click still has to move.
        if state.link_owed is not None:
            self.schedule(channel, game, self.interval(game))

    def schedule(
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
        request was dropped on the floor: the task was still on the
        state and nothing rescheduled it, so the board kept a state the click
        had already moved past until somebody clicked again.

        `delay` is when to *look*, not when to write. This pass is
        usually queued behind a write that is still going, and its
        sleep runs alongside that write rather than after it -- so by
        the time the lock frees, the wait is already spent and the
        board would be written twice in the same instant. What the
        interval is owed is settled once the lock is held, against the
        moment the last write landed.
        """
        state = self.state(game.game_id)
        state.wanted = True

        if state.task is not None:
            return

        async def run() -> None:
            try:
                await asyncio.sleep(delay)

                while True:
                    pass_state = self.state(game.game_id)
                    async with pass_state.lock:
                        await self.wait_out_interval(game)
                        # Cleared after the wait and before the write,
                        # so this pass covers everything asked for up to
                        # the moment it starts drawing, and anything
                        # asked for during the write is left to the next.
                        wanted, pass_state.wanted = pass_state.wanted, False
                        try:
                            # One request a pass and never two. A pass
                            # somebody asked for draws the board; a
                            # pass reached only because the last one
                            # left a link owed pays that instead. See
                            # `write` for why the two may not share.
                            if wanted:
                                await self.write(channel, game)
                            else:
                                await self.settle_link(channel, game)
                        finally:
                            pass_state.refreshed_at = time.monotonic()

                    # Nothing awaits between the check and the `finally`
                    # below, so a want recorded after this reads False
                    # cannot be lost -- it arrives to find the task gone
                    # and schedules its own.
                    #
                    # A link owed keeps the pass going on its own: it is
                    # the one thing left undone that nothing else will
                    # come back and ask for, and `settle_link` clears it
                    # whatever happens, so this cannot spin.
                    if not pass_state.wanted and pass_state.link_owed is None:
                        return

                    await asyncio.sleep(self.interval(game))
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
                # Read back rather than closed over: `forget` may have
                # dropped this game while the pass was running, and
                # this must not file a fresh entry for it.
                finished = self.states.get(game.game_id)
                if finished is not None:
                    finished.task = None
                    finished.wanted = False

        # The loop keeps only a weak reference to a task, so the handle
        # is held here to keep this one from being collected mid-sleep.
        state.task = asyncio.create_task(run())

    def interval(self, game: D12BallGame) -> float:
        """
        How long this game's board waits between writes: the ordinary
        interval, doubled once per board write Discord has refused in a
        row, up to BOARD_REFRESH_BACKOFF_CEILING.

        Every other lever in this module decides *how many* writes a
        turn asks for. This is the one that decides what to do when the
        answer turns out to be too many anyway -- and without it there
        is no answer at all, because a refused write leaves its digest
        unrecorded and so is retried, identically, at the next window,
        for as long as the game goes on.
        """
        state = self.states.get(game.game_id)
        refused = state.writes_refused if state is not None else 0

        if not refused:
            return BOARD_REFRESH_INTERVAL

        return min(
            BOARD_REFRESH_INTERVAL * 2 ** refused,
            BOARD_REFRESH_BACKOFF_CEILING,
        )

    def note_write_refused(self, game: D12BallGame) -> None:
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
        state = self.state(game.game_id)
        state.writes_refused += 1

        LOGGER.warning(
            "Discord refused the board write for D12 Ball game %s "
            "(%d in a row); next attempt in %.0fs.",
            game.game_id,
            state.writes_refused,
            self.interval(game),
        )

    async def wait_out_interval(self, game: D12BallGame) -> None:
        """
        Sleep whatever is left of this game's window, measured from the
        moment its last board write landed.

        The caller holds the game's `lock`, so nothing else can write
        or restamp the clock while this waits -- and a refresh arriving
        meanwhile finds the lock held and books itself in rather than
        going out alongside.

        This is the only place the bot sleeps *before* a request, and
        it is not the pacing "fewer requests, never slower ones" rules
        out: nobody is waiting on the board this pass is going to draw,
        because it has not been drawn yet. Every other write it might
        stand in for is one it is about to make unnecessary.
        """
        state = self.states.get(game.game_id)
        last = state.refreshed_at if state is not None else None

        if last is None:
            return

        remaining = last + self.interval(game) - time.monotonic()

        if remaining > 0:
            await asyncio.sleep(remaining)

    async def write(
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

        So no write ever cuts the link it has just killed. Every one
        of them strips the dead link in the edit it was already paying
        for and records the URL as owed; a later pass with nothing new
        to draw spends its own request putting a live one back. The
        board is linkless for a window or two rather than dead-linked
        for it, which is the honest of the two.

        **The upload and the relink used to be one pass**, and that
        pair is what the last batch of 429s was. Six refusals, evenly
        11.8 seconds apart, every one of them arriving about a third of
        a second after a board upload had just landed and carrying a
        `retry_after` that was the remainder of *that* request's
        window -- the shape of a second request inside a window the
        first had opened, repeated once per settling pass for as long
        as the two coaches kept clicking. discord.py waits out any
        bucket Discord tells it about, so a 429 reaching the log at all
        means a limit the headers did not advertise; the gate spaced
        its passes and then spent two requests inside one of them.

        `relink` now says only whether a pass may spend its request on
        a link it owes when there is no new board to draw. It never
        buys a second request: an interim write (False) leaves the link
        to the trailing pass, and a trailing pass that uploads leaves
        it to the pass after that -- which is what `schedule` keeps
        going for.

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
        interval.
        """
        if game.message_id is None:
            return

        if png is None:
            png = await self.cog.render_match_png(game)

        state = self.state(game.game_id)

        digest = hashlib.sha256(png).digest()
        if state.png_digest == digest:
            if relink:
                await self.settle_link(channel, game)
            return

        # Setting a view replaces the one already there, so the
        # message's own home/visiting buttons get rebuilt with it.
        # Those are inert once the assignment is made, which is the
        # only state a board refresh runs in; before it, this message
        # is still the team/coin prompt, its buttons are live, and it
        # has no link on it to go stale -- so it is left alone.
        strip_link = game.home_and_visiting_selected

        try:
            board_message = channel.get_partial_message(game.message_id)
            updated_message = await board_message.edit(
                attachments=[self.cog.match_file_from_png(game, png)],
                view=(
                    HomeAwaySelectionView(cog=self.cog, game_id=game.game_id)
                    if strip_link
                    else discord.utils.MISSING
                ),
            )
        except (
            discord.NotFound, discord.HTTPException, aiohttp.ClientError,
        ) as error:
            if getattr(error, "status", None) == TOO_MANY_REQUESTS:
                self.note_write_refused(game)
            return

        # Recorded only once the upload has landed, so a failed edit
        # -- a refused write above all -- leaves the next refresh
        # believing it still has work to do.
        state.png_digest = digest
        # One landing is the whole of the recovery: the window goes
        # straight back to its ordinary width rather than stepping down
        # through the backoff, because what the backoff was waiting for
        # has just happened.
        state.writes_refused = 0
        # Whatever was owed was owed against the upload this one just
        # replaced, so it dies with it either way.
        state.link_owed = None

        if not game.home_and_visiting_selected:
            return

        button = build_full_image_button(updated_message)
        if button is not None:
            state.link_owed = button.url

    async def settle_link(
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
        state = self.states.get(game.game_id)

        if state is None:
            return

        # Cleared before the message_id guard, not after: on `main`
        # this read was a `pop`, so a game whose board message has gone
        # stopped owing a link rather than owing one for ever.
        url, state.link_owed = state.link_owed, None

        if url is None or game.message_id is None:
            return

        view = HomeAwaySelectionView(cog=self.cog, game_id=game.game_id)
        view.add_item(full_image_link_button(url))

        try:
            await channel.get_partial_message(game.message_id).edit(view=view)
        except (discord.NotFound, discord.HTTPException, aiohttp.ClientError):
            # As everywhere else the link is concerned: the board is
            # already up, and a missing link is worth less than
            # anything it would take down with it.
            pass

    def forget(self, game: D12BallGame) -> None:
        """
        Drop everything this game's board was carrying, pending write
        included.

        A refresh still waiting on its window would write to a channel
        that has just been archived, and the seven maps would otherwise
        keep a finished game's entries for the life of the process.
        """
        state = self.states.pop(game.game_id, None)

        if state is not None and state.task is not None:
            state.task.cancel()

    def shutdown(self) -> None:
        """
        Drop any board refresh still waiting on its window. The reload
        that follows builds a new cog with its own games, so a task
        holding the old one would edit from state nothing else can see.

        A board whose settling write is cancelled here keeps the board
        it has and loses its full-image link until the next write puts
        one back -- the same trade the link is under everywhere else.
        """
        for task in self.pending_tasks():
            task.cancel()

        for state in self.states.values():
            state.wanted = False

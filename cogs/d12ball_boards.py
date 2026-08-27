"""
The write gate on a game's persistent board message.

Every 429 in two logged sessions of play was a `PATCH` on
`/channels/{id}/messages/{id}`, and `message_id` is not one of
Discord's major rate-limit parameters -- so every edit to every message
in a game's channel shares one bucket of roughly five requests in five
seconds. After the second round of those, the board message is the only
thing in this bot that edits through the channel at all, which makes
this module the whole of that bucket's spending.

What lives here is the state seven parallel game-keyed maps used to
carry on the cog -- when a write landed, the pass waiting to write
again, the board already on the message, the link owed for it, the lock
over the message, the wants arriving mid-write, and the refusals -- and
the six methods that read them. They were only ever touched by each
other; on the cog they were seven of its attributes and seven of its
methods, indistinguishable from the two hundred that carry the game
forward.

`D12Ball.refresh_match_image` is still the way in, and still the only
one the rest of the cog uses. See "Discord's rate limits" in CLAUDE.md
for the measurements every decision here rests on.
"""

import asyncio
import hashlib
import logging
import time
from typing import TYPE_CHECKING, Optional

import aiohttp
import discord

from cogs.d12ball_helpers import (
    add_full_image_button,
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
# three: one interim board, then the settling board and its link. See
# "The board message is one bucket" in CLAUDE.md.
#
# It is also how long the board goes without its full-image link: an
# interim write strips the link rather than paying a second edit to
# re-cut it, and the settling write scheduled at this interval is what
# puts it back. See BoardRefresher.write.
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

        # Per game: when its board message was last edited -- the
        # moment the write *landed*, not the moment it was sent -- the
        # trailing refresh waiting to edit it again, and a digest of
        # the board already sitting on the message. See refresh.
        self.refreshed_at: dict[str, float] = {}
        self.tasks: dict[str, "asyncio.Task[None]"] = {}
        self.png_digests: dict[str, bytes] = {}
        # The full-image URL an interim write took the link off and has
        # not put back yet, by game. A game is in here only while its
        # board message is carrying a board it has no link to, which is
        # what the settling write is for -- see settle_link.
        self.link_owed: dict[str, str] = {}
        # Held for the length of a board write, so two of them can
        # never be in flight on the same message at once, and the set
        # of games whose board has been asked for since the write
        # covering it began. See refresh.
        self.locks: dict[str, asyncio.Lock] = {}
        self.wanted: set[str] = set()
        # Board writes Discord has refused in a row, by game. Widens
        # that game's interval until one lands. See interval.
        self.writes_refused: dict[str, int] = {}

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
        several of them, and each is two edits (see `write`). That is
        what was earning the 429s, and the intermediate boards are
        worth nothing: a coach reads the board once everything has
        finished moving. So a refresh that arrives inside the window
        does not queue behind the last one, it *replaces* it -- one
        trailing refresh is scheduled, and by the time it runs it draws
        whatever the state has become.

        A write already in flight does not stand in for a request that
        arrives during it. Drawing and uploading a board is most of a
        second, and the state the caller wants on the message changed
        after that render began -- so this asks for a trailing pass
        rather than assuming it is covered, and takes `locks` for the
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
        loop one step along. See "Discord's rate limits" in CLAUDE.md.

        `png` is an already-rendered board, for a caller that is
        posting the same one somewhere else in the same breath and
        should not pay to draw it twice. It is only used when the
        refresh happens now; a deferred one re-draws, because the
        board it was handed will be stale by the time it runs.
        """
        if game.message_id is None:
            return

        lock = self.locks.setdefault(game.game_id, asyncio.Lock())

        window = self.interval(game)

        if lock.locked():
            self.schedule(channel, game, window)
            return

        now = time.monotonic()
        last = self.refreshed_at.get(game.game_id)

        if last is not None and now - last < window:
            self.schedule(channel, game, last + window - now)
            return

        async with lock:
            self.wanted.discard(game.game_id)
            try:
                await self.write(channel, game, png, relink=False)
            finally:
                self.refreshed_at[game.game_id] = time.monotonic()

        # That write left the board without its full-image link, so a
        # settling pass is owed whether or not anything else asks for
        # one -- and it is the same pass that draws whatever the rest
        # of this click still has to move.
        if game.game_id in self.link_owed:
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
        request was dropped on the floor: the task was still in `tasks`
        and nothing rescheduled it, so the board kept a state the click
        had already moved past until somebody clicked again.

        `delay` is when to *look*, not when to write. This pass is
        usually queued behind a write that is still going, and its
        sleep runs alongside that write rather than after it -- so by
        the time the lock frees, the wait is already spent and the
        board would be written twice in the same instant. What the
        interval is owed is settled once the lock is held, against the
        moment the last write landed.
        """
        self.wanted.add(game.game_id)

        if game.game_id in self.tasks:
            return

        async def run() -> None:
            try:
                await asyncio.sleep(delay)

                while True:
                    lock = self.locks.setdefault(
                        game.game_id, asyncio.Lock(),
                    )
                    async with lock:
                        await self.wait_out_interval(game)
                        # Discarded after the wait and before the write,
                        # so this pass covers everything asked for up to
                        # the moment it starts drawing, and anything
                        # asked for during the write is left to the next.
                        self.wanted.discard(game.game_id)
                        try:
                            await self.write(channel, game)
                        finally:
                            self.refreshed_at[game.game_id] = (
                                time.monotonic()
                            )

                    # Nothing awaits between the check and the `finally`
                    # below, so a want recorded after this reads False
                    # cannot be lost -- it arrives to find the task gone
                    # and schedules its own.
                    if game.game_id not in self.wanted:
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
                self.tasks.pop(game.game_id, None)
                self.wanted.discard(game.game_id)

        # The loop keeps only a weak reference to a task, so the handle
        # is held here to keep this one from being collected mid-sleep.
        self.tasks[game.game_id] = asyncio.create_task(run())

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
        refused = self.writes_refused.get(game.game_id, 0)

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
        self.writes_refused[game.game_id] = (
            self.writes_refused.get(game.game_id, 0) + 1
        )

        LOGGER.warning(
            "Discord refused the board write for D12 Ball game %s "
            "(%d in a row); next attempt in %.0fs.",
            game.game_id,
            self.writes_refused[game.game_id],
            self.interval(game),
        )

    async def wait_out_interval(self, game: D12BallGame) -> None:
        """
        Sleep whatever is left of this game's window, measured from the
        moment its last board write landed.

        The caller holds `locks`, so nothing else can write or restamp
        the clock while this waits -- and a refresh arriving meanwhile
        finds the lock held and books itself in rather than going out
        alongside.

        This is the only place the bot sleeps *before* a request, and
        it is not the pacing "fewer requests, never slower ones" rules
        out: nobody is waiting on the board this pass is going to draw,
        because it has not been drawn yet. Every other write it might
        stand in for is one it is about to make unnecessary.
        """
        last = self.refreshed_at.get(game.game_id)

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
        interval.
        """
        if game.message_id is None:
            return

        if png is None:
            png = await self.cog.render_match_png(game)

        digest = hashlib.sha256(png).digest()
        if self.png_digests.get(game.game_id) == digest:
            if relink:
                await self.settle_link(channel, game)
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
        # leaves the next refresh believing it still has work to do.
        self.png_digests[game.game_id] = digest
        # One landing is the whole of the recovery: the window goes
        # straight back to its ordinary width rather than stepping down
        # through the backoff, because what the backoff was waiting for
        # has just happened.
        self.writes_refused.pop(game.game_id, None)
        # Whatever was owed was owed against the upload this one just
        # replaced, so it dies with it either way.
        self.link_owed.pop(game.game_id, None)

        if not game.home_and_visiting_selected:
            return

        if relink:
            await add_full_image_button(
                updated_message,
                HomeAwaySelectionView(cog=self.cog, game_id=game.game_id),
            )
            return

        button = build_full_image_button(updated_message)
        if button is not None:
            self.link_owed[game.game_id] = button.url

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
        url = self.link_owed.pop(game.game_id, None)

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
        task = self.tasks.pop(game.game_id, None)
        if task is not None:
            task.cancel()

        self.refreshed_at.pop(game.game_id, None)
        self.png_digests.pop(game.game_id, None)
        self.wanted.discard(game.game_id)
        self.locks.pop(game.game_id, None)
        self.link_owed.pop(game.game_id, None)
        self.writes_refused.pop(game.game_id, None)

    def shutdown(self) -> None:
        """
        Drop any board refresh still waiting on its window. The reload
        that follows builds a new cog with its own games, so a task
        holding the old one would edit from state nothing else can see.

        A board whose settling write is cancelled here keeps the board
        it has and loses its full-image link until the next write puts
        one back -- the same trade the link is under everywhere else.
        """
        for task in list(self.tasks.values()):
            task.cancel()

        self.wanted.clear()

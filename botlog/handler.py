"""
The Discord sink for log records: a logging.Handler that mirrors
anything at its level or above into a Discord channel, so a crash shows
up in the server instead of only in the console of whichever machine is
hosting the bot.

Two rules shape the whole file.

First, emit() runs wherever the log call happened -- possibly on a
worker thread, possibly while the event loop is busy -- so it may not
touch Discord. All it does is format the record and hand it to the loop;
a background worker owns every channel.send. Until start() binds a live
client the handler drops what it is given, because the console handler
still has those records and nothing is lost.

Second, the sink may never log its own failures. A send that failed and
then logged would feed itself the record it just failed to send, and the
handler would spin. Failures print to stderr instead.

Flood control lives in _admit: a run of the same record (a render bug
throwing the same traceback on every board update) collapses to the
first post plus an occasional heartbeat, and a fixed-window cap stops a
storm of varied errors from filling the channel and burning the bot's
rate limit on log posts.
"""

import asyncio
import logging
import sys
from typing import Optional

import discord


# Discord's message limit is 2000; the rest is headroom for the code
# fence and for a formatter that grows.
DEFAULT_CHUNK_LIMIT = 1900

LOG_RECORD_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def chunk_log_message(
    text: str,
    limit: int = DEFAULT_CHUNK_LIMIT,
) -> list[str]:
    """
    Split a formatted record (its message plus any traceback) into
    Discord-sized pieces, each wrapped in a code fence.

    Line boundaries are preferred so a traceback stays readable; a
    single line longer than the limit is hard-split rather than
    dropped. Pure, so the awkward cases are unit-tested.
    """
    text = text.rstrip()

    if not text:
        return []

    lines: list[str] = []

    for line in text.split("\n"):
        while len(line) > limit:
            lines.append(line[:limit])
            line = line[limit:]

        lines.append(line)

    chunks: list[str] = []
    buffered: list[str] = []
    buffered_length = 0

    for line in lines:
        # The + 1 is the newline that rejoins this line to the buffer.
        if buffered and buffered_length + len(line) + 1 > limit:
            chunks.append("\n".join(buffered))
            buffered, buffered_length = [], 0

        buffered.append(line)
        buffered_length += len(line) + 1

    if buffered:
        chunks.append("\n".join(buffered))

    return [f"```\n{chunk}\n```" for chunk in chunks]


class DiscordLogChannelHandler(logging.Handler):
    """
    Mirrors records at `level` and above into one Discord channel.

    Silent until start() binds a client and a channel id, and silent
    again for anything Discord refuses -- in both cases the console
    handler still has the record.
    """

    # Most records posted per window before suppression kicks in.
    RATE_LIMIT = 15
    RATE_WINDOW = 60.0
    # A still-repeating identical record posts once per this many hits.
    DUPLICATE_HEARTBEAT = 100
    # Records dropped rather than queued without bound under a storm.
    QUEUE_SIZE = 1000
    # Records joined into one post when a burst is already queued.
    BATCH_SIZE = 20

    def __init__(self, level: int = logging.ERROR) -> None:
        super().__init__(level)
        self.setFormatter(logging.Formatter(LOG_RECORD_FORMAT))
        self.started = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue: Optional["asyncio.Queue[str]"] = None
        # The event loop only holds a weak reference to a task, so
        # without this the worker can be collected mid-run and the sink
        # would go quiet with nothing to show for it.
        self._worker_task: Optional["asyncio.Task[None]"] = None
        self._client: Optional[discord.Client] = None
        self._channel_id: Optional[int] = None
        # Flood-control state. Only ever touched by _admit, which only
        # the worker calls, so it needs no lock.
        self._last_sent: Optional[str] = None
        self._duplicates = 0
        self._window_start = 0.0
        self._window_count = 0
        self._suppressed = 0

    def start(self, client: discord.Client, channel_id: int) -> None:
        """
        Bind a live client and channel and spawn the worker.

        Must be called from inside the running event loop (on_ready is
        the place, since resolving a channel needs the guild list).
        Idempotent, because on_ready fires again on every reconnect.
        """
        if self.started:
            return

        self._client = client
        self._channel_id = channel_id
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=self.QUEUE_SIZE)
        self._worker_task = self._loop.create_task(self._worker())
        self.started = True

    def emit(self, record: logging.LogRecord) -> None:
        loop, queue = self._loop, self._queue

        if loop is None or queue is None:
            # Not started yet. The console handler has this record.
            return

        try:
            message = self.format(record)
        except Exception:
            # A record that cannot be formatted must not crash logging.
            return

        try:
            loop.call_soon_threadsafe(self._offer, queue, message)
        except RuntimeError:
            # The loop is closed or shutting down.
            pass

    @staticmethod
    def _offer(queue: "asyncio.Queue[str]", message: str) -> None:
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            # Drop under a storm rather than grow without bound.
            pass

    def _admit(self, message: str, now: float) -> list[str]:
        """
        Flood control for one record: the message or messages to
        actually post, which may be none of it, all of it, or a note
        about what was held back.

        Two guards. An identical record repeating goes quiet after the
        first post, with a heartbeat every DUPLICATE_HEARTBEAT hits so
        an ongoing problem does not look like it stopped. Past
        RATE_LIMIT records in a RATE_WINDOW the body is dropped and
        counted, and the count is reported once the window rolls over.

        Pure over its own state and the clock it is passed, so the
        awkward sequences are unit-tested without a client.
        """
        if message == self._last_sent:
            self._duplicates += 1

            if self._duplicates % self.DUPLICATE_HEARTBEAT == 0:
                return [
                    "(still repeating the previous error -- "
                    f"{self._duplicates} times so far)"
                ]

            return []

        notes: list[str] = []

        if self._duplicates:
            notes.append(
                f"(previous message repeated {self._duplicates} "
                "more time(s))"
            )
            self._duplicates = 0

        if now - self._window_start >= self.RATE_WINDOW:
            if self._suppressed:
                notes.append(
                    f"(suppressed {self._suppressed} log record(s) over "
                    f"the last {int(self.RATE_WINDOW)}s to avoid "
                    "flooding)"
                )
                self._suppressed = 0

            self._window_start = now
            self._window_count = 0

        if self._window_count >= self.RATE_LIMIT:
            self._suppressed += 1
            # Drop the body, keep any note about what was held back.
            return notes

        self._window_count += 1
        self._last_sent = message

        return notes + [message]

    async def _worker(self) -> None:
        client, queue = self._client, self._queue
        loop = self._loop

        if client is None or queue is None or loop is None:
            return

        await client.wait_until_ready()

        while True:
            try:
                batch = [await queue.get()]

                # Coalesce a burst, so an error storm is a handful of
                # posts instead of one per record.
                while not queue.empty() and len(batch) < self.BATCH_SIZE:
                    batch.append(queue.get_nowait())

                posts: list[str] = []

                for record in batch:
                    posts.extend(self._admit(record, loop.time()))

                if posts:
                    await self._flush(posts)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # The sink must never die, and must never log.
                print(
                    f"[foolbot] Discord log sink error: {error!r}",
                    file=sys.stderr,
                )

    async def _flush(self, batch: list[str]) -> None:
        channel = (
            self._client.get_channel(self._channel_id)
            if self._client is not None and self._channel_id is not None
            else None
        )

        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return

        for chunk in chunk_log_message("\n\n".join(batch)):
            try:
                await channel.send(chunk)
            except discord.HTTPException as error:
                # Print, never log, or this feeds itself.
                print(
                    f"[foolbot] Could not post a log record to Discord: "
                    f"{error!r}",
                    file=sys.stderr,
                )
                return

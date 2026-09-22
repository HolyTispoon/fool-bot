"""
One game, one answer at a time.

Decision 5 of docs/web-app.md: both frontends run in one process over
one `GameService`, and what keeps two of their answers from being
*presented* out of order is a lock per game (`gamelocks.py`). The
apply itself is synchronous and needs no help; everything a frontend
does afterwards -- renders, uploads, edits, a JSON response built from
a board it drew -- is awaits, and awaits interleave.

The second test here is a ratchet rather than a behaviour: the Discord
half takes the lock by overriding discord.py's own click dispatch,
which is the only place a callback can be wrapped, and a rename
upstream would leave every click unordered without a single test
failing. So this one fails instead.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

import discord

from cogs.d12ball_views.base import SafeView
from gamelocks import GameLocks


class GameLockTests(unittest.IsolatedAsyncioTestCase):
    """The lock itself."""

    async def test_two_answers_on_one_game_do_not_interleave(self) -> None:
        locks = GameLocks()
        order: list[str] = []

        async def answer(name: str) -> None:
            async with locks.hold("g1"):
                order.append(f"{name} in")
                # Where a frontend renders, uploads and edits.
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                order.append(f"{name} out")

        await asyncio.gather(answer("first"), answer("second"))

        self.assertEqual(
            order, ["first in", "first out", "second in", "second out"],
        )

    async def test_two_games_do_not_wait_on_each_other(self) -> None:
        locks = GameLocks()
        started = asyncio.Event()

        async def hold_one() -> None:
            async with locks.hold("g1"):
                started.set()
                await asyncio.sleep(0.05)

        async def the_other_game() -> bool:
            await started.wait()
            async with locks.hold("g2"):
                # The other game is still being held, and this one
                # went through anyway.
                return locks.held("g1")

        _, other = await asyncio.gather(hold_one(), the_other_game())

        self.assertTrue(other)

    async def test_a_game_nobody_has_touched_has_no_lock(self) -> None:
        locks = GameLocks()

        self.assertFalse(locks.held("g1"))
        async with locks.hold("g1"):
            self.assertTrue(locks.held("g1"))
        self.assertFalse(locks.held("g1"))

    def test_the_same_game_is_always_the_same_lock(self) -> None:
        locks = GameLocks()

        self.assertIs(locks.hold("g1"), locks.hold("g1"))
        self.assertIsNot(locks.hold("g1"), locks.hold("g2"))


class ClickDispatchTests(unittest.IsolatedAsyncioTestCase):
    """Where a click takes it."""

    def test_the_dispatch_being_wrapped_still_exists(self) -> None:
        """
        `SafeView._scheduled_task` overrides discord.py's, so the
        override is only doing anything while the library still calls
        a method of that name.
        """
        self.assertTrue(
            hasattr(discord.ui.View, "_scheduled_task"),
            "discord.py no longer dispatches a click through "
            "_scheduled_task: SafeView's override holds nothing.",
        )
        self.assertIsNot(
            SafeView._scheduled_task, discord.ui.View._scheduled_task,
        )

    async def test_a_click_is_answered_while_holding_the_game_s_lock(
        self,
    ) -> None:
        held: list[bool] = []

        class Cog:
            locks = GameLocks()

        class View(SafeView):
            def __init__(self) -> None:
                super().__init__(timeout=None)
                self.cog = Cog()
                self.game_id = "g1"

        view = View()

        async def callback(interaction) -> None:
            held.append(Cog.locks.held("g1"))

        item = _Item(callback)

        await view._scheduled_task(item, _interaction())

        self.assertEqual(held, [True])
        self.assertFalse(Cog.locks.held("g1"))

    async def test_a_cog_that_is_a_test_double_holds_nothing(self) -> None:
        ran: list[bool] = []

        class View(SafeView):
            def __init__(self) -> None:
                super().__init__(timeout=None)
                self.cog = object()
                self.game_id = "g1"

        async def callback(interaction) -> None:
            ran.append(True)

        await View()._scheduled_task(_Item(callback), _interaction())

        self.assertEqual(ran, [True])


def _interaction() -> SimpleNamespace:
    """The least of a `discord.Interaction` that dispatch touches."""
    return SimpleNamespace(data={})


class _Item:
    """The least of a `discord.ui.Item` that dispatch touches."""

    def __init__(self, callback) -> None:
        self.callback = callback

    def _refresh_state(self, interaction, data) -> None:
        pass

    async def _run_checks(self, interaction) -> bool:
        return True


if __name__ == "__main__":
    unittest.main()

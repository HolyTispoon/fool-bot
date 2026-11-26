"""
`/codex replay` (docs/design/codex.md, "The replay"): a game that is
over shown again turn by turn from its channel's pins, through
`tests/codex_cog_fakes.py` -- each slide a pinned board by its address
and its turn's lines from the publisher's record, the last the final
board uploaded once; the buttons stepping through it with the click's
own response, Play through the latest click's token; and a game still
being played, or none, said so.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from codex.game import GameStatus
from cogs.codex_views import replay as replay_view
from cogs.codex_views.replay import FINAL_FILENAME, ReplaySlide, ReplayView, slide_text

import test_codex_publish_hooks as hooks


def pressed(view, which, call):
    button = next(item for item in view.children if item is getattr(view, which))
    return button.callback(call)


class ReplayCommandTests(hooks.HooksTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.attach()
        self.game = await self.table.started()
        await self.end_turn()
        await self.end_turn()
        await self.settled()

    async def finish(self) -> None:
        self.table.cog.service.concede(self.game.game_id, 2)
        self.assertIs(self.game.status, GameStatus.FINISHED)

    async def replayed(self, number=None):
        call = self.table.interaction(self.table.fencer)
        await self.table.cog.replay.callback(self.table.cog, call, number)
        return call

    async def test_a_game_still_played_is_not_replayed(self) -> None:
        call = await self.replayed()
        self.assertIn("No Codex game that is over", call.text())
        call = await self.replayed(self.game.game_number)
        self.assertIn("still being played", call.text())
        call = await self.replayed(999)
        self.assertIn("no Codex game 999", call.text())

    async def test_the_pinned_turns_then_the_final_board(self) -> None:
        await self.finish()
        mark = len(self.table.game_channel.requests)
        call = await self.replayed()
        kind, _, sent = call.last("followup.send")
        view = sent["view"]
        self.assertIsInstance(view, ReplayView)
        # Turns 1 and 2 pinned as they opened -- turn 3, conceded while it
        # waited on its tech, never opened -- then where it ended.
        self.assertEqual([slide.label for slide in view.slides],
                         ["Turn 1's start", "Turn 2's start", "The final board"])
        first = view.slides[0]
        self.assertTrue(first.image_url.startswith("https://cdn.test/"))
        self.assertIsNone(first.png)
        self.assertTrue(first.heading.startswith("**Turn 1**"))
        # Turn 1's lines are the publisher's record's, drawn for Discord.
        self.assertTrue(first.lines)
        self.assertFalse(any("{" in line for line in first.lines), first.lines)
        self.assertIn("End of turn", " ".join(first.lines))
        self.assertEqual(sent["embed"].image.url, first.image_url)
        self.assertNotIn("file", sent)
        self.assertIn("(1 of 3)", sent["embed"].title)
        final = view.slides[-1]
        self.assertIsNotNone(final.png)
        self.assertIn("basher wins", final.heading)
        # One listing of the pins and nothing else in the channel.
        self.assertEqual([kind for kind, _, _ in self.table.game_channel.since(mark)], ["pins"])

    async def test_the_buttons_step_through_it(self) -> None:
        await self.finish()
        view = (await self.replayed()).last("followup.send")[2]["view"]
        self.assertTrue(view.first.disabled and view.previous.disabled)
        call = self.table.interaction(self.table.fencer)
        await pressed(view, "next", call)
        _, _, edited = call.last("response.edit")
        self.assertIn("Turn 2's start", edited["embed"].title)
        self.assertEqual(edited["attachments"], [])
        call = self.table.interaction(self.table.fencer)
        await pressed(view, "final", call)
        _, _, edited = call.last("response.edit")
        self.assertEqual(edited["embed"].image.url, f"attachment://{FINAL_FILENAME}")
        self.assertEqual([one.filename for one in edited["attachments"]], [FINAL_FILENAME])
        self.assertTrue(view.next.disabled and view.final.disabled)
        call = self.table.interaction(self.table.fencer)
        await pressed(view, "first", call)
        self.assertEqual(view.index, 0)

    async def test_the_game_by_its_number_from_another_channel(self) -> None:
        await self.finish()
        call = self.table.interaction(self.table.fencer, self.table.lobby_channel)
        await self.table.cog.replay.callback(self.table.cog, call, self.game.game_number)
        self.assertIsInstance(call.last("followup.send")[2]["view"], ReplayView)


class PlayTests(unittest.IsolatedAsyncioTestCase):
    def slides(self, count=3):
        return [ReplaySlide(label=f"Turn {n}'s start", heading=f"**Turn {n}**",
                            image_url=f"https://cdn.test/{n}") for n in range(1, count + 1)]

    async def test_play_runs_to_the_end_through_the_latest_token(self) -> None:
        view = ReplayView(7, self.slides())
        call = mock.MagicMock()
        call.response.edit_message = mock.AsyncMock()
        call.edit_original_response = mock.AsyncMock()
        with mock.patch.object(replay_view, "REPLAY_EVERY", 0):
            await pressed(view, "play", call)
            self.assertEqual(view.play.label, "Pause")
            await view.playing
        self.assertEqual(view.index, 2)
        self.assertEqual(call.edit_original_response.await_count, 2)
        self.assertIsNone(view.playing)
        self.assertEqual(view.play.label, "Play")

    async def test_a_step_by_hand_pauses_play(self) -> None:
        view = ReplayView(7, self.slides())
        call = mock.MagicMock()
        call.response.edit_message = mock.AsyncMock()
        with mock.patch.object(replay_view, "REPLAY_EVERY", 60):
            await pressed(view, "play", call)
            task = view.playing
            await pressed(view, "next", call)
            await asyncio.sleep(0)
        self.assertTrue(task.cancelled())
        self.assertIsNone(view.playing)

    def test_a_long_turn_is_folded(self) -> None:
        slide = ReplaySlide(label="x", heading="**Turn 1**", lines=["y" * 100] * 100)
        text = slide_text(slide)
        self.assertLessEqual(len(text), 4096)
        self.assertTrue(text.endswith("more*"))


if __name__ == "__main__":
    unittest.main()

"""
A Codex game saved mid-turn comes back to the same question after a
restart (docs/codex-bot.md, step 4; docs/design/recovery.md): from **My
hand** on the turn message, which the restart re-armed, and from
`/codex resume`, which re-posts the table and hands the clicker their
panel afresh. The panel is ephemeral and dies with the old process; the
question is the model's (`pending`), so the new panel asks it again.
"""

from __future__ import annotations

import unittest

from codex.prompts import PromptKind
from codex_cog_fakes import Table
from codex_positions import put
from cogs.codex_views import TechChoiceView, TurnPanelView


class ResumeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.table = Table()
        self.addCleanup(self.table.close)
        self.game = await self.table.started()

    async def mid_turn(self):
        """A card played, so the turn is under way; the panel's prompt."""
        _, view = await self.table.panel()
        slug = next(row.slug for row in view.prompt.options.playable if row.allowed)
        return (await self.table.press(view, ("play", slug))).view().prompt

    async def test_my_hand_resumes_the_same_prompt_after_a_restart(self) -> None:
        before = await self.mid_turn()
        self.table.restart()
        call, view = await self.table.panel()
        self.assertIsInstance(view, TurnPanelView)
        self.assertEqual(view.prompt.to_dict(), before.to_dict())
        self.assertTrue(call.last()[2]["ephemeral"])

    async def test_resume_reposts_the_table_and_the_panel(self) -> None:
        before = await self.mid_turn()
        old = self.game.turn_message_id
        self.table.restart()
        mark = len(self.table.game_channel.requests)
        call = self.table.interaction(self.table.active)
        await self.table.cog.resume.callback(self.table.cog, call)
        new = self.table.game.turn_message_id
        self.assertNotEqual(new, old)
        self.assertEqual(
            [(kind, message_id) for kind, message_id, _ in self.table.game_channel.since(mark)],
            [("send", new), ("pin", new), ("unpin", old)],
        )
        panel = call.answers[-1]
        self.assertEqual(panel[0], "followup.send")
        self.assertTrue(panel[2]["ephemeral"])
        self.assertIsInstance(panel[2]["view"], TurnPanelView)
        self.assertEqual(panel[2]["view"].prompt.to_dict(), before.to_dict())

    async def test_a_declared_attacker_still_asks_its_defender(self) -> None:
        """The attacker is saved while the defender is asked
        (`MatchState.attacking`), so a restart between the two clicks
        asks the same question."""
        match = self.table.match
        attacker = put(match, match.active, "older_brother")
        self.table.cog.service.persist(self.game, match)
        _, view = await self.table.panel()
        opened = (await self.table.press(view, "Attack...")).view()
        asked = (await self.table.press(opened, ("attack", attacker.ref))).view().prompt
        self.assertIs(asked.kind, PromptKind.CHOOSE_DEFENDER)
        self.table.restart()
        _, view = await self.table.panel()
        self.assertEqual(view.prompt.to_dict(), asked.to_dict())

    async def test_resume_hands_the_other_player_their_open_tech(self) -> None:
        _, view = await self.table.panel()
        view = (await self.table.press(view, "End main phase")).view()
        await self.table.press(view, "Lock patrol")
        self.table.restart()
        call = self.table.interaction(self.table.waiting)
        await self.table.cog.resume.callback(self.table.cog, call)
        self.assertIsInstance(call.answers[-1][2]["view"], TechChoiceView)
        self.assertTrue(call.answers[-1][2]["ephemeral"])


if __name__ == "__main__":
    unittest.main()

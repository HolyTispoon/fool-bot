"""
`/codex debug patrol`, `damage`, `rune` and `draw` on the faked Discord: a
correction made through the service, its line joining the turn's lines
on the turn message, edited in place; the game's players and helpers
allowed and nobody else; the autocomplete listing what each may name
(docs/design/codex.md, "Corrections by hand").
"""

from __future__ import annotations

import unittest

from codex_cog_fakes import Table, user
from codex_positions import put


class DebugCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.table = Table()
        self.addCleanup(self.table.close)
        self.game = await self.table.started()
        self.helper = user(303, "helper", helper=True)
        self.outsider = user(404, "outsider")
        match = self.table.cog.service.load(self.game)
        self.card = put(match, 2, "tenderfoot")
        self.table.cog.service.persist(self.game, match)

    async def patrol(self, who, unit: str, slot: str):
        cog = self.table.cog
        call = self.table.interaction(who)
        choice = next(one for one in cog.debug_patrol.parameters if one.name == "slot").choices
        chosen = next(one for one in choice if one.value == slot)
        await cog.debug_patrol.callback(cog, call, unit, chosen)
        return call

    async def test_a_helper_moves_a_unit_and_the_turn_message_says_so(self) -> None:
        mark = len(self.table.game_channel.requests)
        call = await self.patrol(self.helper, f"2|{self.card.ref}", "elite")
        self.assertIn("patrols as elite", call.text())
        match = self.table.cog.service.load(self.game)
        self.assertEqual(match.patrollers(2), {"elite": self.card.ref})
        sent = self.table.game_channel.since(mark)
        self.assertEqual([kind for kind, _, _ in sent], ["edit"], "the turn message, edited in place")
        self.assertIn("Corrected:", sent[0][2]["content"])
        self.assertIn("patrols as elite", sent[0][2]["content"])

    def choice(self, command, parameter: str, value: str):
        found = next(one for one in command.parameters if one.name == parameter).choices
        return next(one for one in found if one.value == value)

    async def test_damage_is_added(self) -> None:
        cog = self.table.cog
        call = self.table.interaction(self.helper)
        await cog.debug_damage.callback(cog, call, f"2|{self.card.ref}",
                                        self.choice(cog.debug_damage, "change", "add"), 1)
        self.assertIn("now has 1 damage", call.text())
        self.assertEqual(cog.service.load(self.game).player(2).instance(self.card.id).damage, 1)

    async def test_a_rune_is_added_and_the_autocomplete_shows_it(self) -> None:
        cog = self.table.cog
        call = self.table.interaction(self.helper)
        await cog.debug_rune.callback(cog, call, f"2|{self.card.ref}", self.choice(cog.debug_rune, "rune", "plus"),
                                      self.choice(cog.debug_rune, "change", "add"), 2)
        self.assertIn("now has 2 +1/+1 runes", call.text())
        found = await cog.debug_rune_autocomplete(self.table.interaction(self.helper), "tender")
        self.assertEqual([one.name for one in found], ["fencer: Tenderfoot, 4/4 HP, 2 +1/+1"])

    async def test_a_player_draws_a_card_and_the_autocomplete_lists_the_seats(self) -> None:
        cog = self.table.cog
        held = len(cog.service.load(self.game).player(2).hand)
        call = self.table.interaction(self.table.basher)
        await cog.debug_draw.callback(cog, call, 1, "2")
        self.assertIn("draws a card", call.text())
        self.assertEqual(len(cog.service.load(self.game).player(2).hand), held + 1)
        found = await cog.debug_draw_autocomplete(self.table.interaction(self.helper), "")
        self.assertEqual([one.value for one in found], ["1", "2"])

    async def test_a_draw_naming_nobody_is_the_askers_own(self) -> None:
        cog = self.table.cog
        seat = self.game.seat_of(self.table.basher.id)
        held = len(cog.service.load(self.game).player(seat).hand)
        await cog.debug_draw.callback(cog, self.table.interaction(self.table.basher), 2)
        self.assertEqual(len(cog.service.load(self.game).player(seat).hand), held + 2)
        call = self.table.interaction(self.helper)
        await cog.debug_draw.callback(cog, call, 1)
        self.assertIn("You hold no seat", call.text())

    async def test_a_refusal_is_the_helpers_alone(self) -> None:
        mark = len(self.table.game_channel.requests)
        call = await self.patrol(self.helper, f"2|{self.card.ref}", "off")
        self.assertIn("isn't patrolling", call.text())
        self.assertEqual(self.table.game_channel.since(mark), [])

    async def test_a_player_of_the_game_may_correct_it(self) -> None:
        call = await self.patrol(self.table.basher, f"2|{self.card.ref}", "elite")
        self.assertIn("patrols as elite", call.text())
        self.assertEqual(self.table.cog.service.load(self.game).patrollers(2), {"elite": self.card.ref})

    async def test_somebody_else_is_refused(self) -> None:
        call = await self.patrol(self.outsider, f"2|{self.card.ref}", "elite")
        self.assertIn("Only the game's players", call.text())
        self.assertEqual(self.table.cog.service.load(self.game).patrollers(2), {})

    async def test_the_autocomplete_lists_the_board_for_a_player_or_helper_alone(self) -> None:
        cog = self.table.cog
        for who in (self.helper, self.table.fencer):
            found = await cog.debug_patrol_autocomplete(self.table.interaction(who), "tender")
            self.assertEqual([(one.name, one.value) for one in found],
                             [("fencer: Tenderfoot, 2/2 HP", f"2|{self.card.ref}")])
        self.assertEqual(await cog.debug_patrol_autocomplete(self.table.interaction(self.outsider), ""), [])

if __name__ == "__main__":
    unittest.main()

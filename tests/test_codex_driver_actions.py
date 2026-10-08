"""
`codex.flow.driver`'s two tables cover their enums exactly -- the same
ratchet `tests/test_d12ball_driver_actions.py` and the package-shape
test keep for D12 Ball -- and the door refuses what the position does
not offer.
"""

from __future__ import annotations

import unittest

from codex.flow import FollowOnStep
from codex.flow import driver
from codex.prompts import CHOICES, OPTIONS, Action, PromptKind

from codex_positions import begin, new_game, put


class TableTests(unittest.TestCase):
    def test_answers_cover_prompt_kind_exactly(self) -> None:
        self.assertEqual(set(driver.ANSWERS), set(PromptKind))
        self.assertEqual(set(driver.ARGUMENTS), set(PromptKind))
        self.assertEqual(set(CHOICES), set(PromptKind))
        self.assertEqual(set(OPTIONS), set(PromptKind))

    def test_model_steps_cover_follow_on_step_exactly(self) -> None:
        self.assertEqual(set(driver.MODEL_STEPS), set(FollowOnStep))


class RefusalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine, self.game, self.match = new_game()

    def apply(self, *args, **kwargs):
        return driver.apply(self.engine, self.game, self.match, Action(*args, **kwargs))

    def test_nothing_is_answered_while_the_bot_owes_a_step(self) -> None:
        refused = self.apply(PromptKind.MAIN_ACTION, "end_main")
        self.assertIsInstance(refused, driver.Refusal)
        self.assertEqual(refused.reason, driver.STEP_OWED)

    def test_a_question_not_asked_is_refused_with_what_is(self) -> None:
        begin(self.engine, self.game, self.match)
        refused = self.apply(PromptKind.PATROL, arguments={"assignment": {}})
        self.assertIsInstance(refused, driver.Refusal)
        self.assertIs(refused.waiting_on.kind, PromptKind.MAIN_ACTION)

    def test_an_answer_the_kind_does_not_offer(self) -> None:
        begin(self.engine, self.game, self.match)
        self.assertIsInstance(self.apply(PromptKind.MAIN_ACTION, "concede"), driver.Refusal)
        self.assertIsInstance(
            self.apply(PromptKind.MAIN_ACTION, "end_main", {"colour": "red"}), driver.Refusal,
        )

    def test_the_position_refuses_with_its_page(self) -> None:
        begin(self.engine, self.game, self.match)
        put(self.match, 1, "iron_man", arrived=True)
        refused = self.apply(PromptKind.MAIN_ACTION, "attack", {"attacker": "unit:1"})
        self.assertIsInstance(refused, driver.Refusal)
        self.assertEqual(refused.reason, "Iron Man can't attack: it arrived this turn.")
        self.assertEqual(refused.cite, "UMR p. 10")

    def test_a_refused_action_changes_nothing_and_is_not_journalled(self) -> None:
        begin(self.engine, self.game, self.match)
        before = self.match.to_dict()
        self.apply(PromptKind.MAIN_ACTION, "build", {"building": "tech3"})
        self.assertEqual(self.match.to_dict(), before)

    def test_an_attack_can_be_taken_back_before_its_defender(self) -> None:
        begin(self.engine, self.game, self.match)
        put(self.match, 1, "iron_man")
        self.apply(PromptKind.MAIN_ACTION, "attack", {"attacker": "unit:1"})
        self.assertEqual(self.match.attacking, "unit:1")
        self.apply(PromptKind.CHOOSE_DEFENDER, "cancel")
        self.assertIsNone(self.match.attacking)
        self.assertFalse(self.match.player(1).play[0].exhausted)

    def test_a_finished_game_takes_no_answer(self) -> None:
        begin(self.engine, self.game, self.match)
        self.match.winner = 1
        self.assertIsInstance(self.apply(PromptKind.GAME_OVER), driver.Refusal)


if __name__ == "__main__":
    unittest.main()

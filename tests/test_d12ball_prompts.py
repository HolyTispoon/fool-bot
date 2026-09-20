"""
The model's own reading of what a match is waiting on.

`d12ball.prompts.pending_prompt` is the branch chain that used to be
`D12Ball.pending_turn_view`'s body. **This module imports no
`discord`**, which is the point of it: it is the same question the bot
asks, asked the way a web app would have to ask it, and it runs under
`tests/test_model_purity.py`'s finder rather than around it.

The fixtures are shared with `tests/test_d12ball_prompt_mapping.py`
(see `tests/prompt_fixtures.py`), so the kind asserted here and the
view asserted there are two answers about one state rather than two
tables that have to be kept level by hand.
"""

import unittest
from dataclasses import fields

from d12ball.prompts import PendingPrompt, PromptKind, pending_prompt
from prompt_fixtures import CASES, ENGINE


class PendingPromptTests(unittest.TestCase):

    def test_every_state_names_its_own_kind(self) -> None:
        for case in CASES:
            with self.subTest(case.name):
                fixture = case.build()

                prompt = pending_prompt(
                    ENGINE, fixture.game, fixture.match,
                )

                self.assertIs(prompt.kind, PromptKind[case.kind])
                self.assertEqual(prompt.ask, fixture.ask)

    def test_a_prompt_carries_what_its_branch_carries_and_no_more(
        self,
    ) -> None:
        """
        Every parameter the branch is about, and every other one left
        at its default. The second half is what keeps the dataclass
        honest: a field filled in speculatively -- a side on a prompt
        that has no side -- is a frontend given something to render
        that the rule never decided.
        """
        defaults = {
            field.name: PendingPrompt(PromptKind.PLAYER_ACTION, "")
            for field in fields(PendingPrompt)
        }
        for case in CASES:
            with self.subTest(case.name):
                fixture = case.build()

                prompt = pending_prompt(
                    ENGINE, fixture.game, fixture.match,
                )

                for name, expected in fixture.params.items():
                    self.assertEqual(
                        getattr(prompt, name), expected, name,
                    )
                for name, blank in defaults.items():
                    if name in ("kind", "ask") or name in fixture.params:
                        continue
                    self.assertEqual(
                        getattr(prompt, name), getattr(blank, name), name,
                    )

    def test_the_fixtures_reach_every_kind(self) -> None:
        """
        A kind no fixture stands in is a branch nothing is watching --
        the move was only safe because every one of them was measured
        on the old code first.
        """
        self.assertEqual(
            {PromptKind[case.kind] for case in CASES},
            set(PromptKind),
        )


if __name__ == "__main__":
    unittest.main()

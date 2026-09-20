"""
`FollowOnStep` and the table under it, asserted as the record they are.

A lifted flow step ends by naming a step of the spine that has not
moved out of `cogs/d12ball/` yet, and `D12Ball.follow_on_methods` is
the only thing that turns one of those names into a call. Both halves
are transitional -- Phase 6 of docs/model-discord-split.md deletes them
together -- and while they exist **the enum is the list of what the cog
still dispatches**, which is what Phase 6 reads instead of six pull
request descriptions.

So the membership is asserted whole, here rather than inside any one
card's tests: a rank that lifts a step onto a spine method nothing had
named before adds a member, and this is the file it says so in. A rank
that adds one without a row in the table would otherwise find out at
run time, on a coach's click, as a `KeyError`.
"""

from __future__ import annotations

import inspect
import unittest

from cogs.d12ball import D12Ball
from d12ball.flow.result import FollowOnStep


def bare_cog() -> D12Ball:
    """
    A cog with nothing on it. `follow_on_methods` reads no state --
    it binds methods off the class and hands them back -- so this
    needs no engine, no catalogs and, above all, **no mocks**: the
    signatures below are the assertion, and an `AsyncMock` answers
    `(*args, **kwargs)` to every one of them.
    """
    return object.__new__(D12Ball)


#: Every member of `FollowOnStep`, by name, and the rank that added it.
#: Spelled out so adding a member is a deliberate edit to this list
#: rather than something a set comprehension absorbs silently.
EXPECTED_MEMBERS = {
    # Phase 2 -- Low Pass.
    "FINISH_MANEUVER_RESOLUTION",
    "OFFER_SCORING_ATTEMPT_CHOICE",
    # Rank O2 -- the two dribbles.
    "OFFER_SPEED_CHOICE",
}


class FollowOnStepTests(unittest.TestCase):
    def test_the_enum_is_what_the_cog_still_dispatches(self) -> None:
        self.assertEqual(
            {member.name for member in FollowOnStep}, EXPECTED_MEMBERS,
        )

    def test_every_member_has_a_row_in_the_table(self) -> None:
        """
        The failure this catches is a `KeyError` on a coach's click:
        the model names a step the cog has no row for, and the turn
        stops dead after the match has already been changed and saved.
        """
        methods = bare_cog().follow_on_methods()
        self.assertEqual(set(methods), set(FollowOnStep))

    def test_every_row_takes_the_narration(self) -> None:
        """
        `dispatch_step_result` hands every follow-on the joined
        narration as `lead_in`, because a resolved maneuver is one
        message rather than two (see "Discord's rate limits" in
        docs/design/rate-limits.md). A method that does not take one is
        a case the dispatcher has not met yet, and the answer is to
        widen it there rather than to post around it.
        """
        for step, method in bare_cog().follow_on_methods().items():
            with self.subTest(step=step.name):
                parameters = inspect.signature(method).parameters
                self.assertIn("lead_in", parameters)


if __name__ == "__main__":
    unittest.main()

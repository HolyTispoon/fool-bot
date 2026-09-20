"""
The cog still puts up the view the old chain put up.

This is the equivalence test for Phase 1 of the model/Discord split:
`pending_turn_view`'s branch chain moved into `d12ball/prompts.py` and
what is left in the cog is a mapping from `PromptKind` to a
`discord.ui.View`. The move is only safe if **not one branch changed
its answer**, so every state the chain can be in is stood in
(`tests/prompt_fixtures.py`) and the view class and the line above it
are asserted.

It was written against the old chain and run green there before
anything moved -- see the branch's first commit. That is what makes it
evidence rather than a restatement: a table written after the move
would only prove the new code agrees with itself.

`pending_turn_view` has two production callers, `restore_saved_views`
and `resume_pending_prompt`, and the whole point of it is that they
cannot drift apart -- see "Recovering a stuck game" in
docs/design/recovery.md.
"""

import unittest
from unittest import mock

import cogs.d12ball_views as views
from cogs.d12ball import D12Ball
from cogs.d12ball_boards import BoardRefresher
from d12ball.ai import build_ai_strategies
from d12ball.engine import RulesEngine
from prompt_fixtures import (
    CASES,
    CATALOG,
    MANEUVERS,
    RULESET,
)


def build_cog() -> D12Ball:
    """
    A cog with no bot behind it -- the chain is a pure read, so
    nothing here needs a connection, a channel or a save.
    """
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = CATALOG
    cog.maneuver_catalog = MANEUVERS
    cog.basic_ruleset = RULESET
    cog.condition_emojis = {}
    cog.ai_strategies = build_ai_strategies(CATALOG, MANEUVERS)
    cog.engine = RulesEngine(
        CATALOG, RULESET, MANEUVERS, cog.ai_strategies,
    )
    cog.boards = BoardRefresher(cog)
    cog.refresh_match_image = mock.AsyncMock()
    return cog


class PendingTurnViewEquivalenceTests(unittest.TestCase):
    """One case per branch, asserted on the view and on the ask."""

    def test_every_state_restores_its_own_prompt(self) -> None:
        for case in CASES:
            with self.subTest(case.name):
                cog = build_cog()
                fixture = case.build()
                cog.games[fixture.game.game_id] = fixture.game

                view, ask = cog.pending_turn_view(
                    fixture.game.game_id, fixture.match,
                )

                self.assertIsInstance(view, getattr(views, case.view))
                self.assertEqual(ask, fixture.ask)

    def test_a_kind_always_means_the_same_view(self) -> None:
        """
        The mapping is a table, so a kind that two cases expect two
        different views from is a kind that has not been split far
        enough -- the counting rule is one kind per view class.
        """
        seen: dict[str, str] = {}
        for case in CASES:
            self.assertEqual(
                seen.setdefault(case.kind, case.view),
                case.view,
                f"{case.kind} maps to two views",
            )


if __name__ == "__main__":
    unittest.main()

"""
A coach changing their maneuver while the other side is still choosing.

Both cards are revealed together (Law 6), so a pick is a card held face
down until the second one is in: the coach who picked first may swap it.
The channel is told the pick changed and never what to; the clicker is
told what they changed it to. Against Dinky there is never a window --
the AI picks before the prompt goes up.
"""

import unittest

from cogs.d12ball_views import ManeuverActionPromptView
from d12ball.flow import driver, turn
from d12ball.components import RuleRefusal
from d12ball.prompts import PromptKind, pending_prompt

from prompt_fixtures import ENGINE, build_game, challenge, maneuver_picks
from save_patches import suppressed_cog_saves
from test_d12ball_uncontested_maneuver import (
    build_cog,
    build_game as build_cog_game,
    build_interaction,
)


def _hand(fixture, side):
    prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
    return next(hand for hand in prompt.options.hands if hand.side == side)


def _pick(fixture, side, key):
    return driver.answer(
        ENGINE, fixture.game, fixture.match,
        driver.Action(
            PromptKind.MANEUVER_ACTION, "",
            {"side": side, "maneuver_key": key},
        ),
    )


class ManeuverChangeTests(unittest.TestCase):
    def test_a_pick_may_change_while_the_other_side_chooses(self) -> None:
        fixture = maneuver_picks()
        first, second = _hand(fixture, "offense").maneuver_keys[:2]

        _pick(fixture, "offense", first)
        changed = _pick(fixture, "offense", second)

        self.assertIsInstance(changed, driver.Answered)
        self.assertEqual(fixture.match.offense_maneuver, second)
        self.assertIsNone(fixture.match.defense_maneuver)
        self.assertEqual(len(changed.result.narration), 1)
        self.assertTrue(
            changed.result.narration[0].endswith(
                " has changed their maneuver."
            )
        )
        # Nothing public names the card.
        self.assertNotIn(
            ENGINE.maneuver_name(second), changed.result.narration[0],
        )
        # Still waiting on the defense, which is what goes up next.
        self.assertIsNone(changed.result.next)

    def test_the_defense_may_change_too(self) -> None:
        fixture = maneuver_picks()
        first, second = _hand(fixture, "defense").maneuver_keys[:2]

        _pick(fixture, "defense", first)
        changed = _pick(fixture, "defense", second)

        self.assertIsInstance(changed, driver.Answered)
        self.assertEqual(fixture.match.defense_maneuver, second)

    def test_the_same_card_twice_is_refused(self) -> None:
        fixture = maneuver_picks()
        first = _hand(fixture, "offense").maneuver_keys[0]

        _pick(fixture, "offense", first)
        refused = _pick(fixture, "offense", first)

        self.assertIsInstance(refused, driver.Refusal)
        self.assertIn(ENGINE.maneuver_name(first), refused.reason)
        self.assertEqual(fixture.match.offense_maneuver, first)

    def test_the_changed_pick_is_the_one_that_resolves(self) -> None:
        fixture = maneuver_picks()
        first, second = _hand(fixture, "offense").maneuver_keys[:2]
        defense = _hand(fixture, "defense").maneuver_keys[0]

        _pick(fixture, "offense", first)
        _pick(fixture, "offense", second)
        settled = _pick(fixture, "defense", defense)

        self.assertIsInstance(settled, driver.Answered)
        self.assertEqual(fixture.match.offense_maneuver, second)
        self.assertIsNotNone(settled.result.next)

    def test_no_change_once_both_sides_have_picked(self) -> None:
        fixture = maneuver_picks()
        match = fixture.match
        offense = _hand(fixture, "offense").maneuver_keys
        match.offense_maneuver = offense[0]
        match.defense_maneuver = _hand(fixture, "defense").maneuver_keys[0]

        self.assertEqual(
            turn.maneuver_pick_refusal(
                ENGINE, fixture.game, match, "offense", offense[1],
            ),
            "You have already chosen your maneuver.",
        )
        with self.assertRaises(RuleRefusal):
            match.change_maneuver("offense", offense[1])

    def test_against_dinky_there_is_no_window(self) -> None:
        fixture = maneuver_picks()
        fixture.game = build_game(player_2_id=None)
        game, match = fixture.game, fixture.match

        # The AI answers its row first, as the service does before the
        # prompt goes up.
        prompt = pending_prompt(ENGINE, game, match)
        ai = driver.ai_action(ENGINE, game, match, prompt)
        self.assertIsNotNone(ai)
        self.assertIsInstance(
            driver.answer(ENGINE, game, match, ai), driver.Answered,
        )

        human = next(
            hand for hand in pending_prompt(ENGINE, game, match).options.hands
            if not hand.picked
        )
        first, second = human.maneuver_keys[:2]
        picked = _pick(fixture, human.side, first)
        self.assertIsInstance(picked, driver.Answered)
        # Both are in, so the maneuver settles on the coach's first pick.
        self.assertIsNotNone(picked.result.next)

        self.assertEqual(
            turn.maneuver_pick_refusal(
                ENGINE, game, match, human.side, second,
            ),
            "You have already chosen your maneuver.",
        )


class ManeuverChangeReplyTests(unittest.IsolatedAsyncioTestCase):
    """What the two coaches read when one changes their pick."""

    def build(self):
        cog = build_cog()
        game = build_cog_game()
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)
        challenge(match)
        game.match_state = match.to_dict()
        return cog, game

    async def click(self, cog, game, key):
        interaction = build_interaction(user_id=111)
        with suppressed_cog_saves():
            await ManeuverActionPromptView(cog, game.game_id).pick(
                interaction, "offense", key,
            )
        return interaction

    def said(self, interaction):
        """The ephemeral reply, and every public line posted after it."""
        reply = interaction.response.send_message.await_args
        public = [
            call.args[0] for call in interaction.followup.send.await_args_list
            if call.args
        ]
        return reply, public

    async def test_the_clicker_is_told_the_new_card_and_the_channel_is_not(
        self,
    ) -> None:
        cog, game = self.build()
        first, second = "low_pass", "high_pass"

        await self.click(cog, game, first)
        interaction = await self.click(cog, game, second)

        reply, public = self.said(interaction)
        name = cog.engine.maneuver_name(second)
        self.assertEqual(
            reply.args[0], f"You changed your maneuver to **{name}**.",
        )
        self.assertTrue(reply.kwargs["ephemeral"])
        self.assertTrue(
            any("has changed their maneuver." in line for line in public),
            public,
        )
        self.assertFalse(any(name in line for line in public), public)
        self.assertEqual(
            cog.engine.load_match_state(game).offense_maneuver, second,
        )

    async def test_a_first_pick_still_reads_as_a_pick(self) -> None:
        cog, game = self.build()

        interaction = await self.click(cog, game, "low_pass")

        reply, public = self.said(interaction)
        self.assertEqual(
            reply.args[0],
            f"You chose **{cog.engine.maneuver_name('low_pass')}**.",
        )
        self.assertTrue(
            any("has picked their maneuver." in line for line in public),
            public,
        )


if __name__ == "__main__":
    unittest.main()

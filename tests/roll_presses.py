"""
Pressing a roll once nobody is still deciding on Overdrive.

A roll with a Cyborg's Overdrive or Boost still open waits on that
Cyborg's coach (Law 20.3.5, `RollOptions.undecided_sides`) -- the
attacker first, then the defender -- until each declares or passes;
Roll is refused until then.

A test whose subject is not Overdrive -- the dice, the verdict, the
injury queue -- presses Roll with `press_roll`, which has every coach
still to decide pass first, in turn and through the service, the way
a click on Pass on Overdrive answers. The die is then thrown by the
interaction the test hands in and goes on to read.
"""

from __future__ import annotations

from d12ball.flow.driver import Action
from d12ball.prompts import ROLL_KINDS, pending_prompt


def pass_on_overdrive(cog, game) -> None:
    """Every coach the roll is waiting on passes, attacker first."""
    while True:
        match = cog.engine.load_match_state(game)
        prompt = pending_prompt(cog.engine, game, match)
        if (
            prompt is None
            or prompt.kind not in ROLL_KINDS
            or prompt.options is None
            or prompt.options.deciding_side is None
        ):
            return
        result = cog.apply_action(
            game,
            Action(
                prompt.kind, "pass",
                {"side": prompt.options.deciding_side.value},
            ),
        )
        assert not result.refused, result.refusal


async def press_roll(view, interaction) -> None:
    """`view.roll(interaction)`, once nobody is deciding on Overdrive."""
    pass_on_overdrive(view.cog, view.cog.games[view.game_id])
    await view.roll(interaction)

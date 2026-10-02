"""
Pressing a roll as the coaches it waits on.

A roll with a Cyborg's Overdrive or Boost still open waits on that
Cyborg's coach (Law 20.3.5, `RollOptions.deciding_sides`): their Roll
says they are done, and anybody else's is refused. Where both coaches
have one open, the first press makes that side ready and the second
throws the die.

A test whose subject is not who presses Roll -- the dice, the verdict,
the injury queue -- presses it with `press_roll`, as every coach the
die waits on in turn, the way they would at the table. The die is
thrown by the last press, which is the interaction the test hands in
and goes on to read; the presses before it are their own.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from d12ball.prompts import ROLL_KINDS, pending_prompt


async def press_roll(view, interaction) -> None:
    """
    `view.roll(interaction)`, pressed by whoever the die waits on --
    the interaction's own user where it waits on nobody.
    """
    cog = view.cog
    game = cog.games[view.game_id]
    match = cog.engine.load_match_state(game)
    prompt = pending_prompt(cog.engine, game, match)
    waiting = (
        prompt.options.deciding_sides
        if prompt is not None
        and prompt.kind in ROLL_KINDS
        and prompt.options is not None
        else ()
    )
    coaches = [cog.engine.side_controller_id(game, side) for side in waiting]
    for coach_id in coaches[:-1]:
        await view.roll(_press(coach_id))
    if coaches:
        interaction.user = SimpleNamespace(
            id=coaches[-1],
            display_name=getattr(interaction.user, "display_name", ""),
        )
    await view.roll(interaction)


def _press(user_id: int) -> SimpleNamespace:
    """A press that only says its side is ready, and is answered by a reply."""
    send = mock.AsyncMock(return_value=SimpleNamespace(id=998))
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id, display_name=""),
        guild=None,
        channel=SimpleNamespace(send=send),
        followup=SimpleNamespace(send=send),
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
            is_done=lambda: False,
        ),
        edit_original_response=mock.AsyncMock(),
        data={},
        extras={},
    )

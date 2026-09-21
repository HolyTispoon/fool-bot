"""
The tutorial's Continue gates: a note held up until the coach presses
on, and what pressing on runs.

Two or more plain-text messages posted back to back with nothing to
click between them are exactly what gets scrolled past in a busy
channel, so a tutorial note with a live prompt behind it -- the
lesson before a turn, the card note before the maneuver hands, the
speed note before the speed choice, the coaching explainer before the
window -- is held behind a single Continue button. Until Phase 6 of
docs/design/model-discord-split.md that was `D12Ball.post_tutorial_note`: the
continuation was a closure on a `TutorialContinueView`, the view was
never registered, and a restart left a dead button. It was also a
click the model could not see -- `pending_prompt` read the position
underneath the note, which is exactly what it was before the note went
up, so a resume put the thing the note explains up *without* the
note, and a second frontend had no way to know the game was waiting.

**The gate is a prompt** (`PromptKind.TUTORIAL_CONTINUE`), and what it
holds is written down on the game record (`D12BallGame.tutorial_gate`):
which note, and the `FollowOn` to run once the coach continues, or
`None` where what follows is simply the question the position already
asks. That second shape is the common one and the reason the asks in
`pending_prompt` for the maneuver pick and the speed choice are the
live wording rather than a bare "Choose:" -- after the note, the game
shows what it is waiting on, and it has to be the same question the
note was put in front of.

**A gate's continuation must not raise the same gate again.** That is
why the turn prompt is two steps (`SEND_TURN_PROMPT` stages the beat
and may gate; `START_TURN` is what runs after), and why the coaching
explainer sets `tutorial_coaching_explained` *before* it gates.
"""

from __future__ import annotations

from typing import Optional

from d12ball import tutorial
from d12ball.components import MatchState
from d12ball.engine import RulesEngine
from d12ball.flow.result import FollowOn, StepResult
from d12ball.game import D12BallGame
from d12ball.prompts import PendingPrompt, PromptKind, pending_prompt


def hold_behind_note(
    game: D12BallGame,
    note: str,
    then: Optional[FollowOn],
    lead_in: str = "",
) -> StepResult:
    """
    Put `note` up behind a Continue button, remembering `then` as what
    the click runs -- or nothing, for a note whose continuation is the
    question the position already asks.

    `lead_in` is whatever was said before the note by the step that is
    now gating, and it goes *above* the note in the same message: the
    event, then the lesson about it, then (after the click) the
    question. It used to ride inside the prompt after the click, which
    put the lesson in front of the thing it was explaining.
    """
    game.tutorial_gate = {
        "note": note,
        "then": then.to_dict() if then is not None else None,
    }
    text = tutorial.note_text(game, note)
    return StepResult(
        next=PendingPrompt(
            PromptKind.TUTORIAL_CONTINUE,
            f"{lead_in}\n\n{text}" if lead_in else text,
        ),
    )


def continue_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    The Continue button, pressed: take the note down and run what it
    was holding up.

    Raises `ValueError` when no note is up, which is a stale click on
    a button a restart re-attached; `driver.answer` has already refused
    it by kind before this is reached, so the raise is for a caller
    that came another way.
    """
    gate = game.tutorial_gate
    if not gate:
        raise ValueError("There is no note to continue from.")
    game.tutorial_gate = None

    then = gate.get("then")
    if then:
        return StepResult(next=FollowOn.from_dict(then))
    return StepResult(next=pending_prompt(engine, game, match))

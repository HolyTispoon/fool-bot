"""
The turn's flow, with no Discord in it.

A flow step takes the engine and the match, changes the match, and
returns a `StepResult`: the narration, whether the board moved, and
what happens next. It sends nothing and saves nothing -- the frontend
posts, and the driver persists. See "The model and the Discord layer"
in CLAUDE.md, and docs/design/model-discord-split.md for what has moved here
and what has not yet.

`from d12ball.flow import StepResult` is the way in; the submodules are
grouped the way `cogs/d12ball/` groups the code they came from.
"""

from d12ball.flow.result import FollowOn, FollowOnStep, Headline, StepResult

__all__ = ["FollowOn", "FollowOnStep", "Headline", "StepResult"]

"""
The whole of a Codex turn, with no Discord in it: `result` (what a step
hands back), `turn` (the phases nobody chooses), `actions` (the main
phase), `combat` (an attack) and `driver` (the loop and the answers).
A step changes the match and says what happened; it sends nothing and
saves nothing (docs/design/model-discord-split.md, principle 4).

Only `result`'s types are re-exported here: `codex.prompts` imports them
and the driver imports the prompts, so the package itself must not
import the driver.
"""

from codex.flow.result import FollowOn, FollowOnStep, Headline, StepResult

__all__ = ["FollowOn", "FollowOnStep", "Headline", "StepResult"]

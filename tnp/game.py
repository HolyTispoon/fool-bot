"""
`RuleRefusal`, the one exception a TNP rule says no with -- the leaf
the rest of the model imports, as `codex.game` and `d12ball.game` hold
theirs. The game record itself comes with the lobby (step 5 of
docs/tnp-bot.md).
"""

from __future__ import annotations

from typing import Optional


class RuleRefusal(ValueError):
    """
    The position refusing what was chosen, with the sentence to show.

    The driver lets this through as a `Refusal` and nothing else, so a
    frontend shows it and a bug propagates. **`cite` is the section of
    docs/tnp-rules.md that says no** ("TNP 6.5"), where one does.
    """

    def __init__(self, message: str, cite: Optional[str] = None) -> None:
        super().__init__(message)
        self.cite = cite

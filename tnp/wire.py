"""
How the TNP model's values are written down for a frontend that talks
over a wire: `jsonable`, `gamekit.wire`'s, re-exported. One-way, and not
a save: the save format is `MatchState.to_dict` (docs/design/codex.md,
"What the two games share").
"""

from gamekit.wire import jsonable

__all__ = ["jsonable"]

"""
How the Codex model's values are written down for a frontend that talks
over a wire -- copied from `d12ball/wire.py`, whose docstring says why.

**A `to_dict` here is not a save**: the save format is
`MatchState.to_dict`. This is the other direction -- a step's result and
the prompt inside it, handed to a client as JSON and read back only as
an `Action` (`Action.from_dict`). One-way on purpose, so a web or Godot
client later costs nothing here (docs/codex-bot.md, "What the repository
gives"). Nothing hidden is on it: a prompt carries what its asked player
may see, and a frontend sends it to them alone.

`jsonable` is the one conversion, so a value that is not JSON raises
here rather than reaching a client as somebody's repr.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping


def jsonable(value: Any) -> Any:
    """
    `value` as JSON: an enum by its value, a mapping and a sequence
    through this function again, anything with a `to_dict` by it. An
    unrecognised value raises.
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Enum):
        return jsonable(value.value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted(jsonable(item) for item in value)
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    raise TypeError(
        f"{type(value).__name__} has no place on the wire: give it a "
        "to_dict, or leave it out of what a frontend is handed."
    )

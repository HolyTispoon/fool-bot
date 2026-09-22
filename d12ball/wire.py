"""
How the model's own values are written down for a frontend that talks
over a wire.

**A `to_dict` here is not a save.** The save format is
`MatchState.to_dict` and `gamesaves/d12ball/storage.py`, and it is a
contract nothing may change (CLAUDE.md, principle 6). What this module
is about is the other direction: a `GameResult` and the
`PendingPrompt` inside it, handed to a web page as JSON and read back
as an `Action` -- finding 10 of docs/web-app.md, and the last thing
the migration to ARCHITECTURE.md owes the second frontend.

**It is one-way, on purpose.** A prompt, a narration group and a roll's
numbers are *written*; only an `Action` is read back (`Action.from_dict`).
Nothing a frontend sends is trusted to describe the position: an action
names the question it answers and carries what the person chose, and
the driver checks both against the match (`d12ball.flow.driver.answer`).
A `from_dict` on a prompt would be the beginning of a frontend telling
the model what it is waiting on.

`jsonable` is the one conversion, so a value that is not JSON raises
here rather than reaching a frontend as `"<TeamSide.HOME: 'home'>"`.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping


def jsonable(value: Any) -> Any:
    """
    `value` as JSON: an enum by its value, a mapping and a sequence
    through this function again, anything with a `to_dict` by it.

    **An unrecognised value raises.** The alternative -- `str(value)` as
    a fallback -- is how a field comes to reach a page as the repr of an
    object nobody meant to send, and a wire format that quietly does
    that is one nobody can read from the other end.
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

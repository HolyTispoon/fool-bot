"""
How the model's own values are written down for a frontend that talks
over a wire.

`jsonable`, the one conversion, is `gamekit.wire`'s, shared with the
Codex bot's model (docs/design/codex.md, "What the two games share");
its docstring says why the conversion is one-way and why an
unrecognised value raises. It is re-exported here so every
`from d12ball.wire import jsonable` keeps working. The `to_dict` on
everything a `GameResult` carries is each class's own.

**A `to_dict` here is not a save.** The save format is
`MatchState.to_dict` and `gamesaves/d12ball/storage.py`, and it is a
contract nothing may change (CLAUDE.md, principle 6).
"""

from gamekit.wire import jsonable

__all__ = ["jsonable"]

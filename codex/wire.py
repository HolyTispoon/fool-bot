"""
How the Codex model's values are written down for a frontend that talks
over a wire: `jsonable`, `gamekit.wire`'s, shared with D12 Ball's model
(docs/design/codex.md, "What the two games share") and re-exported here.

**A `to_dict` here is not a save**: the save format is
`MatchState.to_dict`. This is the other direction -- a step's result and
the prompt inside it, handed to a client as JSON and read back only as
an `Action` (`Action.from_dict`). One-way on purpose, so a web or Godot
client later costs nothing here (docs/codex-bot.md, "What the repository
gives"). Nothing hidden is on it: a prompt carries what its asked player
may see, and a frontend sends it to them alone.
"""

from gamekit.wire import jsonable

__all__ = ["jsonable"]

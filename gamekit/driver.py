"""
The two refusals both games' drivers give in the same words, whatever
the game (`d12ball.flow.driver`, `codex.flow.driver`, which re-export
them): each driver's own `STALE_CLICK` names what moved on for each of
its prompt kinds, and these are what is left over.
"""

#: The sentence for a kind a driver's `STALE_CLICK` does not name.
MOVED_ON = "That answers a question this match has moved on from."

#: What an action arriving while the bot owes a step is told -- a
#: click on a prompt a restart left up over a half-run cascade, a web
#: request between two of the bot's own steps. The step is the game's
#: `owed_step`'s and its `GameService.resume` runs it.
STEP_OWED = (
    "Nothing is being asked yet: the game still has a step of its own "
    "to run here."
)

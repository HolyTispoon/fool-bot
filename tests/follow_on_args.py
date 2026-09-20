"""
Reading an argument off a recorded call to a spine step, through the
step's own signature rather than off `call.args`.

**Why this exists is the model/Discord split.** A step that has moved
into `d12ball/flow/` ends by naming a spine step the cog still
dispatches, and `D12Ball.dispatch_step_result` calls it
`method(interaction, game, match, lead_in=..., **kwargs)` -- so every
argument a follow-on carries arrives **by keyword**, where the cog used
to hand it over positionally. A pre-existing assertion reading
`await_args.args[3]` then breaks on a move that changed nothing about
what the call means.

Rank D2 of docs/model-discord-split.md wrote the lesson down -- the fix
is the assertion, not the call -- and ranks D1 and O3 met it twice
more. Binding the recorded call to the real method's signature answers
for both shapes at once, so a test does not have to know which side of
the seam its subject is on this week.

`tests/follow_on_args.py` rather than a copy per module: the same
three lines had been written out in three test files by the time the
front half of Phase 4 needed a fourth, and each copy carried a comment
listing the others.
"""

import inspect


def follow_on_argument(method, call, name: str):
    """
    The value `name` was passed as, in `call`, read through `method`'s
    signature.

    `method` is the **unbound** function off the class
    (`D12Ball.begin_loose_ball`), so `None` stands in for `self` --
    the binding only has to be well formed, never callable.
    """
    return inspect.signature(method).bind(
        None, *call.args, **call.kwargs,
    ).arguments[name]

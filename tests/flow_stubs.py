"""
Stopping a turn's chain at a named step, from either side of the seam.

A great many tests drive one step and assert what it hands off to, and
until Phase 6 of docs/model-discord-split.md there was one way to do
that: stub the cog method `D12Ball.follow_on_methods` names for the
`FollowOnStep` in question, and read its `await_args`. That worked
because the cog ran every follow-on.

`d12ball.flow.driver` runs some of them now (see `MODEL_STEPS`), and a
member it runs has no cog method to stub -- which is how sixty-odd
tests failed on a move that changed nothing a coach can see. **Where
the stub goes is a fact about the seam, not about the test**, so it is
answered here, once, rather than in each file: `chain_stops_at` puts
the stub on whichever side owns the step today, and a member moving
across the seam in a later phase changes this module and nothing else.

The recorder it yields is the stub itself. Its call is shaped like the
side it replaced -- a cog method is awaited with
`(interaction, game, match, lead_in=..., **kwargs)` and a driver step
is called with `(engine, game, match, lead_in=..., **kwargs)` -- so a
test reading arguments should use `arguments_of`, which normalises the
two, rather than indexing either.
"""

from __future__ import annotations

import contextlib
import inspect
from typing import Any, Iterator, Mapping
from unittest import mock

from cogs.d12ball import D12Ball
from d12ball.flow import FollowOnStep, StepResult
from d12ball.flow import driver


class _NameProbe:
    """
    A stand-in for the cog that answers every attribute with its own
    name, so `follow_on_methods` comes back as a table of *names*.

    The table is `{member: self.some_method}`, and a test needs the
    method's name to stub it. Reading `__name__` off the bound method
    works only on a cog nobody has stubbed yet -- and the recording
    tables stub the lot in `build_cog`, at which point `__name__` is a
    `Mock`. Asking a probe is what makes the mapping a fact about the
    cog rather than about the order a test does things in.
    """

    def __getattr__(self, name: str) -> str:
        return name


#: Which cog method each `FollowOnStep` the cog still dispatches names.
COG_METHOD_NAMES: Mapping[FollowOnStep, str] = dict(
    D12Ball.follow_on_methods(_NameProbe()),
)


#: The driver's table as it really is, taken once at import.
#: `chain_stops_at` patches `driver.MODEL_STEPS` while a test runs, so
#: anything wanting the *real* step -- a signature to read a recorded
#: call through -- has to have kept it.
REAL_MODEL_STEPS = dict(driver.MODEL_STEPS)


def runs_in_the_model(member: FollowOnStep) -> bool:
    """Whether the driver's loop runs this step rather than the cog."""
    return driver.runs(member)


@contextlib.contextmanager
def chain_stops_at(
    cog: Any,
    member: FollowOnStep,
    result: StepResult | None = None,
) -> Iterator[Any]:
    """
    Stub whatever runs `member`, so a chain reaching it stops there.

    `result` is what the stub hands back where the step is the
    driver's -- a real step returns a `StepResult` and the loop reads
    its `next`, so a stub that returned a `Mock` would be walked into.
    The default is a result that says nothing moved and nothing
    follows, which is the "stop here" a cog-side `AsyncMock` gave for
    free.
    """
    if runs_in_the_model(member):
        recorder = mock.Mock(return_value=result or StepResult())
        patched = dict(driver.MODEL_STEPS)
        patched[member] = recorder
        with mock.patch.object(driver, "MODEL_STEPS", patched):
            yield recorder
        return

    name = COG_METHOD_NAMES[member]
    recorder = mock.AsyncMock()
    original = getattr(cog, name, None)
    setattr(cog, name, recorder)
    try:
        yield recorder
    finally:
        if original is not None:
            setattr(cog, name, original)


def arguments_of(recorder: Any) -> tuple[tuple[Any, ...], Mapping[str, Any]]:
    """
    The positional and keyword arguments a stub was called with,
    whichever side it was on.

    The leading three differ by side -- `(interaction, game, match)`
    against `(engine, game, match)` -- and every argument a step
    actually carries arrives by keyword (rank D2's lesson, in
    docs/model-discord-split.md), so a test wanting `distance_moved`
    or `lead_in` reads the mapping and never an index.
    """
    if not recorder.call_args_list:  # pragma: no cover - never reached
        raise AssertionError("the chain never reached that step")
    call = recorder.call_args_list[0]
    return call.args, call.kwargs


@contextlib.contextmanager
def every_step_stubbed(
    cog: Any,
    members: Any,
) -> Iterator[dict[FollowOnStep, Any]]:
    """
    Stub every one of `members`, each on the side that runs it, and
    hand back the recorders by member.

    This is `chain_stops_at` for the recording tables, which stub every
    step a rank can end on and then assert that exactly one of them was
    reached. The recorders come back keyed by `FollowOnStep` rather
    than by method name because the name is the cog's and half of them
    no longer have one.
    """
    stack = contextlib.ExitStack()
    recorders: dict[FollowOnStep, Any] = {}
    with stack:
        for member in members:
            recorders[member] = stack.enter_context(chain_stops_at(cog, member))
        yield recorders


def was_reached(recorder: Any) -> bool:
    """
    Whether a stub from `chain_stops_at` was called at all.

    **`call_args_list` and never `await_args_list`**: a driver-side
    stub is a plain `Mock`, whose `await_args_list` is an auto-created
    child mock and therefore truthy -- so a test asking that way reads
    every step as reached and passes nothing. An `AsyncMock` records
    into `call_args_list` as well, so one attribute answers both sides.
    """
    return bool(recorder.call_args_list)


def reached_once(recorder: Any) -> bool:
    """Whether a stub was called exactly once."""
    return len(recorder.call_args_list) == 1


def named_arguments(
    member: FollowOnStep,
    signature_of: Any,
    recorder: Any,
    plumbing: Any,
) -> dict:
    """
    One recorded call as named arguments, plumbing dropped.

    `signature_of` is the cog method the member used to name, which is
    still the signature a cog-side call is read through. A driver-side
    step is read through the flow function `MODEL_STEPS` holds and
    takes no `self`, which is the whole of the difference -- the
    arguments themselves are the same, because
    `dispatch_step_result` already passed every one of them by keyword
    (rank D2's lesson, in docs/model-discord-split.md).
    """
    call = (recorder.call_args_list)[0]
    if runs_in_the_model(member):
        bound = inspect.signature(
            REAL_MODEL_STEPS[member],
        ).bind(*call.args, **call.kwargs)
    else:
        bound = inspect.signature(signature_of).bind(
            None, *call.args, **call.kwargs,
        )
    dropped = set(plumbing) | {"engine"}
    return {
        name: value
        for name, value in bound.arguments.items()
        if name not in dropped
    }


def lead_in_of(recorder: Any) -> Any:
    """The `lead_in` a stub was called with, from either side."""
    call = (recorder.call_args_list)[0]
    return call.kwargs.get("lead_in")


@contextlib.contextmanager
def chain_records_at(
    cog: Any,
    member: FollowOnStep,
    calls: list,
    label: str | None = None,
) -> Iterator[Any]:
    """
    `chain_stops_at`, for a test recording the *order* things happen
    in rather than the arguments they happen with.

    Appends `label` (the member's cog method name by default) to
    `calls` when the step is reached, so an ordering assertion reads
    the same whichever side of the seam the step is on.
    """
    name = label or COG_METHOD_NAMES.get(member, member.name.lower())

    if runs_in_the_model(member):
        def record(*args: Any, **kwargs: Any) -> StepResult:
            calls.append(name)
            return StepResult()

        patched = dict(driver.MODEL_STEPS)
        patched[member] = record
        with mock.patch.object(driver, "MODEL_STEPS", patched):
            yield record
        return

    async def recorded(*args: Any, **kwargs: Any) -> None:
        calls.append(name)

    attribute = COG_METHOD_NAMES[member]
    original = getattr(cog, attribute, None)
    setattr(cog, attribute, recorded)
    try:
        yield recorded
    finally:
        if original is not None:
            setattr(cog, attribute, original)

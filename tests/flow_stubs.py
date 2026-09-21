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


#: The cog attribute each step the driver runs still answers to.
#:
#: Every one of them kept its cog method -- the driver calls the flow
#: function directly, but the method is an entry point in its own
#: right for a click or a test. The name is the member lower-cased for
#: all of them, which is asserted rather than assumed in
#: `tests/test_d12ball_package_shape.py`.
MODEL_STEP_ATTRIBUTES: Mapping[FollowOnStep, str] = {
    member: member.name.lower() for member in REAL_MODEL_STEPS
}


def _as_a_step(cog: Any, member: FollowOnStep, attribute: str) -> Any:
    """
    A sync shim over whatever the cog is holding under `attribute`.

    The driver calls its steps synchronously; a test's stub is an
    `AsyncMock` and `assert_awaited_once` only counts an *await*. So
    the shim drives the coroutine the mock returns to completion,
    which is what an `await` would have done -- and the test's
    existing `assert_awaited_*` reads true without being rewritten.
    Returns a `StepResult` that stops the loop, the way an
    `AsyncMock`'s cog method stopped the old chain.

    **The attribute is read when the step runs, not when the routing
    is installed.** Plenty of tests build the cog and then stub one
    more method on the way into the case they are about, and a
    routing that snapshotted the cog would miss exactly those. Where
    the attribute is not a stub the real step runs, so installing the
    routing costs a test that does not use it nothing.
    """

    real = REAL_MODEL_STEPS[member]

    def run(*args: Any, **kwargs: Any) -> StepResult:
        stub = getattr(cog, attribute, None)
        if not isinstance(stub, mock.AsyncMock):
            return real(*args, **kwargs)
        coroutine = stub(*args, **kwargs)
        try:
            coroutine.send(None)
        except StopIteration:
            pass
        return StepResult()

    return run


@contextlib.contextmanager
def driver_reaches_cog_stubs(cog: Any) -> Iterator[None]:
    """
    Point the driver's steps at whatever stubs are already on the cog.

    Dozens of tests build a cog with `cog.some_step = AsyncMock()` and
    assert on it afterwards. Phase 6 moved some of those steps into
    `d12ball.flow.driver`, which never looks at the cog -- so the stub
    is still there and nothing reaches it. This wraps the drive and
    routes the loop back through it, which keeps the assertions those
    tests were written with and changes only where the stub is
    plugged in.

    A test asserting on the *arguments* should prefer
    `chain_stops_at`: the two sides differ in their first parameter
    (`interaction` against `engine`), and this shim does not pretend
    otherwise.
    """
    patched = dict(driver.MODEL_STEPS)
    for member, attribute in MODEL_STEP_ATTRIBUTES.items():
        patched[member] = _as_a_step(cog, member, attribute)
    with mock.patch.object(driver, "MODEL_STEPS", patched):
        yield


@contextlib.contextmanager
def injury_queue_stops_the_chain(cog: Any) -> Iterator[Any]:
    """
    Stop a contest where it hands on to the injury tests it owes.

    A roll that settles a contest ends by queueing whatever injury
    tests it owes, and dozens of tests stop there -- "everything past
    the roll is mocked" -- by putting an `AsyncMock` on
    `cog.begin_injury_tests`. **Phase 6 moved that hand-off across the
    seam**: `d12ball.flow.rolls` calls
    `d12ball.flow.injuries.begin_injury_tests` itself now, so the cog
    method is no longer on the path and a stub on it is never reached.

    Which side runs it is a fact about the seam and not about the
    test, so it is answered here, once, exactly as `chain_stops_at`
    answers it for a `FollowOnStep`. The recorder it yields is the
    model-side stub; it is called `(engine, game, match, players,
    resume)` and hands back a `StepResult` that neither says nor names
    anything, which is the "stop here" the `AsyncMock` gave for free.
    """
    recorder = mock.Mock(return_value=StepResult())
    cog.begin_injury_tests = mock.AsyncMock()
    with mock.patch(
        "d12ball.flow.injuries.begin_injury_tests", recorder,
    ), mock.patch(
        "d12ball.flow.rolls.injuries.begin_injury_tests", recorder,
    ):
        yield recorder

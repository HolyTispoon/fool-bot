"""
Stopping a turn's chain at a named step.

A great many tests drive one step and assert what it hands off to, and
until Phase 6 of docs/design/model-discord-split.md there was one way to do
that: stub the cog method `D12Ball.follow_on_methods` named for the
`FollowOnStep` in question, and read its `await_args`. That worked
because the cog ran every follow-on.

`d12ball.flow.driver` runs every one of them now (see `MODEL_STEPS`),
and the cog's table is gone -- so a stub goes on the driver's table,
always. **Where the stub goes is a fact about the seam, not about the
test**, which is why it is answered here, once, rather than in each
file, and why the module kept its two-sided shape through the phases
that moved members one at a time: `chain_stops_at` put the stub on
whichever side owned the step that week, and a member moving across
the seam changed this module and nothing else. The cog side of it is
empty now and the helpers that told the two apart answer "the model"
for every member.

The recorder it yields is the stub itself, called with
`(engine, game, match, lead_in=..., **kwargs)`; a test reading
arguments should use `arguments_of` rather than indexing.

`driver_reaches_cog_stubs` is the other half: dozens of tests build a
cog with `cog.some_step = AsyncMock()` and assert on it afterwards, and
the cog keeps a thin entry point of that name for most steps. The
routing below points the driver's table at whatever stub a test has
put on the cog, so those assertions still read what they were written
to read.
"""

from __future__ import annotations

import contextlib
import inspect
from typing import Any, Iterator, Mapping
from unittest import mock

from d12ball.flow import FollowOnStep, StepResult
from d12ball.flow import driver


#: The driver's table as it really is, taken once at import.
#: `chain_stops_at` patches `driver.MODEL_STEPS` while a test runs, so
#: anything wanting the *real* step -- a signature to read a recorded
#: call through -- has to have kept it.
REAL_MODEL_STEPS = dict(driver.MODEL_STEPS)


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
    recorder = mock.Mock(return_value=result or StepResult())
    # Marked, so the cog-stub routing lets it through: a test that
    # asked for a recorder by member is reading it, whatever else
    # its cog builder stubbed. See `_as_a_step`.
    recorder._flow_recorder = True
    patched = dict(driver.MODEL_STEPS)
    patched[member] = recorder
    with mock.patch.object(driver, "MODEL_STEPS", patched):
        yield recorder


def arguments_of(recorder: Any) -> tuple[tuple[Any, ...], Mapping[str, Any]]:
    """
    The positional and keyword arguments a stub was called with,
    whichever side it was on.

    The leading three differ by side -- `(interaction, game, match)`
    against `(engine, game, match)` -- and every argument a step
    actually carries arrives by keyword (rank D2's lesson, in
    docs/design/model-discord-split.md), so a test wanting `distance_moved`
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
    (rank D2's lesson, in docs/design/model-discord-split.md).
    """
    call = (recorder.call_args_list)[0]
    bound = inspect.signature(
        REAL_MODEL_STEPS[member],
    ).bind(*call.args, **call.kwargs)
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
    name = label or member.name.lower()

    def record(*args: Any, **kwargs: Any) -> StepResult:
        calls.append(name)
        return StepResult()

    record._flow_recorder = True
    patched = dict(driver.MODEL_STEPS)
    patched[member] = record
    with mock.patch.object(driver, "MODEL_STEPS", patched):
        yield record


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

    # Whatever the table holds *now* -- the real step, a recorder a
    # `chain_stops_at` around this routing already put there, or the
    # routing of another cog whose context is still open (a test that
    # `enterContext`s one per subtest stacks them). Reading
    # `REAL_MODEL_STEPS` here would silently undo a recorder. The
    # precedence is: a recorder, then this cog's own stub, then
    # whatever the table held -- a test that asked for a recorder by
    # member is reading it, and a test that stubbed its own cog is
    # reading that rather than the previous subtest's.
    real = driver.MODEL_STEPS[member]
    recorded = getattr(real, "_flow_recorder", False)

    def run(*args: Any, **kwargs: Any) -> StepResult:
        stub = getattr(cog, attribute, None)
        if recorded or not isinstance(stub, mock.AsyncMock):
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


def arm_cog_stub_routing() -> None:
    """
    Make every dispatch on every test cog reach the stubs a test has
    put on it, without each test asking.

    Before Phase 6 collapsed the cog's dispatch table, a test that
    stubbed `cog.begin_run_back = AsyncMock()` stopped the chain there
    for free: the cog awaited its own attribute. The driver never
    looks at the cog, so the same stub is now reached only through
    `driver_reaches_cog_stubs` -- and fifty-odd cog builders across
    the suite were written against the old behaviour. Rather than
    wrap each of them, `D12Ball.dispatch_step_result` is wrapped once,
    at the class, so the routing is in force for the duration of every
    dispatch on any cog. A cog with no stubs on it runs the real steps,
    exactly as `_as_a_step` promises.

    Armed by importing this module, the way `save_patches` arms the
    stray-save guard: `unittest discover` imports every test module
    before it runs any test, and `save_patches` -- which nearly every
    cog test imports -- imports this one.
    """
    from cogs.d12ball import D12Ball

    def wrap_async(name: str) -> None:
        original = getattr(D12Ball, name)
        if getattr(original, "_routes_cog_stubs", False):
            return

        async def routed(self, *args, **kwargs):
            with driver_reaches_cog_stubs(self):
                return await original(self, *args, **kwargs)

        routed._routes_cog_stubs = True
        routed.__wrapped__ = original
        setattr(D12Ball, name, routed)

    def wrap_sync(name: str) -> None:
        original = getattr(D12Ball, name)
        if getattr(original, "_routes_cog_stubs", False):
            return

        def routed(self, *args, **kwargs):
            with driver_reaches_cog_stubs(self):
                return original(self, *args, **kwargs)

        routed._routes_cog_stubs = True
        routed.__wrapped__ = original
        setattr(D12Ball, name, routed)

    # The two cog methods that run the service's loop: the bot's own
    # steps go through `dispatch_step_result`, a click through
    # `apply_action`. Both are wrapped at the class so the routing is
    # in force for the duration of every run on any cog.
    wrap_async("dispatch_step_result")
    wrap_sync("apply_action")
    # The recovery and setup entry points run the service too.
    wrap_async("resume_game")
    wrap_async("begin_setup_coaching")
    wrap_async("send_turn_prompt")


arm_cog_stub_routing()

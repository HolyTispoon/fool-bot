"""
Stopping the cog package and the service writing to disk during a test.

`from ... import save_games` binds the name into each module that
saves, so a patch on the package reaches none of them, silently: the
patch still applies, the test still passes, and the real save runs and
writes `data/d12ball_games.json`. `suppressed_cog_saves` patches every
module that binds it -- the cog mixins that write the game record, and
the service, where every click's one match save is -- rather than
asking each call site to know which. Every one of those patches is pure
suppression, never bound with `as` or asserted on, so there is nothing
here for a caller to inspect. No view saves.

`tests/test_d12ball_package_shape.py` is what keeps the lists honest:
it fails if a module starts importing `save_games` and is not named
here.

And a call site that forgets one of these entirely is what
`guard_stray_saves` at the foot of this file catches -- see the
reasoning there.
"""

import contextlib
import importlib
from unittest import mock

# The view submodules that call `save_games` themselves. **None**: a
# view changes the record through `GameService`, whose save
# `suppressed_cog_saves` reaches. The list stays so the package-shape
# test keeps proving it empty -- a view that starts binding `save_games`
# again fails the suite rather than writing `data/d12ball_games.json`
# during it.
SAVING_VIEW_MODULES = ()


# The cog mixins that call `save_games`. All six do: it is how a turn
# is written down, and every phase of a turn writes.
SAVING_COG_MODULES = (
    "cogs.d12ball.core",
    "cogs.d12ball.effects",
    "cogs.d12ball.periods",
    "cogs.d12ball.presentation",
    "cogs.d12ball.slash_commands",
)

# The service is where the one save per click lives (ARCHITECTURE.md,
# part 2), so every cog test that suppresses saves has to reach it.
SAVING_SERVICE_MODULES = (
    "gamesaves.d12ball.service",
)


@contextlib.contextmanager
def suppressed_cog_saves():
    """Keep every cog mixin's `save_games`, and the service's, off the
    disk."""
    with contextlib.ExitStack() as stack:
        for module in (*SAVING_COG_MODULES, *SAVING_SERVICE_MODULES):
            stack.enter_context(mock.patch(f"{module}.save_games"))
        yield


# The cog mixins that call `add_full_image_button`. Tests mock it for
# the same reason they mock the saves: it is an extra Discord edit that
# no assertion in them is about.
#
# It was every mixin until the five distance prompts moved onto one
# `send_field_prompt`, which took `cogs.d12ball.effects`' only
# call with them -- and a `mock.patch` of a name a module no longer
# binds is an AttributeError, not a no-op, so this is its own list
# rather than `SAVING_COG_MODULES`.
# `tests/test_d12ball_package_shape.py` fails if the two come apart.
LINKING_COG_MODULES = (
    "cogs.d12ball.core",
    "cogs.d12ball.periods",
    "cogs.d12ball.presentation",
    "cogs.d12ball.slash_commands",
)


@contextlib.contextmanager
def suppressed_full_image_links():
    """Keep every cog mixin's `add_full_image_button` off the wire."""
    with contextlib.ExitStack() as stack:
        for module in LINKING_COG_MODULES:
            stack.enter_context(
                mock.patch(f"{module}.add_full_image_button", mock.AsyncMock())
            )
        yield


# `cogs/debug.py` binds `save_games` too, and belongs to neither
# package -- `/debug reset_channels` saves the games it clears the
# channels of. Nothing in either list above would ever name it, so the
# guard below would have one binding it could not see.
SAVING_OTHER_MODULES = (
    "cogs.debug",
)

# Every module in the bot that holds a `save_games` of its own. This is
# what the guard arms; the two lists above are what a test suppresses.
SAVING_MODULES = (
    *SAVING_VIEW_MODULES,
    *SAVING_COG_MODULES,
    *SAVING_SERVICE_MODULES,
    *SAVING_OTHER_MODULES,
)


class StraySaveError(AssertionError):
    """A test reached the real `save_games` without suppressing it."""


def refuse_stray_save(*args, **kwargs):
    raise StraySaveError(
        "This test reached the real save_games and would have written "
        "data/d12ball_games.json. Wrap the call in suppressed_cog_saves() "
        "from tests/save_patches.py, which reaches the service's save."
    )


def guard_stray_saves() -> None:
    """
    Make a forgotten suppression fail the test that forgot it.

    The failure this exists for is silent by construction. A patch on
    the wrong binding still applies, so the `with` block succeeds and
    the assertions after it pass -- and the real save runs underneath,
    writing `data/d12ball_games.json`, which on a developer's machine
    is the bot's own saved games. Nineteen call sites were doing that,
    and the only way anybody found out was replacing the real function
    with a recorder and reading the stack of every caller.

    So the guard replaces the binding rather than watching it: a stray
    save raises where it happens, naming the test that owes the
    suppression, instead of being discovered months later by a script.
    Nothing in the packages catches a broad exception, so it lands in
    the test.

    Armed by importing this module, which is enough for the whole run:
    `unittest discover` imports every test module before it runs any
    test, and twenty-six of them import this one -- so the nine that
    exercise the cog without importing it are covered too. It arms the
    modules' own bindings and never `gamesaves.d12ball.storage`
    itself, which is what leaves `tests/test_game_storage.py` -- the
    one place that means to reach the disk, and does it through a
    `GAMES_FILE` pointed at a tempdir -- working untouched.

    `mock.patch` restores whatever it replaced, so a suppression
    helper puts the guard back on its way out.
    """
    for module in SAVING_MODULES:
        setattr(
            importlib.import_module(module), "save_games", refuse_stray_save,
        )


guard_stray_saves()

# The other import-time arming a cog test needs: every dispatch on a
# test cog reaches the step stubs the test put on it. See
# `flow_stubs.arm_cog_stub_routing`.
import flow_stubs  # noqa: E402,F401

"""
Stopping the view package writing to disk during a test.

`cogs/d12ball_views` used to be one module, so one
`suppressed_view_saves()` covered every view in the
game. It is a package now, and `from ... import save_games` binds the
name into each submodule -- so patching the package reaches none of
them, silently: the patch still applies, the test still passes, and the
real save runs and writes `data/d12ball_games.json`.

Three submodules import it, and a test exercising two views can need
two of them, so this patches all three rather than asking each call
site to know which. Every one of those forty-odd patches was pure
suppression -- not one was bound with `as` or asserted on -- so there
is nothing here for a caller to inspect.

`tests/test_d12ball_views_package.py` is what keeps this honest: it
fails if a fourth submodule starts importing `save_games` and is not
named here.
"""

import contextlib
from unittest import mock

# The view submodules that call `save_games` themselves. Views not
# listed here save through `self.cog.persist`, which is patched at
# `cogs.d12ball.save_games` by the same call sites.
SAVING_VIEW_MODULES = (
    "cogs.d12ball_views.setup",
    "cogs.d12ball_views.turn",
    "cogs.d12ball_views.loose_ball",

)


@contextlib.contextmanager
def suppressed_view_saves():
    """Keep every view's own `save_games` off the disk."""
    with contextlib.ExitStack() as stack:
        for module in SAVING_VIEW_MODULES:
            stack.enter_context(mock.patch(f"{module}.save_games"))
        yield

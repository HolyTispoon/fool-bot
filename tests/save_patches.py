"""
Stopping the view and cog packages writing to disk during a test.

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

`cogs/d12ball` went the same way and needs the same answer -- all six
of its mixins call `save_games`, where the single module needed one
patch.

`tests/test_d12ball_package_shape.py` is what keeps both honest: it
fails if a submodule starts importing `save_games` and is not named
here.
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


# The cog mixins that call `save_games`. All six do: it is how a turn
# is written down, and every phase of a turn writes.
SAVING_COG_MODULES = (
    "cogs.d12ball.core",
    "cogs.d12ball.effects",
    "cogs.d12ball.turnovers",
    "cogs.d12ball.periods",
    "cogs.d12ball.presentation",
    "cogs.d12ball.slash_commands",
)


@contextlib.contextmanager
def suppressed_cog_saves():
    """Keep every cog mixin's `save_games` off the disk."""
    with contextlib.ExitStack() as stack:
        for module in SAVING_COG_MODULES:
            stack.enter_context(mock.patch(f"{module}.save_games"))
        yield


# `add_full_image_button` is imported by all six mixins too. Tests mock
# it for the same reason they mock the saves: it is an extra Discord
# edit that no assertion in them is about.
@contextlib.contextmanager
def suppressed_full_image_links():
    """Keep every cog mixin's `add_full_image_button` off the wire."""
    with contextlib.ExitStack() as stack:
        for module in SAVING_COG_MODULES:
            stack.enter_context(
                mock.patch(f"{module}.add_full_image_button", mock.AsyncMock())
            )
        yield

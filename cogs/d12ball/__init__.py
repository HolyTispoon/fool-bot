"""
D12 Ball's cog: every slash command, and the game flow behind them.

One class of 217 methods over 10,087 lines is what this package
replaced, split along the section banners the file already carried.
The parts are mixins rather than collaborator objects for one reason:
these methods genuinely co-operate through the cog's own state and
call each other by the hundred, so `self.foo(...)` has to keep working
across every seam. Turning those into explicit dependencies is a far
larger change and a different one.

The command module is `slash_commands` rather than `commands`: a
submodule of this package binds its own name into this namespace, so
`commands.py` would quietly shadow `discord.ext.commands` right where
`commands.GroupCog` is read.

`D12Ball` is assembled here and nowhere else. The mixin order is the
order the file read in, and carries no resolution: no method is
defined twice, which `tests/test_d12ball_cog_package.py` is what
checks. `commands.GroupCog` comes last, so the mixins sit ahead of it
in the MRO -- discord.py collects commands by walking the whole MRO
(`CogMeta.__new__`), so a command defined on a mixin is registered
exactly as one defined here would be.

Everything the single module exposed is re-exported, so
`from cogs.d12ball import D12Ball` -- and `HIGH_PASS_CONTEST_HEADLINE`,
which the tests import -- go on working unchanged.
"""

from discord.ext import commands

from cogs.d12ball_helpers import (
    HIGH_PASS_CONTEST_HEADLINE,
    LOGGER,
)
from d12ball.engine import (
    FULL_TIME_STAGES,
    HALFTIME_STAGES,
    LEGACY_HALFTIME_STAGES,
    SETUP_STAGES,
)

from cogs.d12ball.slash_commands import CommandsMixin
from cogs.d12ball.core import CoreMixin
from cogs.d12ball.effects import ManeuverEffectsMixin
from cogs.d12ball.periods import PeriodMixin
from cogs.d12ball.presentation import PresentationMixin
from cogs.d12ball.turnovers import TurnoverMixin


class D12Ball(
    CoreMixin,
    ManeuverEffectsMixin,
    TurnoverMixin,
    PeriodMixin,
    PresentationMixin,
    CommandsMixin,
    commands.GroupCog,
    group_name="d12ball",
    group_description="Play D12 Ball -- one game per channel.",
):
    """
    A Discord cog running games of D12 Ball, one per channel.

    The body of this class is its parts -- see the module docstring.

    `group_description` is passed explicitly because discord.py falls
    back to this docstring for it, and Discord refuses a command group
    description over 100 characters -- which is a failed `tree.sync()`
    out of `setup_hook`, so the bot does not start at all. The single
    module carried no docstring here, so the split was what first gave
    the group one.
    """


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(D12Ball(bot))


__all__ = [
    "D12Ball",
    "setup",
    "LOGGER",
    "HIGH_PASS_CONTEST_HEADLINE",
    "SETUP_STAGES",
    "HALFTIME_STAGES",
    "FULL_TIME_STAGES",
    "LEGACY_HALFTIME_STAGES",
]

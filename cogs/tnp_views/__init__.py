"""
The TNP frontend's views (docs/design/tnp.md, "The lobby, the channel
and the table"): `base` (`SafeView`, which imports no sibling), `lobby`
(`LobbyView`) and `table` (`TableView`, **My board**). Every name is
re-exported here. No view saves.
"""

from cogs.tnp_views.base import ERROR_RECOVERY_ADVICE, SafeView, send_ephemeral
from cogs.tnp_views.lobby import LobbyView
from cogs.tnp_views.table import TableView

__all__ = ["ERROR_RECOVERY_ADVICE", "LobbyView", "SafeView", "TableView", "send_ephemeral"]

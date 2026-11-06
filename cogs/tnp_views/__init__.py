"""
The TNP frontend's views (docs/design/tnp.md, "The lobby, the channel
and the table"): `base` (`SafeView`, which imports no sibling), `lobby`
(`LobbyView`), `table` (`TableView`, **My board**) and `panel` (a
seat's controls, one view a turn prompt kind, `panel_view`). Every name is
re-exported here. No view saves.
"""

from cogs.tnp_views.base import ERROR_RECOVERY_ADVICE, SafeView, send_ephemeral
from cogs.tnp_views.lobby import LobbyView
from cogs.tnp_views.panel import (
    PANEL_TIMEOUT, ConquerPanelView, HarvestPanelView, PanelState, PanelView, PlanPanelView,
    TradePanelView, panel_view,
)
from cogs.tnp_views.table import TableView

__all__ = [
    "ConquerPanelView", "ERROR_RECOVERY_ADVICE", "HarvestPanelView", "LobbyView", "PANEL_TIMEOUT",
    "PanelState", "PanelView", "PlanPanelView", "SafeView", "TableView", "TradePanelView",
    "panel_view", "send_ephemeral",
]

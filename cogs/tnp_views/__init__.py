"""
The TNP frontend's views (docs/design/tnp.md, "The lobby, the channel
and the table"): `base` (`SafeView`, which imports no sibling), `lobby`
(`LobbyView`), `table` (`TableView`, **My board**), `panel` (a
seat's controls, one view a turn prompt kind, `panel_view`) and `battle`
(a battle's controls on its own message, one view a battle prompt kind,
`battle_view`) and `ending` (`ConcedeConfirmView`, `RematchView`). Every name is re-exported here. No view saves.
"""

from cogs.tnp_views.base import ERROR_RECOVERY_ADVICE, SafeView, send_ephemeral
from cogs.tnp_views.battle import BATTLE_VIEWS, BattleHeld, BattleView, battle_view
from cogs.tnp_views.ending import ConcedeConfirmView, RematchView
from cogs.tnp_views.lobby import LobbyView
from cogs.tnp_views.panel import (
    DEPLOYMENT, INFRASTRUCTURE, PANEL_TIMEOUT, ConquerPanelView, HarvestPanelView, PanelState, PanelView,
    PlanPanelView, TradePanelView, empty_steps, panel_view,
)
from cogs.tnp_views.table import TableView

__all__ = [
    "BATTLE_VIEWS", "BattleHeld", "BattleView", "battle_view",
    "ConcedeConfirmView", "RematchView",
    "ConquerPanelView", "DEPLOYMENT", "ERROR_RECOVERY_ADVICE", "INFRASTRUCTURE", "empty_steps", "HarvestPanelView", "LobbyView", "PANEL_TIMEOUT",
    "PanelState", "PanelView", "PlanPanelView", "SafeView", "TableView", "TradePanelView",
    "panel_view", "send_ephemeral",
]

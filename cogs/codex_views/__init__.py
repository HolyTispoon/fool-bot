"""
The Codex bot's `discord.ui.View` classes, one module per prompt a
player can be shown: `base` (`SafeView`, which imports no sibling, so the
package is a DAG), `lobby`, `turn_message`, and the panel's: `turn`
(`TurnPanelView`, `UndoConfirmView`), `patrol` (`PatrolView`) and `tech`
(`TechChoiceView`, `TechConfirmView`). Every name is re-exported here.
"""

from cogs.codex_views.base import (
    ERROR_RECOVERY_ADVICE,
    HelperConfirmationView,
    SafeView,
    send_ephemeral,
)
from cogs.codex_views.lobby import LobbyView
from cogs.codex_views.patrol import PatrolView, next_empty
from cogs.codex_views.tech import TechChoiceView, TechConfirmView, picks_listed
from cogs.codex_views.turn import (
    NOT_YOUR_PANEL,
    PanelView,
    TurnPanelView,
    UndoConfirmView,
    building_label,
    hand_numbers,
)
from cogs.codex_views.turn_message import (
    CODEX_VIEW_LABELS,
    NOT_YOUR_TABLE,
    CodexBrowser,
    TurnMessageView,
    hand_caption,
    hand_file,
    swap_label,
)

__all__ = [
    "CODEX_VIEW_LABELS",
    "CodexBrowser",
    "ERROR_RECOVERY_ADVICE",
    "HelperConfirmationView",
    "LobbyView",
    "NOT_YOUR_PANEL",
    "NOT_YOUR_TABLE",
    "PanelView",
    "PatrolView",
    "SafeView",
    "TechChoiceView",
    "TechConfirmView",
    "TurnMessageView",
    "TurnPanelView",
    "UndoConfirmView",
    "building_label",
    "hand_caption",
    "hand_file",
    "hand_numbers",
    "next_empty",
    "picks_listed",
    "send_ephemeral",
    "swap_label",
]

"""
The Codex bot's `discord.ui.View` classes, one module per prompt a
player can be shown: `base` (`SafeView`, which imports no sibling, so the
package is a DAG), `lobby` and `turn_message`. Every name is re-exported
here.
"""

from cogs.codex_views.base import ERROR_RECOVERY_ADVICE, SafeView, send_ephemeral
from cogs.codex_views.lobby import LobbyView
from cogs.codex_views.turn_message import (
    CODEX_VIEW_LABELS,
    NOT_YOUR_TABLE,
    CodexBrowser,
    TurnMessageView,
    hand_caption,
    hand_file,
    side_label,
    swap_label,
)

__all__ = [
    "CODEX_VIEW_LABELS",
    "CodexBrowser",
    "ERROR_RECOVERY_ADVICE",
    "LobbyView",
    "NOT_YOUR_TABLE",
    "SafeView",
    "TurnMessageView",
    "hand_caption",
    "hand_file",
    "send_ephemeral",
    "side_label",
    "swap_label",
]

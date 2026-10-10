"""
The Codex bot's `discord.ui.View` classes, one module per prompt a
player can be shown: `base` (`SafeView`, which imports no sibling, so the
package is a DAG), `lobby`, `turn_message`, `ending` (`ConcedeConfirmView`,
`RematchView`), and the panel's: `turn`
(`TurnPanelView`, `UndoView`, `UndoConfirmView`), `patrol` (`PatrolView`) and `tech`
(`TechChoiceView`, `TechConfirmView`, `TechGateView`). Every name is re-exported here.
"""

from cogs.codex_views.base import (
    ERROR_RECOVERY_ADVICE,
    HelperConfirmationView,
    SafeView,
    kept_pictures,
    picture_file,
    send_ephemeral,
)
from cogs.codex_views.ending import ConcedeConfirmView, RematchView
from cogs.codex_views.lobby import MODE_LABELS, LobbyView, MixedTeamView, hero_options
from cogs.codex_views.patrol import PatrolView, next_empty
from cogs.codex_views.tech import (
    TechChoiceView, TechConfirmView, TechGateView, deck_counted, picks_listed,
)
from cogs.codex_views.turn import (
    NOT_YOUR_PANEL,
    PanelButton,
    PanelView,
    TurnPanelView,
    UndoConfirmView,
    UndoView,
    building_label,
    hand_numbers,
)
from cogs.codex_views.turn_message import (
    NOT_YOUR_TABLE,
    CodexBrowser,
    HandView,
    TurnMessageView,
    codex_view_menu,
    deck_button,
    deck_caption,
    deck_file,
    hand_caption,
    hand_file,
    revealed_caption,
    revealed_files,
    side_label,
    swap_label,
)

__all__ = [
    "CodexBrowser",
    "ConcedeConfirmView",
    "ERROR_RECOVERY_ADVICE",
    "HandView",
    "HelperConfirmationView",
    "LobbyView",
    "MixedTeamView",
    "MODE_LABELS",
    "NOT_YOUR_PANEL",
    "NOT_YOUR_TABLE",
    "PanelButton",
    "PanelView",
    "PatrolView",
    "RematchView",
    "SafeView",
    "TechChoiceView",
    "TechConfirmView",
    "TechGateView",
    "TurnMessageView",
    "TurnPanelView",
    "UndoConfirmView",
    "UndoView",
    "building_label",
    "codex_view_menu",
    "deck_button",
    "deck_caption",
    "deck_counted",
    "deck_file",
    "hand_caption",
    "hand_file",
    "hand_numbers",
    "revealed_caption",
    "revealed_files",
    "hero_options",
    "kept_pictures",
    "next_empty",
    "picks_listed",
    "picture_file",
    "send_ephemeral",
    "side_label",
    "swap_label",
]

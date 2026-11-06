"""
`MatchState`, a TNP game as it stands, with its `SavedField` table --
**the save format is the contract from the first commit** (the
preamble's save rule): every field is in `MATCH_SAVED_FIELDS`, and a
saved key is never renamed.

Step 2 gives it the one thing it holds so far, the battle being fought
(`tnp.battle.BattleState`, saved whole under `battle`); step 4 adds the
turn around it -- the seats, the map, the phases -- each a new row with
its fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from gamekit.saved import SavedField
from tnp.battle import BattleState


def _battle_out(battle: Optional[BattleState]) -> Optional[dict]:
    return None if battle is None else battle.to_dict()


def _battle_in(data: Optional[Mapping[str, Any]]) -> Optional[BattleState]:
    return None if data is None else BattleState.from_dict(data)


@dataclass
class MatchState:
    #: The battle being fought, or the last one fought, until the March
    #: (step 4) puts its outcome on the map and clears it.
    battle: Optional[BattleState] = None

    def to_dict(self) -> dict:
        return {row.name: row.stored(getattr(self, row.name)) for row in MATCH_SAVED_FIELDS}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MatchState":
        return cls(**{row.name: row.restored(data) for row in MATCH_SAVED_FIELDS})


MATCH_SAVED_FIELDS: tuple[SavedField, ...] = (
    SavedField("battle", write=_battle_out, read=_battle_in),
)

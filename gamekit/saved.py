"""
`SavedField`, one row of a match's save table, for both games
(`d12ball.components`, `codex.components`, which import it): what each
game's `MATCH_SAVED_FIELDS` is made of. The tables themselves -- which
fields, which fallbacks -- are each game's save format, and the save
format is the contract (CLAUDE.md, principle 6); only the row's shape is
shared.
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class SavedField:
    """
    One field of a match that is saved and read back on its own terms:
    its key, what a save older than the field comes back as, and any
    conversion either way.

    `default` is for an immutable fallback and `factory` for a mutable
    one, exactly as `dataclasses.field` splits them -- a shared `[]`
    handed to every game that predates a field is the same bug there
    as anywhere else.

    `write` and `read` are the copies. A mutable field written straight
    into the dict is one the live match can go on mutating between
    `to_dict` and the save landing, and one read straight out is a
    match holding a reference into the loaded JSON. Both directions are
    usually the same callable; D12 Ball's `time_outs_used` is one that
    differs, stored `sorted` so a save file is stable and read back as
    a set.
    """

    name: str
    default: Any = None
    factory: Optional[Callable[[], Any]] = None
    write: Optional[Callable[[Any], Any]] = None
    read: Optional[Callable[[Any], Any]] = None

    def stored(self, value: Any) -> Any:
        """The value as it goes into the save."""
        return self.write(value) if self.write is not None else value

    def restored(self, data: dict) -> Any:
        """The value as it comes back, for a save that may predate it."""
        if self.name not in data:
            return self.factory() if self.factory is not None else self.default
        value = data[self.name]
        return self.read(value) if self.read is not None else value

"""
What the publisher writes into the bucket, as the dicts dumped to JSON
(docs/pbd-site.md, "The bucket's layout"; docs/design/pbd-site.md):

- `index_entry` -- a game in `index.json`, the games being played;
- `archive_entry` -- a game in `archive.json`, the finished and
  abandoned, the same fields and the winner;
- `index` and `archive` -- the two lists whole;
- `live` -- a game's `live.json`, what its page polls;
- `history` -- a game's `history.json`, one entry per finished turn.

Pure functions of the record, the match and the publisher's own entry.
They read only what the channel already shows: the seats' names, the
teams, the turn, whose turn it is, the winner, the turn's lines and the
board's key -- never a hand, a codex, a tech choice or anything an
ephemeral message carries (docs/pbd-site.md, "Hidden information").
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Optional

from codex import seats
from codex.formatting import team_name
from cogs.codex_helpers import seat_label
from cogs.codex_publish import keys
from cogs.codex_publish.record import PublishedGame
from cogs.codex_publish.segments import segments

if TYPE_CHECKING:
    from codex.components import MatchState
    from codex.game import CodexGame


def _seats(game: "CodexGame", match: "Optional[MatchState]") -> list[dict]:
    """Every seat dealt in, by its player's name off the record and its
    team's name."""
    found = []
    for seat in game.playing_seats():
        specs = match.player(seat).specs if match is not None else game.player_specs.get(seat, [])
        found.append({
            "seat": seat,
            "name": seat_label(game, seat),
            "team": team_name(specs) if specs else None,
        })
    return found


def _sides(game: "CodexGame") -> list[list[int]]:
    """The seats as they play against each other: a dragon's two teams,
    and every other game's seats each a side of its own."""
    playing = set(game.playing_seats())
    return [[seat for seat in team if seat in playing]
            for team in game.teams() if any(seat in playing for seat in team)]


def _winner(match: "Optional[MatchState]") -> Optional[list[int]]:
    """The seats that won -- one, or a dragon's two -- or `None`."""
    if match is None or match.winner is None:
        return None
    return list(seats.dragon_of(match, match.winner))


def index_entry(game: "CodexGame", match: "Optional[MatchState]",
                updated: Optional[str] = None) -> dict:
    """A game in `index.json`: id, number, mode and variant, the seats
    (name and team) and the sides they make, the turn, whose turn it is
    -- a list, since a two-headed dragon's turn is two seats' -- and when
    it last changed."""
    return {
        "id": game.game_id,
        "number": game.game_number,
        "mode": game.mode,
        "variant": game.variant,
        "seats": _seats(game, match),
        "sides": _sides(game),
        "turn": match.turn if match is not None else None,
        "turn_seats": list(seats.turn_seats(match)) if match is not None else [],
        "updated": updated,
    }


def archive_entry(game: "CodexGame", match: "Optional[MatchState]",
                  updated: Optional[str] = None) -> dict:
    """A game in `archive.json`: the index's fields, how it ended and
    who won -- `None` for an abandoned game."""
    return {
        **index_entry(game, match, updated),
        "status": game.status.value,
        "winner": _winner(match),
    }


def _newest_first(entries: Iterable[dict]) -> list[dict]:
    return sorted(entries, key=lambda entry: entry.get("updated") or "", reverse=True)


def index(entries: Iterable[dict]) -> dict:
    """`index.json`: the games being played, newest activity first."""
    return {"games": _newest_first(entries)}


def archive(entries: Iterable[dict]) -> dict:
    """`archive.json`: the finished and abandoned games, newest first."""
    return {"games": _newest_first(entries)}


def live(game: "CodexGame", match: "Optional[MatchState]", published: PublishedGame) -> dict:
    """
    A game's `live.json`: the game as the lists name it, its status, the
    current turn's heading and lines as segments, the current board's
    key, and the history's version -- which changes whenever
    `history.json` does, so the page fetches it only then.
    """
    return {
        **archive_entry(game, match, published.updated),
        "heading": segments(published.heading, game) if published.heading else [],
        "lines": [segments(line, game) for line in published.lines],
        "board": published.board,
        "history_version": published.history_version,
        "history": keys.history_key(game.game_id),
    }


def history(game: "CodexGame", published: PublishedGame) -> dict:
    """
    A game's `history.json`: one entry per finished turn, oldest first
    -- its `turn`, `heading` and `lines` as segments, the `board` it
    ended on -- every line whole, never folded at Discord's 2000
    characters. Any other field an entry carries is passed through, so
    a later per-action history adds one rather than changing the shape
    (docs/pbd-site.md, decision 5).
    """
    turns = []
    for entry in published.history:
        written = dict(entry)
        written["heading"] = segments(entry["heading"], game) if entry.get("heading") else []
        written["lines"] = [segments(line, game) for line in entry.get("lines", [])]
        turns.append(written)
    return {"id": game.game_id, "version": published.history_version, "turns": turns}


"""
What the publisher writes into the bucket, as the dicts dumped to JSON
(docs/pbd-site.md, "The bucket's layout"; docs/design/pbd-site.md):

- `on_site` -- whether a game is on the site at all: only once started;
- `index_entry` -- a game in `index.json`, the games being played;
- `archive_entry` -- a game in `archive.json`, the finished and
  abandoned, the same fields and the winner, each in its own section;
- `index` and `archive` -- the two lists whole;
- `live` -- a game's `live.json`, what its page polls;
- `history` -- a game's `history.json`, one entry per finished turn;
- `board_map` -- a board's map, where its cards are, beside it.

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
from codex.game import GameStatus
from cogs.codex_helpers import seat_label
from cogs.codex_publish import cards, keys
from cogs.codex_publish.record import PublishedGame
from cogs.codex_publish.segments import segments

if TYPE_CHECKING:
    from codex.components import MatchState
    from codex.game import CodexGame


def on_site(game: "CodexGame") -> bool:
    """
    Whether `game` is on the site: **only once it has started** (the
    author, 2026-10-16). A lobby is not listed, and a game abandoned in
    its lobby -- which never dealt a match -- is never archived; a game
    abandoned after its Start is.
    """
    return game.status is not GameStatus.LOBBY and game.match_state is not None


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
    """
    `archive.json`: the finished games and the abandoned ones, each a
    section of its own and newest first (the author, 2026-10-16: a
    finished game goes to a finished games section in the archive) --
    a game played out is read for how it was won, an abandoned one is
    not, and the page builds no split of its own.
    """
    entries = list(entries)
    return {
        "finished": _newest_first(entry for entry in entries
                                  if entry.get("status") == GameStatus.FINISHED.value),
        "abandoned": _newest_first(entry for entry in entries
                                   if entry.get("status") == GameStatus.ABANDONED.value),
    }


def mapped_key(board: Optional[str], mapped: Iterable[str]) -> Optional[str]:
    """The key of `board`'s map where it is among `mapped` -- the maps up,
    or going up before the JSON that names them -- else `None`."""
    if not board:
        return None
    found = keys.board_map_key(board)
    return found if found in mapped else None


def live(game: "CodexGame", match: "Optional[MatchState]", published: PublishedGame,
         mapped: Iterable[str] = ()) -> dict:
    """
    A game's `live.json`: the game as the lists name it, its status, the
    current turn's heading and lines as segments, the current board's
    key and its map's (`board_map`, `None` where it has none up), and
    the history's version -- which changes whenever `history.json`
    does, so the page fetches it only then.
    """
    mapped = set(mapped)
    return {
        **archive_entry(game, match, published.updated),
        "heading": segments(published.heading, game) if published.heading else [],
        "lines": [segments(line, game) for line in published.lines],
        "board": published.board,
        "board_map": mapped_key(published.board, mapped),
        "history_version": published.history_version,
        "history": keys.history_key(game.game_id),
    }


def history(game: "CodexGame", published: PublishedGame, mapped: Iterable[str] = ()) -> dict:
    """
    A game's `history.json`: one entry per finished turn, oldest first
    -- its `turn`, `heading` and `lines` as segments, the `board` it
    ended on and that board's map (`board_map`, `None` where it has
    none up) -- every line whole, never folded at Discord's 2000
    characters. Any other field an entry carries is passed through, so
    a later per-action history adds one rather than changing the shape
    (docs/pbd-site.md, decision 5).
    """
    mapped = set(mapped)
    turns = []
    for entry in published.history:
        written = dict(entry)
        written["board_map"] = mapped_key(entry.get("board"), mapped)
        written["heading"] = segments(entry["heading"], game) if entry.get("heading") else []
        written["lines"] = [segments(line, game) for line in entry.get("lines", [])]
        turns.append(written)
    return {"id": game.game_id, "version": published.history_version, "turns": turns}



def board_map(drawn: dict) -> dict:
    """
    A board's map as the page reads it, from `render_board_mapped`'s:
    the picture's `width` and `height`, and its `regions` -- each a
    `box` in the picture's pixels, the `cards` it shows (`cards.entry`:
    one for a card on the table, a codex's for a tech building) and,
    for a codex, its `title`. The boxes are the board's, which shows
    only what the channel sees; a codex is the spec's printed cards,
    never what is left in a player's own.
    """
    regions = []
    for region in drawn.get("regions", []):
        found = {"box": list(region["box"])}
        if "card" in region:
            found["cards"] = [cards.entry(region["card"])]
        else:
            found["cards"] = [cards.entry(slug) for slug in region.get("codex", [])]
            found["title"] = region.get("title")
        regions.append(found)
    return {"width": drawn.get("width"), "height": drawn.get("height"), "regions": regions}

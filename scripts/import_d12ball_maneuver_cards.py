#!/usr/bin/env python3
"""
Import the sheet's `maneuvers 2.1` tab: D12 Ball 2.1's twenty-four
maneuver cards into `d12ball/data/maneuver_cards.json`.

**A card is keyed by its sheet `Index`** (`P1` to `P4`, `B1` to `B4`,
`H1` to `H4` on offense; `F1` to `F4`, `S1` to `S4`, `R1` to `R4` on
defense), never by its name: the names collide -- P3 is named
"Pinpoint", 1.0's advanced pass, and P4 "Reset", which is not 2.0's
"Reset Play" -- and an index is what the deck holds.

Every card plays its rank's basic maneuver (the `Maneuver` column,
which has to be the 1.0 tab's basic card on that rank: its key is read
from `d12ball/data/maneuvers.json`), with that maneuver's `Effect`,
identical across the rank's four cards -- refused otherwise. Its
`Special` is a role interaction, "If <player> is A [or B], ...", and
**the four cards of a rank name all six roles between them, each
exactly once** -- refused otherwise -- since a role tells which card's
special a player plays (docs/rules-2.1.md, section 2).

**Rows whose `Mode` is Advanced are skipped** (2.1 has no advanced
maneuvers; the author, 2026-10-31), and each is printed. **A blank
`Mode` reads as Basic and a blank `Time` as 1**, as the 2.0 importer
did, and each default is printed. Text is stripped of the spaces at its
ends -- the importer's normalisation, never a correction of the words.

Same CSV source rules as `import_d12ball_maneuvers.py`: a public CSV
URL or a local path, and `scripts/import_from_workbook.py` where the
sheet cannot be fetched. See docs/design/maneuver-deck.md.
"""

import argparse
import csv
import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.components import maneuver_key  # noqa: E402
from import_d12ball_maneuvers import read_source  # noqa: E402

DEFAULT_SOURCE = (
    "https://docs.google.com/spreadsheets/d/"
    "1PKPpTseisPmM-tH6PMLbtsrYsZ_zG8smluP5VmHKcMw/"
    "export?format=csv&gid=1310773351"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "d12ball" / "data" / "maneuver_cards.json"
DEFAULT_CATALOG = PROJECT_ROOT / "d12ball" / "data" / "maneuvers.json"

REQUIRED_COLUMNS = {
    "Index", "Rank", "Maneuver", "Name", "Type", "Effect", "Special",
    "Mode", "Time", "Spec",
}
EXPECTED_TYPES = {"offense", "defense"}
#: The cards a rank has.
CARD_NUMBERS = (1, 2, 3, 4)
DEFAULT_MODE = "basic"
DEFAULT_TIME = "1"

#: The sheet's role abbreviations, by the role's saved value.
ROLE_ABBREVIATIONS = {
    "FB": "fullback",
    "DD": "defender",
    "MF": "midfielder",
    "PM": "playmaker",
    "WG": "winger",
    "SK": "striker",
}
#: "If passer is MF or SK, ..." -- the roles a special names.
SPECIAL_ROLES = re.compile(
    r"^If\s+\w+\s+is\s+(?:an?\s+)?([A-Z]{2})(?:\s+or\s+([A-Z]{2}))?\b",
    re.IGNORECASE,
)


def clean(text: str) -> str:
    """A cell with the spaces at the ends of each line taken off."""
    return "\n".join(line.strip() for line in (text or "").strip().splitlines())


def read_basic_keys(path: Path) -> dict[tuple[str, int], str]:
    """The 1.0 basic card's key on each (side, rank)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        (side, maneuver["rank"]): maneuver.get("key") or maneuver_key(maneuver["name"])
        for side, maneuvers in data["maneuvers"].items()
        for maneuver in maneuvers
        if maneuver.get("tier", "basic") == "basic"
    }


def special_roles(index: str, special: str) -> list[str]:
    match = SPECIAL_ROLES.match(special)
    if match is None:
        raise ValueError(
            f"{index}: Special {special!r} does not read "
            "'If <player> is A [or B], ...'."
        )
    roles = []
    for abbreviation in filter(None, match.groups()):
        role = ROLE_ABBREVIATIONS.get(abbreviation.upper())
        if role is None:
            raise ValueError(f"{index}: unknown role {abbreviation!r}.")
        roles.append(role)
    return roles


def import_cards(
    rows: Iterable[dict[str, str]],
    basic_keys: dict[tuple[str, int], str],
) -> tuple[list[dict], list[str]]:
    """The file's `cards`, and a line for every row skipped or default
    filled in."""
    cards: list[dict] = []
    notes: list[str] = []
    seen: set[str] = set()
    letters: dict[tuple[str, int], str] = {}
    effects: dict[tuple[str, int], str] = {}
    roles_by_rank: dict[tuple[str, int], list[str]] = defaultdict(list)

    for row_number, row in enumerate(rows, start=2):
        index = clean(row.get("Index")).upper()
        name = clean(row.get("Name"))
        if not index and not name:
            continue
        mode = clean(row.get("Mode")).lower()
        if mode == "advanced":
            notes.append(f"Skipped: row {row_number} {index} {name} (Advanced)")
            continue
        if not mode:
            mode = DEFAULT_MODE
            notes.append(f"Default: row {row_number} {index} {name}: Mode -> Basic")
        if mode != "basic":
            raise ValueError(f"{index}: unknown Mode {mode!r}.")
        time = clean(row.get("Time"))
        if not time:
            time = DEFAULT_TIME
            notes.append(f"Default: row {row_number} {index} {name}: Time -> 1")
        if not time.isdigit():
            raise ValueError(f"{index}: Time {time!r} must be a number.")

        side = clean(row.get("Type")).lower()
        if side not in EXPECTED_TYPES:
            raise ValueError(f"{index}: unknown Type {side!r}.")
        rank_match = re.fullmatch(r"([OD])\s*(\d+)", clean(row.get("Rank")).upper())
        if rank_match is None or rank_match.group(1) != side[0].upper():
            raise ValueError(f"{index}: Rank is not a {side} rank.")
        rank = int(rank_match.group(2))
        if (side, rank) not in basic_keys:
            raise ValueError(f"{index}: {side} rank {rank} is not a 1.0 rank.")

        index_match = re.fullmatch(r"([A-Z])(\d)", index)
        if index_match is None:
            raise ValueError(f"row {row_number}: Index {index!r} is not a letter and a digit.")
        letter, number = index_match.group(1), int(index_match.group(2))
        if number not in CARD_NUMBERS:
            raise ValueError(f"{index}: a basic card is numbered 1 to 4.")
        if letters.setdefault((side, rank), letter) != letter:
            raise ValueError(f"{index}: Index letter differs from the rest of its rank.")
        if index in seen:
            raise ValueError(f"Duplicate Index {index}.")
        seen.add(index)

        maneuver = maneuver_key(clean(row.get("Maneuver")))
        if maneuver != basic_keys[(side, rank)]:
            raise ValueError(
                f"{index}: Maneuver {row.get('Maneuver')!r} is not 1.0's "
                f"basic {side} card on rank {rank}."
            )
        effect = clean(row.get("Effect"))
        if not effect:
            raise ValueError(f"{index}: Effect is required.")
        if effects.setdefault((side, rank), effect) != effect:
            raise ValueError(
                f"{index}: Effect differs from the rest of {side} rank {rank}."
            )
        special = clean(row.get("Special"))
        roles = special_roles(index, special)
        roles_by_rank[(side, rank)].extend(roles)

        cards.append({
            "index": index,
            "name": name,
            "side": side,
            "rank": rank,
            "number": number,
            "maneuver": maneuver,
            "effect": effect,
            "special": special,
            "roles": roles,
            "spec": clean(row.get("Spec")),
            "time": time,
        })

    every_role = sorted(ROLE_ABBREVIATIONS.values())
    for (side, rank) in sorted(basic_keys):
        numbers = sorted(
            card["number"] for card in cards
            if card["side"] == side and card["rank"] == rank
        )
        if numbers != list(CARD_NUMBERS):
            raise ValueError(f"{side.title()} rank {rank} has cards {numbers}, not 1 to 4.")
        named = sorted(roles_by_rank[(side, rank)])
        if named != every_role:
            raise ValueError(
                f"{side.title()} rank {rank}'s specials name {named}, not "
                "each of the six roles once."
            )

    cards.sort(key=lambda card: (
        card["side"] != "offense", card["rank"], card["number"],
    ))
    return cards, notes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate D12 Ball 2.1's maneuver cards from their tab.",
    )
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--catalog", type=Path, default=DEFAULT_CATALOG,
        help="The 1.0 import whose basic cards each rank plays.",
    )
    parser.add_argument("--data-version", type=int, default=1)
    args = parser.parse_args()

    reader = csv.DictReader(io.StringIO(read_source(args.source)))
    missing_columns = sorted(REQUIRED_COLUMNS - set(reader.fieldnames or []))
    if missing_columns:
        raise ValueError(
            "Spreadsheet is missing columns: " + ", ".join(missing_columns)
        )
    cards, notes = import_cards(reader, read_basic_keys(args.catalog))
    for line in notes:
        print(line)
    output = {
        "data_version": args.data_version,
        "source": DEFAULT_SOURCE,
        "cards": cards,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output} with {len(cards)} cards.")


if __name__ == "__main__":
    main()

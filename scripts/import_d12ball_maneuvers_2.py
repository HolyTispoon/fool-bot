#!/usr/bin/env python3
"""
Import the sheet's `maneuvers 2.0` tab: D12 Ball 2.0's thirty
maneuvers, five a rank, into `d12ball/data/maneuvers_2.json`.

Each rank on each side has five rows, numbered by the tab's `Index`
(`P1` to `P5` for O1, `F1` to `F5` for D1, ...): row 1 is the rank's
basic maneuver, rows 2 to 4 its three variants, and row 5 its advanced
maneuver. The deck's two-headed cards pair an offensive row with the
defensive row of the same rank and number -- `P2` with `F2` -- so the
number is written out as `deck_index` (docs/rules-2.0.md section 1).

The tab has no `Defeats` column: who beats whom is the rank's, and the
2.0 ranks are the 1.0 ranks, so the cycle is read from the 1.0 tab's
import (`d12ball/data/maneuvers.json`) rather than written here.

**A blank `Mode` reads as Basic and a blank `Time` as 1** (the author,
2026-10-27): the tab leaves them blank on the defensive variants. Each
default is printed, so a run says which cells it filled.

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
DEFAULT_OUTPUT = PROJECT_ROOT / "d12ball" / "data" / "maneuvers_2.json"
DEFAULT_CYCLE = PROJECT_ROOT / "d12ball" / "data" / "maneuvers.json"

REQUIRED_COLUMNS = {"Rank", "Maneuver", "Type", "Effect", "Mode", "Time"}
#: The tab's first column numbers the rows (`P1` ... `R5`). It is read by
#: position, because its header has not stayed put: "Index" when the tab
#: was first imported, "Q1 " on 2026-10-28.
INDEX_COLUMN = "Index"
EXPECTED_TYPES = {"offense", "defense"}
EXPECTED_TIERS = {"basic", "advanced"}
#: The rows a rank has: 1 basic, 2-4 variants, 5 advanced.
DECK_INDEXES = (1, 2, 3, 4, 5)
ADVANCED_INDEX = 5
DEFAULT_MODE = "basic"
DEFAULT_TIME = "1"


def read_cycle(path: Path) -> dict[tuple[str, int], int]:
    """The rank each (side, rank) beats, off the 1.0 import."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        (side, maneuver["rank"]): maneuver["defeats_rank"]
        for side, maneuvers in data["maneuvers"].items()
        for maneuver in maneuvers
    }


def import_maneuvers(
    rows: Iterable[dict[str, str]],
    cycle: dict[tuple[str, int], int],
) -> tuple[dict, list[str]]:
    """The file's `maneuvers`, and a line for every default filled in."""
    by_type: dict[str, list[dict]] = defaultdict(list)
    seen: dict[str, set[tuple[int, int]]] = defaultdict(set)
    letters: dict[tuple[str, int], str] = {}
    keys: set[str] = set()
    defaults: list[str] = []

    for row_number, row in enumerate(rows, start=2):
        name = (row.get("Maneuver") or "").strip()
        if not name:
            continue
        maneuver_type = (row.get("Type") or "").strip().lower()
        if maneuver_type not in EXPECTED_TYPES:
            raise ValueError(f"{name}: unknown Type {maneuver_type!r}.")

        rank_match = re.fullmatch(
            r"([OD])\s*(\d+)", (row.get("Rank") or "").strip().upper(),
        )
        if rank_match is None:
            raise ValueError(f"{name}: Rank must be O or D and a number.")
        if rank_match.group(1) != maneuver_type[0].upper():
            raise ValueError(f"{name}: Rank is not a {maneuver_type} rank.")
        rank = int(rank_match.group(2))
        if (maneuver_type, rank) not in cycle:
            raise ValueError(
                f"{name}: {maneuver_type} rank {rank} is not a 1.0 rank."
            )

        index_match = re.fullmatch(
            r"([A-Z])(\d)", (row.get("Index") or "").strip().upper(),
        )
        if index_match is None:
            raise ValueError(f"{name}: Index must be a letter and a digit.")
        letter, digit = index_match.groups()
        deck_index = int(digit)
        if deck_index not in DECK_INDEXES:
            raise ValueError(f"{name}: Index {deck_index} is not 1 to 5.")
        if letters.setdefault((maneuver_type, rank), letter) != letter:
            raise ValueError(
                f"{name}: Index letter {letter} differs from the rest "
                f"of {maneuver_type} rank {rank}."
            )
        if (rank, deck_index) in seen[maneuver_type]:
            raise ValueError(
                f"{name}: {maneuver_type} rank {rank} has two rows "
                f"numbered {deck_index}."
            )
        seen[maneuver_type].add((rank, deck_index))

        tier = (row.get("Mode") or "").strip().lower()
        if not tier:
            tier = DEFAULT_MODE
            defaults.append(f"row {row_number} {name}: Mode -> Basic")
        if tier not in EXPECTED_TIERS:
            raise ValueError(f"{name}: unknown Mode {tier!r}.")
        if (tier == "advanced") != (deck_index == ADVANCED_INDEX):
            raise ValueError(
                f"{name}: row {deck_index} of a rank must be "
                + ("advanced." if deck_index == ADVANCED_INDEX else "basic.")
            )
        time = (row.get("Time") or "").strip()
        if not time:
            time = DEFAULT_TIME
            defaults.append(f"row {row_number} {name}: Time -> 1")
        if not time.isdigit():
            raise ValueError(f"{name}: Time {time!r} must be a number.")

        effect = "\n".join(
            line.strip()
            for line in (row.get("Effect") or "").strip().splitlines()
        )
        if not effect:
            raise ValueError(f"{name}: Effect is required.")

        key = maneuver_key(name)
        if key in keys:
            raise ValueError(f"Duplicate maneuver: {name}")
        keys.add(key)
        by_type[maneuver_type].append({
            "name": name,
            "key": key,
            "rank": rank,
            "tier": tier,
            "deck_index": deck_index,
            "defeats_rank": cycle[(maneuver_type, rank)],
            "effect": effect,
            "time": time,
        })

    for maneuver_type in EXPECTED_TYPES:
        ranks = {rank for side, rank in cycle if side == maneuver_type}
        expected = {(rank, index) for rank in ranks for index in DECK_INDEXES}
        missing = sorted(expected - seen[maneuver_type])
        if missing:
            raise ValueError(
                f"{maneuver_type.title()} is missing rank/index rows "
                f"{missing}."
            )

    return {
        maneuver_type: sorted(
            by_type[maneuver_type],
            key=lambda item: (item["rank"], item["deck_index"]),
        )
        for maneuver_type in ("offense", "defense")
    }, defaults


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate D12 Ball 2.0's maneuver JSON from its tab.",
    )
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--cycle", type=Path, default=DEFAULT_CYCLE,
        help="The 1.0 import whose ranks give the cycle.",
    )
    parser.add_argument("--data-version", type=int, default=1)
    args = parser.parse_args()

    reader = csv.DictReader(io.StringIO(read_source(args.source)))
    fieldnames = list(reader.fieldnames or [])
    missing_columns = sorted(REQUIRED_COLUMNS - set(fieldnames))
    if missing_columns or not fieldnames:
        raise ValueError(
            "Spreadsheet is missing columns: " + ", ".join(missing_columns)
        )
    first = fieldnames[0]
    rows = (
        {**row, INDEX_COLUMN: row.get(first, "")} for row in reader
    )
    maneuvers, defaults = import_maneuvers(rows, read_cycle(args.cycle))
    for line in defaults:
        print(f"Default: {line}")
    output = {
        "data_version": args.data_version,
        "source": DEFAULT_SOURCE,
        "maneuvers": maneuvers,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    counts = {side: len(rows) for side, rows in maneuvers.items()}
    print(f"Wrote {args.output} with {counts}.")


if __name__ == "__main__":
    main()

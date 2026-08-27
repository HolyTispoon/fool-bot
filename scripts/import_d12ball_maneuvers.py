#!/usr/bin/env python3
import argparse
import csv
import io
import json
import re
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Iterable


DEFAULT_SOURCE = (
    "https://docs.google.com/spreadsheets/d/"
    "1PKPpTseisPmM-tH6PMLbtsrYsZ_zG8smluP5VmHKcMw/"
    "export?format=csv&gid=1487033386"
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "d12ball" / "data" / "maneuvers.json"

EXPECTED_TYPES = {"offense", "defense"}
EXPECTED_TIERS = {"basic", "advanced"}
DIE_FACES = set(range(1, 7))
REQUIRED_COLUMNS = {
    "Maneuver",
    "Mode",
    "Type",
    "Rank",
    "Die value",
    "Defeats",
    "Effect",
    "Time",
}

# The sheet renames a row without rewriting the references to it. The
# author renamed the basic D2 card from "Steal Intercept" to "Steal" on
# 2026-08-18 (the advanced D2 card is "Intercept" now), and four other
# rows still name it the old way in their `Defeats`/`Defeated by`
# columns. Same shape as `LEGACY_RENAMED_NAMES` in
# `gamesaves/d12ball/storage.py`: a rename is the one thing that cannot
# be derived, so it is written down. Add an entry whenever a maneuver
# is renamed upstream, and drop one once the sheet's own references
# have caught up.
LEGACY_MANEUVER_NAMES = {
    "steal intercept": "Steal",
    # The advanced O1 card became "Skilled Pass" on 2026-08-26.
    "precise pass": "Skilled Pass",
}


def read_source(source: str) -> str:
    if source.startswith(("https://", "http://")):
        with urllib.request.urlopen(source, timeout=30) as response:
            return response.read().decode("utf-8-sig")

    return Path(source).read_text(encoding="utf-8-sig")


def maneuver_key(name: str) -> str:
    """The same slug `d12ball.components.maneuver_key` builds."""
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def canonical_name(name: str) -> str:
    return LEGACY_MANEUVER_NAMES.get(name.strip().lower(), name.strip())


def parse_die_values(raw_value: str, maneuver: str) -> list[int]:
    values = []
    for part in raw_value.split(","):
        part = part.strip()
        try:
            value = int(part)
        except ValueError as error:
            raise ValueError(
                f"{maneuver}: Die value {raw_value!r} must be a "
                "comma-separated list of numbers from 1 to 6."
            ) from error

        if value not in DIE_FACES:
            raise ValueError(
                f"{maneuver}: Die value {value} must be from 1 to 6."
            )
        values.append(value)

    if not values:
        raise ValueError(f"{maneuver}: Die value is required.")

    return values


def import_maneuvers(rows: Iterable[dict[str, str]]) -> dict:
    maneuvers_by_type: dict[str, list[dict]] = defaultdict(list)
    keys_by_type: dict[str, set[str]] = defaultdict(set)
    rank_by_name: dict[tuple[str, str], int] = {}
    die_faces_by_type: dict[str, set[int]] = defaultdict(set)

    for row_number, row in enumerate(rows, start=2):
        # " Intercept" is stored with a leading space, the same way the
        # players sheet stores its abbreviated-ability header.
        name = canonical_name(row.get("Maneuver") or "")
        tier = (row.get("Mode") or "").strip().lower()
        maneuver_type = (row.get("Type") or "").strip().lower()
        rank_raw = (row.get("Rank") or "").strip()
        defeats = canonical_name(row.get("Defeats") or "")
        effect = (row.get("Effect") or "").strip()
        time = (row.get("Time") or "").strip()

        if not name:
            raise ValueError(f"Row {row_number}: Maneuver name is required.")
        if maneuver_type not in EXPECTED_TYPES:
            raise ValueError(f"{name}: unknown Type {maneuver_type!r}.")
        if tier not in EXPECTED_TIERS:
            raise ValueError(f"{name}: unknown Mode {tier!r}.")

        key = maneuver_key(name)
        if key in keys_by_type[maneuver_type]:
            raise ValueError(f"Duplicate maneuver in {maneuver_type}: {name}")
        if not defeats:
            raise ValueError(f"{name}: Defeats is required.")
        if not effect:
            raise ValueError(f"{name}: Effect is required.")

        try:
            rank = int(rank_raw)
        except ValueError as error:
            raise ValueError(f"{name}: Rank must be a number.") from error

        # The die values are retained but no longer validated for
        # uniqueness: an advanced card sits on its basic counterpart's
        # rank and reuses its faces, and the selection die is off the
        # rules altogether since 2026-08-17. Only the basic rows have
        # to cover all six faces, which is checked below.
        die_values = parse_die_values(row.get("Die value") or "", name)
        if tier == "basic":
            overlap = die_faces_by_type[maneuver_type] & set(die_values)
            if overlap:
                raise ValueError(
                    f"{name}: Die value(s) {sorted(overlap)} already used by "
                    f"another basic {maneuver_type} maneuver."
                )
            die_faces_by_type[maneuver_type].update(die_values)

        keys_by_type[maneuver_type].add(key)
        rank_by_name[(maneuver_type, name)] = rank
        maneuvers_by_type[maneuver_type].append(
            {
                "name": name,
                "key": key,
                "rank": rank,
                "tier": tier,
                "die_values": die_values,
                "defeats": defeats,
                "effect": effect,
                "time": time,
            }
        )

    if set(maneuvers_by_type) != EXPECTED_TYPES:
        raise ValueError(
            "The spreadsheet must contain both Offense and Defense maneuvers."
        )

    for maneuver_type, faces in die_faces_by_type.items():
        if faces != DIE_FACES:
            missing = sorted(DIE_FACES - faces)
            raise ValueError(
                f"{maneuver_type.title()} maneuvers must cover all six die "
                f"faces; missing {missing}."
            )

    # `Defeats` names a card; what the bot resolves against is a
    # **rank**, because since advanced mode each rank carries two cards
    # and rank alone decides who wins (the author, 2026-08-18). So the
    # name is resolved here and the rank is what is written out. The
    # column is still the source of the relation -- nothing about the
    # cycle is written into the code.
    for maneuver_type, maneuvers in maneuvers_by_type.items():
        opposite_type = "defense" if maneuver_type == "offense" else "offense"
        for maneuver in maneuvers:
            defeated_rank = rank_by_name.get(
                (opposite_type, maneuver["defeats"])
            )
            if defeated_rank is None:
                raise ValueError(
                    f"{maneuver['name']}: Defeats {maneuver['defeats']!r} is "
                    f"not a known {opposite_type} maneuver."
                )
            maneuver["defeats_rank"] = defeated_rank
            del maneuver["defeats"]

    # Both cards on a rank have to beat the same rank, or "rank alone
    # decides" is not true of the data and `ManeuverCatalog.resolve`
    # would answer differently for a card and its counterpart.
    for maneuver_type, maneuvers in maneuvers_by_type.items():
        by_rank: dict[int, set[int]] = defaultdict(set)
        for maneuver in maneuvers:
            by_rank[maneuver["rank"]].add(maneuver["defeats_rank"])
        for rank, defeated in sorted(by_rank.items()):
            if len(defeated) != 1:
                raise ValueError(
                    f"{maneuver_type.title()} rank {rank} defeats more than "
                    f"one rank ({sorted(defeated)}); rank alone has to decide."
                )
    ordered_maneuvers = {
        maneuver_type: sorted(
            maneuvers_by_type[maneuver_type],
            key=lambda item: (item["rank"], item["tier"] != "basic"),
        )
        for maneuver_type in ("offense", "defense")
    }

    return {
        "data_version": None,
        "source": DEFAULT_SOURCE,
        "maneuvers": ordered_maneuvers,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate and validate D12 Ball maneuver JSON from a CSV export."
        )
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE,
        help="A local CSV path or public CSV URL.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument(
        "--data-version",
        type=int,
        default=1,
    )
    args = parser.parse_args()

    source_text = read_source(args.source)
    reader = csv.DictReader(io.StringIO(source_text))
    columns = set(reader.fieldnames or [])
    missing_columns = sorted(REQUIRED_COLUMNS - columns)
    if missing_columns:
        raise ValueError(
            "Spreadsheet is missing columns: " + ", ".join(missing_columns)
        )

    output = import_maneuvers(reader)
    output["data_version"] = args.data_version
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2) + "\n",
        encoding="utf-8",
    )
    counts = {
        maneuver_type: len(maneuvers)
        for maneuver_type, maneuvers in output["maneuvers"].items()
    }
    print(f"Wrote {args.output} with {counts}.")


if __name__ == "__main__":
    main()

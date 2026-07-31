#!/usr/bin/env python3
import argparse
import csv
import io
import json
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
DIE_FACES = set(range(1, 7))
REQUIRED_COLUMNS = {
    "Maneuver",
    "Type",
    "Rank",
    "Die value",
    "Defeats",
    "Effect",
    "Time",
}


def read_source(source: str) -> str:
    if source.startswith(("https://", "http://")):
        with urllib.request.urlopen(source, timeout=30) as response:
            return response.read().decode("utf-8-sig")

    return Path(source).read_text(encoding="utf-8-sig")


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
    names_by_type: dict[str, set[str]] = defaultdict(set)
    die_faces_by_type: dict[str, set[int]] = defaultdict(set)

    for row_number, row in enumerate(rows, start=2):
        name = (row.get("Maneuver") or "").strip()
        maneuver_type = (row.get("Type") or "").strip().lower()
        rank_raw = (row.get("Rank") or "").strip()
        defeats = (row.get("Defeats") or "").strip()
        effect = (row.get("Effect") or "").strip()
        time = (row.get("Time") or "").strip()

        if not name:
            raise ValueError(f"Row {row_number}: Maneuver name is required.")
        if maneuver_type not in EXPECTED_TYPES:
            raise ValueError(f"{name}: unknown Type {maneuver_type!r}.")
        if name in names_by_type[maneuver_type]:
            raise ValueError(f"Duplicate maneuver in {maneuver_type}: {name}")
        if not defeats:
            raise ValueError(f"{name}: Defeats is required.")
        if not effect:
            raise ValueError(f"{name}: Effect is required.")

        try:
            rank = int(rank_raw)
        except ValueError as error:
            raise ValueError(f"{name}: Rank must be a number.") from error

        die_values = parse_die_values(row.get("Die value") or "", name)
        overlap = die_faces_by_type[maneuver_type] & set(die_values)
        if overlap:
            raise ValueError(
                f"{name}: Die value(s) {sorted(overlap)} already used by "
                f"another {maneuver_type} maneuver."
            )
        die_faces_by_type[maneuver_type].update(die_values)

        names_by_type[maneuver_type].add(name)
        maneuvers_by_type[maneuver_type].append(
            {
                "name": name,
                "rank": rank,
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

    for maneuver_type, maneuvers in maneuvers_by_type.items():
        opposite_type = "defense" if maneuver_type == "offense" else "offense"
        opposite_names = names_by_type[opposite_type]
        for maneuver in maneuvers:
            if maneuver["defeats"] not in opposite_names:
                raise ValueError(
                    f"{maneuver['name']}: Defeats {maneuver['defeats']!r} is "
                    f"not a known {opposite_type} maneuver."
                )

    ordered_maneuvers = {
        maneuver_type: sorted(
            maneuvers_by_type[maneuver_type], key=lambda item: item["rank"]
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

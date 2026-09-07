#!/usr/bin/env python3
"""
Generate `d12ball/data/species.json` from the spreadsheet's
`spec_abilities` tab.

    python3 scripts/import_d12ball_species.py

Each of the four species -- Fire Demon, Cyborg, Telekinetic, Ooze --
carries one ability that applies to every player of that species,
whichever team is fielding them. The tab has four columns: `Spec`, the
ability's `Name`, the full `Ability` sentence, and an `Abbreviated`
form for anywhere there is no room for the sentence.

This is the species counterpart of `scripts/import_d12ball_players.py`
and follows the same rules: the file is regenerated whole by re-running
this, revisions are made upstream in the sheet rather than in
`species.json`, and the leading formula-guard backtick a spreadsheet
adds to a cell starting `+`/`-`/`=` is stripped on the way in.
"""
import argparse
import csv
import io
import json
import urllib.request
from pathlib import Path

# The `spec_abilities` tab. `gid=0` and the other tabs are the player,
# maneuver and role-ability sources -- see import_d12ball_players.py and
# import_d12ball_maneuvers.py.
DEFAULT_SOURCE = (
    "https://docs.google.com/spreadsheets/d/"
    "1PKPpTseisPmM-tH6PMLbtsrYsZ_zG8smluP5VmHKcMw/"
    "export?format=csv&gid=123199571"
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "d12ball" / "data" / "species.json"

# The same four names import_d12ball_players.py validates a player's
# Species column against -- add a fifth to both together if the setting
# ever themes one in.
EXPECTED_SPECIES = {"fire_demon", "cyborg", "telekinetic", "ooze"}
REQUIRED_COLUMNS = {"Spec", "Name", "Ability", "Abbreviated"}


def strip_formula_escape(value: str) -> str:
    """
    Drop the leading backtick or apostrophe a spreadsheet needs on a
    cell whose text starts with +, - or =. The escape is in the export
    and is not part of the ability -- same guard as the player import.
    """
    if value[:1] in ("`", "'") and value[1:2] in ("+", "-", "="):
        return value[1:]
    return value


def read_source(source: str) -> str:
    if source.startswith(("https://", "http://")):
        with urllib.request.urlopen(source, timeout=30) as response:
            return response.read().decode("utf-8-sig")
    return Path(source).read_text(encoding="utf-8-sig")


def species_key(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def import_species(rows: list[dict[str, str]], data_version: int) -> dict:
    species: dict[str, dict] = {}

    for row_number, row in enumerate(rows, start=2):
        spec = (row.get("Spec") or "").strip()
        if not spec:
            continue
        key = species_key(spec)
        if key not in EXPECTED_SPECIES:
            raise ValueError(f"Row {row_number}: unknown species {spec!r}.")
        if key in species:
            raise ValueError(f"Duplicate species in the sheet: {spec}")

        name = (row.get("Name") or "").strip()
        ability = strip_formula_escape((row.get("Ability") or "").strip())
        short = strip_formula_escape((row.get("Abbreviated") or "").strip())

        if not name:
            raise ValueError(f"{spec}: Name is required.")
        if not ability:
            raise ValueError(f"{spec}: Ability is required.")
        if not short:
            raise ValueError(
                f"{spec}: Abbreviated is required -- every ability needs a "
                "short form for anywhere the sentence does not fit."
            )

        species[key] = {
            "name": name,
            "ability": ability,
            "ability_short": short,
        }

    missing = sorted(EXPECTED_SPECIES - set(species))
    if missing:
        raise ValueError(
            "The spec_abilities tab is missing species: " + ", ".join(missing)
        )

    ordered = {
        key: species[key]
        for key in ("fire_demon", "cyborg", "telekinetic", "ooze")
    }
    return {
        "data_version": data_version,
        "source": DEFAULT_SOURCE,
        "species": ordered,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate and validate D12 Ball species JSON.",
    )
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--data-version", type=int, default=1)
    args = parser.parse_args()

    reader = csv.DictReader(io.StringIO(read_source(args.source)))
    reader.fieldnames = [name.strip() for name in (reader.fieldnames or [])]
    missing_columns = sorted(REQUIRED_COLUMNS - set(reader.fieldnames))
    if missing_columns:
        raise ValueError(
            "spec_abilities tab is missing columns: "
            + ", ".join(missing_columns)
        )

    output = import_species(list(reader), args.data_version)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {args.output} with "
        f"{len(output['species'])} species abilities."
    )


if __name__ == "__main__":
    main()

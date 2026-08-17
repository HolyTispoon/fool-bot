#!/usr/bin/env python3
import argparse
import csv
import io
import json
import re
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, NamedTuple


DEFAULT_SOURCE = (
    "https://docs.google.com/spreadsheets/d/"
    "1PKPpTseisPmM-tH6PMLbtsrYsZ_zG8smluP5VmHKcMw/"
    "export?format=csv&gid=0"
)
DEFAULT_ABILITIES_SOURCE = (
    "https://docs.google.com/spreadsheets/d/"
    "1PKPpTseisPmM-tH6PMLbtsrYsZ_zG8smluP5VmHKcMw/"
    "export?format=csv&gid=1822486506"
)
# --abilities takes a CSV path or URL; this asks for the player cards
# sheet's own Basic column instead of a separate abilities sheet.
ABILITIES_FROM_PLAYERS = "players"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "d12ball" / "data" / "players.json"
DEFAULT_IMAGES = PROJECT_ROOT / "d12ball" / "images" / "player_images"

EXPECTED_TEAMS = {"orange", "teal", "purple", "slime"}
# A player's species, not their team -- since the 2026-08-17 reshuffle a
# team is 3 of its own species plus 2 of each other, so this is no
# longer read off Team. Fixed to the same four as EXPECTED_TEAMS because
# that is every species the setting has today; add to both together if
# a fifth is ever introduced.
EXPECTED_SPECIES = {"fire_demon", "cyborg", "telekinetic", "ooze"}
EXPECTED_ROLE_COUNTS = {
    "fullback": 1,
    "defender": 2,
    "midfielder": 1,
    "playmaker": 2,
    "winger": 1,
    "striker": 2,
}
PLAYER_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)+$")
REQUIRED_COLUMNS = {
    "player_id",
    "Name",
    "Team",
    "Species",
    "Role",
    "Oskill",
    "Dskill",
}
# The player cards sheet's copy of the basic ability, formerly "Ability".
# It is required only when that sheet is where the abilities are read from;
# reading the abilities sheet does not need the copy to be there at all.
BASIC_COLUMN = "Basic"
REQUIRED_ABILITY_COLUMNS = {"Role", "Ability"}
# The abilities sheet's short form of each ability, for places that show
# an ability next to something else and have no room for a sentence --
# the matchup images, today. The sheet spells the column "Abbreivated";
# both spellings are accepted so correcting it upstream doesn't break
# the import, and header names are stripped before matching because that
# one is stored with a trailing space.
ABBREVIATED_COLUMNS = ("Abbreviated", "Abbreivated")


class RoleAbility(NamedTuple):
    text: str
    short: str


def strip_formula_escape(value: str) -> str:
    """
    Drop the leading backtick or apostrophe a spreadsheet needs on a
    cell whose text starts with +, - or =, which it would otherwise
    read as a formula. Two of the abbreviations start with "+3", so
    the escape is in the export and is not part of the ability.
    """
    if value[:1] in ("`", "'") and value[1:2] in ("+", "-", "="):
        return value[1:]
    return value


def strip_header_names(reader: csv.DictReader) -> csv.DictReader:
    """
    Trim the whitespace around a sheet's column names, so a header
    typed with a trailing space still matches the name asked for.
    """
    if reader.fieldnames:
        reader.fieldnames = [name.strip() for name in reader.fieldnames]
    return reader


def abbreviated_column(columns: Iterable[str]) -> str | None:
    for name in ABBREVIATED_COLUMNS:
        if name in columns:
            return name
    return None


def read_source(source: str) -> str:
    if source.startswith(("https://", "http://")):
        with urllib.request.urlopen(source, timeout=30) as response:
            return response.read().decode("utf-8-sig")

    return Path(source).read_text(encoding="utf-8-sig")


def parse_skill(raw_value: str, field: str, player_id: str) -> int:
    try:
        value = int(float(raw_value))
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"{player_id}: {field} must be a number from 1 to 6."
        ) from error

    if value not in range(1, 7):
        raise ValueError(
            f"{player_id}: {field} must be a number from 1 to 6."
        )

    return value


def import_abilities(
    rows: Iterable[dict[str, str]],
    short_column: str,
) -> dict[str, RoleAbility]:
    abilities: dict[str, RoleAbility] = {}

    for row_number, row in enumerate(rows, start=2):
        role = (row.get("Role") or "").strip().lower()
        ability = (row.get("Ability") or "").strip()
        short = strip_formula_escape((row.get(short_column) or "").strip())

        if not role:
            continue
        if role not in EXPECTED_ROLE_COUNTS:
            raise ValueError(f"Row {row_number}: unknown role {role!r}.")
        if role in abilities:
            raise ValueError(f"Duplicate role in the abilities sheet: {role}")
        if not ability:
            raise ValueError(f"{role}: Ability is required.")
        if not short:
            raise ValueError(
                f"{role}: {short_column} is required -- every ability needs "
                "a short form for the images that have no room for the "
                "sentence."
            )

        abilities[role] = RoleAbility(text=ability, short=short)

    missing_roles = sorted(set(EXPECTED_ROLE_COUNTS) - set(abilities))
    if missing_roles:
        raise ValueError(
            "The abilities sheet is missing roles: "
            + ", ".join(missing_roles)
        )

    return abilities


def import_players(
    rows: Iterable[dict[str, str]],
    images_folder: Path,
    data_version: int,
    role_abilities: dict[str, RoleAbility] | None = None,
    abilities_source: str = DEFAULT_SOURCE,
) -> dict:
    players_by_team: dict[str, list[dict]] = defaultdict(list)
    role_profiles: dict[str, dict] = {}
    player_ids: set[str] = set()
    player_names: set[str] = set()
    advanced_count = 0

    for row_number, row in enumerate(rows, start=2):
        role = (row.get("Role") or "").strip().lower()
        if role == "backside":
            continue

        player_id = (row.get("player_id") or "").strip()
        name = (row.get("Name") or "").strip()
        team = (row.get("Team") or "").strip().lower()
        species = (row.get("Species") or "").strip().lower().replace(" ", "_")
        basic = (row.get(BASIC_COLUMN) or "").strip()
        if (row.get("Advanced") or "").strip():
            advanced_count += 1

        if not player_id:
            raise ValueError(f"Row {row_number}: player_id is required.")
        if not PLAYER_ID_PATTERN.fullmatch(player_id):
            raise ValueError(
                f"{player_id}: IDs must contain lowercase letters, "
                "numbers, and underscores only."
            )
        if player_id in player_ids:
            raise ValueError(f"Duplicate player_id: {player_id}")
        if team not in EXPECTED_TEAMS:
            raise ValueError(f"{player_id}: unknown team {team!r}.")
        if not player_id.startswith(f"{team}_"):
            raise ValueError(
                f"{player_id}: ID must begin with the team name."
            )
        if species not in EXPECTED_SPECIES:
            raise ValueError(f"{player_id}: unknown species {species!r}.")
        if role not in EXPECTED_ROLE_COUNTS:
            raise ValueError(f"{player_id}: unknown role {role!r}.")
        if not name:
            raise ValueError(f"{player_id}: Name is required.")

        if role_abilities is None:
            if not basic:
                raise ValueError(f"{player_id}: Basic ability is required.")
            # The player cards sheet carries no short form, so the
            # sentence stands in for one. Reading the abilities sheet
            # (the default) is the way to get real abbreviations.
            ability = RoleAbility(text=basic, short=basic)
        else:
            ability = role_abilities[role]
            # The Basic column is copied from the abilities sheet, so a row
            # that disagrees means the copy is stale rather than that the
            # player is special.
            if basic and basic != ability.text:
                raise ValueError(
                    f"{player_id}: Basic ability does not match the "
                    f"{role} ability in the abilities sheet."
                )

        offense = parse_skill(row.get("Oskill"), "Oskill", player_id)
        defense = parse_skill(row.get("Dskill"), "Dskill", player_id)
        profile = {
            "offense": offense,
            "defense": defense,
            "ability": ability.text,
            "ability_short": ability.short,
        }

        existing_profile = role_profiles.get(role)
        if existing_profile is not None and existing_profile != profile:
            raise ValueError(
                f"{player_id}: basic-mode {role} data differs from "
                "other players with that role."
            )
        role_profiles[role] = profile

        image_path = images_folder / f"{name}.png"
        if not image_path.is_file():
            raise ValueError(
                f"{player_id}: missing player image {image_path.name}."
            )

        player_ids.add(player_id)
        player_names.add(name)
        players_by_team[team].append(
            {
                "id": player_id,
                "name": name,
                "role": role,
                "species": species,
                "stat_overrides": {},
            }
        )

    if set(players_by_team) != EXPECTED_TEAMS:
        raise ValueError(
            "The spreadsheet must contain Orange, Teal, Purple, and Slime."
        )

    for team, players in players_by_team.items():
        if len(players) != 9:
            raise ValueError(
                f"{team.title()} must have exactly 9 players; "
                f"found {len(players)}."
            )

        role_counts = Counter(player["role"] for player in players)
        if role_counts != Counter(EXPECTED_ROLE_COUNTS):
            raise ValueError(
                f"{team.title()} has the wrong role distribution: "
                f"{dict(role_counts)}."
            )

    image_names = {
        path.stem
        for path in images_folder.glob("*.png")
    }
    extra_images = sorted(image_names - player_names)
    if extra_images:
        raise ValueError(
            "Player images without spreadsheet players: "
            + ", ".join(extra_images)
        )

    ordered_teams = {
        team: {"players": players_by_team[team]}
        for team in ("orange", "teal", "purple", "slime")
    }
    ordered_profiles = {
        role: role_profiles[role]
        for role in EXPECTED_ROLE_COUNTS
    }

    if advanced_count:
        print(
            f"Note: {advanced_count} players have an Advanced ability. "
            "This import reads basic mode only and drops them."
        )

    return {
        "data_version": data_version,
        "source": DEFAULT_SOURCE,
        "abilities_source": abilities_source,
        "role_profiles": ordered_profiles,
        "teams": ordered_teams,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate and validate D12 Ball player JSON from a CSV export."
        )
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE,
        help="A local CSV path or public CSV URL.",
    )
    parser.add_argument(
        "--abilities",
        default=DEFAULT_ABILITIES_SOURCE,
        help=(
            "Where the basic role abilities come from: a local CSV path or "
            "public CSV URL for the basic_abilities sheet, or "
            f"{ABILITIES_FROM_PLAYERS!r} to read the player cards sheet's "
            "own Basic column instead."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument(
        "--images",
        type=Path,
        default=DEFAULT_IMAGES,
    )
    parser.add_argument(
        "--data-version",
        type=int,
        default=1,
    )
    args = parser.parse_args()

    role_abilities = None
    abilities_source = DEFAULT_SOURCE
    if args.abilities != ABILITIES_FROM_PLAYERS:
        abilities_reader = strip_header_names(
            csv.DictReader(io.StringIO(read_source(args.abilities)))
        )
        ability_columns = set(abilities_reader.fieldnames or [])
        missing_columns = sorted(REQUIRED_ABILITY_COLUMNS - ability_columns)
        short_column = abbreviated_column(ability_columns)
        if short_column is None:
            missing_columns.append(ABBREVIATED_COLUMNS[0])
        if missing_columns:
            raise ValueError(
                "Abilities sheet is missing columns: "
                + ", ".join(sorted(missing_columns))
            )
        role_abilities = import_abilities(abilities_reader, short_column)
        abilities_source = DEFAULT_ABILITIES_SOURCE

    source_text = read_source(args.source)
    reader = strip_header_names(csv.DictReader(io.StringIO(source_text)))
    columns = set(reader.fieldnames or [])
    required_columns = set(REQUIRED_COLUMNS)
    if role_abilities is None:
        required_columns.add(BASIC_COLUMN)
    missing_columns = sorted(required_columns - columns)
    if missing_columns:
        raise ValueError(
            "Spreadsheet is missing columns: "
            + ", ".join(missing_columns)
        )

    output = import_players(
        reader,
        args.images,
        args.data_version,
        role_abilities=role_abilities,
        abilities_source=abilities_source,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {args.output} with "
        f"{sum(len(team['players']) for team in output['teams'].values())} "
        "players."
    )


if __name__ == "__main__":
    main()

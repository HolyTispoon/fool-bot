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


# gid=0 was the sheet's original tab, one row per player, pre-reshuffle.
# "Player Cards" (gid=6660238) replaced it once the reshuffle needed a
# color team and a species on the same row plus the new {name}_{role}
# ids -- gid=0 still exists but is stale, so importing from it silently
# reproduces the old assignment. Confirmed with the author 2026-08-17.
DEFAULT_SOURCE = (
    "https://docs.google.com/spreadsheets/d/"
    "1PKPpTseisPmM-tH6PMLbtsrYsZ_zG8smluP5VmHKcMw/"
    "export?format=csv&gid=6660238"
)
DEFAULT_ABILITIES_SOURCE = (
    "https://docs.google.com/spreadsheets/d/"
    "1PKPpTseisPmM-tH6PMLbtsrYsZ_zG8smluP5VmHKcMw/"
    "export?format=csv&gid=1822486506"
)
# The `advanced_abilities` tab: one row a player, carrying the advanced
# role ability that only some players have. It is the only place that
# ability is read from; the advanced skill scores are the player cards
# sheet's `OskillA` and `DskillA` (the author, 2026-09-24).
DEFAULT_ADVANCED_SOURCE = (
    "https://docs.google.com/spreadsheets/d/"
    "1PKPpTseisPmM-tH6PMLbtsrYsZ_zG8smluP5VmHKcMw/"
    "export?format=csv&gid=354283038"
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "d12ball" / "data" / "players.json"
DEFAULT_IMAGES = PROJECT_ROOT / "d12ball" / "images" / "player_images"

# The four color teams, unchanged since before the reshuffle -- a mixed
# roster of 3 of its own species and 2 of each other, since 2026-08-17.
EXPECTED_TEAMS = {"orange", "teal", "purple", "slime"}
# A player's species, not their team -- a team is mixed since the
# reshuffle, so this is no longer read off Team. Fixed to the same four
# names as EXPECTED_TEAMS/SPECIES_TEAM because that is every species the
# setting has today; add to all three together if a fifth is ever
# introduced.
EXPECTED_SPECIES = {"fire_demon", "cyborg", "telekinetic", "ooze"}
# The species team a player's Species column puts them on -- the
# pre-reshuffle grouping, carried over unchanged in membership under its
# own Team enum key. The mirror image of this map (species team -> old
# color name) is how a legacy saved game's ids and Team values are
# reconstructed on load; see the "legacy migration" gotcha in docs/design/gotchas.md.
SPECIES_TEAM = {
    "fire_demon": "fire_demons",
    "cyborg": "cyborgs",
    "telekinetic": "telekinetics",
    "ooze": "oozes",
}
EXPECTED_ROLE_COUNTS = {
    "fullback": 1,
    "defender": 2,
    "midfielder": 1,
    "playmaker": 2,
    "winger": 1,
    "striker": 2,
}
REQUIRED_COLUMNS = {
    "player_id",
    "Name",
    "Team",
    "Species",
    "Role",
    "Oskill",
    "Dskill",
    "OskillA",
    "DskillA",
}
# The player cards sheet is the roster and the scores: who is on which
# team, in which role, with which species, basic scores and advanced
# scores. Its ability columns (`Basic`, `Advanced`) are the card's
# rendering of the abilities sheets and are neither read nor checked --
# the abilities sheets are the source of truth for abilities (the
# author, 2026-09-24).
ADVANCED_SKILL_COLUMNS = {"offense": "OskillA", "defense": "DskillA"}
# The advanced sheet's ability column.
ADVANCED_COLUMN = "Advanced"
REQUIRED_ABILITY_COLUMNS = {"Role", "Ability"}
REQUIRED_ADVANCED_COLUMNS = {"player_id", ADVANCED_COLUMN}
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
    read as a formula. The escape is in the export and is not part of
    the ability.

    **Every ability column, not only the abbreviations.** It was on the
    abbreviations alone, because those were where the "+3"s were first
    noticed -- and the Striker's *sentence* starts "+3" too, so it went
    into `players.json` as "`+3 for scoring off a set up." and printed
    that way on the maneuver card, the roster and the rules listing.
    Whether a given cell carries the guard is the spreadsheet's
    business and not something to predict: the Midfielder's sentence
    also starts "+3" and is stored without one. So this is applied to
    anything that might be an ability rather than to the columns
    somebody has checked.
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


def slugify_name(name: str) -> str:
    return name.strip().lower()


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


def parse_advanced_skill(raw_value: str, field: str, player_id: str) -> int:
    """
    An advanced skill score is not held to 1-6, and a player's two
    need not sum to 7: the sheet has a fullback at 0 and 8. Only that
    it is a whole number and not negative.
    """
    try:
        value = int(float(raw_value))
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"{player_id}: {field} must be a whole number."
        ) from error

    if value < 0:
        raise ValueError(f"{player_id}: {field} must not be negative.")

    return value


def import_abilities(
    rows: Iterable[dict[str, str]],
    short_column: str,
) -> dict[str, RoleAbility]:
    abilities: dict[str, RoleAbility] = {}

    for row_number, row in enumerate(rows, start=2):
        role = (row.get("Role") or "").strip().lower()
        ability = strip_formula_escape((row.get("Ability") or "").strip())
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


def import_advanced(rows: Iterable[dict[str, str]]) -> dict[str, str]:
    """
    Read the advanced sheet's abilities, keyed by player id. A blank
    `Advanced` is a player with no advanced ability yet, which is not
    an error.
    """
    advanced: dict[str, str] = {}

    for row in rows:
        player_id = (row.get("player_id") or "").strip()
        if not player_id:
            continue
        if player_id in advanced:
            raise ValueError(
                f"Duplicate player_id in the advanced sheet: {player_id}"
            )

        advanced[player_id] = strip_formula_escape(
            (row.get(ADVANCED_COLUMN) or "").strip()
        )

    return advanced


def advanced_skills(
    row: dict[str, str], player_id: str, basic: dict[str, int],
) -> dict[str, int]:
    """
    The player cards sheet's `OskillA` and `DskillA`, as only the
    scores that differ from the basic ones. The sheet shows the basic
    score where a player has no advanced one, and in `players.json` an
    absent key means the basic score, so the two say the same thing; a
    blank cell means it too.
    """
    skills = {}
    for stat, column in ADVANCED_SKILL_COLUMNS.items():
        raw = (row.get(column) or "").strip()
        if not raw:
            continue
        value = parse_advanced_skill(raw, column, player_id)
        if value != basic[stat]:
            skills[stat] = value
    return skills


def import_players(
    rows: Iterable[dict[str, str]],
    images_folder: Path,
    data_version: int,
    role_abilities: dict[str, RoleAbility],
    abilities_source: str = DEFAULT_ABILITIES_SOURCE,
    advanced: dict[str, str] | None = None,
    advanced_source: str = DEFAULT_ADVANCED_SOURCE,
) -> dict:
    """
    Read the player cards sheet into the flat-players + eight-rosters
    shape `load_player_catalog` expects -- see "Team colors" and the
    "Player species" in docs/design/teams-and-players.md.

    Each row still declares exactly one color team (`Team`) and one
    species (`Species`); `players_by_team` and `players_by_species_team`
    are built from the same 36 rows, so a player's id ends up named by
    both rosters without its record ever being written out twice.

    Every ability comes from the abilities sheets: `role_abilities` is
    the basic_abilities sheet by role, and `advanced` the advanced
    sheet's abilities by player id -- a player it does not name has no
    advanced ability. The cards sheet's own ability columns are the
    card's rendering of those and are ignored; its `OskillA` and
    `DskillA` are the advanced scores (see `advanced_skills`).
    """
    flat_players: dict[str, dict] = {}
    players_by_team: dict[str, list[str]] = defaultdict(list)
    players_by_species_team: dict[str, list[str]] = defaultdict(list)
    role_profiles: dict[str, dict] = {}
    player_names: set[str] = set()
    if advanced is None:
        advanced = {}

    for row_number, row in enumerate(rows, start=2):
        role = (row.get("Role") or "").strip().lower()
        if role == "backside":
            continue

        player_id = (row.get("player_id") or "").strip()
        name = (row.get("Name") or "").strip()
        team = (row.get("Team") or "").strip().lower()
        species = (row.get("Species") or "").strip().lower().replace(" ", "_")

        if not name:
            raise ValueError(f"Row {row_number}: Name is required.")
        if not role:
            raise ValueError(f"{name}: Role is required.")
        if role not in EXPECTED_ROLE_COUNTS:
            raise ValueError(f"{name}: unknown role {role!r}.")
        if team not in EXPECTED_TEAMS:
            raise ValueError(f"{name}: unknown team {team!r}.")
        if species not in EXPECTED_SPECIES:
            raise ValueError(f"{name}: unknown species {species!r}.")

        # An id is `{slugified name}_{role}` -- globally unique without a
        # team prefix, since the reshuffle means a player's own color
        # team is no longer part of their identity (see "Team colors" and
        # the "Team colors" in docs/design/teams-and-players.md). Checked exactly
        # rather than merely pattern-matched, the same way the old prefix
        # rule was: this is what catches the sheet's player_id column
        # drifting from a renamed player or a re-keyed role.
        expected_id = f"{slugify_name(name)}_{role}"
        if not player_id:
            raise ValueError(f"{name}: player_id is required.")
        if player_id != expected_id:
            raise ValueError(
                f"{name}: player_id is {player_id!r}, expected "
                f"{expected_id!r} ('{{slugified name}}_{{role}}')."
            )
        if player_id in flat_players:
            raise ValueError(f"Duplicate player_id: {player_id}")

        ability = role_abilities[role]

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

        player_names.add(name)
        flat_players[player_id] = {
            "name": name,
            "role": role,
            "species": species,
            "stat_overrides": {},
            "advanced_ability": advanced.get(player_id, ""),
            "advanced_skills": advanced_skills(
                row, player_id, {"offense": offense, "defense": defense},
            ),
        }
        players_by_team[team].append(player_id)
        players_by_species_team[SPECIES_TEAM[species]].append(player_id)

    if set(players_by_team) != EXPECTED_TEAMS:
        raise ValueError(
            "The spreadsheet must contain Orange, Teal, Purple, and Slime."
        )
    if set(players_by_species_team) != set(SPECIES_TEAM.values()):
        raise ValueError(
            "The spreadsheet must contain every species: "
            + ", ".join(sorted(SPECIES_TEAM))
        )

    # Both axes -- a coach's color team and their species team -- are
    # nine players in the standard 1/2/1/2/1/2 distribution, and neither
    # roster may be checked without the other: a color team getting this
    # right says nothing about the species teams it was drawn from, and
    # the reverse.
    for roster_label, rosters in (
        ("color", players_by_team),
        ("species", players_by_species_team),
    ):
        for team, ids in rosters.items():
            # Not team_display_name (d12ball.game): this script reads a
            # CSV and writes JSON with no other dependency on the
            # package, and a team here is a plain key string, not a
            # Team. Same fix, though -- "fire_demons".title() is
            # "Fire_Demons" same as everywhere else this bug showed up.
            team_label = team.replace("_", " ").title()
            if len(ids) != 9:
                raise ValueError(
                    f"{team_label} ({roster_label} team) must have "
                    f"exactly 9 players; found {len(ids)}."
                )
            role_counts = Counter(flat_players[pid]["role"] for pid in ids)
            if role_counts != Counter(EXPECTED_ROLE_COUNTS):
                raise ValueError(
                    f"{team_label} ({roster_label} team) has the wrong "
                    f"role distribution: {dict(role_counts)}."
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
        team: {"player_ids": players_by_team[team]}
        for team in ("orange", "teal", "purple", "slime")
    } | {
        team: {"player_ids": players_by_species_team[team]}
        for team in (
            "fire_demons", "cyborgs", "telekinetics", "oozes",
        )
    }
    ordered_profiles = {
        role: role_profiles[role]
        for role in EXPECTED_ROLE_COUNTS
    }

    unknown_advanced = sorted(set(advanced) - set(flat_players))
    if unknown_advanced:
        raise ValueError(
            "The advanced sheet names players the player cards sheet "
            "does not have: " + ", ".join(unknown_advanced)
        )

    return {
        "data_version": data_version,
        "source": DEFAULT_SOURCE,
        "abilities_source": abilities_source,
        "advanced_source": advanced_source,
        "role_profiles": ordered_profiles,
        "players": dict(sorted(flat_players.items())),
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
            "public CSV URL for the basic_abilities sheet."
        ),
    )
    parser.add_argument(
        "--advanced",
        default=DEFAULT_ADVANCED_SOURCE,
        help=(
            "Where the advanced abilities come from: a local CSV path or "
            "public CSV URL for the advanced_abilities sheet."
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

    advanced_reader = strip_header_names(
        csv.DictReader(io.StringIO(read_source(args.advanced)))
    )
    missing_columns = sorted(
        REQUIRED_ADVANCED_COLUMNS - set(advanced_reader.fieldnames or [])
    )
    if missing_columns:
        raise ValueError(
            "Advanced sheet is missing columns: " + ", ".join(missing_columns)
        )
    advanced = import_advanced(advanced_reader)

    source_text = read_source(args.source)
    reader = strip_header_names(csv.DictReader(io.StringIO(source_text)))
    columns = set(reader.fieldnames or [])
    missing_columns = sorted(REQUIRED_COLUMNS - columns)
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
        abilities_source=DEFAULT_ABILITIES_SOURCE,
        advanced=advanced,
        advanced_source=DEFAULT_ADVANCED_SOURCE,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {args.output} with "
        f"{len(output['players'])} players across "
        f"{len(output['teams'])} teams."
    )


if __name__ == "__main__":
    main()

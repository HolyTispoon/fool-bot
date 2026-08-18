"""
Reading the abilities sheet, including the two things about it that a
plain csv.DictReader gets wrong.

The sheet spells the short-form column "Abbreivated" and stores that
header with a trailing space, so the name has to be matched loosely.
And a cell whose text starts with "+3" is typed with a leading
backtick, or a spreadsheet reads it as a formula -- the escape is in
the CSV export and is not part of the ability.

See scripts/import_d12ball_players.py, and "The rules" in CLAUDE.md for
where the sheet lives.
"""

import csv
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

from d12ball.components import RoleProfile, load_player_catalog


def load_import_script():
    """
    scripts/ is a folder of tools rather than a package, so the module
    is loaded by path.
    """
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "import_d12ball_players.py"
    )
    spec = importlib.util.spec_from_file_location(
        "import_d12ball_players", path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


importer = load_import_script()

# The real sheet's header and two of its rows, quirks and all.
ABILITIES_CSV = (
    "Role,Ability,Abbreivated \r\n"
    "Fullback,\"Can pass up to 4 with a high pass. When resolving block "
    "deflect, ball goes back 2 spaces.\",High pass: up to 4; Block "
    "Deflect: back 2.\r\n"
    "Defender,Steals the ball when resolving Pressure.,Steals when "
    "pressures\r\n"
    "Midfielder,Gain +3 for skill tests when attempting low pass or "
    "pressure.,`+3 for low pass/pressure\r\n"
    "Playmaker,May advance 2 spaces when resolving Dribble advance.,"
    "Dribble Advance up to 2\r\n"
    "Winger,May set up a scoring opportunity with a low pass.,May set up "
    "with low pass\r\n"
    "Striker,Gain +3 for scoring attempts off a set up.,`+3 for scoring "
    "off setup\r\n"
)


def read_abilities(text: str = ABILITIES_CSV):
    reader = importer.strip_header_names(csv.DictReader(io.StringIO(text)))
    column = importer.abbreviated_column(reader.fieldnames or [])
    return importer.import_abilities(reader, column)


class AbilitiesSheetTests(unittest.TestCase):
    def test_the_short_column_is_found_despite_its_spelling(self) -> None:
        reader = importer.strip_header_names(
            csv.DictReader(io.StringIO(ABILITIES_CSV))
        )

        self.assertEqual(
            importer.abbreviated_column(reader.fieldnames), "Abbreivated",
        )

    def test_the_correct_spelling_is_accepted_too(self) -> None:
        # So that fixing the typo upstream doesn't break the import.
        fixed = ABILITIES_CSV.replace("Abbreivated ", "Abbreviated", 1)
        reader = importer.strip_header_names(csv.DictReader(io.StringIO(fixed)))

        self.assertEqual(
            importer.abbreviated_column(reader.fieldnames), "Abbreviated",
        )

    def test_a_missing_short_column_is_not_found(self) -> None:
        without = "Role,Ability\r\nDefender,Steals the ball.\r\n"
        reader = importer.strip_header_names(
            csv.DictReader(io.StringIO(without))
        )

        self.assertIsNone(importer.abbreviated_column(reader.fieldnames))

    def test_both_forms_of_every_ability_are_read(self) -> None:
        abilities = read_abilities()

        self.assertEqual(set(abilities), set(importer.EXPECTED_ROLE_COUNTS))
        self.assertEqual(
            abilities["defender"].text,
            "Steals the ball when resolving Pressure.",
        )
        self.assertEqual(abilities["defender"].short, "Steals when pressures")

    def test_the_formula_escape_is_not_part_of_the_ability(self) -> None:
        abilities = read_abilities()

        self.assertEqual(
            abilities["midfielder"].short, "+3 for low pass/pressure",
        )
        self.assertEqual(abilities["striker"].short, "+3 for scoring off setup")

    def test_a_role_without_a_short_form_is_an_error(self) -> None:
        # Better here than at render time, where all that can be done
        # about it is to draw the sentence and hope it fits.
        blank = ABILITIES_CSV.replace(",Steals when pressures", ",")

        with self.assertRaises(ValueError) as caught:
            read_abilities(blank)

        self.assertIn("Abbreivated", str(caught.exception))

    def test_only_a_real_formula_escape_is_stripped(self) -> None:
        # A backtick that isn't shielding a +, - or = is somebody's
        # punctuation, and stays.
        self.assertEqual(importer.strip_formula_escape("`+3 sharp"), "+3 sharp")
        self.assertEqual(importer.strip_formula_escape("'=1 each"), "=1 each")
        self.assertEqual(importer.strip_formula_escape("`code` style"),
                         "`code` style")
        self.assertEqual(importer.strip_formula_escape(""), "")


class ShortAbilityTests(unittest.TestCase):
    def test_the_short_form_falls_back_to_the_sentence(self) -> None:
        # A players.json written before the column existed still loads,
        # and every caller still has something to draw.
        profile = RoleProfile(offense=3, defense=4, ability="Does a thing.")

        self.assertEqual(profile.short_ability, "Does a thing.")

    def test_the_short_form_is_used_when_there_is_one(self) -> None:
        profile = RoleProfile(
            offense=3, defense=4, ability="Does a thing.", ability_short="Thing",
        )

        self.assertEqual(profile.short_ability, "Thing")

    def test_every_role_in_the_shipped_catalog_has_one(self) -> None:
        catalog = load_player_catalog()

        for role, profile in catalog.role_profiles.items():
            with self.subTest(role=role):
                self.assertTrue(profile.ability_short)
                self.assertLess(
                    len(profile.ability_short), len(profile.ability),
                )


def build_roster_rows(species_forms):
    """
    A full 36-player roster -- the minimum import_players will accept,
    since it checks every one of the eight rosters (four color teams,
    four species teams) has exactly 9 in the right role counts. Species
    is what varies per test; everything else is just enough to be
    valid. `species_forms` cycling every 4 rows against 9-player teams
    happens to give each species the standard 1/2/1/2/1/2 distribution
    too -- verified, not assumed, since the importer now checks that
    axis as well.

    The id is derived the way the importer itself derives one
    (`{slug(name)}_{role}`), rather than hand-encoded here, so this
    fixture cannot drift from the scheme it is testing.
    """
    role_counts = (
        ("fullback", 1), ("defender", 2), ("midfielder", 1),
        ("playmaker", 2), ("winger", 1), ("striker", 2),
    )
    rows = []
    index = 0
    for team in ("orange", "teal", "purple", "slime"):
        for role, count in role_counts:
            for slot in range(count):
                name = f"{team}_{role}{slot}"
                rows.append({
                    "player_id": f"{importer.slugify_name(name)}_{role}",
                    "Name": name,
                    "Team": team,
                    "Species": species_forms[index % len(species_forms)],
                    "Role": role,
                    "Oskill": "3",
                    "Dskill": "3",
                    "Basic": "",
                })
                index += 1
    return rows


ROLE_ABILITIES = {
    role: importer.RoleAbility(text=f"{role} ability.", short=f"{role} short")
    for role in importer.EXPECTED_ROLE_COUNTS
}


class SpeciesImportTests(unittest.TestCase):
    def test_species_is_normalized_from_the_sheet(self) -> None:
        rows = build_roster_rows(
            ["Fire Demon", "CYBORG", " telekinetic ", "Ooze"]
        )
        with tempfile.TemporaryDirectory() as images_dir:
            images_folder = Path(images_dir)
            for row in rows:
                (images_folder / f"{row['Name']}.png").touch()

            output = importer.import_players(
                rows, images_folder, data_version=1,
                role_abilities=ROLE_ABILITIES, abilities_source="test",
            )

        players = output["players"]
        self.assertEqual(
            players["orange_fullback0_fullback"]["species"], "fire_demon",
        )
        self.assertEqual(
            players["orange_defender0_defender"]["species"], "cyborg",
        )
        self.assertEqual(
            players["orange_defender1_defender"]["species"], "telekinetic",
        )
        self.assertEqual(
            players["orange_midfielder0_midfielder"]["species"], "ooze",
        )

    def test_an_unknown_species_is_rejected(self) -> None:
        rows = build_roster_rows(["Robot"])

        with self.assertRaises(ValueError) as caught:
            # The species check comes before the image lookup, so a
            # bad row is caught without any images existing at all.
            importer.import_players(
                rows, Path("/nonexistent"), data_version=1,
                role_abilities=ROLE_ABILITIES, abilities_source="test",
            )

        self.assertIn("orange_fullback0", str(caught.exception))
        self.assertIn("species", str(caught.exception))


class DualRosterValidationTests(unittest.TestCase):
    """
    The importer's own checks, previously untested altogether: the two
    id/team invariants that only the reshuffle introduced. See "Team
    colors" and the player-catalog notes in CLAUDE.md.
    """

    def _import(self, rows):
        with tempfile.TemporaryDirectory() as images_dir:
            images_folder = Path(images_dir)
            for row in rows:
                (images_folder / f"{row['Name']}.png").touch()
            return importer.import_players(
                rows, images_folder, data_version=1,
                role_abilities=ROLE_ABILITIES, abilities_source="test",
            )

    def test_a_valid_roster_produces_eight_teams_of_nine(self) -> None:
        rows = build_roster_rows(
            ["Fire Demon", "Cyborg", "Telekinetic", "Ooze"]
        )
        output = self._import(rows)

        self.assertEqual(len(output["players"]), 36)
        self.assertEqual(
            set(output["teams"]),
            {
                "orange", "teal", "purple", "slime",
                "fire_demons", "cyborgs", "telekinetics", "oozes",
            },
        )
        for team, roster in output["teams"].items():
            with self.subTest(team=team):
                self.assertEqual(len(roster["player_ids"]), 9)
                self.assertEqual(len(set(roster["player_ids"])), 9)

    def test_a_player_id_must_match_the_slug_and_role(self) -> None:
        rows = build_roster_rows(
            ["Fire Demon", "Cyborg", "Telekinetic", "Ooze"]
        )
        rows[0]["player_id"] = "not_the_expected_id"

        with self.assertRaises(ValueError) as caught:
            self._import(rows)

        self.assertIn("expected", str(caught.exception))

    def test_a_team_short_a_species_role_is_rejected(self) -> None:
        # Every row the same species, so one species team gets all 36
        # and the other three get none -- the color teams are still
        # individually fine, so only the species-axis check should
        # catch this.
        rows = build_roster_rows(["Fire Demon"])

        with self.assertRaises(ValueError) as caught:
            self._import(rows)

        self.assertIn("every species", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

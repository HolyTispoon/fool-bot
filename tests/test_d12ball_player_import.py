"""
Reading the abilities sheets, including the things about them that a
plain csv.DictReader gets wrong.

The sheet spelled the short-form column "Abbreivated" for a while and
stored that header with a trailing space, so the name is matched
loosely still. A cell whose text starts with "+3" may be typed with a
leading backtick, or a spreadsheet reads it as a formula -- the escape
is in the CSV export and is not part of the ability. **It is on
sentences as well as abbreviations**, and not predictably: the
Striker's sentence carries one and the Midfielder's, which also starts
"+3", does not. So every ability column is stripped rather than the
ones somebody has checked.

The player cards sheet is the roster and the scores -- who is on which
team, in which role, with which basic and advanced scores -- and its
ability columns are the card's rendering of the abilities sheets, so
they are neither read nor checked (the author, 2026-09-24).

See scripts/import_d12ball_players.py, and "The rules" in docs/design/rules-and-data.md for
where the sheets live.
"""

import csv
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

from d12ball.components import (
    PlayerDefinition,
    PlayerRole,
    RoleProfile,
    load_player_catalog,
)


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

# The real sheet's header and its rows, quirks and all -- with the
# short-form column as it was spelled and stored when the quirks were
# found, since the loose match is what those tests are about.
ABILITIES_CSV = (
    "Role,Initials,Ability,Abbreivated \r\n"
    "Fullback,FB,\"Can pass up to 4 with a high pass. When resolving block "
    "deflect, ball goes back 2 spaces.\",High pass: up to 4; Block "
    "Deflect: back 2.\r\n"
    "Defender,DD,Steals the ball when resolving Pressure.,Steals when "
    "pressures\r\n"
    "Midfielder,MF,Gain +3 for skill tests when attempting low pass or "
    "pressure.,`+3 for low pass/pressure\r\n"
    "Playmaker,PM,May advance 2 spaces when resolving Dribble advance.,"
    "Dribble Advance up to 2\r\n"
    "Winger,WG,May set up a scoring opportunity with a low pass.,May set up "
    "with low pass\r\n"
    # The Striker's *sentence* carries the escape too, exactly as the
    # real sheet stores it. It was the case nothing stripped, so it
    # reached players.json and printed on the maneuver card.
    "Striker,SK,`+3 for scoring attempts off a set up.,`+3 for scoring "
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

    def test_the_escape_is_stripped_from_the_sentence_as_well(self) -> None:
        # The half that was missed. A short form is only ever drawn
        # next to a portrait; the sentence is what the maneuver card,
        # the roster and the rules listing print, so a stray backtick
        # there is the more visible of the two.
        abilities = read_abilities()

        self.assertEqual(
            abilities["striker"].text, "+3 for scoring attempts off a set up.",
        )

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

    def test_no_shipped_ability_carries_a_formula_escape(self) -> None:
        """
        Asked of the data rather than of the importer, because the
        importer was only half wrong: it stripped the abbreviations and
        not the sentences, so every test about it passed while the
        Striker's sentence shipped as "`+3 for scoring off a set up."
        and printed that way on the High Pass card.

        This is the assertion that would have caught it, and it catches
        the next column somebody adds without asking.
        """
        catalog = load_player_catalog()

        for role, profile in catalog.role_profiles.items():
            for label, text in (
                ("ability", profile.ability),
                ("ability_short", profile.ability_short),
            ):
                with self.subTest(role=role, field=label):
                    self.assertEqual(
                        text, importer.strip_formula_escape(text),
                    )
                # Never longer, rather than strictly shorter: a sentence
                # that already fits (the Fullback's, since 2026-09-20)
                # is its own abbreviation, and the sheet says so by
                # carrying it in both columns.
                self.assertLessEqual(
                    len(profile.ability_short), len(profile.ability),
                )


def build_roster_rows(species_forms, card_columns=False):
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

    `OskillA`/`DskillA` show the basic score, the way the sheet does
    for a player with no advanced one. With `card_columns`, each row
    also carries the card's wording of its abilities -- `Basic` and
    `Advanced` -- saying something else, which the importer ignores.
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
                row = {
                    "player_id": f"{importer.slugify_name(name)}_{role}",
                    "Name": name,
                    "Team": team,
                    "Species": species_forms[index % len(species_forms)],
                    "Role": role,
                    "Oskill": "3",
                    "Dskill": "3",
                    "OskillA": "3",
                    "DskillA": "3",
                }
                if card_columns:
                    row["Basic"] = f"XX: not the {role} ability."
                    row["Advanced"] = "XX. \nNot the advanced ability."
                rows.append(row)
                index += 1
    return rows


ROLE_ABILITIES = {
    role: importer.RoleAbility(
        text=f"{role} ability.",
        short=f"{role} short",
    )
    for role in importer.EXPECTED_ROLE_COUNTS
}

# The advanced sheet as it is filled today: most rows blank, and the
# score columns it still carries, which the importer does not read --
# the advanced scores are the player cards sheet's.
ADVANCED_CSV = (
    "player_id,Name,Role,Advanced,OskillA,DskillA\r\n"
    "orange_fullback0_fullback,orange_fullback0,Fullback,High defensive "
    "skill.,0,8\r\n"
    "orange_defender0_defender,orange_defender0,Defender,Always Blazes "
    "(no burn).,,\r\n"
    "orange_midfielder0_midfielder,orange_midfielder0,Midfielder,`+3 for "
    "Mind Pull. ,,\r\n"
    "orange_striker0_striker,orange_striker0,Striker,,,4\r\n"
    "teal_defender1_defender,teal_defender1,Defender,,,\r\n"
)


def set_advanced_scores(rows, player_id, offense, defense):
    row = next(row for row in rows if row["player_id"] == player_id)
    row["OskillA"] = offense
    row["DskillA"] = defense


def read_advanced(text: str = ADVANCED_CSV):
    reader = importer.strip_header_names(csv.DictReader(io.StringIO(text)))
    return importer.import_advanced(reader)


def import_roster(rows, advanced=None):
    with tempfile.TemporaryDirectory() as images_dir:
        images_folder = Path(images_dir)
        for row in rows:
            (images_folder / f"{row['Name']}.png").touch()
        return importer.import_players(
            rows, images_folder, data_version=1,
            role_abilities=ROLE_ABILITIES, abilities_source="test",
            advanced=advanced, advanced_source="advanced-test",
        )


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
    colors" and "Player species" in docs/design/teams-and-players.md.
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


class CardColumnsTests(unittest.TestCase):
    """
    The player cards sheet's `Basic` and `Advanced` are what the card
    prints. The abilities sheets are the source of truth, so the card's
    copies are ignored -- a card that says something else is not an
    error and does not reach the output.
    """

    def test_the_card_ability_columns_are_ignored(self) -> None:
        rows = build_roster_rows(
            ["Fire Demon", "Cyborg", "Telekinetic", "Ooze"],
            card_columns=True,
        )

        output = import_roster(rows, advanced=read_advanced())

        self.assertEqual(
            output["role_profiles"]["defender"]["ability"],
            "defender ability.",
        )
        self.assertEqual(
            output["players"]["orange_defender0_defender"]["advanced_ability"],
            "Always Blazes (no burn).",
        )


class AdvancedSheetTests(unittest.TestCase):
    def test_a_row_is_its_ability(self) -> None:
        advanced = read_advanced()

        self.assertEqual(
            advanced["orange_fullback0_fullback"], "High defensive skill.",
        )
        self.assertEqual(
            advanced["orange_defender0_defender"], "Always Blazes (no burn).",
        )
        self.assertEqual(advanced["teal_defender1_defender"], "")

    def test_the_escape_and_the_padding_are_not_the_ability(self) -> None:
        advanced = read_advanced()

        self.assertEqual(
            advanced["orange_midfielder0_midfielder"], "+3 for Mind Pull.",
        )

    def test_the_score_columns_are_not_required(self) -> None:
        advanced = read_advanced(
            "player_id,Advanced\r\n"
            "orange_fullback0_fullback,High defensive skill.\r\n"
        )

        self.assertEqual(
            advanced, {"orange_fullback0_fullback": "High defensive skill."},
        )

    def test_an_advanced_row_for_an_unknown_player_is_rejected(self) -> None:
        rows = build_roster_rows(["Fire Demon", "Cyborg", "Telekinetic", "Ooze"])
        advanced = read_advanced(
            "player_id,Advanced\r\n"
            "nobody_striker,Scores from anywhere.\r\n"
        )

        with self.assertRaises(ValueError) as caught:
            import_roster(rows, advanced=advanced)

        self.assertIn("nobody_striker", str(caught.exception))


class AdvancedScoresTests(unittest.TestCase):
    """
    The advanced scores are the player cards sheet's `OskillA` and
    `DskillA`. The sheet shows the basic score where there is no
    advanced one, and `players.json` keeps only the scores that differ.
    """

    def _rows(self):
        return build_roster_rows(
            ["Fire Demon", "Cyborg", "Telekinetic", "Ooze"],
        )

    def test_the_advanced_data_is_written_per_player(self) -> None:
        rows = self._rows()
        set_advanced_scores(rows, "orange_fullback0_fullback", "0", "8")
        set_advanced_scores(rows, "orange_striker0_striker", "3", "4")

        output = import_roster(rows, advanced=read_advanced())

        players = output["players"]
        self.assertEqual(
            players["orange_fullback0_fullback"]["advanced_ability"],
            "High defensive skill.",
        )
        self.assertEqual(
            players["orange_fullback0_fullback"]["advanced_skills"],
            {"offense": 0, "defense": 8},
        )
        self.assertEqual(
            players["orange_striker0_striker"]["advanced_skills"],
            {"defense": 4},
        )
        self.assertEqual(
            players["orange_striker0_striker"]["advanced_ability"], "",
        )
        # A player the advanced sheet leaves blank, and one it does
        # not name at all, come out the same.
        for player_id in (
            "teal_defender1_defender", "purple_winger0_winger",
        ):
            with self.subTest(player_id=player_id):
                self.assertEqual(players[player_id]["advanced_ability"], "")
                self.assertEqual(players[player_id]["advanced_skills"], {})
        self.assertEqual(output["advanced_source"], "advanced-test")

    def test_the_advanced_sheet_scores_are_not_read(self) -> None:
        # ADVANCED_CSV gives the fullback 0 and 8; the player cards
        # sheet, which is the one read, gives the basic 3 and 3.
        output = import_roster(self._rows(), advanced=read_advanced())

        self.assertEqual(
            output["players"]["orange_fullback0_fullback"]["advanced_skills"],
            {},
        )

    def test_a_blank_score_is_the_basic_score(self) -> None:
        rows = self._rows()
        set_advanced_scores(rows, "orange_fullback0_fullback", "", "8")

        output = import_roster(rows)

        self.assertEqual(
            output["players"]["orange_fullback0_fullback"]["advanced_skills"],
            {"defense": 8},
        )

    def test_a_score_must_be_a_whole_number(self) -> None:
        rows = self._rows()
        set_advanced_scores(rows, "orange_fullback0_fullback", "high", "8")

        with self.assertRaises(ValueError) as caught:
            import_roster(rows)

        self.assertIn("OskillA", str(caught.exception))

    def test_a_score_may_not_be_negative(self) -> None:
        rows = self._rows()
        set_advanced_scores(rows, "orange_fullback0_fullback", "-1", "8")

        with self.assertRaises(ValueError) as caught:
            import_roster(rows)

        self.assertIn("OskillA", str(caught.exception))


class AdvancedCatalogTests(unittest.TestCase):
    def test_the_fields_default_for_an_older_players_json(self) -> None:
        player = PlayerDefinition(
            player_id="x_striker", name="X", role=PlayerRole.STRIKER,
            stat_overrides={},
        )

        self.assertEqual(player.advanced_ability, "")
        self.assertEqual(player.advanced_skills, {})

    def test_the_shipped_catalog_carries_the_advanced_data(self) -> None:
        catalog = load_player_catalog()
        players = {
            player.player_id: player
            for roster in catalog.teams.values()
            for player in roster.players
        }

        with_ability = [
            player for player in players.values() if player.advanced_ability
        ]
        with_scores = [
            player for player in players.values() if player.advanced_skills
        ]
        self.assertTrue(with_ability)
        self.assertTrue(with_scores)
        for player in players.values():
            with self.subTest(player=player.player_id):
                self.assertEqual(
                    player.advanced_ability,
                    importer.strip_formula_escape(player.advanced_ability),
                )
                self.assertLessEqual(
                    set(player.advanced_skills), {"offense", "defense"},
                )
                for score in player.advanced_skills.values():
                    self.assertIsInstance(score, int)
                    self.assertGreaterEqual(score, 0)

    def test_the_advanced_data_changes_no_basic_profile(self) -> None:
        # Carried, not played: the effective profile is the basic one
        # for a player whose advanced scores are 0 and 8 as for anyone.
        catalog = load_player_catalog()
        for roster in catalog.teams.values():
            for player in roster.players:
                with self.subTest(player=player.player_id):
                    profile = catalog.effective_profile(player)
                    self.assertEqual(
                        profile, catalog.role_profiles[player.role],
                    )


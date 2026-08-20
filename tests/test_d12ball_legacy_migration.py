"""
The 2026-08-17 eight-team reshuffle broke every saved game outright.

Orange used to be Fire Demons' own roster; after the reshuffle it is a
mixed one, so a game saved with `orange_hellguard` on its board and
`"team": "orange"` on its side stopped matching the catalog the moment
this landed -- the live traceback pasted by the other developer was
`ValueError('The setup does not match the team roster.')` out of
`TeamSetup.validate`, raised by `/d12ball resume` on their in-progress
game.

`gamesaves.d12ball.storage.migrate_legacy_game_data` is the fix,
applied tolerantly on every load rather than as a one-time rewrite --
see the legacy-migration gotcha in CLAUDE.md. These build a synthetic
pre-reshuffle save by taking a real match played against the *current*
catalog (home = Fire Demons, visiting = Cyborgs -- species teams,
whose membership is exactly the old Orange/Teal rosters) and renaming
its ids and Team values backward onto their pre-reshuffle forms, so
the fixture is a real, validatable match wearing old names rather than
36 ids typed by hand.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from d12ball.components import (
    MatchState,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import Team
from gamesaves.d12ball import storage

# The mirror image of storage.LEGACY_COLOR_FOR_SPECIES, kept
# independent here rather than imported: these tests are proving the
# module's behavior from the outside, and importing its own answer key
# to build the fixture would let a bug in one hide behind the same bug
# in the other.
LEGACY_COLOR_FOR_SPECIES = {
    "fire_demon": "orange",
    "cyborg": "teal",
    "telekinetic": "purple",
    "ooze": "slime",
}


# The names these three players had before 36250a9 renamed them on
# 2026-08-17 -- a day before the reshuffle, and a separate break. Kept
# independent of storage.LEGACY_RENAMED_NAMES for the same reason the
# color table above is: a fixture built from the module's own answer
# key cannot catch the module being wrong.
NAMES_BEFORE_THE_RENAME = {
    "brightburn": "blazekick",
    "kindlefinger": "kindlefoot",
    "sizzifizik": "sizzik",
}


def legacy_id_for(player, before_the_rename: bool = False) -> str:
    name = player.name.lower()
    if before_the_rename:
        name = NAMES_BEFORE_THE_RENAME.get(name, name)
    return f"{LEGACY_COLOR_FOR_SPECIES[player.species]}_{name}"


def rename_ids(value, renames: dict[str, str]):
    """
    Walk a JSON-shaped value, rewriting every string (including dict
    keys) found in `renames`. Used both to build the legacy fixture
    (new ids -> old ids) and would equally well check a migration's
    output the other way -- the point is that one generic walk is
    exactly what a save's shape asks for, on both sides of this test.
    """
    if isinstance(value, str):
        return renames.get(value, value)
    if isinstance(value, list):
        return [rename_ids(item, renames) for item in value]
    if isinstance(value, dict):
        return {
            (renames.get(key, key) if isinstance(key, str) else key):
                rename_ids(item, renames)
            for key, item in value.items()
        }
    return value


class LegacyGameMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()
        cls.maneuvers = load_maneuver_catalog()

        # Cleared once per test class rather than per test: it is
        # rebuilt from the real catalog on first use and does not
        # change within a run, so there is nothing to isolate between
        # tests here -- and leaving it set is what lets
        # test_load_games_migrates_a_saved_legacy_game skip a real
        # players.json parse on top of the one setUpClass already did.
        storage._legacy_id_map = None

    def build_legacy_match_state(self, before_the_rename: bool = False) -> dict:
        """
        A pre-reshuffle save, optionally from before the three orange
        players were renamed as well -- which is a *second*, earlier
        break, and the one the migration shipped unable to handle.
        """
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.FIRE_DEMONS,
            visiting_team=Team.CYBORGS,
        )
        match.validate(self.catalog)
        data = match.to_dict()

        new_to_old = {
            player.player_id: legacy_id_for(
                player, before_the_rename=before_the_rename,
            )
            for roster in self.catalog.teams.values()
            for player in roster.players
            if player.species in LEGACY_COLOR_FOR_SPECIES
        }
        legacy_data = rename_ids(data, new_to_old)
        legacy_data["home"]["team"] = "orange"
        legacy_data["visiting"]["team"] = "teal"
        return legacy_data

    def build_legacy_game_data(self, before_the_rename: bool = False) -> dict:
        return {
            "game_id": "legacy-game",
            "game_number": 1,
            "guild_id": 1,
            "channel_id": 2,
            "message_id": None,
            "player_1_id": 111,
            "player_2_id": 222,
            "player_1_name": "One",
            "player_2_name": "Two",
            "player_1_team": "orange",
            "player_2_team": "teal",
            "home_player_number": 1,
            "visiting_player_number": 2,
            "match_state": self.build_legacy_match_state(
                before_the_rename=before_the_rename,
            ),
        }

    def test_the_unmigrated_save_fails_exactly_as_reported(self) -> None:
        # Proves the fixture is genuinely old-shaped by reproducing the
        # concrete traceback before checking the fix -- a passing
        # migration test means nothing if this half never actually
        # failed.
        legacy_match_state = self.build_legacy_match_state()
        match = MatchState.from_dict(legacy_match_state, self.rules)

        with self.assertRaises(ValueError) as caught:
            match.validate(self.catalog)

        self.assertEqual(
            str(caught.exception),
            "The setup does not match the team roster.",
        )

    def test_migration_remaps_ids_and_team(self) -> None:
        game_data = self.build_legacy_game_data()

        migrated = storage.migrate_legacy_game_data(game_data)

        self.assertEqual(migrated["player_1_team"], "fire_demons")
        self.assertEqual(migrated["player_2_team"], "cyborgs")
        self.assertEqual(
            migrated["match_state"]["home"]["team"], "fire_demons",
        )
        self.assertEqual(
            migrated["match_state"]["visiting"]["team"], "cyborgs",
        )

        match = MatchState.from_dict(migrated["match_state"], self.rules)
        match.validate(self.catalog)  # the traceback's exact call

        roster_ids = (
            match.home.field_players
            + match.home.team_board.bench
            + match.home.team_board.back_bench
            + match.visiting.field_players
            + match.visiting.team_board.bench
            + match.visiting.team_board.back_bench
        )
        self.assertEqual(len(roster_ids), 18)
        for player_id in roster_ids:
            with self.subTest(player_id=player_id):
                self.assertFalse(
                    player_id.startswith(
                        ("orange_", "teal_", "purple_", "slime_"),
                    ),
                )
                # Resolves in the current catalog -- the whole point.
                self.catalog.player_by_id(player_id)

    def test_a_save_older_than_the_rename_migrates_too(self) -> None:
        """
        The second live traceback: `/d12ball resume` on a game started
        before the eight-team split raised the same
        `ValueError('The setup does not match the team roster.')`, on
        the visiting side.

        Its ids carry the names three orange players had before
        36250a9, so the reconstruction -- which builds a legacy id out
        of a player's *current* name -- could not produce them. Six of
        that side's nine remapped and three did not, which is worse
        than none: the save still fails to load, and the traceback
        names nobody.
        """
        game_data = self.build_legacy_game_data(before_the_rename=True)

        home_ids = [
            player_id
            for zone in game_data["match_state"]["home"]["zones"].values()
            for player_id in zone
        ] + game_data["match_state"]["home"]["team_board"]["bench"]
        self.assertIn("orange_blazekick", home_ids)

        migrated = storage.migrate_legacy_game_data(game_data)
        match = MatchState.from_dict(migrated["match_state"], self.rules)
        match.validate(self.catalog)

        self.assertEqual(match.home.team, Team.FIRE_DEMONS)
        self.assertEqual(match.visiting.team, Team.CYBORGS)
        # The renamed three land on the players they became, not on
        # whoever happens to hold that roster slot now.
        self.assertIn(
            "brightburn_striker",
            match.home.field_players + match.home.team_board.bench,
        )

    def test_every_recorded_rename_names_a_player_who_exists(self) -> None:
        """
        A typo or a stale entry in the table would be silent: the old
        id simply would not map, which is the bug it was added to fix.
        """
        current_names = {
            player.name.lower()
            for roster in self.catalog.teams.values()
            for player in roster.players
        }
        self.assertTrue(storage.LEGACY_RENAMED_NAMES)
        for old_name, current_name in storage.LEGACY_RENAMED_NAMES.items():
            with self.subTest(old=old_name):
                self.assertIn(current_name, current_names)
                self.assertNotIn(old_name, current_names)

        # And they reach the map under their legacy color, which is
        # read off the species rather than written down beside them.
        legacy_ids = storage._build_legacy_id_map()
        for old_name in storage.LEGACY_RENAMED_NAMES:
            with self.subTest(old=old_name):
                self.assertIn(f"orange_{old_name}", legacy_ids)

    def test_a_half_migrated_save_says_so_in_the_log(self) -> None:
        """
        The next rename that nobody records should not come back as
        `The setup does not match the team roster.` with no name in
        it. A leftover legacy id *is* the diagnosis, so it goes to
        #logs -- an ERROR because somebody has to add the entry.
        """
        game_data = self.build_legacy_game_data()
        zones = game_data["match_state"]["home"]["zones"]
        first_zone = next(iter(zones))
        zones[first_zone][0] = "orange_someone_renamed_later"

        with self.assertLogs(storage.LOGGER, level="ERROR") as logged:
            storage.migrate_legacy_game_data(game_data)

        message = "\n".join(logged.output)
        self.assertIn("orange_someone_renamed_later", message)
        self.assertIn("LEGACY_RENAMED_NAMES", message)
        self.assertIn("legacy-game", message)

    def test_a_fully_migrated_save_logs_nothing(self) -> None:
        for before_the_rename in (False, True):
            with self.subTest(before_the_rename=before_the_rename):
                game_data = self.build_legacy_game_data(
                    before_the_rename=before_the_rename,
                )
                with mock.patch.object(storage.LOGGER, "error") as error:
                    storage.migrate_legacy_game_data(game_data)
                error.assert_not_called()

    def test_an_already_new_shape_save_is_untouched(self) -> None:
        # "orange" is a legal Team value both before and after the
        # reshuffle, just for a different roster -- so a fresh game
        # using the real new Orange must not be rewritten just because
        # its team value happens to be one of the four legacy names.
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.TEAL,
        )
        game_data = {
            "player_1_team": "orange",
            "player_2_team": "teal",
            "match_state": match.to_dict(),
        }

        migrated = storage.migrate_legacy_game_data(game_data)

        self.assertIs(migrated, game_data)

    def test_load_games_migrates_a_saved_legacy_game(self) -> None:
        # End to end through the real file-loading path, which is what
        # a restart actually does.
        legacy_game_data = self.build_legacy_game_data()

        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir) / "data"
            folder.mkdir()
            games_file = folder / "d12ball_games.json"
            games_file.write_text(
                json.dumps({"legacy-game": legacy_game_data}),
                encoding="utf-8",
            )

            with mock.patch.object(storage, "DATA_FOLDER", folder), \
                 mock.patch.object(storage, "GAMES_FILE", games_file):
                games = storage.load_games()

        game = games["legacy-game"]
        self.assertEqual(game.player_1_team, Team.FIRE_DEMONS)
        self.assertEqual(game.player_2_team, Team.CYBORGS)

        match = MatchState.from_dict(game.match_state, self.rules)
        match.validate(self.catalog)

    def test_a_migrated_match_plays_a_turn(self) -> None:
        for before_the_rename in (False, True):
            with self.subTest(before_the_rename=before_the_rename):
                self.play_a_turn(before_the_rename)

    def play_a_turn(self, before_the_rename: bool) -> None:
        game_data = self.build_legacy_game_data(
            before_the_rename=before_the_rename,
        )
        migrated = storage.migrate_legacy_game_data(game_data)
        match = MatchState.from_dict(migrated["match_state"], self.rules)
        match.validate(self.catalog)

        handler = match.turn_handler_candidates()[0]
        match.active_player_id = handler
        match.choose_offense_maneuver("dribble_advance")

        challenger = match.challenge_candidates()[0]
        match.choose_challenger(challenger)
        match.choose_defense_maneuver("pressure")

        self.assertTrue(match.maneuver_selections_complete)
        winner = self.maneuvers.resolve(
            match.offense_maneuver, match.defense_maneuver,
        )
        self.assertIn(winner, ("offense", "defense", "tie"))

        # Real id-keyed mutation, the kind an effect makes -- exactly
        # what a stray unmigrated id would raise on.
        match.set_ball_carrier(handler)
        match.add_exhaustion(challenger, 1)
        match.reset_maneuver()

        match.validate(self.catalog)  # still consistent afterward


if __name__ == "__main__":
    unittest.main()

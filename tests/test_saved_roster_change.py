"""
A game outlives a roster change.

Players move between teams in the sheet (Viscor and Gurgoth traded
Purple and Slime on 2026-09-30), and a game kicked off before the move
holds the side it was dealt. Loading used to check each saved side
against *today's* roster, so every in-progress game with either team
stopped loading the moment the import landed. A loaded match is now
checked against itself (`TeamSetup.validate_saved`), and against the
catalog roster only at kickoff -- see "A roster change and a saved
game" in docs/design/gotchas.md.

The move is built here rather than named: the test takes today's
catalog, trades one same-role pair between Purple and Slime backwards,
and deals the game on that. So it keeps working after the next import,
whoever moves.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from d12ball.ai import build_ai_strategies
from d12ball.components import (
    PLAYERS_FILE,
    MatchState,
    TeamSide,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.game import Team
from prompt_fixtures import CATALOG, MANEUVERS, RULESET

import test_driver_full_game as full_game


def traded_catalog(first: Team, second: Team):
    """
    Today's catalog with one same-role pair traded between two teams:
    the roster as it stood before a move. Returns the catalog and the
    two traded ids (first's player, second's player, as *today* has
    them).
    """
    data = json.loads(PLAYERS_FILE.read_text(encoding="utf-8"))
    teams = data["teams"]
    players = data["players"]
    one, two = teams[first.value]["player_ids"], teams[second.value]["player_ids"]
    for role in dict.fromkeys(players[pid]["role"] for pid in one):
        mine = [p for p in one if players[p]["role"] == role and p not in two]
        theirs = [p for p in two if players[p]["role"] == role and p not in one]
        if mine and theirs:
            a, b = mine[-1], theirs[-1]
            break
    else:
        raise AssertionError("no same-role pair to trade")
    one[one.index(a)] = b
    two[two.index(b)] = a
    folder = Path(tempfile.mkdtemp())
    path = folder / "players.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return load_player_catalog(path), a, b


def engine_for(catalog) -> RulesEngine:
    return RulesEngine(
        catalog, RULESET, MANEUVERS, build_ai_strategies(catalog, MANEUVERS),
    )


class SavedRosterChangeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.before, self.moved_in, self.moved_out = traded_catalog(
            Team.PURPLE, Team.SLIME,
        )
        # Dealt on the roster as it stood; the saved side holds the
        # player today's Purple no longer lists.
        match = MatchState.standard(
            catalog=self.before,
            ruleset=RULESET,
            board_size=7,
            home_team=Team.PURPLE,
            visiting_team=Team.SLIME,
        )
        self.game = full_game.build_game()
        self.game.player_1_team = Team.PURPLE
        self.game.player_2_team = Team.SLIME
        self.game.match_state = match.to_dict()
        self.engine = engine_for(CATALOG)

    def test_the_fixture_is_a_roster_today_does_not_match(self) -> None:
        # The half that makes the rest mean something: checked the way
        # a kickoff is, this save fails today.
        match = MatchState.from_dict(self.game.match_state, RULESET)
        self.assertIn(self.moved_out, match.home.team_board.bench
                      + match.home.field_players)
        with self.assertRaisesRegex(ValueError, "does not match the team roster"):
            match.validate(CATALOG)

    def test_a_game_saved_before_a_roster_change_loads(self) -> None:
        match = self.engine.load_match_state(self.game)
        self.assertEqual(match.team_for_player(self.moved_out), Team.PURPLE)
        self.assertEqual(match.team_for_player(self.moved_in), Team.SLIME)

    def test_the_roster_lists_the_side_it_holds(self) -> None:
        match = self.engine.load_match_state(self.game)
        for setup in (match.home, match.visiting):
            listed = [
                player_id
                for _, members in self.engine.roster_places(match, setup)
                for player_id, _ in members
            ]
            held = (
                setup.field_players
                + setup.team_board.bench
                + setup.team_board.back_bench
            )
            with self.subTest(team=setup.team):
                self.assertCountEqual(listed, held)

    def test_it_plays_to_the_end_and_the_last_save_loads(self) -> None:
        match = self.engine.load_match_state(self.game)
        game, final, _ = full_game.play(
            full_game.SEED, game=self.game, match=match,
        )
        self.assertTrue(game.is_finished)
        game.match_state = final.to_dict()
        self.engine.load_match_state(game)

    def test_a_card_nobody_knows_still_refuses(self) -> None:
        # A rename with no RENAMED_PLAYER_IDS entry must still fail
        # loudly rather than load a player the catalog cannot draw.
        state = json.loads(
            json.dumps(self.game.match_state).replace(
                self.moved_out, "nobody_defender",
            )
        )
        self.game.match_state = state
        with self.assertRaisesRegex(ValueError, "Unknown player"):
            self.engine.load_match_state(self.game)

    def test_a_side_short_of_a_card_still_refuses(self) -> None:
        match = MatchState.from_dict(self.game.match_state, RULESET)
        side = match.setup_for_side(TeamSide.HOME)
        side.team_board.bench.pop()
        self.game.match_state = match.to_dict()
        with self.assertRaisesRegex(ValueError, "does not match the team roster"):
            self.engine.load_match_state(self.game)

    def test_a_kickoff_still_checks_todays_roster(self) -> None:
        # The deal is the one place membership is still asked: a match
        # built on today's catalog for today's teams validates strictly.
        match = MatchState.standard(
            catalog=CATALOG,
            ruleset=RULESET,
            board_size=7,
            home_team=Team.PURPLE,
            visiting_team=Team.SLIME,
        )
        match.validate(CATALOG)


if __name__ == "__main__":
    unittest.main()

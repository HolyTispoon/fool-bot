"""
Whole basic games of TNP -- Blue against Green, Humans against Humans --
played through `tnp.flow.driver.apply` alone, from setup to a win: no
cog, no view, no Discord (docs/tnp-bot.md, step 4's stop).

It does what a frontend will: read the prompts open now -- both seats'
in Infrastructure and Deployment and in the trade -- build an action
off each prompt's options the way a view builds its controls, hand it
to `driver.apply`, and go again. **Every position round-trips through
its save** before the next question is read (`tnp_games.play`), the
restart written as a loop. The seats' strategies are `tnp_games`':

- **to a fallen base** (TNP 1.3, 6.10): Blue raids -- Workers
  harvesting beside its base pay for Mercenaries, one Mercenary a turn
  takes the road 10, 2, 1, 3, 11, and once it is held every Mercenary
  attacks Green's base -- against a Green that harvests and keeps its
  Mercenaries home;
- **to 51%** (TNP 1.3, 5.10): Blue harvests -- Workers to the richest
  territory it can reach, a Mercenary taking the territory that opens
  the way to more -- against the same Green, until 49 of the map's 96
  tokens are Blue's at Cleanup.

Both harvest tokens and trade them for materials. Run it with `-v` and
it prints each game's narration in plain words.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path

from tnp.components import HARVEST_TO_WIN, OVER, WON_BY_BASE, WON_BY_HARVEST
from tnp.prompts import pending_all
from tnp.tokens import plain

from tnp_games import Harvester, Raider, Turtle, opening, play

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SEED = 20261106
TURN_LIMIT = 20


def base_game(seed: int = SEED):
    engine, game, match = opening(seed)
    match, runs = play(engine, game, match, {"blue": Raider(), "green": Turtle()}, turns=TURN_LIMIT)
    return engine, game, match, runs


def harvest_game(seed: int = SEED):
    engine, game, match = opening(seed)
    match, runs = play(engine, game, match, {"blue": Harvester(), "green": Turtle()}, turns=TURN_LIMIT)
    return engine, game, match, runs


def transcript(engine, runs) -> list[str]:
    return [plain(line, engine.catalog) for run in runs for line in run.narration if line]


#: Run in a fresh interpreter: `unittest discover` has imported the cogs
#: and discord long before this test runs, so only a new process can say
#: the game needs neither.
ISOLATED = """
import sys
sys.path.insert(0, "tests")
import test_tnp_driver_full_game as full
results = [full.base_game()[2].winner, full.harvest_game()[2].winner]
leaked = sorted(name for name in sys.modules
                if name == "discord" or name.startswith("discord.")
                or name == "cogs" or name.startswith("cogs."))
print(repr((results, leaked)))
"""


class _Played:
    game_of = staticmethod(base_game)

    @classmethod
    def setUpClass(cls) -> None:
        cls.engine, cls.game, cls.match, cls.runs = cls.game_of()
        cls.lines = transcript(cls.engine, cls.runs)
        if "-v" in sys.argv or "--verbose" in sys.argv:
            print()
            for line in cls.lines:
                print("   ", line)

    def test_the_game_is_over_and_waits_on_nothing(self) -> None:
        self.assertEqual(self.match.phase, OVER)
        self.assertEqual(pending_all(self.engine, self.game, self.match), ())

    def test_both_seats_harvested_and_traded(self) -> None:
        said = " ".join(self.lines)
        for seat in ("Blue", "Green"):
            self.assertRegex(said, rf"{seat}'s \d+ Worker harvest area \d+", seat)
            self.assertRegex(said, rf"{seat} trades [^.]* for \d+ materials?", seat)
            self.assertGreater(self.match.seat(seat.lower()).harvested, 0)

    def test_nothing_planned_is_said_before_march(self) -> None:
        """A seat's queue and deployment are its own until March reveals
        a pile (TNP 5.2, 5.3): the plan phase and its reveal say who
        locked in and what was paid, and name no unit."""
        for run in self.runs:
            for line in run.narration:
                head = line.split("March begins.")[0]
                if "locks in" in head or "spends" in head:
                    self.assertNotIn("{unit:", head, line)

    def test_two_runs_on_one_seed_agree(self) -> None:
        _, _, again, runs = self.game_of()
        self.assertEqual(again.to_dict(), self.match.to_dict())
        self.assertEqual(transcript(self.engine, runs), self.lines)


class FallenBaseGameTests(_Played, unittest.TestCase):
    game_of = staticmethod(base_game)

    def test_blue_takes_greens_base(self) -> None:
        self.assertEqual((self.match.winner, self.match.won_by), ("blue", WON_BY_BASE))
        self.assertLessEqual(self.match.turn, TURN_LIMIT)
        self.assertIn("Blue wins the battle, and Green base falls.", " ".join(self.lines))

    def test_the_road_was_taken_a_territory_at_a_time(self) -> None:
        for area in ("10", "2", "1", "3", "11"):
            self.assertEqual(self.match.controller(area), "blue", area)


class HarvestGameTests(_Played, unittest.TestCase):
    game_of = staticmethod(harvest_game)

    def test_blue_harvests_51_percent(self) -> None:
        self.assertEqual((self.match.winner, self.match.won_by), ("blue", WON_BY_HARVEST))
        self.assertGreaterEqual(self.match.seat("blue").harvested, HARVEST_TO_WIN)
        self.assertLess(self.match.seat("green").harvested, HARVEST_TO_WIN)
        left = sum(area.tokens_left() for area in self.match.areas.values())
        taken = sum(self.match.seat(seat).harvested for seat in ("blue", "green"))
        self.assertEqual(left + taken, 96)

    def test_the_win_is_counted_at_cleanup(self) -> None:
        """TNP 1.3, 5.10: the game ends at Cleanup, after the trade, not
        as the 49th token is taken."""
        traded, won = self.lines[-2:]
        self.assertTrue(won.startswith("Blue wins the game") and won.endswith("51% of them."), won)
        self.assertIn("Blue trades ", traded)


class NoFrontendTests(unittest.TestCase):
    def test_the_games_need_no_frontend(self) -> None:
        probe = subprocess.run(
            [sys.executable, "-c", ISOLATED],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=300,
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        winners, leaked = ast.literal_eval(probe.stdout.strip().splitlines()[-1])
        self.assertEqual(winners, ["blue", "blue"])
        self.assertEqual(leaked, [])


del _Played

if __name__ == "__main__":
    unittest.main()

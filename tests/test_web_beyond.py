"""
What Discord has that the page lacked: abandoning a game, and the
statistics -- step 9 of docs/web-app-next.md ("Beyond the game" in
docs/design/web-app.md).

Each is a service door or a `d12ball/stats.py` reading the bot's
command calls too, so what is watched here is that the web app asks
the same question and decides nothing of its own:

- **Abandoning is `GameService.abandon`**, over the record's
  `abandon`, which refuses a game already over; a seat may abandon
  and an observer may not.
- **A game's numbers are `stats.game_tables`**, the tables `/d12ball
  stats game` posts, and every web game's are `stats.report_tables`
  over this process's own games, cut by kind. **The page never reads
  the bot's file**: any source but the web app's is a 400, and
  nothing here loads a games file at all.

Saves are counted, never written: the service here is handed a save
that touches no file.
"""

from __future__ import annotations

import unittest
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

from d12ball import stats
from d12ball.components import EVENT_MANEUVER, EVENT_TURN_ACTION, TeamSide
from d12ball.game import GameStatus
from d12ball.components import RuleRefusal
from gamelocks import GameLocks
from gamesaves.d12ball.service import GameService
from prompt_fixtures import ENGINE
from test_web_app import as_coach, case
from webapp.rooms import Rooms
from webapp.server import WebApp


WATCHER = 303


def played(fixture, *, guild_id=None):
    """A fixture's game with one maneuver turn in its log, as a web
    game (no guild) unless told otherwise."""
    match = fixture.match
    match.record_event(
        EVENT_TURN_ACTION,
        side=TeamSide.HOME,
        player_id="somebody",
        action="maneuver",
        by_ai=False,
        exhaustion={},
    )
    match.record_event(
        EVENT_MANEUVER,
        side=TeamSide.HOME,
        offense_key="low_pass",
        defense_key="deflect",
        winner_key="deflect",
        decision="cards",
    )
    game = fixture.game
    game.guild_id = guild_id
    game.channel_id = None
    game.match_state = match.to_dict()
    return game


class Harness(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        ENGINE.rng.seed(7)
        self.saves = 0

        def save(games) -> None:
            self.saves += 1

        self.games = {}
        self.service = GameService(ENGINE, self.games, save=save)
        self.web = WebApp(self.service, GameLocks(), rooms=Rooms())
        self.web.watch()
        self.client = TestClient(TestServer(self.web.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.addAsyncCleanup(self.web.stop)

    def file(self, game):
        self.games[game.game_id] = game
        return game

    async def get(self, path: str, coach_id=None):
        headers = {} if coach_id is None else as_coach(coach_id)
        return await self.client.get(path, headers=headers)


class AbandonTests(Harness):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.game = self.file(played(case("smooth")))
        self.room = self.game.game_id

    async def abandon(self, coach_id=None):
        headers = {} if coach_id is None else as_coach(coach_id)
        return await self.client.post(
            f"/api/room/{self.room}/abandon", headers=headers,
        )

    async def test_a_seat_abandons_the_game_and_the_room_stays(self) -> None:
        response = await self.abandon(self.game.player_1_id)
        self.assertEqual(response.status, 200, await response.text())
        state = await response.json()
        self.assertEqual(state["game"]["status"], "finished")
        self.assertTrue(state["game"]["abandoned"])
        self.assertEqual(self.game.status, GameStatus.FINISHED)
        self.assertTrue(self.game.abandoned)
        self.assertIn(self.room, self.games)
        self.assertEqual(self.saves, 1)
        # Nothing more is asked of it, and nothing more is played.
        self.assertEqual(state["prompt"]["kind"], "game_over")

    async def test_an_observer_may_not_and_nor_may_nobody(self) -> None:
        refused = await self.abandon(WATCHER)
        self.assertEqual(refused.status, 403)
        anonymous = await self.abandon()
        self.assertEqual(anonymous.status, 401)
        self.assertEqual(self.game.status, GameStatus.IN_PROGRESS)
        self.assertEqual(self.saves, 0)

    async def test_an_admin_without_a_seat_may_not(self) -> None:
        """An admin may close a room nobody played in, but only a
        coach ends a game that was (the author, 2026-09-26)."""
        self.web.rooms.make_admin(self.room, WATCHER)
        refused = await self.abandon(WATCHER)
        self.assertEqual(refused.status, 403)
        self.assertEqual(self.game.status, GameStatus.IN_PROGRESS)
        self.assertEqual(self.saves, 0)

    async def test_an_abandoned_game_offers_the_rematch(self) -> None:
        state = await (await self.abandon(self.game.player_1_id)).json()
        [control] = state["prompt"]["controls"][0]["controls"]
        self.assertEqual(
            (control["label"], control["post"]), ("Rematch", "/rematch"),
        )
        response = await self.client.post(
            f"/api/room/{self.room}/rematch",
            headers=as_coach(self.game.player_2_id),
        )
        self.assertEqual(response.status, 200, await response.text())
        self.assertIsNotNone((await response.json())["rematch"])

    async def test_a_game_already_over_is_the_record_s_refusal(self) -> None:
        await self.abandon(self.game.player_2_id)
        again = await self.abandon(self.game.player_1_id)
        self.assertEqual(again.status, 409)
        self.assertIn("already finished", await again.text())
        self.assertEqual(self.saves, 1)

    async def test_a_room_in_setup_may_be_abandoned_and_leaves_no_table(
        self,
    ) -> None:
        opened = await self.client.post(
            "/api/rooms", headers=as_coach(101, "Creator"),
        )
        room = (await opened.json())["id"]
        response = await self.client.post(
            f"/api/room/{room}/abandon", headers=as_coach(101),
        )
        self.assertEqual(response.status, 200, await response.text())
        state = await response.json()
        self.assertIsNone(state["table"])
        self.assertTrue(state["game"]["abandoned"])

        # The front door lists it as abandoned, under the finished.
        rooms = await (await self.get("/api/rooms", 101)).json()
        [listed] = rooms["mine"]["finished"]
        self.assertTrue(listed["abandoned"])


class RoomStatsTests(Harness):
    async def test_a_game_s_report_is_the_bot_s_tables(self) -> None:
        fixture = case("game over")
        game = self.file(played(fixture))
        response = await self.get(f"/api/room/{game.game_id}/stats", WATCHER)
        self.assertEqual(response.status, 200)
        report = await response.json()
        match = ENGINE.load_match_state(game)
        self.assertEqual(
            report["tables"],
            stats.game_tables(
                [match], ENGINE.maneuver_catalog, ENGINE.player_catalog,
            ),
        )
        self.assertTrue(report["tables"])
        self.assertEqual(report["standing"], "finished")
        self.assertIn("finished", report["heading"])

    async def test_a_game_nothing_was_played_in_has_no_tables(self) -> None:
        opened = await self.client.post(
            "/api/rooms", headers=as_coach(101, "Creator"),
        )
        room = (await opened.json())["id"]
        report = await (await self.get(f"/api/room/{room}/stats")).json()
        self.assertEqual(report["tables"], [])
        self.assertEqual(report["standing"], "in setup")


class AllStatsTests(Harness):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        human = played(case("smooth"))
        human.game_id = "human"
        self.file(human)
        solo = played(case("game over"))
        solo.game_id, solo.player_2_id = "solo", None
        self.file(solo)

    async def stats(self, query: str = ""):
        return await self.get(f"/api/stats{query}")

    async def test_every_web_game_by_kind(self) -> None:
        response = await self.stats()
        self.assertEqual(response.status, 200)
        report = await response.json()
        self.assertEqual(report["kind"], stats.SCOPE_ALL)
        self.assertIn("2 all games", report["heading"][0])
        self.assertEqual(
            [one["name"] for one in report["reports"]], list(stats.REPORTS),
        )
        pairs = [
            (game, ENGINE.load_match_state(game))
            for game in self.games.values()
        ]
        self.assertEqual(
            report["reports"][0]["tables"],
            stats.report_tables(
                stats.REPORT_OVERVIEW, pairs,
                ENGINE.maneuver_catalog, ENGINE.player_catalog,
            ),
        )

        dinky = await (await self.stats("?kind=dinky&source=web")).json()
        self.assertIn("1 games against Dinky", dinky["heading"][0])
        test = await (await self.stats("?kind=test")).json()
        self.assertEqual(test["reports"], [])

    async def test_the_page_never_reads_the_bot_s_file(self) -> None:
        for source in (stats.SOURCE_DISCORD, stats.SOURCE_BOTH):
            with self.subTest(source):
                response = await self.stats(f"?source={source}")
                self.assertEqual(response.status, 400)
        with mock.patch("gamesaves.d12ball.storage.load_games") as load:
            await self.stats("?source=web")
        load.assert_not_called()

    async def test_a_kind_it_does_not_know_is_a_bug(self) -> None:
        for kind in ("this_game", "nonsense"):
            with self.subTest(kind):
                self.assertEqual(
                    (await self.stats(f"?kind={kind}")).status, 400,
                )

    async def test_the_page_is_served(self) -> None:
        response = await self.get("/stats")
        self.assertEqual(response.status, 200)
        self.assertIn("/static/stats.js", await response.text())


class ModelTests(unittest.TestCase):
    """The readings the two frontends now share."""

    def test_a_match_that_will_not_load_is_left_out_and_counted(self) -> None:
        good = played(case("smooth"))
        bad = played(case("game over"))
        bad.game_id = "bad"
        bad.match_state = dict(bad.match_state, home={"nonsense": True})
        with self.assertLogs(stats.LOGGER, level="INFO"):
            pairs, empty = stats.readable_matches(
                [good, bad], ENGINE.load_match_state,
            )
        self.assertEqual([game for game, _ in pairs], [good])
        self.assertEqual(empty, 1)

    def test_where_a_game_stands(self) -> None:
        game = case("smooth").game
        self.assertEqual(stats.game_standing(game), "in progress")
        game.abandon()
        self.assertEqual(stats.game_standing(game), "abandoned")

    def test_a_report_it_does_not_know_raises(self) -> None:
        with self.assertRaises(ValueError):
            stats.report_tables(
                "nonsense", [], ENGINE.maneuver_catalog, ENGINE.player_catalog,
            )

    def test_the_service_abandons_and_saves_once(self) -> None:
        saves = []
        game = case("smooth").game
        service = GameService(
            ENGINE, {game.game_id: game}, save=lambda games: saves.append(1),
        )
        service.abandon(game.game_id)
        self.assertTrue(game.abandoned)
        self.assertEqual(saves, [1])
        with self.assertRaises(RuleRefusal):
            service.abandon(game.game_id)
        self.assertEqual(saves, [1])


if __name__ == "__main__":
    unittest.main()

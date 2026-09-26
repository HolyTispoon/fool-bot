"""
The room's table over HTTP: from two seats claimed to the first
prompt, and the rematch at the end.

Step 3 of docs/web-app-next.md. `tests/test_game_service_setup.py`
walks the same path through the service with no frontend; this walks
it through the web app's routes, which are one service door each over
a rule on the record. What it watches for, beyond "the routes answer":

- **Every question on the table is the record's.** The teams a seat is
  offered are `teams_open_to`, and a pick the record refuses comes
  back as a 409 with the record's own sentence and nothing written.
- **Only somebody seated sets the table.** An observer is sent the
  table and presses nothing on it.
- **The toss or the choice deals the match and the pre-kickoff window
  opens in the same request**, so the page goes from the table
  straight to the first prompt.

Saves are counted, never written: the service here is handed a save
that touches no file.
"""

from __future__ import annotations

import unittest

from aiohttp.test_utils import TestClient, TestServer

from d12ball.game import GameMode, GameStatus, Team, paired_team
from gamelocks import GameLocks
from gamesaves.d12ball.service import GameService
from prompt_fixtures import ENGINE
from test_web_app import as_coach, case
from webapp.rooms import Rooms
from webapp.server import WebApp


CREATOR, SECOND, WATCHER = 101, 202, 303


class TableHarness(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        ENGINE.rng.seed(7)
        self.saves = 0

        def save(games) -> None:
            self.saves += 1

        self.games = {}
        self.service = GameService(ENGINE, self.games, save=save)
        await self.serve()

    async def serve(self) -> None:
        self.web = WebApp(self.service, GameLocks(), rooms=Rooms())
        self.web.watch()
        self.client = TestClient(TestServer(self.web.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.addAsyncCleanup(self.web.stop)

    async def open_room(self, **body) -> str:
        response = await self.client.post(
            "/api/rooms", headers=as_coach(CREATOR, "Creator"), json=body,
        )
        self.assertEqual(response.status, 200)
        return (await response.json())["id"]

    async def state(self, room: str, coach_id: int) -> dict:
        response = await self.client.get(
            f"/api/game/{room}", headers=as_coach(coach_id),
        )
        self.assertEqual(response.status, 200)
        return await response.json()

    async def press(self, room: str, coach_id: int, move: str, body=None):
        return await self.client.post(
            f"/api/room/{room}/table/{move}",
            headers=as_coach(coach_id),
            json=body or {},
        )

    async def pressed(self, room: str, coach_id: int, move: str, body=None):
        response = await self.press(room, coach_id, move, body)
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def seated_pair(self) -> str:
        """A room with both seats taken and its lobby left."""
        room = await self.open_room()
        await self.state(room, CREATOR)
        await self.state(room, SECOND)
        await self.pressed(room, CREATOR, "start")
        return room


class TwoCoachTableTests(TableHarness):
    async def test_two_coaches_set_the_table_and_reach_the_first_prompt(
        self,
    ) -> None:
        room = await self.open_room()
        await self.state(room, CREATOR)
        second = await self.state(room, SECOND)
        # The lobby: a table in the prompt's place, and no prompt.
        self.assertIsNone(second["prompt"])
        self.assertTrue(second["table"]["lobby"])
        self.assertTrue(second["table"]["start"]["may"])

        started = await self.pressed(room, CREATOR, "start")
        mine = started["table"]["seats"][0]
        self.assertTrue(mine["yours"])
        self.assertEqual(
            {team["key"] for team in mine["teams"] if team["open"]},
            {team.value for team in Team},
        )

        await self.pressed(
            room, CREATOR, "pick_team", {"team": Team.ORANGE.value},
        )
        picked = await self.state(room, SECOND)
        theirs = picked["table"]["seats"][1]
        # What the other seat is offered is the record's answer, and
        # the first pick's pairing is greyed with it.
        game = self.games[room]
        self.assertEqual(
            {team["key"] for team in theirs["teams"] if team["open"]},
            {team.value for team in game.teams_open_to(None)},
        )
        self.assertNotIn(
            paired_team(Team.ORANGE).value,
            {team["key"] for team in theirs["teams"] if team["open"]},
        )
        await self.pressed(
            room, SECOND, "pick_team", {"team": Team.PURPLE.value},
        )

        tossed = await self.pressed(room, SECOND, "flip_coin")
        winner = game.coin_winner_player_number
        self.assertTrue(tossed["table"]["coin"]["flipped"])
        self.assertEqual(tossed["table"]["sides"]["owed_by"], winner)
        # Before the choice no seat is Home.
        self.assertEqual(
            [seat["label"] for seat in tossed["room"]["seats"]],
            ["Coach 1", "Coach 2"],
        )

        winner_id, loser_id = (
            (CREATOR, SECOND) if winner == 1 else (SECOND, CREATOR)
        )
        refused = await self.press(
            room, loser_id, "choose", {"choice": "home"},
        )
        self.assertEqual(refused.status, 409)
        self.assertEqual(
            (await refused.json())["refusal"],
            "Only the coin-toss winner can choose.",
        )

        chosen = await self.pressed(
            room, winner_id, "choose", {"choice": "home"},
        )
        # The choice dealt the match, and begin opened the pre-kickoff
        # window in the same request: the table gives way to a prompt.
        self.assertIsNone(chosen["table"])
        self.assertEqual(chosen["prompt"]["kind"], "coaching_hub")
        self.assertEqual(game.home_player_number, winner)
        labels = {
            seat["number"]: seat["label"] for seat in chosen["room"]["seats"]
        }
        self.assertEqual(labels[winner], "Home Team Coach")
        self.assertEqual(labels[3 - winner], "Visitors Team Coach")
        home = await self.state(room, winner_id)
        self.assertTrue(home["prompt"]["yours"])
        self.assertEqual(home["room"]["role"], "home")

    async def test_a_refused_pick_is_the_record_s_sentence_and_writes_nothing(
        self,
    ) -> None:
        room = await self.seated_pair()
        await self.pressed(room, CREATOR, "pick_team", {"team": Team.TEAL.value})
        game = self.games[room]
        before, saves = game.to_dict(), self.saves

        for taken in (Team.TEAL, paired_team(Team.TEAL)):
            with self.subTest(team=taken.value):
                response = await self.press(
                    room, SECOND, "pick_team", {"team": taken.value},
                )
                self.assertEqual(response.status, 409)
                self.assertEqual(
                    (await response.json())["refusal"],
                    "That team is no longer available.",
                )
        self.assertEqual(game.to_dict(), before)
        self.assertEqual(self.saves, saves)

    async def test_an_observer_sees_the_table_and_presses_nothing(self) -> None:
        room = await self.open_room()
        await self.state(room, CREATOR)
        await self.state(room, SECOND)
        watching = await self.state(room, WATCHER)

        table = watching["table"]
        self.assertFalse(table["start"]["may"])
        self.assertFalse(any(one["may_change"] for one in table["settings"]))
        self.assertTrue(all(not seat["teams"] for seat in table["seats"]))

        game = self.games[room]
        before, saves = game.to_dict(), self.saves
        for move, body in (
            ("start", None),
            ("configure", {"setting": "mode", "value": "advanced"}),
            ("pick_team", {"team": Team.ORANGE.value}),
            ("flip_coin", None),
            ("choose", {"choice": "home"}),
        ):
            with self.subTest(move=move):
                response = await self.press(room, WATCHER, move, body)
                self.assertEqual(response.status, 403)
        self.assertEqual(game.to_dict(), before)
        self.assertEqual(self.saves, saves)

    async def test_a_setting_is_the_record_s_and_a_bad_one_is_a_bug(
        self,
    ) -> None:
        room = await self.open_room()
        await self.state(room, CREATOR)

        changed = await self.pressed(
            room, CREATOR, "configure", {"setting": "mode", "value": "advanced"},
        )
        values = {one["name"]: one["value"] for one in changed["table"]["settings"]}
        # Advanced defaults the board to nine: the record's, not the page's.
        self.assertEqual((values["mode"], values["board"]), ("advanced", "9"))

        for body in (
            {"setting": "colour", "value": "red"},
            {"setting": "board", "value": "8"},
            {},
        ):
            with self.subTest(body=body):
                response = await self.press(room, CREATOR, "configure", body)
                self.assertEqual(response.status, 400)

        await self.pressed(room, CREATOR, "configure", {"setting": "tutorial"})
        refused = await self.press(
            room, CREATOR, "configure", {"setting": "board", "value": "9"},
        )
        self.assertEqual(refused.status, 409)
        self.assertIn("7-space", (await refused.json())["refusal"])

    async def test_a_lobby_setting_closes_with_the_lobby(self) -> None:
        room = await self.seated_pair()
        state = await self.state(room, CREATOR)
        shown = {one["name"]: one for one in state["table"]["settings"]}
        open_ones = {name for name, one in shown.items() if one["may_change"]}
        # Two people hold the seats, so there is no AI row to show.
        self.assertNotIn("ai", shown)
        self.assertEqual(
            open_ones, set(self.games[room].open_settings()) & set(shown),
        )
        self.assertNotIn("name", open_ones)
        self.assertIn("mode", open_ones)


class AIRoomTests(TableHarness):
    async def test_an_ai_room_reaches_the_first_prompt(self) -> None:
        for seed in range(6):
            with self.subTest(seed=seed):
                ENGINE.rng.seed(seed)
                room = await self.open_room(ai=True)
                game = self.games[room]
                self.assertFalse(game.in_lobby)
                self.assertTrue(game.ai_holds(2))

                opened = await self.state(room, CREATOR)
                self.assertFalse(opened["table"]["start"]["owed"])
                self.assertTrue(opened["room"]["seats"][1]["ai"])

                picked = await self.pressed(
                    room, CREATOR, "pick_team", {"team": Team.ORANGE.value},
                )
                # The AI's team is drawn by the engine from the pool the
                # record leaves it.
                self.assertIn(game.player_2_team, set(Team) - {
                    Team.ORANGE, paired_team(Team.ORANGE),
                })
                self.assertEqual(
                    picked["table"]["seats"][1]["team_key"],
                    game.player_2_team.value,
                )

                tossed = await self.pressed(room, CREATOR, "flip_coin")
                if game.coin_winner_player_number == 1:
                    tossed = await self.pressed(
                        room, CREATOR, "choose", {"choice": "visiting"},
                    )
                # Whoever won, the table gives way to the first prompt.
                self.assertIsNone(tossed["table"])
                self.assertIsNotNone(tossed["prompt"])
                self.assertEqual(game.status, GameStatus.IN_PROGRESS)

    async def test_the_tutorial_against_the_ai_takes_the_record_s_pins(
        self,
    ) -> None:
        room = await self.open_room(ai=True, tutorial=True)
        game = self.games[room]

        self.assertTrue(game.tutorial)
        self.assertFalse(game.in_lobby)
        self.assertTrue(game.ai_holds(2))
        self.assertEqual((game.mode, game.board_size), (GameMode.TRAINING, 7))


class FrontDoorTests(TableHarness):
    async def test_my_rooms_by_status_and_the_open_ones(self) -> None:
        lobby = await self.open_room()
        ai = await self.open_room(ai=True)
        response = await self.client.post(
            "/api/rooms", headers=as_coach(SECOND, "Second"), json={},
        )
        theirs = (await response.json())["id"]

        listed = await (
            await self.client.get("/api/rooms", headers=as_coach(CREATOR))
        ).json()
        self.assertEqual(
            [room["id"] for room in listed["mine"]["lobby"]], [lobby],
        )
        self.assertEqual(
            [room["id"] for room in listed["mine"]["setup"]], [ai],
        )
        self.assertEqual([room["id"] for room in listed["open"]], [theirs])
        one = listed["open"][0]
        self.assertEqual(
            set(one),
            {"id", "number", "name", "status", "seats", "observers",
             "tutorial", "url"},
        )
        self.assertEqual(one["seats"][1]["free"], True)

    async def test_a_room_that_never_started_may_be_closed(self) -> None:
        room = await self.open_room()
        await self.state(room, CREATOR)

        watcher = await self.client.delete(
            f"/api/room/{room}", headers=as_coach(WATCHER),
        )
        self.assertEqual(watcher.status, 403)
        closed = await self.client.delete(
            f"/api/room/{room}", headers=as_coach(CREATOR),
        )
        self.assertEqual(closed.status, 200)
        self.assertNotIn(room, self.games)

    async def test_a_room_that_has_kicked_off_is_not_closed(self) -> None:
        room = await self.open_room(ai=True)
        await self.pressed(room, CREATOR, "pick_team", {"team": Team.ORANGE.value})
        await self.pressed(room, CREATOR, "flip_coin")
        game = self.games[room]
        if game.home_choice_owed_by == 1:
            await self.pressed(room, CREATOR, "choose", {"choice": "home"})

        response = await self.client.delete(
            f"/api/room/{room}", headers=as_coach(CREATOR),
        )
        self.assertEqual(response.status, 409)
        self.assertIn(room, self.games)


class RematchTests(TableHarness):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        fixture = case("game over")
        self.finished = fixture.game
        self.finished.match_state = fixture.match.to_dict()
        self.games[self.finished.game_id] = self.finished
        self.room = self.finished.game_id

    async def test_a_finished_game_rematches_into_a_room_the_same_two_hold(
        self,
    ) -> None:
        one, two = self.finished.player_1_id, self.finished.player_2_id
        watching = await self.state(self.room, WATCHER)
        self.assertIsNone(watching["rematch"])
        coach = await self.state(self.room, one)
        self.assertEqual(coach["prompt"]["kind"], "game_over")
        [control] = coach["prompt"]["controls"][0]["controls"]
        self.assertEqual((control["label"], control["post"]), ("Rematch", "/rematch"))
        self.assertEqual(watching["prompt"]["controls"], [])

        refused = await self.client.post(
            f"/api/room/{self.room}/rematch", headers=as_coach(WATCHER),
        )
        self.assertEqual(refused.status, 403)

        response = await self.client.post(
            f"/api/room/{self.room}/rematch", headers=as_coach(two),
        )
        self.assertEqual(response.status, 200)
        state = await response.json()
        new_id = state["rematch"]["id"]
        self.assertEqual(state["rematch"]["url"], f"/room/{new_id}")
        rematch = self.games[new_id]
        self.assertEqual((rematch.player_1_id, rematch.player_2_id), (one, two))
        self.assertEqual(
            (rematch.mode, rematch.board_size),
            (self.finished.mode, self.finished.board_size),
        )
        self.assertTrue(rematch.in_lobby)

        # Everybody in the old room is told where it went.
        self.assertEqual(
            (await self.state(self.room, WATCHER))["rematch"]["id"], new_id,
        )
        # Both coaches hold their seats in the new room, and a second
        # ask finds it rather than opening another.
        again = await self.client.post(
            f"/api/room/{self.room}/rematch", headers=as_coach(one),
        )
        self.assertEqual((await again.json())["rematch"]["id"], new_id)
        self.assertEqual(len(self.games), 2)
        first = await self.state(new_id, one)
        self.assertEqual(first["you"]["player_number"], 1)
        self.assertTrue(first["table"]["start"]["may"])

    async def test_the_rematch_is_not_an_action_on_the_game(self) -> None:
        coach = await self.state(self.room, self.finished.player_1_id)
        [control] = coach["prompt"]["controls"][0]["controls"]
        response = await self.client.post(
            f"/api/game/{self.room}/action",
            headers=as_coach(self.finished.player_1_id),
            json={"action": control["action"]},
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(len(self.games), 1)


if __name__ == "__main__":
    unittest.main()

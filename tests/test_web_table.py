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

import re
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from d12ball.formatting import (
    GAME_MODE_NAMES, SETTING_DEFINITIONS, board_size_recommendation,
    describe_game_mode,
)
from d12ball.game import (
    GAME_COINS, GameMode, GameStatus, Team, coin_face_name, paired_team,
)
from gamelocks import GameLocks
from gamesaves.d12ball.service import GameService
from prompt_fixtures import ENGINE
from test_web_app import as_coach, case
from webapp import server
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

    async def open_room(self) -> str:
        response = await self.client.post(
            "/api/rooms", headers=as_coach(CREATOR, "Creator"),
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

    async def seat_move(self, room: str, coach_id: int, move: str, body=None):
        """The AI and tutorial are now the lobby's own choices, put in
        through the seat and table routes rather than at creation."""
        return await self.client.post(
            f"/api/room/{room}/seat/{move}",
            headers=as_coach(coach_id),
            json=body or {},
        )

    async def pressed(self, room: str, coach_id: int, move: str, body=None):
        response = await self.press(room, coach_id, move, body)
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def seated_pair(self) -> str:
        """A room with both seats taken, still in its lobby -- where a
        web room picks its teams."""
        room = await self.open_room()
        await self.state(room, CREATOR)
        await self.state(room, SECOND)
        return room

    async def started_pair(self) -> str:
        """A room with both seats taken, both teams picked and its lobby
        left: the coin is next."""
        room = await self.seated_pair()
        await self.pressed(room, CREATOR, "pick_team", {"team": Team.ORANGE.value})
        await self.pressed(room, SECOND, "pick_team", {"team": Team.PURPLE.value})
        await self.pressed(room, CREATOR, "start")
        return room


class TwoCoachTableTests(TableHarness):
    async def test_two_coaches_set_the_table_and_reach_the_first_prompt(
        self,
    ) -> None:
        room = await self.open_room()
        await self.state(room, CREATOR)
        second = await self.state(room, SECOND)
        # The lobby: a table in the prompt's place, and no prompt. A web
        # room picks its teams here, before Start.
        self.assertIsNone(second["prompt"])
        self.assertTrue(second["table"]["lobby"])
        self.assertTrue(second["table"]["start"]["may"])
        self.assertIn("no team yet", second["table"]["start"]["refusal"])

        started = await self.state(room, CREATOR)
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
        await self.pressed(room, CREATOR, "start")

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

    async def test_start_is_grey_with_the_record_s_sentence_while_a_seat_is_empty(
        self,
    ) -> None:
        """The whistle's note is `start_lobby`'s own refusal, read of a
        copy -- and reading it changes nothing on the record."""
        room = await self.open_room()
        alone = await self.state(room, CREATOR)
        refusal = alone["table"]["start"]["refusal"]
        self.assertIn("Seat 2 is empty", refusal)
        self.assertTrue(self.games[room].in_lobby)
        refused = await self.press(room, CREATOR, "start")
        self.assertEqual(refused.status, 409)
        self.assertIn(refusal, await refused.text())

        await self.state(room, SECOND)
        both = await self.state(room, CREATOR)
        # Both seats held; the room still owes its teams.
        self.assertEqual(
            both["table"]["start"]["refusal"],
            "Seat 1 has no team yet -- pick one to start.",
        )
        await self.pressed(room, CREATOR, "pick_team", {"team": Team.ORANGE.value})
        await self.pressed(room, SECOND, "pick_team", {"team": Team.PURPLE.value})
        ready = await self.state(room, CREATOR)
        self.assertIsNone(ready["table"]["start"]["refusal"])
        self.assertTrue(ready["table"]["start"]["may"])

    async def test_the_coin_starts_a_game_still_in_its_lobby(self) -> None:
        """The author, 2026-09-27: no whistle -- the coin, flipped in
        the lobby, leaves it and tosses in one request, and is refused
        in `start_lobby`'s own sentence while the table is not set."""
        room = await self.seated_pair()
        refused = await self.press(room, CREATOR, "flip_coin")
        self.assertEqual(refused.status, 409)
        self.assertIn("no team yet", await refused.text())
        self.assertTrue(self.games[room].in_lobby)

        await self.pressed(room, CREATOR, "pick_team", {"team": Team.ORANGE.value})
        await self.pressed(room, SECOND, "pick_team", {"team": Team.PURPLE.value})
        tossed = await self.pressed(room, CREATOR, "flip_coin")
        self.assertFalse(self.games[room].in_lobby)
        self.assertTrue(tossed["table"]["coin"]["flipped"])
        self.assertFalse(tossed["table"]["start"]["owed"])

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
        # The swatches are drawn for everybody; none may be pressed.
        self.assertFalse(any(
            team["open"] for seat in table["seats"] for team in seat["teams"]
        ))

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
        room = await self.started_pair()
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
                room = await self.open_room()
                put = await self.seat_move(room, CREATOR, "ai", {"seat": 2})
                self.assertEqual(put.status, 200)
                await self.pressed(
                    room, CREATOR, "pick_team", {"team": Team.ORANGE.value},
                )
                game = self.games[room]
                # Nobody picked the AI's team: it waits for Start.
                self.assertIsNone(game.player_2_team)
                picked = await self.pressed(room, CREATOR, "start")
                self.assertFalse(game.in_lobby)
                self.assertTrue(game.ai_holds(2))
                self.assertFalse(picked["table"]["start"]["owed"])
                self.assertTrue(picked["room"]["seats"][1]["ai"])
                # The AI's team is drawn by the engine at Start, from the
                # pool the record leaves it.
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

    async def test_the_tutorial_is_a_training_game_for_one_against_the_ai(
        self,
    ) -> None:
        """The tutorial toggle (`configure`'s `tutorial` setting) pins
        the record's own training game for one, in the lobby -- Start
        is what puts the AI in the empty seat and leaves it."""
        room = await self.open_room()
        toggled = await self.pressed(
            room, CREATOR, "configure", {"setting": "tutorial"},
        )
        game = self.games[room]

        self.assertTrue(game.tutorial)
        self.assertTrue(game.in_lobby)
        self.assertEqual((game.mode, game.board_size), (GameMode.TRAINING, 7))
        self.assertFalse(game.seat_is_free(2))
        self.assertTrue(toggled["table"]["lobby"])

        await self.pressed(room, CREATOR, "pick_team", {"team": Team.ORANGE.value})
        await self.pressed(room, CREATOR, "start")
        self.assertFalse(game.in_lobby)
        self.assertTrue(game.ai_holds(2))


class FrontDoorTests(TableHarness):
    async def test_my_rooms_by_status_and_the_open_ones(self) -> None:
        lobby = await self.open_room()
        ai = await self.open_room()
        await self.seat_move(ai, CREATOR, "ai", {"seat": 2})
        await self.pressed(ai, CREATOR, "pick_team", {"team": Team.ORANGE.value})
        await self.pressed(ai, CREATOR, "start")
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
            {"id", "number", "name", "status", "abandoned", "seats",
             "observers", "tutorial", "mode", "board_size", "clock",
             "your_move", "may_close", "close_asks", "may_abandon",
             "may_leave", "url"},
        )
        self.assertEqual(listed["full"], [])
        self.assertEqual(one["seats"][1]["free"], True)
        # Somebody else's room is never this reader's move.
        self.assertFalse(one["your_move"])

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
        room = await self.open_room()
        await self.seat_move(room, CREATOR, "ai", {"seat": 2})
        await self.pressed(room, CREATOR, "pick_team", {"team": Team.ORANGE.value})
        await self.pressed(room, CREATOR, "start")
        await self.pressed(room, CREATOR, "flip_coin")
        game = self.games[room]
        if game.home_choice_owed_by == 1:
            await self.pressed(room, CREATOR, "choose", {"choice": "home"})

        response = await self.client.delete(
            f"/api/room/{room}", headers=as_coach(CREATOR),
        )
        self.assertEqual(response.status, 409)
        self.assertIn(room, self.games)


class RedesignedTableTests(TableHarness):
    """
    Step 9 of docs/web-app-redesign.md: the front door's new room with
    its two ticks, the seat cards, the settings' notes, the coin and
    the goal to defend -- a room driven from creation to kickoff
    through the controls the page now draws, each still one service
    door over the record's rule.
    """

    async def rooms(self, coach_id: int) -> dict:
        response = await self.client.get("/api/rooms", headers=as_coach(coach_id))
        self.assertEqual(response.status, 200)
        return await response.json()

    async def ticked_room(self, *, ai: bool, tutorial: bool) -> str:
        """A new room and its ticks, in the order the front door makes
        them (webapp/static/index.js): Dinky first, then the tutorial."""
        room = await self.open_room()
        if ai:
            put = await self.seat_move(room, CREATOR, "ai", {"seat": 2})
            self.assertEqual(put.status, 200, await put.text())
        if tutorial:
            await self.pressed(room, CREATOR, "configure", {"setting": "tutorial"})
        return room

    async def test_the_dinky_tick_seats_the_ai_in_coach_2(self) -> None:
        room = await self.ticked_room(ai=True, tutorial=False)
        state = await self.state(room, CREATOR)
        game = self.games[room]
        self.assertTrue(game.ai_holds(2))
        self.assertFalse(game.tutorial)
        self.assertEqual(state["room"]["seats"][1]["name"], "Dinky AI")
        self.assertTrue(state["room"]["seats"][1]["ai"])
        # Nothing is empty, so the AI is offered nowhere else.
        self.assertEqual(state["room"]["ai_seats"], [])
        # Dinky's seat says it picks at Start unless a coach picks for it.
        self.assertTrue(state["table"]["seats"][1]["picks_itself"])
        self.assertIn("no team yet", state["table"]["start"]["refusal"])

    async def test_the_tutorial_tick_alone_is_the_record_s_tutorial(self) -> None:
        room = await self.ticked_room(ai=False, tutorial=True)
        game = self.games[room]
        self.assertTrue(game.tutorial)
        self.assertEqual((game.mode, game.board_size), (GameMode.TRAINING, 7))
        await self.pressed(room, CREATOR, "pick_team", {"team": Team.ORANGE.value})
        await self.pressed(room, CREATOR, "start")
        self.assertTrue(game.ai_holds(2))

    async def test_both_ticks_are_a_tutorial_against_dinky(self) -> None:
        """Dinky first, then the tutorial: the record takes both in that
        order, since the AI's seat holds no id and so nobody has
        joined -- and would refuse the AI after the tutorial, which
        makes the room a game for one."""
        room = await self.ticked_room(ai=True, tutorial=True)
        game = self.games[room]
        self.assertTrue(game.tutorial)
        self.assertTrue(game.ai_holds(2))
        await self.pressed(room, CREATOR, "pick_team", {"team": Team.ORANGE.value})
        await self.pressed(room, CREATOR, "start")
        self.assertEqual(game.ai_seats, [2])

        other = await self.open_room()
        await self.pressed(other, CREATOR, "configure", {"setting": "tutorial"})
        refused = await self.seat_move(other, CREATOR, "ai", {"seat": 2})
        self.assertEqual(refused.status, 409)

    async def test_a_room_from_creation_to_kickoff_through_the_new_controls(
        self,
    ) -> None:
        room = await self.open_room()
        await self.state(room, CREATOR)
        second = await self.client.get(
            f"/api/game/{room}", headers=as_coach(SECOND, "Second"),
        )
        self.assertEqual(second.status, 200)
        watching = await self.client.get(
            f"/api/game/{room}", headers=as_coach(WATCHER, "Watcher"),
        )
        self.assertEqual(watching.status, 200)
        game = self.games[room]

        # The sideline names who is watching -- by the name their cookie
        # last carried -- the reader marked.
        seen = (await watching.json())["room"]
        self.assertEqual(seen["watching"], [{"name": "Watcher", "yours": True}])
        self.assertEqual(seen["role"], "observer")
        # Both seats are held, so the AI may sit nowhere -- and an
        # observer is offered it nowhere in any case.
        self.assertEqual(seen["ai_seats"], [])

        # The lobby: the teams are picked here, so it is each coach's
        # move until their side has one -- on the table and on the
        # front door's card alike -- and Start is dark until then.
        lobby = await self.state(room, CREATOR)
        self.assertTrue(lobby["table"]["yours"])
        self.assertIn("no team yet", lobby["table"]["start"]["refusal"])
        self.assertEqual(lobby["game"]["topic"], "Creator vs. Second")
        [card] = (await self.rooms(CREATOR))["mine"]["lobby"]
        self.assertTrue(card["your_move"])
        # A new room is Standard, which starts on the nine-space board
        # (the author, 2026-10-05).
        self.assertEqual((card["mode"], card["board_size"]), ("Standard", 9))
        self.assertIsNone(card["clock"])

        # A setting says what it is in the model's words, and why a
        # value is dark in the record's: somebody has joined, so the
        # toggles stay off.
        settings = {one["name"]: one for one in lobby["table"]["settings"]}
        self.assertFalse(settings["tutorial"]["toggle_open"])
        self.assertEqual(
            settings["tutorial"]["note"],
            "Someone has already joined -- they would have to leave first.",
        )
        self.assertEqual(
            settings["test"]["definition"], SETTING_DEFINITIONS["test"],
        )
        self.assertTrue(all(one["open"] for one in settings["mode"]["choices"]))
        self.assertIsNone(settings["mode"]["note"])
        self.assertEqual(
            settings["mode"]["definition"], describe_game_mode(game),
        )
        # The board row carries the nine-space recommendation, the
        # sentence the Discord setup screens show.
        self.assertEqual(
            settings["board"]["definition"], board_size_recommendation(game),
        )
        self.assertIn("standard mode", settings["board"]["definition"])
        # Each mode pill carries the definition of the mode it would pick.
        self.assertEqual(
            {one["label"]: one["definition"] for one in settings["mode"]["choices"]},
            {
                GAME_MODE_NAMES[mode]: describe_game_mode(game, mode)
                for mode in GameMode
            },
        )

        mine, theirs = lobby["table"]["seats"]
        # Both seats carry their swatches, each greyed or offered as the
        # record says; only the reader's own may be pressed.
        self.assertEqual(len(mine["teams"]), len(Team))
        self.assertEqual(len(theirs["teams"]), len(Team))
        self.assertTrue(all(team["open"] for team in mine["teams"]))
        self.assertFalse(any(team["open"] for team in theirs["teams"]))
        self.assertTrue(all(team["offered"] for team in theirs["teams"]))
        refused = await self.press(
            room, CREATOR, "pick_team", {"team": Team.TEAL.value, "seat": 2},
        )
        self.assertEqual(refused.status, 403)

        picked = await self.pressed(
            room, CREATOR, "pick_team", {"team": Team.ORANGE.value},
        )
        mine, theirs = picked["table"]["seats"]
        [orange] = [team for team in mine["teams"] if team["picked"]]
        self.assertEqual(orange["key"], Team.ORANGE.value)
        greyed = {team["key"] for team in theirs["teams"] if not team["offered"]}
        self.assertEqual(
            greyed, {Team.ORANGE.value, paired_team(Team.ORANGE).value},
        )
        self.assertEqual(
            greyed,
            {team.value for team in Team} - {
                team.value for team in game.teams_open_to(2)
            },
        )
        # The creator has picked; it is the second coach's move now.
        self.assertFalse(picked["table"]["yours"])
        self.assertTrue((await self.state(room, SECOND))["table"]["yours"])

        await self.pressed(room, SECOND, "pick_team", {"team": Team.PURPLE.value})
        ready = await self.state(room, CREATOR)
        self.assertIsNone(ready["table"]["start"]["refusal"])
        self.assertTrue(ready["table"]["yours"])
        await self.pressed(room, CREATOR, "start")
        coin = (await self.state(room, CREATOR))["table"]["coin"]
        self.assertTrue(coin["owed"] and coin["may"])
        # The game's own coin -- one of six, drawn when the room was
        # made -- and every one of them is served.
        self.assertIn(game.coin, GAME_COINS)
        self.assertEqual(
            coin["faces"],
            {
                "fortune": f"/emoji/{coin_face_name(game.coin, 'fortune')}.png",
                "doom": f"/emoji/{coin_face_name(game.coin, 'doom')}.png",
            },
        )
        for key in GAME_COINS:
            for face in ("fortune", "doom"):
                name = coin_face_name(key, face)
                served = await self.client.get(f"/emoji/{name}.png")
                self.assertEqual(served.status, 200, name)
        for face in coin["faces"].values():
            served = await self.client.get(face)
            self.assertEqual(served.status, 200)

        tossed = await self.pressed(room, CREATOR, "flip_coin")
        winner = game.coin_winner_player_number
        sides = tossed["table"]["sides"]
        # The miniature field's ends are the goals the board draws
        # there: home's goal on the left.
        self.assertEqual(
            {choice["value"]: choice["end"] for choice in sides["choices"]},
            {"home": "left", "visiting": "right"},
        )
        self.assertEqual(sides["board_size"], 9)
        winner_id = CREATOR if winner == 1 else SECOND
        before = await self.state(room, winner_id)
        self.assertEqual(before["room"]["role"], "coach")
        self.assertTrue(before["table"]["yours"])

        [right] = [one for one in sides["choices"] if one["end"] == "right"]
        chosen = await self.pressed(
            room, winner_id, "choose", {"choice": right["value"]},
        )
        self.assertIsNone(chosen["table"])
        self.assertEqual(game.visiting_player_number, winner)
        self.assertEqual(chosen["room"]["role"], "visiting")
        # Once kicked off, the front door's card carries the clock.
        [card] = (await self.rooms(winner_id))["mine"]["in_progress"]
        self.assertEqual(card["clock"], "00' First Half")

    async def test_a_seated_coach_picks_dinky_s_team_or_dinky_picks_at_start(
        self,
    ) -> None:
        """The author, 2026-09-26: a seated coach may pick the AI's team;
        if nobody does, the AI picks its own at the whistle."""
        room = await self.ticked_room(ai=True, tutorial=False)
        state = await self.state(room, CREATOR)
        dinky = state["table"]["seats"][1]
        self.assertTrue(all(team["open"] for team in dinky["teams"]))
        await self.pressed(
            room, CREATOR, "pick_team", {"team": Team.TEAL.value, "seat": 2},
        )
        await self.pressed(room, CREATOR, "pick_team", {"team": Team.ORANGE.value})
        started = await self.pressed(room, CREATOR, "start")
        game = self.games[room]
        self.assertEqual(game.player_2_team, Team.TEAL)
        self.assertTrue(started["table"]["coin"]["owed"])

        # An observer may not pick for Dinky.
        other = await self.ticked_room(ai=True, tutorial=False)
        await self.state(other, WATCHER)
        refused = await self.press(
            other, WATCHER, "pick_team", {"team": Team.TEAL.value, "seat": 2},
        )
        self.assertEqual(refused.status, 403)

    async def test_the_test_game_toggle_warns_it_would_kick_dinky(self) -> None:
        room = await self.ticked_room(ai=True, tutorial=False)
        state = await self.state(room, CREATOR)
        settings = {one["name"]: one for one in state["table"]["settings"]}
        self.assertEqual(settings["test"]["warning"], "That would kick Dinky AI.")
        self.assertIsNone(settings["tutorial"]["warning"])

        toggled = await self.pressed(room, CREATOR, "configure", {"setting": "test"})
        self.assertFalse(toggled["room"]["seats"][1]["ai"])
        settings = {one["name"]: one for one in toggled["table"]["settings"]}
        self.assertIsNone(settings["test"]["warning"])

        # The page asks before it sends a setting that warns.
        script = (Path(server.STATIC) / "app.js").read_text(encoding="utf-8")
        start = script.index("function drawSetting(")
        body = script[start:script.index("\n}\n", start)]
        self.assertIn("if (setting.warning && !confirm(setting.warning)) return;", body)

    async def test_a_test_game_s_one_coach_picks_both_teams_in_the_lobby(
        self,
    ) -> None:
        room = await self.open_room()
        await self.pressed(room, CREATOR, "configure", {"setting": "test"})
        await self.pressed(room, CREATOR, "pick_team", {"team": Team.ORANGE.value})
        await self.pressed(
            room, CREATOR, "pick_team", {"team": Team.PURPLE.value, "seat": 2},
        )
        await self.pressed(room, CREATOR, "start")
        game = self.games[room]
        self.assertEqual(
            (game.player_1_team, game.player_2_team), (Team.ORANGE, Team.PURPLE),
        )
        self.assertEqual(game.player_2_id, CREATOR)

    async def test_a_kicked_coach_is_asked_about_first_and_lands_on_the_sideline(
        self,
    ) -> None:
        room = await self.open_room()
        await self.state(room, CREATOR)
        await self.client.get(
            f"/api/game/{room}", headers=as_coach(SECOND, "Second"),
        )

        # Only an admin kicks; anybody else is refused and nothing moves.
        refused = await self.seat_move(room, CREATOR, "kick", {"seat": 2})
        self.assertEqual(refused.status, 403)
        self.assertEqual(self.games[room].player_2_id, SECOND)

        admin = await self.client.post(
            f"/api/room/{room}/admin", headers=as_coach(CREATOR),
        )
        self.assertEqual(admin.status, 200)
        kicked = await self.seat_move(room, CREATOR, "kick", {"seat": 2})
        self.assertEqual(kicked.status, 200, await kicked.text())
        state = await kicked.json()
        self.assertTrue(state["room"]["seats"][1]["free"])
        self.assertEqual(
            state["room"]["watching"], [{"name": "Second", "yours": False}],
        )
        # The empty seat is where Dinky may now be dragged.
        self.assertEqual(state["room"]["ai_seats"], [2])
        # The kicked coach watches, and the free seat is theirs to take.
        again = await self.state(room, SECOND)
        self.assertEqual(again["room"]["role"], "observer")
        taken = await self.seat_move(room, SECOND, "take", {"seat": 2})
        self.assertEqual(taken.status, 200)

        # Every way the page takes somebody else out of a seat -- the ✕
        # on the card, a drag to the sideline, the in-game Kick -- goes
        # through the one function that asks "Are you sure?" first.
        script = (Path(server.STATIC) / "app.js").read_text(encoding="utf-8")
        self.assertEqual(script.count('"/seat/kick"'), 1)
        start = script.index("function kickSeat(")
        body = script[start:script.index("\n}\n", start)]
        self.assertRegex(body, r"if \(confirm\(`Are you sure\?")
        self.assertIn('"/seat/kick"', body)
        self.assertGreaterEqual(len(re.findall(r"kickSeat\(seat\)", script)), 2)


    async def test_anybody_seated_takes_dinky_out_and_nobody_watching_does(
        self,
    ) -> None:
        # Whoever may put the AI in may take it out again -- no admin
        # needed -- and somebody watching may do neither.
        room = await self.open_room()
        await self.state(room, CREATOR)
        await self.seat_move(room, CREATOR, "ai", {"seat": 2})
        self.assertTrue(self.games[room].ai_holds(2))
        await self.client.get(
            f"/api/game/{room}", headers=as_coach(WATCHER, "Watcher"),
        )
        refused = await self.seat_move(room, WATCHER, "kick", {"seat": 2})
        self.assertEqual(refused.status, 403)
        self.assertTrue(self.games[room].ai_holds(2))

        out = await self.seat_move(room, CREATOR, "kick", {"seat": 2})
        self.assertEqual(out.status, 200, await out.text())
        self.assertFalse(self.games[room].ai_holds(2))
        self.assertTrue((await out.json())["room"]["seats"][1]["free"])


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

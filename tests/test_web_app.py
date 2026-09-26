"""
The web frontend, played over HTTP.

Step 10 of docs/architecture-migration.md. **No `discord` is imported
here**: what this measures is a second frontend over the same
`GameService` the bot plays through, on the same fixtures the bot's
prompts are measured on (`tests/prompt_fixtures.py`). A turn taken
here is the same `Action` through the same door.

What it is watching for, beyond "the routes answer":

- **A control comes off the prompt's options and nothing else**
  (principle 10). Every kind the chain can ask has a builder, and
  every control a page is offered is an action the driver accepts.
- **A page may only send back what it was offered.** An action nobody
  offered is refused by the frontend before the model sees it, and
  nothing is written.
- **A secret stays secret.** A coach's maneuver pick is theirs until
  both are in, so the other side's hand is not in what this viewer is
  sent -- a frontend that sends it and hides it in the page has
  published it.
- **The other coach's turn reaches a page that did not ask for it**,
  through `GameService.listeners`.
"""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

from d12ball.components import TeamSide
from d12ball.prompts import Action, PromptKind, asked_sides, pending_prompt
from gamesaves.d12ball import storage
from gamesaves.d12ball.service import GameService
from webapp import identity, server
from webapp.identity import Coach
from gamelocks import GameLocks
from webapp.present import CONTROLS, Viewer, controls_for, render_text
from webapp.chat import CHAT_LENGTH, Chats
from webapp.rooms import Rooms
from webapp.server import WebApp, _was_offered
from prompt_fixtures import (
    CASES,
    ENGINE,
    PromptFixture,
    build_game,
    take_the_ball,
)


def service_over(fixture: PromptFixture) -> GameService:
    """A service over one fixture that writes to nothing."""
    fixture.game.match_state = fixture.match.to_dict()
    return GameService(
        ENGINE, {fixture.game.game_id: fixture.game}, save=lambda games: None,
    )


def as_coach(coach_id: int, name: str = None) -> dict:
    """The request headers of somebody whose cookie names `coach_id`
    -- a browser that said who it is (`webapp/identity.py`)."""
    coach = Coach(coach_id, name or f"Coach {coach_id}")
    return {"Cookie": f"{identity.COOKIE}={identity.encode(coach)}"}


#: Somebody with a name who holds neither seat of a fixture's game.
STRANGER = 999


def case(name: str) -> PromptFixture:
    for entry in CASES:
        if entry.name == name:
            return entry.build()
    raise AssertionError(f"no fixture called {name}")


class ControlTests(unittest.TestCase):
    """What a page is offered, and who is offered it."""

    def setUp(self) -> None:
        ENGINE.rng.seed(11)

    def test_every_kind_the_chain_asks_can_be_offered(self) -> None:
        """
        A kind with no builder is a prompt this frontend cannot put
        up -- the web app's half of `view_for_prompt` covering
        `PromptKind`.
        """
        for kind in PromptKind:
            with self.subTest(kind.name):
                self.assertIn(kind, CONTROLS)

    def test_the_coach_who_is_asked_is_the_one_offered_controls(self) -> None:
        for entry in CASES:
            if not entry.asked or entry.ai:
                continue
            with self.subTest(entry.name):
                fixture = entry.build()
                prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
                if prompt.kind is PromptKind.GAME_OVER:
                    continue
                sides = asked_sides(fixture.match, prompt)
                for player_number in (1, 2):
                    side = ENGINE.side_player_number
                    offered = controls_for(
                        ENGINE,
                        fixture.game,
                        fixture.match,
                        prompt,
                        Viewer(player_number),
                    )
                    theirs = not sides or any(
                        side(fixture.game, one) == player_number
                        for one in sides
                    )
                    self.assertEqual(
                        bool(offered),
                        theirs,
                        f"{prompt.kind.name} for player {player_number}",
                    )

    def test_a_spectator_is_offered_nothing(self) -> None:
        for entry in CASES:
            if not entry.asked:
                continue
            with self.subTest(entry.name):
                fixture = entry.build()
                prompt = pending_prompt(ENGINE, fixture.game, fixture.match)

                self.assertEqual(
                    controls_for(
                        ENGINE, fixture.game, fixture.match, prompt, Viewer(),
                    ),
                    [],
                )

    def test_a_maneuver_row_is_the_coach_s_own(self) -> None:
        """
        The pick is secret until both are in, so the other side's hand
        is not in what a coach is sent.
        """
        fixture = case("maneuver picks")
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        offered = controls_for(
            ENGINE, fixture.game, fixture.match, prompt, Viewer(1),
        )
        mine = {
            side
            for side in ("offense", "defense")
            if any(
                control["action"]["arguments"]["side"] == side
                for group in offered
                for control in group["controls"]
            )
        }

        self.assertEqual(len(mine), 1)

    def test_every_control_is_an_answer_the_driver_takes(self) -> None:
        """
        The measure of principle 10: a page presses what it was
        offered and the model accepts it, with nothing added.
        """
        for entry in CASES:
            if not entry.asked or entry.ai:
                continue
            with self.subTest(entry.name):
                fixture = entry.build()
                prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
                if prompt.kind is PromptKind.GAME_OVER:
                    continue
                for player_number in (1, 2):
                    for group in controls_for(
                        ENGINE,
                        fixture.game,
                        fixture.match,
                        prompt,
                        Viewer(player_number),
                    ):
                        for control in group["controls"]:
                            self._accepted(entry, control)

    def _accepted(self, entry, control) -> None:
        """One control, pressed on a fresh copy of its own fixture."""
        if control.get("disabled"):
            return
        arguments = dict(control["action"]["arguments"])
        if control["type"] == "chooser":
            for one in control["fields"]:
                arguments[one["name"]] = one["choices"][0]["value"]
        fixture = entry.build()
        if control["action"]["kind"] == PromptKind.OWN_GOAL_ROLL.value:
            # `pending_own_goal` is the whole of what the chain reads,
            # so the fixture sets that and nothing else -- but the
            # player who rolls is the one the Pressure left standing
            # on the ball. Finishing the position is the fixture's, as
            # it is in `tests/test_d12ball_driver_actions.py`; here it
            # has to be a player the save would validate, since this
            # goes through the service.
            take_the_ball(fixture.match)
        service = service_over(fixture)
        result = service.apply_action(
            fixture.game.game_id,
            Action.from_dict({**control["action"], "arguments": arguments}),
        )
        self.assertFalse(
            result.refused,
            f"{control['label']!r} was offered and refused: {result.refusal}",
        )


class OfferedTests(unittest.TestCase):
    """What the server lets through to the model."""

    def setUp(self) -> None:
        ENGINE.rng.seed(11)
        fixture = case("coaching hub")
        self.fixture = fixture
        self.prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        self.offered = controls_for(
            ENGINE, fixture.game, fixture.match, self.prompt, Viewer(1),
        )

    def live(self) -> dict:
        """The first control that is not greyed -- a dead one is not
        an offer, and the server refuses it like anything else."""
        return next(
            control
            for group in self.offered
            for control in group["controls"]
            if control["type"] == "button" and not control["disabled"]
        )

    def test_a_control_as_it_was_offered_is_let_through(self) -> None:
        self.assertTrue(_was_offered(self.offered, self.live()["action"]))

    def test_a_control_this_prompt_has_greyed_is_not_an_offer(self) -> None:
        """The hub greys the formation a side is already standing in;
        the tutorial greys everything off its rail."""
        dead = next(
            control
            for group in self.offered
            for control in group["controls"]
            if control["type"] == "button" and control["disabled"]
        )

        self.assertFalse(_was_offered(self.offered, dead["action"]))

    def test_an_argument_nothing_offered_is_refused(self) -> None:
        control = dict(self.live())
        action = dict(control["action"])
        action["arguments"] = {**action["arguments"], "space_index": 99}

        self.assertFalse(_was_offered(self.offered, action))

    def test_a_chooser_takes_only_the_values_it_listed(self) -> None:
        chooser = next(
            control
            for group in self.offered
            for control in group["controls"]
            if control["type"] == "chooser"
        )
        good = {
            **chooser["action"]["arguments"],
            **{
                one["name"]: one["choices"][0]["value"]
                for one in chooser["fields"]
            },
        }
        bad = {**good, chooser["fields"][0]["name"]: "somebody-else"}

        self.assertTrue(
            _was_offered(self.offered, {**chooser["action"], "arguments": good}),
        )
        self.assertFalse(
            _was_offered(self.offered, {**chooser["action"], "arguments": bad}),
        )

    def test_a_question_this_viewer_is_not_asked_offers_nothing(self) -> None:
        theirs = controls_for(
            ENGINE, self.fixture.game, self.fixture.match, self.prompt,
            Viewer(2),
        )

        self.assertEqual(theirs, [])
        self.assertFalse(_was_offered(theirs, self.live()["action"]))


class TokenTests(unittest.TestCase):
    """The model's marks, drawn this frontend's way."""

    def test_the_narration_s_own_markdown_is_rendered(self) -> None:
        """
        A sentence is written in the markdown a coach reads in a
        Discord message; that is the model's voice, so this frontend
        renders it too.
        """
        rendered = render_text(build_game(), "## **Goal!**\nA *quiet* note.")

        self.assertIn(
            '<span class="headline h2"><strong>Goal!</strong></span>',
            rendered,
        )
        self.assertIn("<em>quiet</em>", rendered)

    def test_a_sentence_is_escaped_and_then_tokenised(self) -> None:
        game = build_game(player_1_name="A <script>")
        rendered = render_text(
            game, "{team:orange} {coach:1} is {condition:exhausted} <b>",
        )

        self.assertIn("A &lt;script&gt;", rendered)
        self.assertIn("&lt;b&gt;", rendered)
        self.assertNotIn("{team:", rendered)
        # The bot's own emoji, as a Discord message draws them.
        self.assertIn('src="/emoji/team_orange.png"', rendered)
        self.assertIn('src="/emoji/exhausted.png"', rendered)


class WebAppTests(unittest.IsolatedAsyncioTestCase):
    """The routes, over a real client."""

    async def asyncSetUp(self) -> None:
        ENGINE.rng.seed(11)
        self.client, self.game = await self.open("kickoff")
        self.coach = as_coach(self.game.player_1_id)

    async def open(self, name: str):
        """A server over one fixture, and a client on it."""
        from gamelocks import GameLocks

        fixture = case(name)
        self.service = service_over(fixture)
        self.web = WebApp(self.service, GameLocks())
        self.web.watch()
        client = TestClient(TestServer(self.web.app))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        self.addAsyncCleanup(self.web.stop)
        return client, fixture.game

    async def state(self, headers: dict = None) -> dict:
        response = await self.client.get(
            f"/api/game/{self.game.game_id}",
            headers=headers if headers is not None else self.coach,
        )
        self.assertEqual(response.status, 200)
        return await response.json()

    async def press(
        self, action: dict, *, headers: dict = None, since: int = 0,
    ):
        return await self.client.post(
            f"/api/game/{self.game.game_id}/action",
            params={"since": str(since)},
            headers=headers if headers is not None else self.coach,
            data=json.dumps({"action": action}),
        )

    def live(self, state: dict) -> dict:
        """The first control on the prompt that is not greyed."""
        return next(
            control
            for group in state["prompt"]["controls"]
            for control in group["controls"]
            if not control["disabled"]
        )

    async def test_a_coach_is_offered_the_prompt_and_a_spectator_is_not(
        self,
    ) -> None:
        mine = await self.state()
        theirs = await self.state(headers=as_coach(STRANGER))

        self.assertTrue(mine["you"]["is_coach"])
        self.assertTrue(mine["prompt"]["yours"])
        self.assertTrue(mine["prompt"]["controls"])
        self.assertFalse(theirs["you"]["is_coach"])
        self.assertEqual(theirs["prompt"]["controls"], [])

    async def test_a_control_pressed_plays_the_turn(self) -> None:
        state = await self.state()

        response = await self.press(self.live(state)["action"])
        played = await response.json()

        self.assertEqual(response.status, 200)
        self.assertIsNone(played["refusal"])
        # The ball has a handler: what the match asks now is the turn
        # itself, and the page is handed its controls in the same
        # answer.
        self.assertEqual(played["prompt"]["kind"], "player_action")
        self.assertTrue(played["prompt"]["controls"])

    async def test_an_action_nobody_offered_is_refused_and_nothing_moves(
        self,
    ) -> None:
        before = dict(self.game.match_state)

        response = await self.press(
            {
                "kind": PromptKind.SHOOTOUT_TEST.value,
                "choice": "roll",
                "arguments": {},
            },
        )
        refused = await response.json()

        self.assertEqual(response.status, 409)
        self.assertIn("not one of the controls", refused["refusal"])
        self.assertEqual(self.game.match_state, before)

    async def test_a_spectator_may_not_act(self) -> None:
        state = await self.state()
        before = dict(self.game.match_state)

        response = await self.press(
            self.live(state)["action"], headers=as_coach(STRANGER),
        )

        self.assertEqual(response.status, 409)
        self.assertEqual(self.game.match_state, before)

    async def test_a_turn_taken_elsewhere_reaches_the_page(self) -> None:
        """
        The other coach is on another page: their click goes through
        the service, and the journal is fed by the service
        (`GameService.listeners`), so the page sees what was said
        without having asked for it.
        """
        self.client, self.game = await self.open("coaching hub")
        state = await self.state()
        action = Action.from_dict(self.live(state)["action"])

        self.service.apply_action(self.game.game_id, action)
        caught_up = await self.client.get(
            f"/api/game/{self.game.game_id}",
            params={"since": str(state["latest"])},
            headers=self.coach,
        )
        page = await caught_up.json()

        self.assertTrue(page["entries"])
        self.assertTrue(page["entries"][0]["lines"])

    async def test_the_board_is_drawn_without_the_driver(self) -> None:
        response = await self.client.get(
            f"/api/game/{self.game.game_id}/board.png",
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "image/png")
        self.assertTrue((await response.read()).startswith(b"\x89PNG"))

    async def test_a_game_nobody_knows_is_not_found(self) -> None:
        response = await self.client.get("/api/game/nope")

        self.assertEqual(response.status, 404)


class IdentityTests(unittest.IsolatedAsyncioTestCase):
    """Who is reading: a name in a signed cookie, stored nowhere."""

    def test_a_cookie_round_trips(self) -> None:
        coach = identity.issue("  Ann  ")

        self.assertEqual(coach.name, "Ann")
        self.assertTrue(0 < coach.id <= identity.MAX_ID)
        self.assertEqual(identity.decode(identity.encode(coach)), coach)

    def test_a_tampered_cookie_is_nobody(self) -> None:
        value = identity.encode(Coach(111, "Ann"))
        payload, signature = value.rsplit(".", 1)
        forged = identity.encode(Coach(222, "Ann")).rsplit(".", 1)[0]

        for bad in (
            None,
            "",
            "no-dot",
            f"{payload}.{'0' * len(signature)}",
            f"{forged}.{signature}",
            f"not base64!.{signature}",
            "é.é",
        ):
            with self.subTest(bad):
                self.assertIsNone(identity.decode(bad))

    def test_a_signed_payload_that_is_not_a_coach_is_nobody(self) -> None:
        for data in ([1, 2], {"id": "111", "name": "Ann"},
                     {"id": 0, "name": "Ann"}, {"id": True, "name": "Ann"},
                     {"id": 111, "name": ""}):
            with self.subTest(data):
                payload = base64.urlsafe_b64encode(
                    json.dumps(data).encode("utf-8"),
                ).decode("ascii")
                self.assertIsNone(
                    identity.decode(f"{payload}.{identity._sign(payload)}"),
                )

    async def test_a_name_is_taken_and_a_rename_keeps_the_id(self) -> None:
        web = WebApp(GameService(ENGINE, {}, save=lambda games: None), GameLocks())
        client = TestClient(TestServer(web.app))
        await client.start_server()
        self.addAsyncCleanup(client.close)

        nobody = await client.get("/api/me")
        self.assertIsNone(await nobody.json())
        first = await (await client.post("/api/me", json={"name": "Ann"})).json()
        again = await (await client.get("/api/me")).json()
        renamed = await (await client.post("/api/me", json={"name": "Bea"})).json()

        self.assertEqual(again, first)
        self.assertEqual(renamed, {"id": first["id"], "name": "Bea"})
        for name in ("", "   ", "x" * 33, 7):
            with self.subTest(name):
                refused = await client.post("/api/me", json={"name": name})
                self.assertEqual(refused.status, 400)
                self.assertTrue(await refused.text())

    async def test_leaving_the_app_forgets_the_cookie(self) -> None:
        """Nothing is stored, so leaving is only forgetting the cookie
        -- a seat held under it is untouched, the way another device
        already leaves it alone."""
        web = WebApp(GameService(ENGINE, {}, save=lambda games: None), GameLocks())
        client = TestClient(TestServer(web.app))
        await client.start_server()
        self.addAsyncCleanup(client.close)

        await client.post("/api/me", json={"name": "Ann"})
        self.assertIsNotNone(await (await client.get("/api/me")).json())

        left = await client.delete("/api/me")
        self.assertEqual(left.status, 200)
        self.assertIsNone(await (await client.get("/api/me")).json())


class RoomTests(unittest.IsolatedAsyncioTestCase):
    """
    A room over the service: the first two in are its coaches and
    everybody after watches; a seat changes hands and the record
    judges every move; an admin kicks.
    """

    CREATOR, SECOND, THIRD, PHONE = 101, 202, 303, 404

    async def asyncSetUp(self) -> None:
        ENGINE.rng.seed(11)
        self.saved = 0

        def save(games) -> None:
            self.saved += 1

        self.games = {}
        self.service = GameService(ENGINE, self.games, save=save)
        self.client = await self.serve(Rooms())

    async def serve(self, rooms: Rooms) -> TestClient:
        self.web = WebApp(self.service, GameLocks(), rooms=rooms)
        self.web.watch()
        client = TestClient(TestServer(self.web.app))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        self.addAsyncCleanup(self.web.stop)
        return client

    async def open_room(self) -> str:
        response = await self.client.post(
            "/api/rooms", headers=as_coach(self.CREATOR, "Creator"),
        )
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertEqual(body["url"], f"/room/{body['id']}")
        return body["id"]

    async def arrive(self, room: str, coach_id: int) -> dict:
        response = await self.client.get(
            f"/api/game/{room}", headers=as_coach(coach_id),
        )
        self.assertEqual(response.status, 200)
        return await response.json()

    async def move(self, room: str, coach_id: int, path: str, body=None):
        return await self.client.post(
            f"/api/room/{room}{path}",
            headers=as_coach(coach_id),
            json=body or {},
        )

    def kick_off(self, room: str) -> None:
        """The lobby left and a match dealt, the way a fixture's game
        stands -- step 3's table is what does this on the page."""
        game = self.games[room]
        fixture = case("kickoff")
        game.in_lobby = False
        for name in (
            "status", "mode", "player_1_team", "player_2_team",
            "home_player_number", "visiting_player_number",
        ):
            setattr(game, name, getattr(fixture.game, name))
        game.match_state = fixture.match.to_dict()

    def controls(self, room: str, player_number) -> list:
        game = self.games[room]
        match = self.service.load(game)
        return controls_for(
            ENGINE, game, match, pending_prompt(ENGINE, game, match),
            Viewer(player_number),
        )

    async def test_opening_a_room_needs_a_name(self) -> None:
        response = await self.client.post("/api/rooms")

        self.assertEqual(response.status, 401)
        self.assertEqual(self.games, {})

    async def test_the_first_two_in_are_its_coaches(self) -> None:
        room = await self.open_room()
        page = await self.client.get(f"/room/{room}")
        self.assertEqual(page.status, 200)

        creator = await self.arrive(room, self.CREATOR)
        second = await self.arrive(room, self.SECOND)
        third = await self.arrive(room, self.THIRD)

        game = self.games[room]
        self.assertEqual((game.player_1_id, game.player_2_id),
                         (self.CREATOR, self.SECOND))
        self.assertEqual(creator["room"]["role"], "coach")
        self.assertEqual(creator["you"]["player_number"], 1)
        self.assertEqual(second["you"]["player_number"], 2)
        self.assertEqual(third["room"]["role"], "observer")
        self.assertFalse(third["you"]["is_coach"])
        self.assertEqual(third["room"]["observers"], 1)
        self.assertEqual(
            [(seat["label"], seat["name"]) for seat in third["room"]["seats"]],
            [("Coach 1", "Creator"), ("Coach 2", f"Coach {self.SECOND}")],
        )
        self.assertEqual(
            [seat["yours"] for seat in second["room"]["seats"]],
            [False, True],
        )

    async def test_each_coach_gets_their_own_controls_and_a_watcher_none(
        self,
    ) -> None:
        room = await self.open_room()
        await self.arrive(room, self.SECOND)
        await self.arrive(room, self.THIRD)
        self.kick_off(room)

        creator = await self.arrive(room, self.CREATOR)
        second = await self.arrive(room, self.SECOND)
        third = await self.arrive(room, self.THIRD)

        self.assertEqual(creator["prompt"]["controls"], self.controls(room, 1))
        self.assertEqual(second["prompt"]["controls"], self.controls(room, 2))
        self.assertTrue(
            creator["prompt"]["controls"] or second["prompt"]["controls"],
        )
        self.assertEqual(third["prompt"]["controls"], [])
        # The coin has settled home and visiting: the seats say so.
        self.assertEqual(creator["room"]["role"], "home")
        self.assertEqual(second["room"]["role"], "visiting")
        self.assertEqual(
            [seat["label"] for seat in third["room"]["seats"]],
            ["Home Team Coach", "Visitors Team Coach"],
        )

    async def test_a_seat_left_is_taken_from_another_device(self) -> None:
        room = await self.open_room()
        await self.arrive(room, self.SECOND)

        left = await self.move(room, self.SECOND, "/seat/leave")
        self.assertEqual(left.status, 200)
        self.assertIsNone(self.games[room].player_2_id)
        # Somebody who left is not sat back down by their next poll.
        again = await self.arrive(room, self.SECOND)
        self.assertEqual(again["room"]["role"], "observer")

        phone = await self.arrive(room, self.PHONE)

        self.assertEqual(phone["you"]["player_number"], 2)
        self.assertEqual(self.games[room].player_2_id, self.PHONE)

    async def test_a_seat_changes_hands_mid_match_with_the_same_controls(
        self,
    ) -> None:
        room = await self.open_room()
        await self.arrive(room, self.SECOND)
        self.kick_off(room)
        before = (await self.arrive(room, self.CREATOR))["prompt"]

        left = await self.move(room, self.CREATOR, "/seat/leave")
        self.assertEqual(left.status, 200)
        taken = await self.move(room, self.PHONE, "/seat/take", {"seat": 1})
        self.assertEqual(taken.status, 200)
        after = (await self.arrive(room, self.PHONE))["prompt"]

        self.assertEqual(after, before)
        self.assertEqual(
            (await self.arrive(room, self.CREATOR))["prompt"]["controls"], [],
        )

    async def test_seat_two_left_mid_match_waits_for_somebody(self) -> None:
        """An empty seat is nobody's -- not the AI's -- and its side's
        question waits for whoever takes it."""
        room = await self.open_room()
        await self.arrive(room, self.SECOND)
        self.kick_off(room)
        before = self.controls(room, 2)

        response = await self.move(room, self.SECOND, "/seat/leave")
        state = await response.json()

        self.assertEqual(response.status, 200)
        self.assertFalse(self.games[room].is_solo_game)
        self.assertEqual(
            (state["room"]["seats"][1]["name"], state["room"]["seats"][1]["ai"]),
            (None, False),
        )
        phone = await self.arrive(room, self.PHONE)
        self.assertEqual(phone["you"]["player_number"], 2)
        self.assertEqual(phone["prompt"]["controls"], before)

    async def test_anybody_seated_puts_dinky_in_and_an_admin_kicks_it(
        self,
    ) -> None:
        room = await self.open_room()
        await self.arrive(room, self.SECOND)
        await self.move(room, self.SECOND, "/seat/leave")
        self.assertIsNone(self.games[room].player_2_id)

        # Somebody watching may not; somebody seated may.
        refused = await self.move(room, self.SECOND, "/seat/ai", {"seat": 2})
        self.assertEqual(refused.status, 403)
        put = await self.move(room, self.CREATOR, "/seat/ai", {"seat": 2})
        seats = (await put.json())["room"]["seats"]

        self.assertEqual(put.status, 200)
        self.assertEqual((seats[1]["name"], seats[1]["ai"]), ("Dinky AI", True))
        self.assertTrue(self.games[room].ai_holds(2))

        kick = await self.move(room, self.SECOND, "/seat/kick", {"seat": 2})
        self.assertEqual(kick.status, 403)
        await self.move(room, self.SECOND, "/admin")
        kicked = await self.move(room, self.SECOND, "/seat/kick", {"seat": 2})
        self.assertEqual(kicked.status, 200)
        self.assertFalse(self.games[room].is_solo_game)

        taken = await self.move(room, self.SECOND, "/seat/take", {"seat": 2})
        self.assertEqual((await taken.json())["you"]["player_number"], 2)

    async def test_dinky_seated_mid_match_answers_its_side(self) -> None:
        """The kickoff is the home side's question; its coach leaves,
        the other coach puts Dinky in, and Dinky answers it -- the
        page sees the answer through the journal."""
        room = await self.open_room()
        await self.arrive(room, self.SECOND)
        self.kick_off(room)
        before = pending_prompt(
            ENGINE, self.games[room], self.service.load(self.games[room]),
        ).kind
        await self.move(room, self.CREATOR, "/seat/leave")

        put = await self.move(room, self.SECOND, "/seat/ai", {"seat": 1})
        state = await put.json()

        self.assertEqual(put.status, 200)
        self.assertEqual(state["room"]["seats"][0]["name"], "Dinky AI")
        self.assertNotEqual(state["prompt"]["kind"], before.value)
        self.assertTrue(state["entries"])

    async def test_an_admin_gives_the_role_up(self) -> None:
        room = await self.open_room()
        made = await self.move(room, self.CREATOR, "/admin")
        self.assertTrue((await made.json())["room"]["admin"])

        dropped = await self.client.delete(
            f"/api/room/{room}/admin", headers=as_coach(self.CREATOR),
        )

        self.assertFalse((await dropped.json())["room"]["admin"])
        self.assertFalse(self.web.rooms.is_admin(room, self.CREATOR))

    async def test_a_held_seat_refuses_with_the_record_s_sentence(self) -> None:
        room = await self.open_room()
        saved = self.saved

        response = await self.move(room, self.THIRD, "/seat/take", {"seat": 1})
        body = await response.json()

        self.assertEqual(response.status, 409)
        self.assertEqual(body["refusal"], "That seat is held by somebody else.")
        self.assertEqual(self.games[room].player_1_id, self.CREATOR)
        self.assertEqual(self.saved, saved)

    async def test_only_an_admin_kicks(self) -> None:
        room = await self.open_room()
        await self.arrive(room, self.SECOND)
        await self.arrive(room, self.THIRD)

        refused = await self.move(room, self.THIRD, "/seat/kick", {"seat": 2})
        self.assertEqual(refused.status, 403)
        self.assertEqual(self.games[room].player_2_id, self.SECOND)

        made = await self.move(room, self.THIRD, "/admin")
        self.assertTrue((await made.json())["room"]["admin"])
        kicked = await self.move(room, self.THIRD, "/seat/kick", {"seat": 2})

        self.assertEqual(kicked.status, 200)
        self.assertIsNone(self.games[room].player_2_id)
        taken = await self.move(room, self.THIRD, "/seat/take")
        self.assertEqual((await taken.json())["you"]["player_number"], 2)

    async def test_an_observer_is_sent_neither_side_s_secret(self) -> None:
        """What the observer is handed does not change with the secret
        a side has set -- so it does not carry it."""
        def set_pick(match, key):
            match.offense_maneuver = key

        def set_order(match, reverse):
            squad = list(match.shootout_squad(TeamSide.HOME))
            match.set_shootout_order(
                TeamSide.HOME, squad[::-1] if reverse else squad,
            )

        for name, secret, one, other in (
            ("maneuver picks", set_pick, "low_pass", "double_team"),
            ("shootout order", set_order, False, True),
        ):
            with self.subTest(name):
                seen = []
                for value in (one, other):
                    fixture = case(name)
                    secret(fixture.match, value)
                    service = service_over(fixture)
                    web = WebApp(service, GameLocks())
                    client = TestClient(TestServer(web.app))
                    await client.start_server()
                    response = await client.get(
                        f"/api/game/{fixture.game.game_id}",
                        headers=as_coach(STRANGER),
                    )
                    state = await response.json()
                    await client.close()
                    self.assertEqual(state["room"]["role"], "observer")
                    self.assertEqual(state["prompt"]["controls"], [])
                    seen.append(json.dumps(state, sort_keys=True))
                self.assertEqual(seen[0], seen[1])

    async def test_the_room_and_its_admin_survive_a_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            games_file = folder / "web_games.json"
            rooms_file = folder / "web_rooms.json"
            self.service._save = lambda games: storage.save_games(
                games, games_file,
            )
            self.client = await self.serve(Rooms(rooms_file))
            room = await self.open_room()
            await self.arrive(room, self.SECOND)
            await self.move(room, self.SECOND, "/admin")

            # A new process: both files read again.
            self.games = storage.load_games(games_file)
            self.service = GameService(
                ENGINE, self.games, save=lambda games: None,
            )
            self.client = await self.serve(
                Rooms.load(rooms_file, self.games),
            )
            page = await self.client.get(f"/room/{room}")
            state = await self.arrive(room, self.SECOND)

        self.assertEqual(page.status, 200)
        self.assertEqual(state["you"]["player_number"], 2)
        self.assertTrue(state["room"]["admin"])

    def test_a_room_the_games_file_has_lost_is_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rooms.json"
            path.write_text(json.dumps({
                "kept": {"admins": [1], "seen": [1, 2]},
                "gone": {"admins": [3], "seen": [3]},
            }))

            rooms = Rooms.load(path, ["kept"])

        self.assertEqual(set(rooms.rooms), {"kept"})
        self.assertTrue(rooms.is_admin("kept", 1))


class ChatTests(unittest.IsolatedAsyncioTestCase):
    """
    The room's chat (step 4 of docs/web-app-next.md): people talking,
    under the name on their cookie, riding on the poll, kept in the web
    app's own file and never on the game.
    """

    CREATOR, SECOND, THIRD = 101, 202, 303

    async def asyncSetUp(self) -> None:
        ENGINE.rng.seed(11)
        self.games = {}
        self.service = GameService(ENGINE, self.games, save=lambda games: None)
        self.client = await self.serve(Rooms(), Chats())
        self.room = await self.open_room()
        for coach_id in (self.SECOND, self.THIRD):
            await self.poll(coach_id)

    async def serve(self, rooms: Rooms, chats: Chats) -> TestClient:
        self.web = WebApp(self.service, GameLocks(), rooms=rooms, chats=chats)
        self.web.watch()
        client = TestClient(TestServer(self.web.app))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        self.addAsyncCleanup(self.web.stop)
        return client

    async def open_room(self) -> str:
        response = await self.client.post(
            "/api/rooms", headers=as_coach(self.CREATOR, "Creator"),
        )
        return (await response.json())["id"]

    async def say(self, coach_id, text, since: int = 0):
        headers = {} if coach_id is None else as_coach(
            coach_id, f"Person {coach_id}",
        )
        return await self.client.post(
            f"/api/room/{self.room}/chat",
            params={"chat_since": str(since)},
            headers=headers,
            json={"text": text},
        )

    async def poll(self, coach_id, since: int = 0) -> dict:
        response = await self.client.get(
            f"/api/game/{self.room}",
            params={"chat_since": str(since)},
            headers=as_coach(coach_id, f"Person {coach_id}"),
        )
        self.assertEqual(response.status, 200)
        return await response.json()

    async def test_a_coach_posts_and_everybody_in_the_room_sees_it(
        self,
    ) -> None:
        response = await self.say(self.CREATOR, "good luck")
        self.assertEqual(response.status, 200)

        for coach_id in (self.CREATOR, self.SECOND, self.THIRD):
            with self.subTest(coach_id):
                chat = (await self.poll(coach_id))["chat"]
                self.assertEqual(
                    [(one["name"], one["text"]) for one in chat],
                    [(f"Person {self.CREATOR}", "good luck")],
                )
                self.assertEqual(chat[0]["yours"], coach_id == self.CREATOR)
        # The poster's own answer carries the line, so it shows at once.
        self.assertEqual(
            [one["text"] for one in (await response.json())["chat"]],
            ["good luck"],
        )

    async def test_an_observer_may_post_and_is_drawn_plain(self) -> None:
        self.kick_off()
        await self.say(self.CREATOR, "ready")
        response = await self.say(self.THIRD, "watching")

        self.assertEqual(response.status, 200)
        chat = (await self.poll(self.SECOND))["chat"]
        self.assertEqual(
            [(one["name"], one["text"]) for one in chat],
            [(f"Person {self.CREATOR}", "ready"),
             (f"Person {self.THIRD}", "watching")],
        )
        # A coach's name in their team's colour; an observer's plain.
        self.assertEqual(
            chat[0]["colour"], self.web._coach(self.games[self.room], 1)["colour"],
        )
        self.assertIsNotNone(chat[0]["colour"])
        self.assertIsNone(chat[1]["colour"])

    def kick_off(self) -> None:
        game = self.games[self.room]
        fixture = case("kickoff")
        game.in_lobby = False
        for name in (
            "status", "mode", "player_1_team", "player_2_team",
            "home_player_number", "visiting_player_number",
        ):
            setattr(game, name, getattr(fixture.game, name))
        game.match_state = fixture.match.to_dict()

    async def test_nobody_named_may_not_post(self) -> None:
        response = await self.say(None, "hello")

        self.assertEqual(response.status, 403)
        self.assertEqual(self.web.chats.chat(self.room).since(0), [])

    async def test_a_message_too_long_or_empty_is_refused(self) -> None:
        for text in ("x" * 501, "   ", "", None):
            with self.subTest(repr(text)[:20]):
                response = await self.say(self.CREATOR, text)
                self.assertEqual(response.status, 400)
        # 500 after stripping is taken whole.
        response = await self.say(self.CREATOR, "  " + "x" * 500 + "  ")
        self.assertEqual(response.status, 200)
        self.assertEqual(
            [len(one.text) for one in self.web.chats.chat(self.room).since(0)],
            [500],
        )

    async def test_the_cursor_hands_over_only_what_is_newer(self) -> None:
        await self.say(self.CREATOR, "one")
        await self.say(self.SECOND, "two")
        state = await self.poll(self.THIRD, since=1)

        self.assertEqual([one["text"] for one in state["chat"]], ["two"])
        self.assertEqual(state["chat_latest"], 2)
        # An answer to an action reads the cursor too, so a page that
        # acts is not handed the whole chat again.
        response = await self.client.post(
            f"/api/room/{self.room}/admin",
            params={"chat_since": "2"},
            headers=as_coach(self.THIRD),
        )
        self.assertEqual((await response.json())["chat"], [])

    async def test_the_bound_holds_and_the_ids_keep_counting(self) -> None:
        chats = self.web.chats
        for number in range(CHAT_LENGTH + 5):
            chats.post(self.room, self.CREATOR, "Creator", str(number))

        state = await self.poll(self.SECOND)

        self.assertEqual(len(state["chat"]), CHAT_LENGTH)
        self.assertEqual(state["chat"][0]["text"], "5")
        self.assertEqual(state["chat_latest"], CHAT_LENGTH + 5)

    async def test_the_chat_survives_a_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chat_file = Path(directory) / "web_chat.json"
            self.client = await self.serve(Rooms(), Chats(chat_file))
            await self.say(self.CREATOR, "before")
            await self.say(self.THIRD, "the restart")

            # A new process: the file read again.
            self.client = await self.serve(
                Rooms(), Chats.load(chat_file, self.games),
            )
            await self.say(self.SECOND, "after")
            state = await self.poll(self.THIRD)

            # A room the games file has lost is dropped on load.
            self.assertEqual(Chats.load(chat_file, []).chats, {})

        self.assertEqual(
            [(one["id"], one["text"]) for one in state["chat"]],
            [(1, "before"), (2, "the restart"), (3, "after")],
        )
        self.assertEqual(
            [one["yours"] for one in state["chat"]], [False, True, False],
        )

    async def test_markup_is_handed_over_as_the_text_it_was_and_never_saved(
        self,
    ) -> None:
        """
        A chat line is not the model's voice: `<b>`, a token and
        markdown arrive exactly as typed -- plain text for the page to
        set with `textContent` -- where the journal's sentences are
        escaped and tokenised (`render_text`). And the game's save
        never holds it.
        """
        written = "<b>{team:orange}</b> **not bold**"
        with tempfile.TemporaryDirectory() as directory:
            games_file = Path(directory) / "web_games.json"
            self.service._save = lambda games: storage.save_games(
                games, games_file,
            )
            self.kick_off()
            self.service._save(self.games)
            response = await self.say(self.CREATOR, written)
            said = (await response.json())["chat"][0]["text"]
            saved = games_file.read_text(encoding="utf-8")

        self.assertEqual(said, written)
        self.assertNotIn("not bold", saved)
        self.assertNotIn("not bold", json.dumps(self.games[self.room].to_dict()))
        self.assertNotIn("<b>", render_text(self.games[self.room], written))

    def test_the_page_sets_a_chat_line_as_text(self) -> None:
        """The page never hands a chat line to innerHTML."""
        script = (Path(server.STATIC) / "app.js").read_text(encoding="utf-8")
        start = script.index("function drawChat(")
        body = script[start:script.index("\n}\n", start)]
        self.assertNotIn("html", body.lower())
        self.assertIn("message.text", body)


class EntryPointTests(unittest.TestCase):
    """
    `python3 -m webapp` builds a service of its own over its own file
    (docs/web-app-next.md, step 1): the bot's games are never loaded
    and never written.
    """

    def test_the_service_saves_the_file_it_was_given_and_no_other(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            bot_file = folder / "d12ball_games.json"
            web_file = folder / "d12ball_web_games.json"
            with mock.patch.object(storage, "GAMES_FILE", bot_file), \
                 mock.patch.object(storage, "DATA_FOLDER", folder):
                service = server.build_service(web_file)
                service.create_game(player_1_id=1, player_1_name="One")

            self.assertTrue(web_file.exists())
            self.assertFalse(bot_file.exists())
            self.assertEqual(len(json.loads(web_file.read_text())), 1)

    def test_it_takes_the_default_batching(self) -> None:
        """Discord's economy is the cog's; the web app has no rate
        limit to batch for."""
        with tempfile.TemporaryDirectory() as directory:
            service = server.build_service(Path(directory) / "web.json")

        self.assertEqual(service.batching, GameService(None, {}).batching)


if __name__ == "__main__":
    unittest.main()

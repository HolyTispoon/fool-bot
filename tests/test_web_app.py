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

import asyncio
import base64
import importlib
import inspect
import html
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aiohttp import DummyCookieJar
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

from d12ball.components import MatchState, TeamSide
from d12ball.engine import SPREADABLE_NOTE
from d12ball.render import TEAM_COLORS
from d12ball.flow import FollowOnStep
from d12ball.formatting import coach_name
from d12ball.game import AIOpponent, GameMode, Team, team_display_name
from d12ball.prompts import Action, PromptKind, asked_sides, pending_prompt
from gamesaves.d12ball import storage
from gamesaves.d12ball.service import GameService
from webapp import identity, keys, present, server
from webapp.board import board_layout, side_colour
from webapp.identity import Coach
from gamelocks import GameLocks
from webapp.present import CONTROLS, Viewer, controls_for, lit_line, render_text
from webapp.chat import CHAT_LENGTH, WEB_CHAT_FILE, Chats
from webapp.journal import WEB_JOURNAL_FILE, Entry
from webapp.names import Names
from webapp.rooms import WEB_ROOMS_FILE, Rooms
from webapp.server import (
    ABANDON_IDLE, OPEN_ROOM_IDLE, UNPLAYED_ROOM_IDLE, WebApp, _was_offered,
)
from prompt_fixtures import (
    CASES,
    ENGINE,
    GAME_ID,
    build_match,
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
        offered and the model accepts it, with nothing added -- whether
        the control is an object lit on the board (step 4 of
        docs/web-app-redesign.md) or the neutral one, it sends the
        `Action` the button always sent, and the server lets it
        through as offered.
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
                    offered = controls_for(
                        ENGINE,
                        fixture.game,
                        fixture.match,
                        prompt,
                        Viewer(player_number),
                    )
                    for group in offered:
                        for control in group["controls"]:
                            self._accepted(entry, control, offered)

    def _accepted(self, entry, control, offered) -> None:
        """One control, pressed on a fresh copy of its own fixture: as
        the page sends it, every answer of a chooser opened from its
        object on the board, the first of one in the box."""
        if control.get("disabled"):
            return
        if control["type"] == "chooser" and control.get("place"):
            one = control["fields"][0]
            for choice in one["choices"]:
                self._pressed(entry, control, offered, {one["name"]: choice["value"]})
            return
        chosen = {}
        if control["type"] == "chooser":
            for one in control["fields"]:
                chosen[one["name"]] = one["choices"][0]["value"]
        self._pressed(entry, control, offered, chosen)

    def _pressed(self, entry, control, offered, chosen) -> None:
        arguments = {**control["action"]["arguments"], **chosen}
        self.assertTrue(
            _was_offered(offered, {**control["action"], "arguments": arguments}),
            f"{control['label']!r} as the page sends it is not an offer",
        )
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
        """The hub answers on the board now (step 6), and a chooser is
        left only where a move needs a second question -- which of two
        teammates sharing a space comes back -- so the chooser is built
        here, the way `_repositions` builds it."""
        chooser = present.chooser(
            "Hellguard [FB] to space 2 -- who comes back?",
            "Move",
            [present.field("swap_with", "", [("a", "A [DD]"), ("b", "B [MF]")])],
            PromptKind.COACHING_HUB,
            "reposition",
            side="home",
            player_id="p",
            space_index=1,
        )
        offered = [present.section(None, [chooser])]
        good = {
            **chooser["action"]["arguments"],
            **{
                one["name"]: one["choices"][0]["value"]
                for one in chooser["fields"]
            },
        }
        bad = {**good, chooser["fields"][0]["name"]: "somebody-else"}

        self.assertTrue(
            _was_offered(offered, {**chooser["action"], "arguments": good}),
        )
        self.assertFalse(
            _was_offered(offered, {**chooser["action"], "arguments": bad}),
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

    async def test_the_page_and_its_script_are_asked_for_fresh(
        self,
    ) -> None:
        # Unversioned names under one page: kept without asking, the
        # old script ran under the new page and a room drew nothing.
        for path in (
            "/static/app.js", "/static/app.css", "/static/game.html",
            f"/room/{self.game.game_id}", "/",
        ):
            with self.subTest(path=path):
                response = await self.client.get(path, headers=self.coach)
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Cache-Control"], "no-cache")

    async def test_a_picture_that_says_how_long_to_keep_it_keeps_its_own(
        self,
    ) -> None:
        response = await self.client.get("/emoji/team_orange.png")

        self.assertEqual(response.status, 200)
        self.assertNotEqual(response.headers["Cache-Control"], "no-cache")

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

    async def test_the_lit_time_out_tile_is_the_time_out_button(self) -> None:
        """
        The time out left the question box for the jumbotron bar's tile
        (step 2 of docs/web-app-redesign.md): pressing the lit tile
        sends the turn's own answer, and plays exactly what the Time
        out button did -- the same `Action` through the same door.
        """
        ENGINE.rng.seed(11)
        self.client, self.game = await self.open("plain turn")
        state = await self.state()
        tile = next(
            control
            for group in state["prompt"]["controls"]
            for control in group["controls"]
            if control.get("place", {}).get("at") == "time_out_tile"
        )
        self.assertFalse(tile["disabled"])

        response = await self.press(tile["action"])
        pressed = await response.json()
        self.assertEqual(response.status, 200)
        self.assertIsNone(pressed["refusal"])

        ENGINE.rng.seed(11)
        fixture = case("plain turn")
        button = service_over(fixture)
        result = button.apply_action(
            fixture.game.game_id,
            Action(PromptKind.PLAYER_ACTION, "time_out"),
        )

        self.assertIsNone(result.refusal)
        self.assertEqual(
            self.game.match_state, fixture.game.match_state,
        )
        self.assertEqual(pressed["prompt"]["kind"], result.prompt.kind.value)
        # The bar now shows the time out spent for the side that
        # called it.
        side = tile["place"]["side"]
        self.assertEqual(
            pressed["board"]["layout"]["jumbotron"][side]["time_out"], "spent",
        )

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


class LitLineTests(unittest.TestCase):
    """What the question box says is lit on the board, and what is
    dark (`present.lit_line`), off the controls it was built from."""

    def setUp(self) -> None:
        ENGINE.rng.seed(11)

    def lines(self, fixture, player_number):
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        viewer = Viewer(player_number)
        controls = controls_for(
            ENGINE, fixture.game, fixture.match, prompt, viewer,
        )
        return lit_line(
            ENGINE, fixture.game, fixture.match, prompt, viewer, controls,
        )

    def test_the_turn_says_what_is_lit_and_what_is_dark(self) -> None:
        fixture = case("plain turn")
        fixture.match.scoreboard.last_possession = True
        mine = ENGINE.side_player_number(
            fixture.game, fixture.match.ball.possession,
        )
        lines = self.lines(fixture, mine)
        lit = [line["text"] for line in lines if not line["dark"]]
        dark = [line["text"] for line in lines if line["dark"]]
        self.assertTrue(any(text.startswith("The ball") for text in lit))
        self.assertTrue(any("time-out tile is dark" in text for text in dark))

    def test_a_choice_carries_its_picture_and_the_control_it_presses(self) -> None:
        """Beside the ball's picture the box says only what choosing it
        does -- the picture says it is the ball -- and each live line
        names the control the thing on the field presses (the author,
        2026-09-29)."""
        fixture = case("plain turn")
        mine = ENGINE.side_player_number(
            fixture.game, fixture.match.ball.possession,
        )
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        controls = controls_for(
            ENGINE, fixture.game, fixture.match, prompt, Viewer(mine),
        )
        lines = lit_line(
            ENGINE, fixture.game, fixture.match, prompt, Viewer(mine), controls,
        )
        live = [line for line in lines if not line["dark"]]
        self.assertTrue(live)
        for line in live:
            group, index = line["control"]
            self.assertEqual(
                controls[group]["controls"][index]["place"], line["place"],
            )
        ball = next(line for line in live if line["place"] == {"at": "ball"})
        self.assertEqual(ball["words"], "maneuver")

    def test_the_goal_says_score_on_the_field_and_more_in_the_box(self) -> None:
        """The goal's chip on the field is "score!", and the question
        box says "shoot to score" beside its picture (the author,
        2026-09-29)."""
        fixture = case("plain turn")
        mine = ENGINE.side_player_number(
            fixture.game, fixture.match.ball.possession,
        )
        with mock.patch.object(MatchState, "can_attempt_score", return_value=True):
            prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
            controls = controls_for(
                ENGINE, fixture.game, fixture.match, prompt, Viewer(mine),
            )
            lines = lit_line(
                ENGINE, fixture.game, fixture.match, prompt, Viewer(mine),
                controls,
            )
        shot = next(
            control
            for group in controls for control in group["controls"]
            if control["action"]["choice"] == "shoot"
        )
        self.assertEqual(shot["chip"], "score!")
        goal = next(line for line in lines if line.get("place") == shot["place"])
        self.assertEqual(goal["words"], "shoot to score")

    def test_nobody_but_the_coach_asked_is_told_what_is_lit(self) -> None:
        fixture = case("plain turn")
        mine = ENGINE.side_player_number(
            fixture.game, fixture.match.ball.possession,
        )
        self.assertEqual(self.lines(fixture, 2 if mine == 1 else 1), [])

    def test_a_lit_meeple_is_named_with_what_clicking_it_means(self) -> None:
        fixture = case("maneuver challenge")
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        side = asked_sides(fixture.match, prompt)[0]
        number = ENGINE.side_player_number(fixture.game, side)
        lines = self.lines(fixture, number)
        names = {
            ENGINE.format_roster_player(one)
            for one in prompt.options.player_ids
        }
        for name in names:
            self.assertTrue(
                any(line["text"].startswith(name) for line in lines), name,
            )


class QuestionBoxTests(unittest.TestCase):
    """
    The question box (step 3 of docs/web-app-redesign.md): every
    prompt is put up in it under one of four tags, and which tag is
    read off whose question it is -- `asked_sides` -- never decided by
    the page.
    """

    TAGS = {"yours", "waiting", "now", "full_time"}

    def setUp(self) -> None:
        ENGINE.rng.seed(11)

    def box(self, fixture: PromptFixture, viewer: Viewer) -> dict:
        web = WebApp(service_over(fixture), GameLocks())
        return web._state(fixture.game, viewer)["prompt"]

    def test_every_prompt_fixture_renders_in_the_box(self) -> None:
        for entry in CASES:
            if not entry.asked or entry.ai:
                continue
            with self.subTest(entry.name):
                fixture = entry.build()
                prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
                sides = asked_sides(fixture.match, prompt)
                for number in (1, 2, None):
                    box = self.box(fixture, Viewer(number))
                    self.assertIn(box["state"], self.TAGS)
                    if prompt.kind is PromptKind.GAME_OVER:
                        expected = "full_time"
                    elif not sides:
                        expected = "now"
                    elif box["controls"]:
                        expected = "yours"
                    else:
                        expected = "waiting"
                    self.assertEqual(box["state"], expected, number)
                    if box["state"] in ("yours", "waiting"):
                        self.assertEqual(box["yours"], box["state"] == "yours")

    def test_a_roll_is_now_for_both_coaches_and_an_observer(self) -> None:
        fixture = case("skill test")
        for number in (1, 2, None):
            self.assertEqual(self.box(fixture, Viewer(number))["state"], "now")

    def test_a_turn_is_yours_to_one_coach_and_waited_on_by_the_rest(
        self,
    ) -> None:
        fixture = case("plain turn")
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        (side,) = asked_sides(fixture.match, prompt)
        asked = ENGINE.side_player_number(fixture.game, side)
        other = 3 - asked
        self.assertEqual(self.box(fixture, Viewer(asked))["state"], "yours")
        self.assertEqual(self.box(fixture, Viewer(other))["state"], "waiting")
        self.assertEqual(self.box(fixture, Viewer(None))["state"], "waiting")

    def test_the_finished_game_is_full_time(self) -> None:
        fixture = case("game over")
        for number in (1, 2, None):
            self.assertEqual(
                self.box(fixture, Viewer(number))["state"], "full_time",
            )

    def named(self, fixture: PromptFixture) -> PromptFixture:
        fixture.game.player_1_name = "bright_bear_42696"
        fixture.game.player_2_name = "jolly_sprite_44424"
        return fixture

    def test_a_turn_names_the_coach_it_waits_on(self) -> None:
        fixture = self.named(case("plain turn"))
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        (side,) = asked_sides(fixture.match, prompt)
        asked = ENGINE.side_player_number(fixture.game, side)
        name = coach_name(fixture.game, asked)
        for number in (3 - asked, None):
            self.assertEqual(
                self.box(fixture, Viewer(number))["waiting_on"], [name],
            )

    def test_the_ai_is_named_as_the_record_names_it(self) -> None:
        fixture = self.named(case("plain turn"))
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        (side,) = asked_sides(fixture.match, prompt)
        asked = ENGINE.side_player_number(fixture.game, side)
        setattr(fixture.game, f"player_{asked}_id", None)
        fixture.game.ai_seats = [asked]
        fixture.game.ai_opponent = AIOpponent.DINKY
        self.assertEqual(
            self.box(fixture, Viewer(None))["waiting_on"],
            [coach_name(fixture.game, asked)],
        )
        self.assertIn("Dinky", self.box(fixture, Viewer(None))["waiting_on"][0])

    def test_the_maneuver_pick_names_the_other_hand_whoever_has_picked(
        self,
    ) -> None:
        fixture = self.named(case("maneuver picks"))
        offense = ENGINE.side_player_number(
            fixture.game, fixture.match.ball.possession,
        )
        other = [coach_name(fixture.game, 3 - offense)]
        both = [coach_name(fixture.game, number) for number in (1, 2)]
        self.assertCountEqual(
            self.box(fixture, Viewer(None))["waiting_on"], both,
        )
        fixture.match.offense_maneuver = "low_pass"
        box = self.box(fixture, Viewer(offense))
        self.assertEqual(box["state"], "waiting")
        self.assertEqual(box["waiting_on"], other)
        # Nobody learns from it that a card is down: the observer is
        # told both names still.
        self.assertCountEqual(
            self.box(fixture, Viewer(None))["waiting_on"], both,
        )

    def test_a_question_that_is_yours_waits_on_nobody_else(self) -> None:
        fixture = self.named(case("plain turn"))
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        (side,) = asked_sides(fixture.match, prompt)
        asked = ENGINE.side_player_number(fixture.game, side)
        self.assertEqual(self.box(fixture, Viewer(asked))["waiting_on"], [])

    def test_a_roll_waits_on_nobody(self) -> None:
        fixture = self.named(case("skill test"))
        self.assertEqual(self.box(fixture, Viewer(None))["waiting_on"], [])


class OutcomeBannerTests(unittest.TestCase):
    """
    The outcome the question box puts up large (step 3 of
    docs/web-app-redesign.md) is the model's own: its headline is a
    heading line the narration already says, word for word, and the
    line under it one the narration says too -- never the page's
    wording. Driven through the service, as a click is, with the web
    app's journal listening.
    """

    def setUp(self) -> None:
        ENGINE.rng.seed(11)

    def open(self, name: str):
        fixture = case(name)
        if name == "own goal":
            # The fixture asks the question; rolling it needs the
            # ball-handler whose roll it is.
            take_the_ball(fixture.match)
        web = WebApp(service_over(fixture), GameLocks())
        web.watch()
        return web, fixture.game

    def press(self, web, game, number: int, keep) -> None:
        match = web.service.load(game)
        prompt = pending_prompt(ENGINE, game, match)
        (control,) = [
            control
            for group in controls_for(
                ENGINE, game, match, prompt, Viewer(number),
            )
            for control in group["controls"]
            if not control["disabled"] and keep(control["action"])
        ]
        result = web.service.apply_action(
            game.game_id, Action.from_dict(control["action"]),
        )
        self.assertIsNone(result.refusal)

    def said(self, web, game) -> list[str]:
        """Every line the page's log holds, as the model wrote it."""
        return [
            line
            for entry in web.journal(game.game_id).entries
            for block in entry.lines
            for line in block.split("\n")
        ]

    def assert_the_narration_s_own(self, web, game) -> dict:
        """Every headline up is a heading the narration says, and the
        banner is them one after the other, as the canvas joins them;
        the first is handed back."""
        headlines = web.journal(game.game_id).showing_outcomes
        self.assertTrue(headlines, "no outcome up")
        said = self.said(web, game)
        for written in headlines:
            # Words the narration says, as it says them: a heading, or
            # the sentence a loose ball's winner is announced in.
            self.assertTrue(
                any(written["text"] in line for line in said),
                (written, said),
            )
            if written["under"]:
                self.assertTrue(
                    any(written["under"] in line for line in said),
                    (written, said),
                )
        state = web._state(game, Viewer(None))
        self.assertEqual(
            state["outcome"]["headline"],
            " · ".join(render_text(game, one["text"]) for one in headlines),
        )
        under = next((one["under"] for one in headlines if one["under"]), "")
        self.assertEqual(state["outcome"]["under"], render_text(game, under))
        return headlines[0]

    def pick(self, web, game, offense_key: str, defense_key: str) -> None:
        self.press(
            web, game, 1,
            lambda action: action["arguments"].get("maneuver_key")
            == offense_key,
        )
        self.press(
            web, game, 2,
            lambda action: action["arguments"].get("maneuver_key")
            == defense_key,
        )

    def test_a_resolved_maneuver_is_headed_by_its_own_line(self) -> None:
        web, game = self.open("maneuver picks")
        offense, defense = next(
            (offense, defense)
            for offense in ("low_pass", "dribble_advance", "high_pass")
            for defense in ("deflect", "steal", "pressure")
            if ENGINE.maneuver_catalog.resolve(offense, defense)
            == "offense"
        )
        self.pick(web, game, offense, defense)

        written = self.assert_the_narration_s_own(web, game)
        self.assertEqual(
            written["text"], f"**{ENGINE.maneuver_name(offense)}** wins!",
        )
        match = web.service.load(game)
        self.assertEqual(
            web._state(game, Viewer(None))["outcome"]["colour"],
            TEAM_COLORS[match.setup_for_side(TeamSide(written["side"])).team],
        )

    def test_a_saved_shot_is_headed_by_its_own_line(self) -> None:
        web, game = self.open("score attempt")
        match = web.service.load(game)
        defending = match.defending_side()
        # The attack rolls a 1 and the defence a 12.
        with mock.patch(
            "d12ball.flow.rolls.scripted_or_random",
            lambda engine, game, kind, count: [1, 12],
        ):
            self.press(
                web, game, 1, lambda action: action["choice"] == "roll",
            )

        written = self.assert_the_narration_s_own(web, game)
        self.assertEqual(written["text"], "Missed attempt!")
        self.assertEqual(written["side"], defending.value)
        self.assertTrue(written["under"])
        # The arithmetic is written out, from the numbers rolled.
        self.assertIn("rolled **1**", written["working"])
        self.assertIn("rolled **12**", written["working"])
        self.assertTrue(
            written["working"].endswith("the attack does not score."),
        )
        self.assertEqual(
            web._state(game, Viewer(None))["outcome"]["working"],
            render_text(game, written["working"]),
        )

    def test_a_skill_test_writes_its_arithmetic_out(self) -> None:
        web, game = self.open("skill test")
        with mock.patch(
            "d12ball.flow.rolls.scripted_or_random",
            lambda engine, game, kind, count: [9, 2],
        ):
            self.press(
                web, game, 1, lambda action: action["choice"] == "roll",
            )

        written = self.assert_the_narration_s_own(web, game)
        self.assertTrue(written["text"].endswith("wins the skill test!"))
        working = written["working"]
        self.assertIn("rolled **9**", working)
        self.assertIn("rolled **2**", working)
        self.assertIn("Offensive skill +", working)
        self.assertIn("Defensive skill +", working)
        self.assertIn(" beats ", working)

    def test_a_steal_is_headed_by_its_own_line(self) -> None:
        web, game = self.open("maneuver picks")
        offense = next(
            offense
            for offense in ("low_pass", "dribble_advance", "high_pass")
            if ENGINE.maneuver_catalog.resolve(offense, "steal")
            == "defense"
        )
        match = web.service.load(game)
        defending = match.defending_side()
        self.pick(web, game, offense, "steal")

        written = self.assert_the_narration_s_own(web, game)
        self.assertEqual(written["side"], defending.value)
        # The card and the turnover it caused, one after the other --
        # "STEAL · TURNOVER", as the canvas has it (the author, on
        # redesign step 3's PR).
        self.assertEqual(
            [one["text"] for one in web.journal(game.game_id).showing_outcomes],
            ["**Steal** wins!", "Turnover!"],
        )

    def roll_with(self, name: str, faces: list[int]):
        """Open `name`, press its roll as whichever coach is offered
        it, with these faces off the dice; the web app and the game."""
        web, game = self.open(name)
        faces = iter(faces)
        rolled = lambda engine, game, kind, count: [
            next(faces) for _ in range(count)
        ]
        with mock.patch("d12ball.flow.rolls.scripted_or_random", rolled), \
                mock.patch("d12ball.flow.effects.scripted_or_random", rolled):
            for number in (1, 2):
                match = web.service.load(game)
                prompt = pending_prompt(ENGINE, game, match)
                if any(
                    control["action"]["choice"] == "roll"
                    for group in controls_for(
                        ENGINE, game, match, prompt, Viewer(number),
                    )
                    for control in group["controls"]
                ):
                    self.press(
                        web, game, number,
                        lambda action: action["choice"] == "roll",
                    )
                    break
        return web, game

    def test_every_roll_writes_its_arithmetic_out(self) -> None:
        """The loose ball, the own goal and the shootout test are
        headed and worked like the skill test and the shot (the author,
        on redesign step 3's PR: "these should all get a headline and
        arithmetic")."""
        for name, faces, rolled in (
            ("loose ball roll", [9, 2], ("rolled **9**", "rolled **2**")),
            ("own goal", [3, 9], ("higher of 3/9",)),
            ("shootout test", [9, 2], ("rolled **9**", "rolled **2**")),
        ):
            with self.subTest(name):
                ENGINE.rng.seed(11)
                web, game = self.roll_with(name, faces)
                self.assert_the_narration_s_own(web, game)
                working = next(
                    one["working"]
                    for one in web.journal(game.game_id).showing_outcomes
                    if one["working"]
                )
                for said in rolled:
                    self.assertIn(said, working)
                self.assertEqual(
                    web._state(game, Viewer(None))["outcome"]["working"],
                    render_text(game, working),
                )

    def test_a_result_with_no_outcome_takes_the_banner_down(self) -> None:
        web, game = self.open("maneuver picks")
        self.press(
            web, game, 1,
            lambda action: action["arguments"].get("maneuver_key")
            == "low_pass",
        )
        self.assertEqual(web.journal(game.game_id).showing_outcomes, [])
        self.assertIsNone(web._state(game, Viewer(1))["outcome"])


class DiceTests(unittest.IsolatedAsyncioTestCase):
    """
    The dice a roll is drawn with: one fixture per shape a roll's
    `detail` comes in, pressed through the route, and the dice the page
    is handed for it (`present.rolled_dice`), which it draws itself.
    """

    #: The fixture and the shape its roll writes, named here rather
    #: than read off `present.ROLL_SHAPES`, so a wrong shape is caught.
    ROLLS = (
        ("skill test", "contest"),
        ("loose ball roll", "contest"),
        ("shootout test", "contest"),
        ("score attempt", "shot"),
        ("own goal", "own_goal"),
        ("mind pull", "mind_pull"),
        ("injury test", "injury"),
    )

    async def open(self, name: str):
        fixture = case(name)
        if name == "own goal":
            # The fixture asks the question; rolling it needs the
            # ball-handler whose roll it is.
            take_the_ball(fixture.match)
        service = service_over(fixture)
        web = WebApp(service, GameLocks())
        web.watch()
        client = TestClient(TestServer(web.app))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        self.addAsyncCleanup(web.stop)
        return client, fixture.game

    async def roll(self, client, game) -> tuple[dict, dict]:
        """Press the roll -- or, for a Mind Pull, take the ball --
        as whichever coach is offered it; the entry that carries it."""
        for coach_id in (game.player_1_id, game.player_2_id):
            headers = as_coach(coach_id)
            state = await (
                await client.get(f"/api/game/{game.game_id}", headers=headers)
            ).json()
            pressed = [
                control["action"]
                for group in state["prompt"]["controls"]
                for control in group["controls"]
                if not control["disabled"]
                and control["action"]["choice"] in ("roll", "take")
            ]
            if pressed:
                break
        response = await client.post(
            f"/api/game/{game.game_id}/action",
            params={"since": str(state["latest"])},
            headers=headers,
            data=json.dumps({"action": pressed[0]}),
        )
        played = await response.json()
        self.assertIsNone(played["refusal"])
        rolled = [entry for entry in played["entries"] if entry["dice"]]
        self.assertEqual(len(rolled), 1, played["entries"])
        return rolled[0], headers

    async def test_the_dice_are_up_until_the_next_thing(
        self,
    ) -> None:
        ENGINE.rng.seed(11)
        client, game = await self.open("injury test")
        entry, headers = await self.roll(client, game)

        state = await (
            await client.get(f"/api/game/{game.game_id}", headers=headers)
        ).json()
        watcher = await (
            await client.get(
                f"/api/game/{game.game_id}", headers=as_coach(STRANGER),
            )
        ).json()
        self.assertEqual(state["roll"]["shape"], entry["dice"])
        self.assertTrue(state["roll"]["dice"])
        # Everybody in the room sees what was rolled.
        self.assertEqual(watcher["roll"], state["roll"])

        # The next thing that happens takes them down.
        for coach_id in (game.player_1_id, game.player_2_id):
            headers = as_coach(coach_id)
            state = await (
                await client.get(f"/api/game/{game.game_id}", headers=headers)
            ).json()
            live = [
                control["action"]
                for group in (state["prompt"] or {}).get("controls", [])
                for control in group["controls"]
                if not control["disabled"]
            ]
            if live:
                break
        self.assertTrue(live, "no question after the injury test")
        played = await (
            await client.post(
                f"/api/game/{game.game_id}/action",
                params={"since": str(state["latest"])},
                headers=headers,
                data=json.dumps({"action": live[0]}),
            )
        ).json()
        self.assertIsNone(played["refusal"])
        rolled_again = any(said["dice"] for said in played["entries"])
        if rolled_again:
            self.assertTrue(played["roll"]["dice"])
        else:
            self.assertIsNone(played["roll"])

    async def test_every_roll_s_dice_are_handed_to_the_page_bare(self) -> None:
        """The page draws the dice itself, right after the headline, off
        `roll.dice`: a face a die in the roller's colour, and nothing
        the working already says (the author, 2026-09-29)."""
        count = {"contest": 2, "shot": 2, "own_goal": 2, "mind_pull": 1, "injury": 1}
        for name, shape in self.ROLLS:
            with self.subTest(name):
                ENGINE.rng.seed(11)
                client, game = await self.open(name)
                _, headers = await self.roll(client, game)
                state = await (
                    await client.get(f"/api/game/{game.game_id}", headers=headers)
                ).json()
                dice = state["roll"]["dice"]
                self.assertEqual(len(dice), count[shape])
                for one in dice:
                    self.assertEqual(set(one), {"face", "colour", "halo", "counts"})
                    self.assertIn(one["face"], range(1, 13))
                    self.assertIn(one["colour"], TEAM_COLORS.values())
                # Only the own-goal roll has a die that does not count.
                self.assertEqual(
                    sum(not one["counts"] for one in dice),
                    1 if shape == "own_goal" else 0,
                )

    def test_the_dice_are_the_roll_s_own_faces(self) -> None:
        fixture = case("own goal")
        match = fixture.match
        handler = take_the_ball(match)
        colour = TEAM_COLORS[match.team_for_player(handler)]
        self.assertEqual(
            present.rolled_dice(match, {
                "shape": "own_goal", "rolls": [9, 3], "offense_skill": 4,
                "safe": True, "overdrive": 2, "player_id": handler,
            }),
            [
                {"face": 9, "colour": colour, "halo": TEAM_COLORS[Team.CYBORGS], "counts": True},
                {"face": 3, "colour": colour, "halo": TEAM_COLORS[Team.CYBORGS], "counts": False},
            ],
        )
        self.assertEqual(
            present.rolled_dice(match, {
                "shape": "contest", "ignites": [],
                "contestants": [
                    {"roll": 7, "team": Team.ORANGE.value, "detail": [], "total": 7,
                     "overdriven": False, "merge": []},
                    {"roll": 12, "team": Team.PURPLE.value, "detail": [], "total": 12,
                     "overdriven": True, "merge": []},
                ],
            }),
            [
                {"face": 7, "colour": TEAM_COLORS[Team.ORANGE], "halo": None, "counts": True},
                {"face": 12, "colour": TEAM_COLORS[Team.PURPLE],
                 "halo": TEAM_COLORS[Team.CYBORGS], "counts": True},
            ],
        )
        self.assertEqual(present.rolled_dice(match, None), [])

    async def test_an_entry_with_no_roll_has_no_dice(self) -> None:
        ENGINE.rng.seed(11)
        client, game = await self.open("coaching hub")
        headers = as_coach(game.player_1_id)
        state = await (
            await client.get(f"/api/game/{game.game_id}", headers=headers)
        ).json()
        control = next(
            control
            for group in state["prompt"]["controls"]
            for control in group["controls"]
            if not control["disabled"]
        )

        played = await (
            await client.post(
                f"/api/game/{game.game_id}/action",
                headers=headers,
                data=json.dumps({"action": control["action"]}),
            )
        ).json()

        self.assertIsNone(played["entries"][0]["dice"])
        self.assertIsNone(played["roll"])


class SituationTests(unittest.IsolatedAsyncioTestCase):
    """
    The situation a question is asked over (docs/design/web-app.md,
    "The situation"): the two matchups the cog posts a PNG of with the
    same question -- the shot over its roll, the challenge over the
    maneuver pick -- handed to the page as the same brief's words and
    the players' portraits, for it to lay out on its own background.
    The field strip and the coach's half-field are not drawn: the board
    is beside the prompt.
    """

    async def open(self, name: str):
        fixture = case(name)
        fixture.game.match_state = fixture.match.to_dict()
        service = GameService(
            ENGINE,
            {fixture.game.game_id: fixture.game},
            batching=server.WEB_BATCHING,
            save=lambda games: None,
        )
        web = WebApp(service, GameLocks())
        web.watch()
        client = TestClient(TestServer(web.app))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        self.addAsyncCleanup(web.stop)
        return client, fixture

    async def get_state(self, client, game, headers) -> dict:
        response = await client.get(f"/api/game/{game.game_id}", headers=headers)
        self.assertEqual(response.status, 200)
        return await response.json()

    def names(self, side: dict) -> list[str]:
        return [player["id"] for player in side["players"]]

    async def test_the_challenge_is_the_ball_against_the_challenger(
        self,
    ) -> None:
        from d12ball.dice_brief import maneuver_challenge_brief

        ENGINE.rng.seed(11)
        client, fixture = await self.open("maneuver picks")
        match, game = fixture.match, fixture.game
        coach = await self.get_state(client, game, as_coach(game.player_1_id))
        watcher = await self.get_state(client, game, as_coach(STRANGER))
        situation = coach["prompt"]["situation"]
        # The position's, so nobody's hand: an observer is handed the
        # same one.
        self.assertEqual(watcher["prompt"]["situation"], situation)

        [offense], [defense], where = maneuver_challenge_brief(
            ENGINE, match, match.challenger_id, game,
        )
        attack, defence = situation["sides"]
        self.assertEqual(situation["where"], where)
        self.assertEqual(self.names(attack), [match.active_player_id])
        self.assertEqual(self.names(defence), [match.challenger_id])
        # The numbers are the brief's, the one the PNG is drawn from.
        self.assertEqual(
            attack["skill"], f"{offense.skill_name} skill +{offense.skill}",
        )
        self.assertEqual(
            defence["skill"], f"{defense.skill_name} skill +{defense.skill}",
        )
        self.assertEqual(attack["ability"], offense.ability)
        self.assertEqual(defence["ability"], defense.ability)
        # A player is named with their role.
        label = attack["players"][0]["label"]
        self.assertIn(
            ENGINE.get_player_definition(match.active_player_id).name, label,
        )
        self.assertIn("badge", label)

    async def test_the_shot_is_the_shooter_against_the_wall(self) -> None:
        from d12ball.dice_brief import score_attempt_brief

        ENGINE.rng.seed(11)
        client, fixture = await self.open("score attempt")
        match, game = fixture.match, fixture.game
        state = await self.get_state(client, game, as_coach(STRANGER))
        situation = state["prompt"]["situation"]

        [shooter], defenders, where = score_attempt_brief(ENGINE, match, game)
        attack, defence = situation["sides"]
        self.assertEqual(situation["where"], where)
        self.assertEqual(self.names(attack), [match.active_player_id])
        self.assertEqual(
            self.names(defence),
            [
                defender.player.player_id
                for defender in ENGINE.intervening_defenders(match, game)
            ],
        )
        self.assertEqual(
            [player["value"] for player in defence["players"]],
            [defender.value for defender in defenders],
        )
        self.assertEqual(
            [player["halved"] for player in defence["players"]],
            [defender.halved for defender in defenders],
        )
        self.assertEqual(attack["modifiers"], list(shooter.modifiers))
        # A shot weighs numbers, not abilities, as the PNG does.
        self.assertIsNone(attack["ability"])
        self.assertIsNone(defence["ability"])
        if len(defenders) > 1:
            self.assertTrue(
                defence["skill"].endswith(
                    f"= {sum(defender.value for defender in defenders)}",
                ),
            )
        elif not defenders:
            self.assertEqual(defence["empty"], "No one in the way")

    async def open_staged(self, name: str, stage):
        """A fixture with the position moved on first, where the fixture
        alone is barer than any game reaches (no tokens on a player who
        owes an injury check, nobody on the ball at an own-goal roll)."""
        fixture = case(name)
        stage(fixture.match)
        fixture.game.match_state = fixture.match.to_dict()
        service = GameService(
            ENGINE,
            {fixture.game.game_id: fixture.game},
            batching=server.WEB_BATCHING,
            save=lambda games: None,
        )
        web = WebApp(service, GameLocks())
        web.watch()
        client = TestClient(TestServer(web.app))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        self.addAsyncCleanup(web.stop)
        state = await self.get_state(client, fixture.game, as_coach(STRANGER))
        return fixture, state["prompt"]["situation"]

    async def test_an_injury_check_needs_more_than_the_tokens(self) -> None:
        def seven_tokens(match):
            match.exhaustion[match.pending_injury_tests[0]] = 7

        ENGINE.rng.seed(11)
        fixture, situation = await self.open_staged("injury test", seven_tokens)
        hurt = fixture.match.pending_injury_tests[0]
        (roller,) = situation["sides"]
        self.assertEqual(self.names(roller), [hurt])
        self.assertEqual(roller["skill"], "Carries 7 exhaustion tokens")
        self.assertEqual(
            situation["roll"]["target"],
            ENGINE.injury_test_target(fixture.match, hurt),
        )
        self.assertEqual(situation["roll"]["face"], 8)
        self.assertEqual(situation["roll"]["dice"], 1)
        self.assertEqual(situation["title"], "INJURY TEST")

    async def test_an_own_goal_needs_the_safe_total_less_the_skill(
        self,
    ) -> None:
        from d12ball.flow.effects import OWN_GOAL_SAFE_TOTAL

        def on_the_ball(match):
            match.active_player_id = match.eligible_ball_handlers()[0]

        ENGINE.rng.seed(11)
        fixture, situation = await self.open_staged("own goal", on_the_ball)
        match, game = fixture.match, fixture.game
        skill = ENGINE.attacking_skill(
            game, match, match.active_player_id, "own_goal",
        )
        (roller,) = situation["sides"]
        self.assertEqual(self.names(roller), [match.active_player_id])
        self.assertEqual(situation["roll"]["dice"], 2)
        self.assertEqual(situation["roll"]["target"], OWN_GOAL_SAFE_TOTAL)
        self.assertEqual(
            situation["roll"]["face"],
            min(max(OWN_GOAL_SAFE_TOTAL - skill, 1), 12),
        )

    def test_umbrik_s_own_goal_names_his_defensive_skill(self) -> None:
        # Umbrik adds his defensive skill avoiding an own goal (Law 21),
        # and the window says so, in an advanced game only (the author,
        # 2026-09-28). Granted by the ability, never named by the player.
        from unittest import mock

        from d12ball.components import catalog_player_id
        from d12ball.special_abilities import (
            SPECIAL_ABILITIES,
            SpecialAbility,
        )
        from d12ball.prompts import pending
        from webapp.present import situation

        for mode, word in (
            (GameMode.STANDARD, "Offensive"), (GameMode.ADVANCED, "Defensive"),
        ):
            with self.subTest(mode):
                fixture = case("own goal")
                fixture.game.mode = mode
                handler = take_the_ball(fixture.match)
                with mock.patch.dict(
                    SPECIAL_ABILITIES,
                    {
                        catalog_player_id(handler):
                        (SpecialAbility.DEFENSIVE_THROW, "test"),
                    },
                ):
                    skill = ENGINE.attacking_skill(
                        fixture.game, fixture.match, handler, "own_goal",
                    )
                    got = situation(
                        ENGINE, fixture.game, fixture.match,
                        pending(ENGINE, fixture.game, fixture.match),
                    )
                (roller,) = got["sides"]
                self.assertEqual(roller["skill"], f"{word} skill {skill:+d}")

    def situation_in(self, name: str, mode, stage=lambda match: None):
        from d12ball.prompts import pending
        from webapp.present import situation

        fixture = case(name)
        fixture.game.mode = mode
        stage(fixture.match)
        return fixture, situation(
            ENGINE, fixture.game, fixture.match,
            pending(ENGINE, fixture.game, fixture.match),
        )

    def test_the_species_abilities_that_bear_on_the_roll_are_named(
        self,
    ) -> None:
        # Volatile and Lithium Powered on whoever rolls a skill test,
        # Lithium Powered alone on an injury check or an own-goal roll
        # (Laws 20.2.3, 20.3.5) -- and in no game that does not play
        # the species abilities (the author, 2026-09-28).
        from d12ball.components import SPECIES_CYBORG, SPECIES_FIRE_DEMON
        from d12ball.player_cards import species_ability

        rolls = (
            ("maneuver picks", (SPECIES_FIRE_DEMON, SPECIES_CYBORG)),
            ("injury test", (SPECIES_CYBORG,)),
        )
        for name, bearing in rolls:
            for mode in (GameMode.TRAINING, GameMode.STANDARD):
                with self.subTest(name=name, mode=mode):
                    fixture, got = self.situation_in(name, mode)
                    for side in got["sides"]:
                        for player in side["players"]:
                            named = [
                                note["name"] for note in player["abilities"]
                                if note["kind"] == "species"
                            ]
                            self.assertEqual(named, [
                                species_ability(kind)["name"]
                                for kind in bearing
                                if ENGINE.has_species_ability(
                                    fixture.game, player["id"], kind,
                                )
                            ])

    def test_goopkeeper_is_named_only_beyond_the_ball(self) -> None:
        # The chip and the band say it where it changes the shot, and
        # nowhere else (the author, 2026-09-30).
        from unittest import mock

        from d12ball.components import catalog_player_id
        from d12ball.special_abilities import (
            SPECIAL_ABILITIES,
            SpecialAbility,
        )

        def named(player):
            return any(
                note["kind"] == "special" for note in player["abilities"]
            )

        fixture = case("score attempt")
        wall = ENGINE.intervening_defenders(fixture.match, fixture.game)
        on_ball = [d for d in wall if d.on_ball]
        beyond = [d for d in wall if not d.on_ball]
        self.assertTrue(on_ball and beyond)
        for defender, expected in ((on_ball[0], False), (beyond[0], True)):
            player_id = defender.player.player_id
            with self.subTest(beyond=expected), mock.patch.dict(
                SPECIAL_ABILITIES,
                {
                    catalog_player_id(player_id):
                    (SpecialAbility.FULL_BLOCK, "test"),
                },
            ):
                _, got = self.situation_in(
                    "score attempt", GameMode.ADVANCED,
                )
                (player,) = [
                    player for player in got["sides"][1]["players"]
                    if player["id"] == player_id
                ]
                self.assertEqual(named(player), expected)
                self.assertEqual(player["as_on_ball"], expected)
                bands = [band["text"] for band in got["sides"][1]["bands"]]
                self.assertEqual(
                    "COUNTS AS ON THE BALL" in bands, expected,
                )

    def test_volatile_s_upgrade_is_said_only_at_a_skill_test(self) -> None:
        # "In a scoring attempt and anywhere outside a skill test, we can
        # cut out the part of Volatile about upgrading maneuvers" (the
        # author, 2026-09-30).
        from d12ball.components import SPECIES_FIRE_DEMON

        for name, skill_test in (
            ("maneuver picks", True), ("score attempt", False),
        ):
            with self.subTest(name):
                _, got = self.situation_in(name, GameMode.STANDARD)
                texts = [
                    note["text"]
                    for side in got["sides"]
                    for player in side["players"]
                    for note in player["abilities"]
                    if note.get("species") == SPECIES_FIRE_DEMON
                ]
                self.assertTrue(texts)
                for text in texts:
                    self.assertEqual("In a skill test" in text, skill_test)

    def test_an_ooze_merging_is_drawn_in_the_side(self) -> None:
        # An Ooze of each side stood on the ball, neither rolling: each
        # is part of the side they Merge into (the author, 2026-09-30),
        # after its player, with what `merge_contributions` says they
        # add -- the dice's number -- and the side's skill added up.
        from d12ball.components import SPECIES_OOZE

        def oozes_on_the_ball(match):
            for setup in (match.home, match.visiting):
                ooze = next(
                    player_id for player_id in setup.field_players
                    if ENGINE.species_of(player_id) == SPECIES_OOZE
                    and player_id not in (
                        match.active_player_id, match.challenger_id,
                    )
                )
                match.move_meeple(
                    ooze, match.ball.zone, match.ball.space_index,
                )

        fixture, got = self.situation_in(
            "maneuver picks", GameMode.STANDARD, oozes_on_the_ball,
        )
        match, game = fixture.match, fixture.game
        rolling = (match.active_player_id, match.challenger_id)
        attack, defence = got["sides"]
        for side, lead, team_side, skill in (
            (attack, match.active_player_id, match.ball.possession,
             "offense"),
            (defence, match.challenger_id, match.defending_side(),
             "defense"),
        ):
            merging = ENGINE.merge_contributions(
                game, match, team_side, rolling, skill,
            )
            self.assertTrue(merging)
            self.assertEqual(
                [
                    (player["id"], player["merging"], player["value"])
                    for player in side["players"][1:]
                ],
                [(ooze, True, value) for ooze, value in merging],
            )
            self.assertEqual(side["players"][0]["id"], lead)
            self.assertFalse(side["players"][0]["merging"])
            self.assertTrue(
                side["skill"].endswith(
                    f"= {sum(p['value'] for p in side['players'])}",
                ),
            )
            self.assertEqual(
                [band["text"] for band in side["bands"]], ["MERGE"],
            )
            # Said once: not a modifier line as well.
            self.assertFalse(
                any("(Merge)" in line for line in side["modifiers"]),
            )

    def test_a_special_ability_is_named_only_where_it_bears(self) -> None:
        # In an advanced game only, and only the abilities that apply to
        # the roll (the author, 2026-09-28): a shooter's clear shot is,
        # a dribble is not. Granted by the ability, never named by the
        # player; the line itself is the card's.
        from unittest import mock

        from d12ball.components import catalog_player_id
        from d12ball.special_abilities import (
            SPECIAL_ABILITIES,
            SpecialAbility,
        )

        def shooter_holding(ability):
            fixture = case("score attempt")
            shooter = fixture.match.active_player_id
            return shooter, mock.patch.dict(
                SPECIAL_ABILITIES,
                {catalog_player_id(shooter): (ability, "test")},
            )

        for mode, ability, shown in (
            (GameMode.ADVANCED, SpecialAbility.CLEAR_SHOT, True),
            (GameMode.ADVANCED, SpecialAbility.FREE_BURST, False),
            (GameMode.STANDARD, SpecialAbility.CLEAR_SHOT, False),
        ):
            with self.subTest(mode=mode, ability=ability):
                shooter, holding = shooter_holding(ability)
                with holding:
                    fixture, got = self.situation_in("score attempt", mode)
                (player,) = got["sides"][0]["players"]
                special = [
                    note for note in player["abilities"]
                    if note["kind"] == "special"
                ]
                self.assertEqual(bool(special), shown)

    def test_a_maneuver_s_ability_is_named_on_the_side_that_plays_it(
        self,
    ) -> None:
        # On the maneuver challenge the coach is choosing a maneuver, so
        # what one does once won is named too, on the attack alone (the
        # author, 2026-09-28); a run on is a teammate's pass, never the
        # roller's; a drain threshold is named on every roll.
        from unittest import mock

        from d12ball.components import catalog_player_id
        from d12ball.special_abilities import (
            SPECIAL_ABILITIES,
            SpecialAbility,
        )

        cases = (
            (0, SpecialAbility.FREE_BURST, True),
            (1, SpecialAbility.FREE_BURST, False),
            (0, SpecialAbility.PRESSURE_SHOT, True),
            (1, SpecialAbility.PRESSURE_SHOT, False),
            # A teammate's pass, so never a roll the player is in.
            (0, SpecialAbility.RUN_ON, False),
            (1, SpecialAbility.RUN_ON, False),
            # Bulwark's threshold, on every roll.
            (0, SpecialAbility.HIGH_DRAIN_THRESHOLD, True),
            (1, SpecialAbility.HIGH_DRAIN_THRESHOLD, True),
        )
        for side, ability, shown in cases:
            with self.subTest(side=side, ability=ability):
                fixture = case("maneuver picks")
                player_id = (
                    fixture.match.active_player_id,
                    fixture.match.challenger_id,
                )[side]
                with mock.patch.dict(
                    SPECIAL_ABILITIES,
                    {catalog_player_id(player_id): (ability, "test")},
                ):
                    _, got = self.situation_in(
                        "maneuver picks", GameMode.ADVANCED,
                    )
                (player,) = got["sides"][side]["players"]
                named = [
                    note["name"] for note in player["abilities"]
                    if note["kind"] == "special"
                ]
                self.assertEqual(named, ["Special ability"] if shown else [])

    def test_a_pass_runner_is_noted_while_a_teammate_is_on_the_ball(
        self,
    ) -> None:
        # Quantor may run onto any teammate's pass, so the challenge says
        # so while a teammate is on the ball and he is on the field --
        # not when he is the one passing, and not outside an advanced
        # game (the author, 2026-09-28).
        from unittest import mock

        from d12ball.components import catalog_player_id
        from d12ball.special_abilities import (
            SPECIAL_ABILITIES,
            SpecialAbility,
        )

        fixture = case("maneuver picks")
        match = fixture.match
        teammate = next(
            player_id
            for player_id in match.setup_for_side(match.ball.possession)
            .field_players
            if player_id != match.active_player_id
        )
        for mode, runner, noted in (
            (GameMode.ADVANCED, teammate, True),
            (GameMode.ADVANCED, match.active_player_id, False),
            (GameMode.STANDARD, teammate, False),
        ):
            with self.subTest(mode=mode, noted=noted):
                with mock.patch.dict(
                    SPECIAL_ABILITIES,
                    {
                        catalog_player_id(runner):
                        (SpecialAbility.RUN_ON, "test"),
                    },
                    clear=False,
                ):
                    # Nobody else on the side holds it for this test.
                    for player_id, (ability, _) in list(
                        SPECIAL_ABILITIES.items(),
                    ):
                        if (
                            ability is SpecialAbility.RUN_ON
                            and player_id != catalog_player_id(runner)
                        ):
                            del SPECIAL_ABILITIES[player_id]
                    _, got = self.situation_in("maneuver picks", mode)
                self.assertEqual(
                    [note["id"] for note in got["notes"]],
                    [runner] if noted else [],
                )

    def test_the_join_offer_is_the_challenge_with_the_joiner_noted(
        self,
    ) -> None:
        # Glompex is offered the ball before the cards are chosen, so his
        # ability is said there, over the challenge he would step into.
        from unittest import mock

        from d12ball.components import catalog_player_id
        from d12ball.special_abilities import (
            SPECIAL_ABILITIES,
            SpecialAbility,
        )

        fixture = case("join the ball")
        fixture.game.mode = GameMode.ADVANCED
        joiner = fixture.match.pending_join[0]
        with mock.patch.dict(
            SPECIAL_ABILITIES,
            {catalog_player_id(joiner): (SpecialAbility.JOINS_THE_BALL, "test")},
        ):
            _, got = self.situation_in("join the ball", GameMode.ADVANCED)
        self.assertEqual(got["title"], "MANEUVER CHALLENGE")
        self.assertEqual(got["notes"][0]["id"], joiner)
        self.assertEqual(
            got["notes"][0]["text"],
            ENGINE.special_ability_text(fixture.game, joiner),
        )

    def test_a_contest_for_the_ball_is_its_two_contestants(self) -> None:
        # The loose ball's roll has a window too (the author,
        # 2026-09-28): the two sent, the side on the ball's offensive
        # skill against the other's defensive, nothing for an injured
        # one, and the species abilities that reach a contest.
        from d12ball.components import SPECIES_CYBORG, SPECIES_FIRE_DEMON
        from d12ball.player_cards import species_ability

        for injured in (False, True):
            with self.subTest(injured=injured):
                def stage(match):
                    if injured:
                        match.injured.add(match.loose_ball_offense_player)

                fixture, got = self.situation_in(
                    "loose ball roll", GameMode.STANDARD, stage,
                )
                match, game = fixture.match, fixture.game
                offense, defense = got["sides"]
                self.assertEqual(
                    self.names(offense), [match.loose_ball_offense_player],
                )
                self.assertEqual(
                    self.names(defense), [match.loose_ball_defense_player],
                )
                self.assertEqual(
                    offense["skill"],
                    "Offensive skill +0 (injured)" if injured else
                    "Offensive skill "
                    f"+{ENGINE.skills(game, offense['players'][0]['id']).offense}",
                )
                self.assertEqual(
                    defense["skill"],
                    "Defensive skill "
                    f"+{ENGINE.skills(game, defense['players'][0]['id']).defense}",
                )
                for side in (offense, defense):
                    (player,) = side["players"]
                    self.assertEqual(
                        [
                            note["name"] for note in player["abilities"]
                            if note["kind"] == "species"
                        ],
                        [
                            species_ability(kind)["name"]
                            for kind in (SPECIES_FIRE_DEMON, SPECIES_CYBORG)
                            if ENGINE.has_species_ability(
                                game, player["id"], kind,
                            )
                        ],
                    )

    def test_a_set_up_off_zytheris_s_ability_names_it(self) -> None:
        # A scoring opportunity Zytheris's special ability offered has a
        # window naming it (the author, 2026-09-28); any other set-up is
        # the ask's to say, and has none.
        from unittest import mock

        from d12ball.components import catalog_player_id
        from d12ball.special_abilities import (
            SPECIAL_ABILITIES,
            SpecialAbility,
        )

        fixture, bare = self.situation_in("set-up attempt", GameMode.ADVANCED)
        self.assertIsNone(bare)
        shooter = fixture.match.pending_scoring_opportunity["shooter_id"]
        with mock.patch.dict(
            SPECIAL_ABILITIES,
            {
                catalog_player_id(shooter):
                (SpecialAbility.SHOOTS_OFF_ANY_PASS, "test"),
            },
        ):
            _, got = self.situation_in("set-up attempt", GameMode.ADVANCED)
        (side,) = got["sides"]
        (player,) = side["players"]
        self.assertEqual(player["id"], shooter)
        self.assertIn(
            "Special ability", [note["name"] for note in player["abilities"]],
        )

    def test_an_advanced_score_is_named_where_the_roll_adds_it(self) -> None:
        # The wall adds defensive skill, so a defender whose card line is
        # a raised defensive score has it named, and one whose line is
        # about something else does not.
        from d12ball.special_abilities import SpecialAbility

        fixture, got = self.situation_in("score attempt", GameMode.ADVANCED)
        game = fixture.game
        wall = got["sides"][1]["players"]
        beyond = {
            defender.player.player_id
            for defender in ENGINE.intervening_defenders(fixture.match, game)
            if defender.as_on_ball
        }
        for player in wall:
            raised = (
                ENGINE.skills(game, player["id"]).defense
                != ENGINE.skills(None, player["id"]).defense
            )
            # Goopkeeper's is named only beyond the ball, where it
            # changes the shot (the author, 2026-09-30).
            blocks = player["id"] in beyond
            self.assertEqual(
                player["as_on_ball"], blocks, player["short"],
            )
            named = any(
                note["kind"] == "special" for note in player["abilities"]
            )
            self.assertEqual(named, raised or blocks, player["short"])
        self.assertTrue(any(
            note["kind"] == "special"
            for player in wall for note in player["abilities"]
        ))

    async def test_a_mind_pull_needs_its_minimum_and_costs_its_token(
        self,
    ) -> None:
        ENGINE.rng.seed(11)
        fixture, situation = await self.open_staged(
            "mind pull", lambda match: None,
        )
        match, game = fixture.match, fixture.game
        puller = match.pending_mind_pull[0]
        (roller,) = situation["sides"]
        self.assertEqual(self.names(roller), [puller])
        self.assertEqual(
            situation["roll"]["target"],
            ENGINE.mind_pull_minimum(game, puller),
        )
        self.assertIn(
            f"Costs {ENGINE.mind_pull_cost(game, puller)}", roller["skill"],
        )

    async def test_every_portrait_is_served(self) -> None:
        for name in ("maneuver picks", "score attempt"):
            with self.subTest(name):
                ENGINE.rng.seed(11)
                client, fixture = await self.open(name)
                state = await self.get_state(
                    client, fixture.game, as_coach(STRANGER),
                )
                players = [
                    player
                    for side in state["prompt"]["situation"]["sides"]
                    for player in side["players"]
                ]
                self.assertTrue(players)
                for player in players:
                    response = await client.get(player["portrait"])
                    body = await response.read()
                    self.assertEqual(response.status, 200, player["id"])
                    self.assertEqual(response.content_type, "image/png")
                    self.assertTrue(body.startswith(b"\x89PNG"))

    async def test_a_player_not_in_the_game_has_no_portrait(self) -> None:
        ENGINE.rng.seed(11)
        client, fixture = await self.open("maneuver picks")
        response = await client.get(
            f"/api/game/{fixture.game.game_id}/portrait/nobody.png",
        )
        self.assertEqual(response.status, 404)

    async def test_every_other_question_has_no_situation(self) -> None:
        # The distance questions and the Coaching Choice among them:
        # the board beside the prompt is the field.
        for name in (
            "low pass", "run back, where", "coaching hub", "coaching offer",
            "kickoff", "skill test",
        ):
            with self.subTest(name):
                ENGINE.rng.seed(11)
                client, fixture = await self.open(name)
                state = await self.get_state(
                    client, fixture.game, as_coach(fixture.game.player_1_id),
                )
                self.assertIsNone(state["prompt"]["situation"])

    async def test_an_own_goal_with_nobody_on_the_ball_has_none(self) -> None:
        # The bare fixture: a position no game reaches, answered with no
        # situation rather than an error.
        ENGINE.rng.seed(11)
        client, fixture = await self.open("own goal")
        state = await self.get_state(client, fixture.game, as_coach(STRANGER))
        self.assertIsNone(state["prompt"]["situation"])

    async def test_the_log_says_the_challenge_in_words(self) -> None:
        # Sending a challenger walks one in. On Discord the challenge
        # image follows the walk-in; the log draws no picture, so it
        # says who is on the ball, who challenges and where.
        ENGINE.rng.seed(11)
        client, fixture = await self.open("maneuver challenge")
        game = fixture.game
        for coach_id in (game.player_1_id, game.player_2_id):
            headers = as_coach(coach_id)
            state = await self.get_state(client, game, headers)
            sent = [
                control["action"]
                for group in state["prompt"]["controls"]
                for control in group["controls"]
                if not control["disabled"]
            ]
            if sent:
                break
        attacker = fixture.match.active_player_id
        challenger = sent[0]["arguments"]["player_id"]

        played = await (
            await client.post(
                f"/api/game/{game.game_id}/action",
                headers=headers,
                data=json.dumps({"action": sent[0]}),
            )
        ).json()

        self.assertIsNone(played["refusal"])
        self.assertEqual(played["prompt"]["kind"], "maneuver_action")
        self.assertIsNotNone(played["prompt"]["situation"])
        said = [
            line
            for entry in played["entries"]
            for line in entry["lines"]
            if "Maneuver challenge" in line
        ]
        self.assertEqual(len(said), 1, played["entries"])
        for player_id in (attacker, challenger):
            self.assertIn(
                ENGINE.get_player_definition(player_id).name, said[0],
            )


class KeptSecretTests(unittest.TestCase):
    """
    With `FOOLBOT_WEB_SECRET` unset, the running web app keeps the
    secret it made in `data/` (`keys.keep_secret_in`), so a restart that
    comes up without the `.env` line still reads everybody's cookie
    rather than making every seat's holder a stranger.
    """

    def setUp(self) -> None:
        saved = keys._process_secret
        self.addCleanup(setattr, keys, "_process_secret", saved)
        keys._process_secret = None
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "data" / "d12ball_web_secret"

    def restart(self) -> bytes:
        """A new process: nothing made yet, then the file read."""
        keys._process_secret = None
        with self.assertLogs("webapp.keys", level="WARNING"):
            keys.keep_secret_in(self.path)
        return keys.secret()

    def test_a_cookie_outlives_a_restart_with_no_secret_configured(self) -> None:
        with mock.patch.dict("os.environ", {keys.SECRET_VARIABLE: ""}):
            first = self.restart()
            cookie = identity.encode(Coach(4242, "bright_bear_42696"))
            self.assertTrue(self.path.exists())
            self.assertEqual(self.restart(), first)
            self.assertEqual(identity.decode(cookie).id, 4242)

    def test_a_configured_secret_is_the_secret_and_nothing_is_written(
        self,
    ) -> None:
        with mock.patch.dict("os.environ", {keys.SECRET_VARIABLE: "named"}):
            keys.keep_secret_in(self.path)
            self.assertEqual(keys.secret(), b"named")
        self.assertFalse(self.path.exists())


class IdentityTests(unittest.IsolatedAsyncioTestCase):
    """Who is reading: a name in a signed cookie, stored nowhere."""

    def test_a_cookie_round_trips(self) -> None:
        coach = identity.issue("  Ann  ")

        self.assertEqual(coach.name, "Ann")
        self.assertTrue(0 < coach.id <= identity.MAX_ID)
        self.assertEqual(identity.decode(identity.encode(coach)), coach)

    def test_every_made_up_name_is_one_the_app_takes(self) -> None:
        """The longest pair and its number still fit `NAME_LIMIT`, so a
        guest's name is never one `clean_name` would refuse."""
        longest = "_".join((
            max(identity.GUEST_ADJECTIVES, key=len),
            max(identity.GUEST_CREATURES, key=len),
            "99999",
        ))
        self.assertEqual(identity.clean_name(longest), longest)
        self.assertRegex(identity.guest_name(), r"^[a-z]+_[a-z]+_\d{5}$")

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

    async def test_a_first_visit_is_named_and_a_rename_keeps_the_id(self) -> None:
        """Nobody is asked for a name: the first `GET /api/me` makes one
        up and sets the cookie, and a rename after keeps the id."""
        web = WebApp(GameService(ENGINE, {}, save=lambda games: None), GameLocks())
        client = TestClient(TestServer(web.app))
        await client.start_server()
        self.addAsyncCleanup(client.close)

        guest = await (await client.get("/api/me")).json()
        again = await (await client.get("/api/me")).json()
        renamed = await (await client.post("/api/me", json={"name": "Bea"})).json()

        self.assertRegex(guest["name"], r"^[a-z]+_[a-z]+_\d{5}$")
        self.assertEqual(again, guest)
        self.assertEqual(renamed, {"id": guest["id"], "name": "Bea"})
        for name in ("", "   ", "x" * 33, 7):
            with self.subTest(name):
                refused = await client.post("/api/me", json={"name": name})
                self.assertEqual(refused.status, 400)
                self.assertTrue(await refused.text())

    async def test_the_cookie_is_secure_when_the_tunnel_says_https(self) -> None:
        """Behind a tunnel the last hop is plain HTTP from this machine;
        the tunnel's `X-Forwarded-Proto` is what says the browser came
        over HTTPS, and the cookie is `Secure` on its word."""
        web = WebApp(GameService(ENGINE, {}, save=lambda games: None), GameLocks())
        client = TestClient(TestServer(web.app))
        await client.start_server()
        self.addAsyncCleanup(client.close)

        # A name each, since a browser whose Secure cookie the plain
        # test client will not send back is somebody new, and no two
        # people hold one name (webapp/names.py).
        for number, (headers, secure) in enumerate((
            ({}, False),
            ({"X-Forwarded-Proto": "https"}, True),
            ({"X-Forwarded-Proto": "HTTPS, http"}, True),
        )):
            with self.subTest(headers):
                response = await client.post(
                    "/api/me", json={"name": f"Ann {number}"}, headers=headers,
                )
                cookie = response.cookies[identity.COOKIE]
                self.assertEqual(bool(cookie["secure"]), secure)
                # Over the tunnel's HTTPS the browser is told to use
                # nothing else; a laptop's plain HTTP is told nothing.
                self.assertEqual(
                    response.headers.get("Strict-Transport-Security"),
                    server.STRICT_TRANSPORT if secure else None,
                )

    async def test_plain_http_through_the_tunnel_goes_to_https(self) -> None:
        """
        The tunnel carries `http://` as well, where a `Secure` cookie is
        never sent: the browser would be somebody new in the same
        browser, an observer in their own room. So it is sent to the
        same path over HTTPS before anything answers -- a 308, which a
        POST repeats as a POST -- and is handed no cookie.
        """
        web = WebApp(GameService(ENGINE, {}, save=lambda games: None), GameLocks())
        client = TestClient(TestServer(web.app))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        forwarded = {"X-Forwarded-Proto": "http", "Host": "play.example"}

        for method, path in (
            ("GET", "/api/me"),
            ("GET", "/room/abc?x=1"),
            ("POST", "/api/me"),
        ):
            with self.subTest(method=method, path=path):
                with mock.patch.dict(
                    "os.environ", {keys.BASE_URL_VARIABLE: "https://play.d12ball.com"},
                ):
                    response = await client.request(
                        method, path, headers=forwarded, allow_redirects=False,
                    )
                self.assertEqual(response.status, 308)
                self.assertEqual(
                    response.headers["Location"], f"https://play.d12ball.com{path}",
                )
                self.assertNotIn(identity.COOKIE, response.cookies)

        # With no https address configured, the request's own host.
        with mock.patch.dict(
            "os.environ", {keys.BASE_URL_VARIABLE: "http://localhost:8080"},
        ):
            response = await client.get(
                "/api/me", headers=forwarded, allow_redirects=False,
            )
        self.assertEqual(response.status, 308)
        self.assertEqual(response.headers["Location"], "https://play.example/api/me")

    async def test_a_cookie_that_fails_its_signature_is_said_at_warning(
        self,
    ) -> None:
        """Somebody whose cookie this server did not sign is somebody
        new from here on -- an observer in their own rooms -- which is
        never routine, so the log says who was lost and asks after the
        secret. A browser with no cookie at all is only a visitor."""
        web = WebApp(GameService(ENGINE, {}, save=lambda games: None), GameLocks())
        client = TestClient(TestServer(web.app), cookie_jar=DummyCookieJar())
        await client.start_server()
        self.addAsyncCleanup(client.close)
        with mock.patch.object(keys, "secret", return_value=b"the old secret"):
            lost = identity.encode(Coach(4242, "bright_bear_42696"))

        with self.assertLogs("webapp.server", level="WARNING") as said:
            response = await client.get(
                "/api/me", headers={"Cookie": f"{identity.COOKIE}={lost}"},
            )
        self.assertNotEqual((await response.json())["id"], 4242)
        (line,) = said.output
        self.assertIn("'bright_bear_42696' (id 4242)", line)
        self.assertIn(keys.SECRET_VARIABLE, line)

        with self.assertNoLogs("webapp.server", level="WARNING"):
            await client.get("/api/me")

    def test_the_forwarded_scheme_is_believed_only_from_this_machine(self) -> None:
        """Anybody who reaches the port directly can write the header,
        so it counts only from a process on this machine -- the
        tunnel's client."""
        for peer, believed in (
            (("127.0.0.1", 50000), True),
            (("::1", 50000, 0, 0), True),
            (("::ffff:127.0.0.1", 50000, 0, 0), True),
            (("192.168.1.20", 50000), False),
            (("203.0.113.9", 50000), False),
            (None, False),
        ):
            with self.subTest(peer):
                transport = mock.Mock()
                transport.get_extra_info.side_effect = (
                    lambda name, default=None, peer=peer:
                    peer if name == "peername" else default
                )
                request = make_mocked_request(
                    "GET", "/", headers={"X-Forwarded-Proto": "https"},
                    transport=transport,
                )
                self.assertIs(identity.came_over_https(request), believed)


class NameTests(unittest.IsolatedAsyncioTestCase):
    """
    No two people are called the same at once (webapp/names.py): a
    made-up name is one nobody holds, a rename to somebody else's name
    is refused, and a name reaches the seats its holder sits in.
    """

    ANN, BEA = 101, 202

    async def asyncSetUp(self) -> None:
        ENGINE.rng.seed(11)
        self.games = {}
        self.service = GameService(ENGINE, self.games, save=lambda games: None)
        self.names = Names()
        self.web = WebApp(self.service, GameLocks(), names=self.names)
        # Every request says who it is in its own headers, so the
        # client's jar keeps nothing a response sets.
        self.client = TestClient(TestServer(self.web.app), cookie_jar=DummyCookieJar())
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def rename(self, coach_id: int, name: str):
        return await self.client.post(
            "/api/me", json={"name": name}, headers=as_coach(coach_id),
        )

    async def test_a_name_somebody_holds_is_refused(self) -> None:
        self.assertEqual((await self.rename(self.ANN, "Ann")).status, 200)

        for name in ("Ann", "  Ann "):
            with self.subTest(name):
                refused = await self.rename(self.BEA, name)
                self.assertEqual(refused.status, 409)
                self.assertTrue(await refused.text())

    async def test_names_are_told_apart_by_case(self) -> None:
        """"Tom" does not block "tom" (the author, 2026-09-27)."""
        self.assertEqual((await self.rename(self.ANN, "Tom")).status, 200)

        self.assertEqual((await self.rename(self.BEA, "tom")).status, 200)
        self.assertEqual(self.names.name_of(self.ANN), "Tom")
        self.assertEqual(self.names.name_of(self.BEA), "tom")

    async def test_a_rename_frees_the_old_name(self) -> None:
        await self.rename(self.ANN, "Ann")
        await self.rename(self.ANN, "Annie")

        self.assertEqual((await self.rename(self.BEA, "Ann")).status, 200)

    async def test_a_made_up_name_is_never_one_somebody_holds(self) -> None:
        await self.rename(self.ANN, "brave_otter_12345")
        drawn = iter(["brave_otter_12345", "calm_yeti_54321"])

        with mock.patch.object(identity, "guest_name", lambda: next(drawn)):
            guest = await (await self.client.get("/api/me")).json()

        self.assertEqual(guest["name"], "calm_yeti_54321")

    async def test_an_old_cookie_under_a_held_name_is_given_another(self) -> None:
        """A cookie set before the names file knew its id keeps its name
        when it is free, and is given a made-up one when it is not."""
        await self.rename(self.ANN, "Ann")

        kept = await self.client.get("/api/me", headers=as_coach(self.BEA, "Bea"))
        clash = await self.client.get("/api/me", headers=as_coach(303, "Ann"))

        self.assertEqual((await kept.json())["name"], "Bea")
        clashed = await clash.json()
        self.assertEqual(clashed["id"], 303)
        self.assertNotEqual(clashed["name"], "Ann")
        self.assertIn(identity.COOKIE, clash.cookies)

    async def test_a_rename_reaches_the_seats(self) -> None:
        game = self.service.create_game(
            player_1_id=self.ANN, player_1_name="Ann", in_lobby=True,
        )
        await self.rename(self.ANN, "Annie")

        self.assertEqual(self.games[game.game_id].player_1_name, "Annie")

    async def test_deleting_my_games_erases_every_seat_i_hold_and_renames_me(self) -> None:
        mine = self.service.create_game(
            player_1_id=self.ANN, player_1_name="Ann", in_lobby=True,
        )
        played = self.service.create_game(
            player_1_id=self.BEA, player_1_name="Bea", in_lobby=True,
        )
        self.service.take_seat(played.game_id, self.ANN, "Ann")
        played.match_state = case("kickoff").match.to_dict()
        theirs = self.service.create_game(
            player_1_id=self.BEA, player_1_name="Bea", in_lobby=True,
        )
        self.web.chats.post(played.game_id, self.BEA, "Bea", "good game")
        await self.rename(self.ANN, "Ann")

        response = await self.client.delete(
            "/api/me/games", headers=as_coach(self.ANN, "Ann"),
        )

        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertEqual(body["deleted"], 2)
        self.assertEqual(body["coach"]["id"], self.ANN)
        self.assertNotEqual(body["coach"]["name"], "Ann")
        self.assertEqual(self.names.name_of(self.ANN), body["coach"]["name"])
        self.assertEqual(list(self.games), [theirs.game_id])
        self.assertNotIn(played.game_id, self.web.chats.chats)
        gone = await self.client.get(
            f"/api/game/{played.game_id}", headers=as_coach(self.BEA, "Bea"),
        )
        self.assertEqual(gone.status, 404)
        # Ann's old name is free again.
        self.assertEqual((await self.rename(self.BEA, "Ann")).status, 200)
        self.assertNotIn(mine.game_id, self.games)

    async def test_deleting_my_games_needs_a_name(self) -> None:
        response = await self.client.delete("/api/me/games")

        self.assertEqual(response.status, 401)


class NamesFileTests(unittest.TestCase):
    """The names file: kept across a restart under the same secret,
    started afresh under another, and an entry dropped once no cookie
    can still carry it."""

    def test_the_file_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "names.json"
            names = Names(path)
            names.claim(1, "Ann")

            self.assertEqual(Names.load(path).name_of(1), "Ann")

    def test_another_secret_starts_afresh(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "names.json"
            Names(path).claim(1, "Ann")

            with mock.patch.object(server.keys, "secret", lambda: b"another"):
                self.assertIsNone(Names.load(path).name_of(1))

    def test_an_entry_older_than_a_cookie_is_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "names.json"
            Names(path, clock=lambda: 0.0).claim(1, "Ann")

            soon = Names.load(path, clock=lambda: 10.0)
            later = Names.load(
                path, clock=lambda: identity.COOKIE_MAX_AGE + 10.0,
            )

            self.assertEqual(soon.name_of(1), "Ann")
            self.assertIsNone(later.name_of(1))


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

    async def rooms(self, coach_id: int) -> dict:
        response = await self.client.get("/api/rooms", headers=as_coach(coach_id))
        self.assertEqual(response.status, 200)
        return await response.json()

    async def test_a_room_card_offers_its_coach_the_way_out(self) -> None:
        room = await self.open_room()

        lobby = (await self.rooms(self.CREATOR))["mine"]["lobby"][0]
        stranger = (await self.rooms(self.SECOND))["open"][0]

        self.assertTrue(lobby["may_close"])
        self.assertFalse(lobby["may_abandon"])
        self.assertFalse(stranger["may_close"])
        self.assertFalse(stranger["may_abandon"])

        self.kick_off(room)
        playing = (await self.rooms(self.CREATOR))["mine"]["in_progress"][0]

        self.assertFalse(playing["may_close"])
        self.assertTrue(playing["may_abandon"])

    async def test_closing_asks_first_only_over_somebody_else_seated(
        self,
    ) -> None:
        def asks(listed: dict, room: str) -> bool:
            return next(
                one for one in listed["mine"]["lobby"] if one["id"] == room
            )["close_asks"]

        alone = await self.open_room()
        self.assertFalse(asks(await self.rooms(self.CREATOR), alone))
        self.assertFalse((await self.arrive(alone, self.CREATOR))["table"]["close_asks"])

        # The AI is nobody to warn.
        response = await self.move(alone, self.CREATOR, "/seat/ai", {"seat": 2})
        self.assertEqual(response.status, 200)
        self.assertFalse(asks(await self.rooms(self.CREATOR), alone))

        shared = await self.open_room()
        await self.arrive(shared, self.SECOND)
        self.assertTrue(asks(await self.rooms(self.CREATOR), shared))
        self.assertTrue(asks(await self.rooms(self.SECOND), shared))
        self.assertTrue((await self.arrive(shared, self.CREATOR))["table"]["close_asks"])

    async def test_a_room_closed_from_its_card_leaves_the_list(self) -> None:
        room = await self.open_room()

        response = await self.client.delete(
            f"/api/room/{room}", headers=as_coach(self.CREATOR),
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(self.games, {})
        mine = (await self.rooms(self.CREATOR))["mine"]
        self.assertEqual(sum(map(len, mine.values())), 0)

    async def test_a_room_nobody_has_open_for_a_day_leaves_open_rooms(
        self,
    ) -> None:
        room = await self.open_room()
        await self.arrive(room, self.CREATOR)
        now = self.web.clock()
        self.web.clock = lambda: now + OPEN_ROOM_IDLE + 1

        self.assertEqual((await self.rooms(self.SECOND))["open"], [])
        # Its coach still has it, and its card can close it.
        self.assertEqual(
            [one["id"] for one in (await self.rooms(self.CREATOR))["mine"]["lobby"]],
            [room],
        )

        # Somebody looking at it again puts it back.
        await self.arrive(room, self.CREATOR)
        self.assertEqual(
            [one["id"] for one in (await self.rooms(self.SECOND))["open"]],
            [room],
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

    async def test_a_coach_on_another_device_takes_their_seat_over(self) -> None:
        """The author, 2026-09-27: seated in a game on one device, the
        same person opens it on another -- a stranger to the room, who
        watches. They see it in the Master Lobby's full rooms, become
        its admin, and take the seat over in one move; nobody else may."""
        room = await self.open_room()
        await self.arrive(room, self.SECOND)
        self.kick_off(room)

        listed = await self.rooms(self.PHONE)
        self.assertEqual(listed["open"], [])
        self.assertEqual([one["id"] for one in listed["full"]], [room])
        watching = await self.arrive(room, self.PHONE)
        self.assertEqual(watching["room"]["role"], "observer")
        self.assertEqual(watching["room"]["take_over"], [])

        refused = await self.move(room, self.PHONE, "/seat/takeover", {"seat": 1})
        self.assertEqual(refused.status, 403)
        self.assertEqual(self.games[room].player_1_id, self.CREATOR)

        made = await self.move(room, self.PHONE, "/admin")
        self.assertEqual((await made.json())["room"]["take_over"], [1, 2])
        taken = await self.move(room, self.PHONE, "/seat/takeover", {"seat": 1})
        state = await taken.json()

        self.assertEqual(taken.status, 200)
        self.assertEqual(state["you"]["player_number"], 1)
        self.assertEqual(state["room"]["take_over"], [])
        self.assertTrue(state["room"]["may_leave"])
        self.assertTrue(state["room"]["may_abandon"])
        self.assertEqual(self.games[room].player_2_id, self.SECOND)
        # The seat's old holder watches now, and finds the room among
        # the full ones rather than their own.
        self.assertEqual(
            [one["id"] for one in (await self.rooms(self.CREATOR))["full"]], [room],
        )

        # A seated admin takes nothing over: they would hold two seats.
        await self.move(room, self.SECOND, "/admin")
        twice = await self.move(room, self.SECOND, "/seat/takeover", {"seat": 1})
        self.assertEqual(twice.status, 409)

    async def test_a_seat_is_left_from_the_master_lobby(self) -> None:
        room = await self.open_room()
        await self.arrive(room, self.SECOND)
        self.kick_off(room)

        card = (await self.rooms(self.SECOND))["mine"]["in_progress"][0]
        self.assertTrue(card["may_leave"])
        left = await self.move(room, self.SECOND, "/seat/leave")

        self.assertEqual(left.status, 200)
        self.assertIsNone(self.games[room].player_2_id)
        listed = await self.rooms(self.SECOND)
        self.assertEqual([one["id"] for one in listed["open"]], [room])

    async def test_a_finished_room_is_its_coaches_alone(self) -> None:
        room = await self.open_room()
        await self.arrive(room, self.SECOND)
        self.kick_off(room)
        self.service.abandon(room)

        stranger = await self.rooms(self.THIRD)
        coach = await self.rooms(self.SECOND)

        self.assertEqual((stranger["open"], stranger["full"]), ([], []))
        self.assertFalse(coach["mine"]["finished"][0]["may_leave"])

    def at(self, seconds: float) -> None:
        """The web app's clock, set."""
        self.web.clock = lambda: seconds

    async def test_a_game_nothing_happens_in_for_fourteen_days_is_abandoned(
        self,
    ) -> None:
        """The author, 2026-09-27: a game that has started, with no
        move since, counts as abandoned and goes to the archive -- and
        stays in its coaches' finished games."""
        self.at(1_000_000.0)
        room = await self.open_room()
        await self.arrive(room, self.SECOND)
        self.kick_off(room)
        # Looking is not activity: a page left open does not keep it.
        self.at(1_000_000.0 + ABANDON_IDLE - 10)
        await self.arrive(room, self.CREATOR)
        self.assertEqual(await self.web.sweep_idle(), {"deleted": [], "abandoned": []})

        self.at(1_000_000.0 + ABANDON_IDLE + 10)
        self.assertEqual(
            await self.web.sweep_idle(), {"deleted": [], "abandoned": [room]},
        )

        game = self.games[room]
        self.assertTrue(game.is_finished and game.abandoned)
        self.assertEqual(
            [one["id"] for one in (await self.rooms(self.CREATOR))["mine"]["finished"]],
            [room],
        )
        archive = await (
            await self.client.get("/api/archive", headers=as_coach(self.THIRD))
        ).json()
        self.assertEqual([one["id"] for one in archive["games"]], [room])
        self.assertTrue(archive["games"][0]["abandoned"])
        self.assertFalse(archive["games"][0]["yours"])
        # The sweep does not touch it again.
        self.assertEqual(await self.web.sweep_idle(), {"deleted": [], "abandoned": []})

    async def test_a_room_nothing_was_played_in_is_deleted_after_a_day(
        self,
    ) -> None:
        """The author, 2026-09-27: deleted, not abandoned -- as its own
        Close would -- with everything the web app kept about it, while
        a game under way keeps its fourteen days."""
        self.at(0.0)
        lobby = await self.open_room()
        await self.client.post(
            f"/api/room/{lobby}/chat", headers=as_coach(self.CREATOR),
            json={"text": "anyone?"},
        )
        playing = await self.open_room()
        self.kick_off(playing)
        self.at(UNPLAYED_ROOM_IDLE)
        self.assertEqual(await self.web.sweep_idle(), {"deleted": [], "abandoned": []})

        self.at(UNPLAYED_ROOM_IDLE + 10)

        self.assertEqual(
            await self.web.sweep_idle(), {"deleted": [lobby], "abandoned": []},
        )
        self.assertNotIn(lobby, self.games)
        self.assertNotIn(lobby, self.web.rooms.rooms)
        self.assertEqual(self.web.chats.chat(lobby).latest, 0)
        self.assertFalse(self.games[playing].is_finished)
        self.assertEqual((await self.rooms(self.CREATOR))["mine"]["finished"], [])

    async def test_a_move_or_a_word_keeps_a_game_off_the_sweep(self) -> None:
        self.at(0.0)
        room = await self.open_room()
        await self.arrive(room, self.SECOND)
        self.kick_off(room)
        self.at(ABANDON_IDLE - 100)
        said = await self.client.post(
            f"/api/room/{room}/chat", headers=as_coach(self.SECOND),
            json={"text": "still here"},
        )
        self.assertEqual(said.status, 200)

        self.at(ABANDON_IDLE + 100)

        self.assertEqual(await self.web.sweep_idle(), {"deleted": [], "abandoned": []})
        self.assertFalse(self.games[room].is_finished)

    async def test_a_room_from_before_activity_was_kept_gets_its_window(
        self,
    ) -> None:
        room = await self.open_room()
        self.web.rooms.room(room).active_at = None
        self.at(10 * ABANDON_IDLE)

        self.assertEqual(await self.web.sweep_idle(), {"deleted": [], "abandoned": []})
        self.assertEqual(self.web.rooms.room(room).active_at, 10 * ABANDON_IDLE)
        self.assertIn(room, self.games)
        self.assertFalse(self.games[room].is_finished)

    async def test_the_archive_is_every_game_that_is_over(self) -> None:
        playing = await self.open_room()
        await self.arrive(playing, self.SECOND)
        self.kick_off(playing)
        played = await self.open_room()
        self.service.abandon(played)

        archive = await (
            await self.client.get("/api/archive", headers=as_coach(self.CREATOR))
        ).json()
        page = await self.client.get("/archive")

        self.assertEqual([one["id"] for one in archive["games"]], [played])
        self.assertTrue(archive["games"][0]["yours"])
        self.assertEqual(page.status, 200)

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

    def test_a_room_s_activity_survives_a_restart_and_an_old_file_has_none(
        self,
    ) -> None:
        """The idle sweep counts from the rooms file's `active_at`, so
        it outlives the process; a file from before it reads as None,
        and a touch inside `ACTIVE_GRAIN` writes nothing."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rooms.json"
            path.write_text(json.dumps({"old": {"admins": [], "seen": [4]}}))
            rooms = Rooms.load(path, ["old"])
            self.assertIsNone(rooms.room("old").active_at)

            rooms.touch("old", 1000.0)
            written = path.read_text()
            rooms.touch("old", 1030.0)

            self.assertEqual(path.read_text(), written)
            self.assertEqual(Rooms.load(path, ["old"]).room("old").active_at, 1000.0)

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

    def test_a_sideline_name_survives_a_restart_and_an_old_file_has_none(
        self,
    ) -> None:
        """The names the sideline shows are the rooms file's own, and a
        file written before they were kept reads with none."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rooms.json"
            path.write_text(json.dumps({"old": {"admins": [], "seen": [4]}}))
            rooms = Rooms.load(path, ["old"])
            self.assertEqual(rooms.room("old").names, {})

            rooms.call("old", 4, "Maya")
            again = Rooms.load(path, ["old"])

        self.assertEqual(again.room("old").names, {4: "Maya"})


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


class SurveyTests(unittest.IsolatedAsyncioTestCase):
    """
    What the 2026-09-25 survey found untested (step 10 of
    docs/web-app-next.md): picking a game up, a journal entry's board,
    and what a coach is sent of the other side's secret.
    """

    async def serve(self, fixture: PromptFixture) -> tuple[TestClient, WebApp]:
        web = WebApp(service_over(fixture), GameLocks())
        web.watch()
        client = TestClient(TestServer(web.app))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        self.addAsyncCleanup(web.stop)
        return client, web

    async def test_resume_runs_the_owed_step_and_asks_the_next_question(
        self,
    ) -> None:
        for entry in CASES:
            if entry.asked or entry.ai:
                continue
            with self.subTest(entry.name):
                ENGINE.rng.seed(11)
                fixture = entry.build()
                game = fixture.game
                client, _ = await self.serve(fixture)
                url = f"/api/game/{game.game_id}"

                before = await (
                    await client.get(url, headers=as_coach(game.player_1_id))
                ).json()
                self.assertTrue(before["owed"])
                self.assertIsNone(before["prompt"])

                watched = await client.post(
                    f"{url}/resume", headers=as_coach(STRANGER),
                )
                self.assertEqual(watched.status, 403)
                # An observer's press ran nothing.
                self.assertTrue(
                    (await (await client.get(url)).json())["owed"],
                )

                response = await client.post(
                    f"{url}/resume", headers=as_coach(game.player_1_id),
                )
                self.assertEqual(response.status, 200)
                state = await response.json()
                self.assertTrue(state["resumed"])
                self.assertFalse(state["owed"])
                self.assertIsNotNone(state["prompt"])
                self.assertEqual(
                    state["prompt"]["kind"],
                    pending_prompt(
                        ENGINE,
                        game,
                        MatchState.from_dict(
                            game.match_state, ENGINE.basic_ruleset,
                        ),
                    ).kind.value,
                )

    async def test_an_entry_s_board_is_served_where_it_has_one(self) -> None:
        ENGINE.rng.seed(11)
        fixture = case("kickoff")
        game = fixture.game
        client, web = await self.serve(fixture)
        journal = web.journal(game.game_id)
        journal.entries.append(
            Entry(41, ("Stopped here.",), board=fixture.match.to_dict()),
        )
        journal.entries.append(Entry(42, ("Said only.",)))
        url = f"/api/game/{game.game_id}/board.png"

        drawn = await client.get(url, params={"entry": "41"})
        self.assertEqual(drawn.status, 200)
        self.assertEqual(drawn.content_type, "image/png")
        self.assertTrue((await drawn.read()).startswith(b"\x89PNG"))
        for missing in ("42", "43"):
            with self.subTest(entry=missing):
                response = await client.get(url, params={"entry": missing})
                self.assertEqual(response.status, 404)

    async def test_a_coach_is_sent_none_of_the_other_side_s_secret(
        self,
    ) -> None:
        """
        Seat 1's state is the same JSON whatever seat 2 has picked or
        ordered, and carries no control of seat 2's -- so it holds
        neither seat 2's hand nor its order.
        """
        def other_side(fixture) -> TeamSide:
            return next(
                side
                for side in (TeamSide.HOME, TeamSide.VISITING)
                if ENGINE.side_player_number(fixture.game, side) == 2
            )

        def set_pick(fixture, key) -> str:
            prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
            hand = next(
                hand
                for hand in prompt.options.hands
                if hand.team_side == other_side(fixture)
            )
            if key is not None:
                setattr(fixture.match, f"{hand.side}_maneuver", key)
            return hand.side

        def set_order(fixture, reverse) -> str:
            side = other_side(fixture)
            squad = list(fixture.match.shootout_squad(side))
            fixture.match.set_shootout_order(
                side, squad[::-1] if reverse else squad,
            )
            return TeamSide(side).value

        for name, secret, untouched, one, other in (
            ("maneuver picks", set_pick, None, "low_pass", "double_team"),
            ("shootout order", set_order, None, False, True),
        ):
            with self.subTest(name):
                seen = []
                hands = []
                # Untouched first -- seat 2 still to answer, its row
                # open -- then two secrets that must read the same.
                for value in (untouched, one, other):
                    ENGINE.rng.seed(11)
                    fixture = case(name)
                    theirs = secret(fixture, value)
                    client, _ = await self.serve(fixture)
                    state = await (
                        await client.get(
                            f"/api/game/{fixture.game.game_id}",
                            headers=as_coach(fixture.game.player_1_id),
                        )
                    ).json()
                    self.assertEqual(state["you"]["player_number"], 1)
                    # Seat 1 is asked too, so there is a row to leak
                    # beside.
                    self.assertTrue(state["prompt"]["controls"])
                    sides = {
                        control["action"]["arguments"].get("side")
                        for group in state["prompt"]["controls"]
                        for control in group["controls"]
                    }
                    self.assertNotIn(theirs, sides)
                    # Nothing of the prompt's options is sent as it
                    # stands: only this viewer's controls are, and
                    # the rank reference, which is the game's back.
                    self.assertEqual(
                        set(state["prompt"]),
                        {
                            "kind", "ask", "footnote", "situation", "controls",
                            "lit", "yours", "state", "waiting_on",
                            "reference", "hand", "shootout",
                        },
                    )
                    self.assertNotIn("match", state)
                    # The other side's hand face down is the same
                    # before they pick as after: a back that came up
                    # with the pick would say they had.
                    hands.append(state["prompt"]["hand"])
                    if value is not untouched:
                        seen.append(json.dumps(state, sort_keys=True))
                self.assertEqual(seen[0], seen[1])
                self.assertEqual(hands[0], hands[1])
                self.assertEqual(hands[1], hands[2])


class ShootoutOrderTests(unittest.IsolatedAsyncioTestCase):
    """
    The secret order as slots in the question box (step 7 of
    docs/web-app-redesign.md): the page fills its slots in a draft of
    its own and the whistle sends each name in slot order -- the same
    `send` the Discord menu sends a click at a time. Nothing of an
    order reaches anybody but its own seat: not the other coach, not
    an observer, and not the log they all read.
    """

    async def serve(self, fixture: PromptFixture):
        service = service_over(fixture)
        web = WebApp(service, GameLocks())
        web.watch()
        client = TestClient(TestServer(web.app))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        self.addAsyncCleanup(web.stop)
        return client, service

    async def state(self, client, game, coach_id) -> dict:
        response = await client.get(
            f"/api/game/{game.game_id}", headers=as_coach(coach_id),
        )
        self.assertEqual(response.status, 200)
        return await response.json()

    @staticmethod
    def order_group(state: dict):
        groups = [
            group for group in (state["prompt"] or {}).get("controls", [])
            if "order" in group
        ]
        return groups[0] if groups else None

    async def lock(self, client, game, coach_id, player_ids) -> dict:
        """What the whistle does: each name, in slot order, as the
        control the page was offered for it."""
        state = None
        for player_id in player_ids:
            group = self.order_group(await self.state(client, game, coach_id))
            control = next(
                one for one in group["controls"]
                if one["player"] == player_id
            )
            response = await client.post(
                f"/api/game/{game.game_id}/action",
                headers=as_coach(coach_id),
                data=json.dumps({"action": control["action"]}),
            )
            self.assertEqual(response.status, 200)
            state = await response.json()
            self.assertIsNone(state["refusal"])
        return state

    async def test_the_slots_are_the_squad_and_the_pool_is_the_options(
        self,
    ) -> None:
        ENGINE.rng.seed(11)
        fixture = case("shootout order")
        client, _ = await self.serve(fixture)
        game, match = fixture.game, fixture.match

        group = self.order_group(await self.state(client, game, game.player_1_id))

        prompt = pending_prompt(ENGINE, game, match)
        offered = prompt.options.for_side(TeamSide.HOME)
        self.assertEqual(group["order"]["side"], "home")
        self.assertEqual(group["order"]["placed"], [])
        self.assertEqual(group["order"]["slots"], len(offered))
        self.assertEqual(
            [one["player"] for one in group["controls"] if one["player"]],
            list(offered),
        )
        self.assertEqual(
            [one["action"]["choice"] for one in group["controls"]][-1],
            "restart",
        )

    async def test_locking_an_order_sends_what_the_menu_sends(self) -> None:
        ENGINE.rng.seed(11)
        fixture = case("shootout order")
        client, service = await self.serve(fixture)
        game = fixture.game
        squad = list(fixture.match.shootout_squad(TeamSide.HOME))
        order = squad[::-1]

        group = self.order_group(await self.state(client, game, game.player_1_id))
        for control in group["controls"]:
            if control["action"]["choice"] != "send":
                continue
            # `ShootoutOrderSelectView.pick`'s own Action, as the wire
            # writes it.
            self.assertEqual(
                control["action"],
                Action(
                    PromptKind.SHOOTOUT_ORDER,
                    "send",
                    {"side": TeamSide.HOME, "player_id": control["player"]},
                ).to_dict(),
            )
        state = await self.lock(client, game, game.player_1_id, order)

        self.assertEqual(
            service.load(game).shootout_order(TeamSide.HOME), order,
        )
        self.assertIsNone(self.order_group(state))
        home = next(
            one for one in state["prompt"]["shootout"]["sides"]
            if one["team_side"] == "home"
        )
        self.assertTrue(home["done"])

    async def test_a_partial_order_comes_back_in_the_first_slots(self) -> None:
        ENGINE.rng.seed(11)
        fixture = case("shootout order")
        client, _ = await self.serve(fixture)
        game = fixture.game
        squad = list(fixture.match.shootout_squad(TeamSide.HOME))

        await self.lock(client, game, game.player_1_id, squad[:2])
        group = self.order_group(await self.state(client, game, game.player_1_id))

        self.assertEqual(
            [one["id"] for one in group["order"]["placed"]], squad[:2],
        )
        self.assertEqual(group["order"]["slots"], len(squad))

    async def test_the_other_seat_and_an_observer_are_sent_no_order(
        self,
    ) -> None:
        """
        Two different orders, part-built and then whole, read the same
        to seat 2 and to somebody watching -- log included -- so what
        they are sent does not carry the order.
        """
        for count in (3, 6):
            with self.subTest(placed=count):
                seen = {2: [], STRANGER: []}
                for reverse in (False, True):
                    ENGINE.rng.seed(11)
                    fixture = case("shootout order")
                    client, _ = await self.serve(fixture)
                    game = fixture.game
                    squad = list(fixture.match.shootout_squad(TeamSide.HOME))
                    order = (squad[::-1] if reverse else squad)[:count]
                    await self.lock(client, game, game.player_1_id, order)
                    for who, coach_id in (
                        (2, game.player_2_id), (STRANGER, STRANGER),
                    ):
                        state = await self.state(client, game, coach_id)
                        self.assertNotIn(
                            "home",
                            {
                                control["action"]["arguments"].get("side")
                                for group in state["prompt"]["controls"]
                                for control in group["controls"]
                            },
                        )
                        for entry in state["entries"]:
                            entry.pop("at")
                        seen[who].append(json.dumps(state, sort_keys=True))
                for who, states in seen.items():
                    self.assertEqual(states[0], states[1], who)

    async def test_the_log_keeps_no_coach_s_own_block(self) -> None:
        """The order as it stands and "You send out" are the coach's
        own; the line saying the order is set is everybody's. The AI's
        answers are held to the same, from its group's action."""
        ENGINE.rng.seed(11)
        match = build_match()
        match.begin_shootout()
        fixture = PromptFixture(build_game(player_2_id=None), match, "")
        client, service = await self.serve(fixture)
        game = fixture.game
        squad = list(match.shootout_squad(TeamSide.HOME))
        # The AI sets its order where the question is put up, which a
        # pick-up through the page does here.
        picked_up = await client.post(
            f"/api/game/{game.game_id}/resume",
            headers=as_coach(game.player_1_id),
        )
        self.assertEqual(picked_up.status, 200)
        self.assertTrue(
            service.load(game).shootout_order_complete(TeamSide.VISITING),
        )

        state = await self.lock(client, game, game.player_1_id, squad)

        lines = [
            line
            for entry in (await self.state(client, game, STRANGER))["entries"]
            for line in entry["lines"]
        ]
        said = " ".join(lines)
        self.assertIn("has set their shooting order", said)
        self.assertEqual(said.count("has set their shooting order"), 2)
        for private in ("Keep going", "Your shooting order is set", "1. "):
            self.assertNotIn(private, said)
        # Both orders are in, so the game has moved on to the shooting.
        self.assertTrue(
            service.load(game).shootout_orders_complete, state["prompt"],
        )


class HandTests(unittest.IsolatedAsyncioTestCase):
    """
    The maneuver pick as the printed cards, and what follows it (step 5
    of docs/web-app-redesign.md): the hand is exactly the side's
    `maneuver_keys`, a gambit it does not hold is shown dimmed and
    never offered, the other side's hand is a back, an observer sees
    only backs, and a card clicked is the same `Action` through
    `driver.answer`.
    """

    async def serve(self, fixture: PromptFixture) -> tuple[TestClient, WebApp]:
        web = WebApp(service_over(fixture), GameLocks())
        web.watch()
        client = TestClient(TestServer(web.app))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        self.addAsyncCleanup(web.stop)
        return client, web

    async def state_of(self, client, fixture, headers) -> dict:
        response = await client.get(
            f"/api/game/{fixture.game.game_id}", headers=headers,
        )
        self.assertEqual(response.status, 200)
        return await response.json()

    @staticmethod
    def cards(state: dict) -> list[dict]:
        return [
            control
            for group in state["prompt"]["controls"]
            for control in group["controls"]
            if control.get("card")
        ]

    def behind(self) -> PromptFixture:
        """An advanced game where the visitors held the coin and have
        declared a gambit, and the home side (seat 1, on the ball), a
        goal down, has answered with one of its own: both play their
        three advanced maneuvers (Law 19.3)."""
        ENGINE.rng.seed(11)
        fixture = case("maneuver picks")
        fixture.game.mode = GameMode.ADVANCED
        fixture.match.coin_holder = TeamSide.VISITING
        fixture.match.declare_gambit("defense", TeamSide.VISITING)
        fixture.match.scoreboard.visiting_score = 1
        fixture.match.answer_gambit("offense", True)
        return fixture

    def level(self) -> PromptFixture:
        """An advanced game, level, with nobody declared: home (seat 1)
        holds the coin by default, so both hands are the basic three."""
        ENGINE.rng.seed(11)
        fixture = case("maneuver picks")
        fixture.game.mode = GameMode.ADVANCED
        return fixture

    async def test_a_side_holding_three_cards_is_offered_exactly_those(
        self,
    ) -> None:
        ENGINE.rng.seed(11)
        fixture = case("maneuver picks")
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        client, _ = await self.serve(fixture)

        state = await self.state_of(
            client, fixture, as_coach(fixture.game.player_1_id),
        )

        cards = self.cards(state)
        self.assertEqual(
            [control["card"]["key"] for control in cards],
            list(prompt.options.hands[0].maneuver_keys),
        )
        self.assertEqual(len(cards), 3)
        self.assertFalse(any(control["disabled"] for control in cards))
        self.assertFalse(any(control["card"]["gambit"] for control in cards))
        # The visitors' hand is face down beside it.
        self.assertEqual(
            [back["side"] for back in state["prompt"]["hand"]["backs"]],
            ["defense"],
        )

    async def test_after_a_gambit_each_side_is_offered_three(
        self,
    ) -> None:
        fixture = self.behind()
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        offense, defense = prompt.options.hands
        client, _ = await self.serve(fixture)

        home = await self.state_of(
            client, fixture, as_coach(fixture.game.player_1_id),
        )
        away = await self.state_of(
            client, fixture, as_coach(fixture.game.player_2_id),
        )

        answered = self.cards(home)
        self.assertEqual(
            [control["card"]["key"] for control in answered],
            list(offense.maneuver_keys),
        )
        self.assertEqual(len(answered), 3)
        self.assertFalse(any(control["disabled"] for control in answered))
        self.assertTrue(
            all(control["card"]["gambit"] for control in answered),
        )

        # The side that declared plays its three advanced maneuvers.
        three = self.cards(away)
        self.assertEqual(
            [control["card"]["key"] for control in three],
            list(defense.maneuver_keys),
        )
        self.assertTrue(all(control["card"]["gambit"] for control in three))

    async def test_the_coin_holder_is_offered_the_declaration(self) -> None:
        from webapp.present import (
            DECLARE_LABEL,
            WITHHELD_NOTE,
            WITHHELD_TO_DECLARE_NOTE,
        )

        fixture = self.level()
        client, _ = await self.serve(fixture)

        home = await self.state_of(
            client, fixture, as_coach(fixture.game.player_1_id),
        )
        away = await self.state_of(
            client, fixture, as_coach(fixture.game.player_2_id),
        )

        def declarations(state):
            return [
                control
                for group in state["prompt"]["controls"]
                for control in group["controls"]
                if control["label"] == DECLARE_LABEL
            ]

        self.assertEqual(len(declarations(home)), 1)
        self.assertEqual(declarations(away), [])
        for state, note in (
            (home, WITHHELD_TO_DECLARE_NOTE), (away, WITHHELD_NOTE),
        ):
            dimmed = [c for c in self.cards(state) if c["disabled"]]
            self.assertEqual(len(dimmed), 3)
            for control in dimmed:
                self.assertTrue(control["card"]["withheld"])
                self.assertEqual(control["note"], note)
                # Never an answer: pressed anyway, it is refused.
                response = await client.post(
                    f"/api/game/{fixture.game.game_id}/action",
                    headers=as_coach(fixture.game.player_2_id),
                    data=json.dumps({"action": control["action"]}),
                )
                self.assertEqual(response.status, 409)

        response = await client.post(
            f"/api/game/{fixture.game.game_id}/action",
            headers=as_coach(fixture.game.player_1_id),
            data=json.dumps({"action": declarations(home)[0]["action"]}),
        )
        self.assertEqual(response.status, 200)
        declared = await response.json()
        self.assertTrue(
            all(control["card"]["gambit"] for control in self.cards(declared)
                if not control["disabled"])
        )
        self.assertEqual(declarations(declared), [])

    async def test_a_card_is_drawn_as_its_pill(self) -> None:
        """Each card in the hand carries its pill: the name, the rank as
        the card's corner prints it, the diagram (served), the effect in
        the sheet's words, and what it beats, ties and loses to -- the
        catalog's own reading of rank -- over the tiers the game plays."""
        fixture = self.level()
        client, _ = await self.serve(fixture)
        state = await self.state_of(
            client, fixture, as_coach(fixture.game.player_1_id),
        )
        catalog = ENGINE.maneuver_catalog
        outcomes = {"Beats": "offense", "Ties": "tie", "Loses to": "defense"}
        cards = self.cards(state)
        self.assertEqual(len(cards), 6)
        for control in cards:
            key = control["card"]["key"]
            maneuver = catalog.definition(key)
            pill = control["card"]["pill"]
            self.assertEqual(pill["name"], maneuver.name)
            self.assertEqual(pill["rank"], f"O{maneuver.rank}")
            self.assertEqual(pill["effect"], maneuver.effect)
            self.assertEqual(
                [one["said"] for one in pill["matchups"]], list(outcomes),
            )
            for one in pill["matchups"]:
                # An advanced game plays both tiers of every rank.
                self.assertEqual(len(one["names"]), 2)
                for name in one["names"]:
                    other = next(m for m in catalog.defense if m.name == name)
                    self.assertEqual(
                        catalog.resolve(key, other.key), outcomes[one["said"]],
                    )
            response = await client.get(pill["diagram"])
            self.assertEqual(response.status, 200)
            self.assertEqual(response.content_type, "image/png")

    def test_a_special_ability_names_a_card_as_the_sheet_words_it(self) -> None:
        names = present._names_card
        self.assertTrue(names(
            "When high passing for 3: speed ball to 12.", "High Pass",
            "offense", False,
        ))
        self.assertTrue(names(
            "When successfully pressuring into the goal zone.", "Pressure",
            "defense", False,
        ))
        # A count after the word is the verb, not the card.
        self.assertFalse(names(
            "When burns: clear 1 exhaustion.", "Clear", "defense", True,
        ))
        # "Gambit" names a gambit of the side it speaks of, and only that.
        self.assertTrue(names(
            "Offensive gambits succeed when won on a skill test.", "Burst",
            "offense", True,
        ))
        self.assertFalse(names(
            "Defensive gambits succeed when won on a skill test.", "Burst",
            "offense", True,
        ))
        self.assertFalse(names(
            "Offensive gambits succeed when won on a skill test.", "Dribble",
            "offense", False,
        ))

    async def test_the_pick_is_asked_of_nobody_by_name(self) -> None:
        """The page's ask names no coach: the holder of the coin is told
        about it beside the coin itself, and everybody else reads the
        model's sentence about who holds it."""
        from webapp.present import (
            COIN_LINE,
            MANEUVER_ASK,
            MANEUVER_ASK_WATCHING,
        )

        fixture = self.level()
        client, _ = await self.serve(fixture)
        holder, other, watching = [
            await self.state_of(client, fixture, as_coach(coach_id))
            for coach_id in (
                fixture.game.player_1_id, fixture.game.player_2_id, STRANGER,
            )
        ]

        self.assertEqual(
            html.unescape(holder["prompt"]["ask"]), MANEUVER_ASK,
        )
        coin = holder["prompt"]["controls"][0]["controls"][0]
        self.assertEqual(coin["place"], {"at": "coin"})
        self.assertEqual(coin["said"], COIN_LINE)
        self.assertTrue(coin["image"].startswith("/emoji/"))
        for state, ask in (
            (other, MANEUVER_ASK), (watching, MANEUVER_ASK_WATCHING),
        ):
            first, coin_said = html.unescape(
                state["prompt"]["ask"],
            ).split("\n\n")
            self.assertEqual(first, ask)
            self.assertIn("holds the coin, ", coin_said)
            self.assertIn("Fortune up, and may declare a gambit.", coin_said)
            self.assertNotIn('class="coach"', state["prompt"]["ask"])

    def test_no_player_s_ability_is_listed_twice(self) -> None:
        """A card fielded on both sides is one person
        (`catalog_player_id`): a pill's hover lists their ability once,
        under both teams, never once a side (the author, 2026-10-01)."""
        from d12ball.components import MatchState, catalog_player_id

        game = build_game()
        game.mode = GameMode.ADVANCED
        home, visiting = Team.PURPLE, Team.CYBORGS
        match = MatchState.standard(
            catalog=ENGINE.player_catalog, ruleset=ENGINE.basic_ruleset,
            board_size=9, home_team=home, visiting_team=visiting,
        )
        on_both = {
            catalog_player_id(one) for one in match.home.field_players
        } & {
            catalog_player_id(one) for one in match.visiting.field_players
        }
        catalog = ENGINE.maneuver_catalog
        shared_rows = 0
        for maneuver in catalog.offense + catalog.defense:
            side = catalog.side_of(maneuver.key)
            pill = present.maneuver_pill(ENGINE, game, match, maneuver.key, side)
            players = [one for one in pill["abilities"] if "team" in one]
            with self.subTest(maneuver.key):
                self.assertEqual(
                    len({one["who"] for one in players}), len(players),
                )
            shared_rows += sum(
                one["team"] == f"{team_display_name(home)} and "
                f"{team_display_name(visiting)}"
                for one in players
            )
        if not on_both or not shared_rows:
            self.skipTest(
                "these two teams field nobody on both sides whose ability "
                "names a card -- pick two that do",
            )

    async def test_the_coin_shows_the_face_it_landed_on(self) -> None:
        """Law 19.3.3: the coin in the holder's box and on the jumbotron
        is the game's own coin on the face it landed on when it last
        passed -- the same face in both places, and in the sentence."""
        from d12ball.game import CoinFace, coin_face_name

        fixture = self.level()
        fixture.match.coin_face = CoinFace.DOOM
        client, _ = await self.serve(fixture)
        holder, other = [
            await self.state_of(client, fixture, as_coach(coach_id))
            for coach_id in (
                fixture.game.player_1_id, fixture.game.player_2_id,
            )
        ]

        doom = f"/emoji/{coin_face_name(fixture.game.game_coin, CoinFace.DOOM)}.png"
        coin = holder["prompt"]["controls"][0]["controls"][0]
        self.assertEqual(coin["image"], doom)
        for state in (holder, other):
            self.assertEqual(
                state["board"]["layout"]["jumbotron"]["coin"], doom,
            )
        self.assertIn(doom, other["prompt"]["ask"])
        self.assertIn("Doom up", other["prompt"]["ask"])

    async def test_an_observer_sees_two_backs_and_no_face(self) -> None:
        fixture = self.behind()
        client, _ = await self.serve(fixture)

        state = await self.state_of(client, fixture, as_coach(STRANGER))

        self.assertEqual(state["prompt"]["controls"], [])
        hand = state["prompt"]["hand"]
        self.assertEqual(
            [back["side"] for back in hand["backs"]], ["offense", "defense"],
        )
        self.assertEqual(hand["note"], "The hands are turned over together.")
        said = json.dumps(state["prompt"])
        for key in (
            card.key
            for side in ("offense", "defense")
            for card in ENGINE.maneuver_catalog.side(side)
        ):
            self.assertNotIn(f'"{key}"', said)

    async def test_a_card_clicked_reaches_the_driver_with_its_key(
        self,
    ) -> None:
        from d12ball.flow import driver

        fixture = self.behind()
        client, web = await self.serve(fixture)
        state = await self.state_of(
            client, fixture, as_coach(fixture.game.player_1_id),
        )
        card = next(
            control for control in self.cards(state)
            if control["card"]["key"] == "setup_pass"
        )

        with mock.patch.object(
            driver, "answer", wraps=driver.answer,
        ) as answer:
            response = await client.post(
                f"/api/game/{fixture.game.game_id}/action",
                headers=as_coach(fixture.game.player_1_id),
                data=json.dumps({"action": card["action"]}),
            )
        self.assertEqual(response.status, 200)
        action = answer.call_args.args[3]
        self.assertEqual(action.kind, PromptKind.MANEUVER_ACTION)
        self.assertEqual(action.arguments["maneuver_key"], "setup_pass")

        # Laid face down, it stays in its coach's hand ringed and dead,
        # and the rest may replace it while the visitors are still to
        # pick (the author, 2026-09-26); the box is waiting on them.
        picked = await response.json()
        cards = self.cards(picked)
        ringed = [one for one in cards if one["card"].get("picked")]
        self.assertEqual(
            [one["card"]["key"] for one in ringed], ["setup_pass"],
        )
        self.assertTrue(ringed[0]["disabled"])
        live = [one for one in cards if not one["disabled"]]
        self.assertEqual(len(live), 2)
        self.assertEqual(picked["prompt"]["state"], "waiting")
        self.assertFalse(picked["prompt"]["yours"])
        self.assertEqual(
            [back["side"] for back in picked["prompt"]["hand"]["backs"]],
            ["defense"],
        )
        # The other coach is not shown it, and their question is theirs.
        theirs = await self.state_of(
            client, fixture, as_coach(fixture.game.player_2_id),
        )
        self.assertNotIn('"setup_pass"', json.dumps(theirs["prompt"]))
        self.assertEqual(theirs["prompt"]["state"], "yours")

        # A change of card is taken over the old one.
        instead = next(one for one in live if one["card"]["key"] == "dribble_burst")
        response = await client.post(
            f"/api/game/{fixture.game.game_id}/action",
            headers=as_coach(fixture.game.player_1_id),
            data=json.dumps({"action": instead["action"]}),
        )
        self.assertEqual(response.status, 200)
        changed = await response.json()
        self.assertIsNone(changed["refusal"])
        self.assertEqual(
            web.service.games[fixture.game.game_id].match_state[
                "offense_maneuver"
            ],
            "dribble_burst",
        )
        self.assertEqual(
            [one["card"]["key"] for one in self.cards(changed)
             if one["card"].get("picked")],
            ["dribble_burst"],
        )

    async def test_both_cards_turn_over_together(self) -> None:
        """The skill test's tie: both cards face up with TIE between
        them, for a coach and an observer alike."""
        ENGINE.rng.seed(11)
        fixture = case("skill test")
        client, _ = await self.serve(fixture)
        for headers in (as_coach(fixture.game.player_1_id), as_coach(STRANGER)):
            state = await self.state_of(client, fixture, headers)
            shown = state["reveal"]
            self.assertEqual(
                [(one["key"], one["side"]) for one in shown["cards"]],
                [
                    (fixture.match.offense_maneuver, "offense"),
                    (fixture.match.defense_maneuver, "defense"),
                ],
            )
            self.assertEqual(shown["between"], "TIE")
        self.assertEqual(ENGINE.cards_outcome(fixture.match), "tie")


class FullTimeTests(unittest.IsolatedAsyncioTestCase):
    """The full-time block (step 5 of docs/web-app-redesign.md, with
    step 12 folded in): `stats.py`'s numbers per side, the rematch
    and the log as text."""

    async def asyncSetUp(self) -> None:
        from d12ball import stats
        from d12ball.components import (
            DECISION_CARDS,
            EVENT_MANEUVER,
            EVENT_SHOT,
            EVENT_TIME_OUT,
            EVENT_TURN_ACTION,
        )

        ENGINE.rng.seed(11)
        self.fixture = case("game over")
        match = self.fixture.match
        scorer = match.home.field_players[0]
        match.record_event(
            EVENT_TURN_ACTION, side=TeamSide.HOME, action="maneuver",
            exhaustion={scorer: 2},
        )
        match.record_event(
            EVENT_MANEUVER, side=TeamSide.HOME, offense_key="low_pass",
            defense_key="pressure", winner_key="low_pass",
            decision=DECISION_CARDS,
        )
        match.record_event(EVENT_SHOT, side=TeamSide.HOME, scored=True)
        match.record_goal(TeamSide.HOME, scorer)
        match.record_event(EVENT_TIME_OUT, side=TeamSide.VISITING)
        self.sides = stats.collect_sides(match)
        self.service = service_over(self.fixture)
        self.web = WebApp(self.service, GameLocks())
        self.web.watch()
        self.client = TestClient(TestServer(self.web.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.addAsyncCleanup(self.web.stop)
        self.game = self.fixture.game

    async def state(self, headers=None) -> dict:
        response = await self.client.get(
            f"/api/game/{self.game.game_id}",
            headers=headers or as_coach(self.game.player_1_id),
        )
        return await response.json()

    async def test_the_block_is_stats_numbers_in_each_side_s_colour(
        self,
    ) -> None:
        state = await self.state()
        block = state["full_time"]
        home, visiting = self.sides[TeamSide.HOME], self.sides[TeamSide.VISITING]

        rows = {row["label"]: (row["home"], row["visiting"]) for row in block["rows"]}
        self.assertEqual(
            list(rows),
            [
                "goals", "shots", "maneuvers won", "skill tests",
                "exhaustion taken", "time outs",
            ],
        )
        self.assertEqual(rows["goals"], (str(home.goals), str(visiting.goals)))
        self.assertEqual(rows["goals"][0], "1")
        self.assertEqual(rows["shots"], ("1", "0"))
        self.assertEqual(rows["maneuvers won"], ("1", "0"))
        self.assertEqual(rows["exhaustion taken"], ("2", "0"))
        self.assertEqual(rows["time outs"], ("0", "1"))
        self.assertEqual(
            (block["home_colour"], block["visiting_colour"]),
            (
                side_colour(self.fixture.match, TeamSide.HOME),
                side_colour(self.fixture.match, TeamSide.VISITING),
            ),
        )
        self.assertEqual(block["log"], f"/api/room/{self.game.game_id}/log.txt")
        # An observer is shown the same numbers.
        self.assertEqual((await self.state(as_coach(STRANGER)))["full_time"], block)

    async def test_a_game_under_way_has_no_block(self) -> None:
        ENGINE.rng.seed(11)
        fixture = case("plain turn")
        web = WebApp(service_over(fixture), GameLocks())
        client = TestClient(TestServer(web.app))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        state = await (
            await client.get(
                f"/api/game/{fixture.game.game_id}",
                headers=as_coach(fixture.game.player_1_id),
            )
        ).json()
        self.assertIsNone(state["full_time"])

    async def test_the_rematch_links_to_the_room_the_service_made(
        self,
    ) -> None:
        state = await self.state()
        mark = next(
            control
            for group in state["prompt"]["controls"]
            for control in group["controls"]
            if (control.get("place") or {}).get("at") == "rematch"
        )
        self.assertEqual(mark["post"], "/rematch")

        response = await self.client.post(
            f"/api/room/{self.game.game_id}/rematch",
            headers=as_coach(self.game.player_1_id),
        )
        self.assertEqual(response.status, 200)
        after = await response.json()

        made = self.service.games[self.game.game_id].rematch_game_id
        self.assertIn(made, self.service.games)
        self.assertEqual(after["rematch"]["url"], f"/room/{made}")

    async def test_the_log_is_its_words_as_text(self) -> None:
        journal = self.web.journals.journal(self.game.game_id)
        journal.entries.append(Entry(
            id=1,
            lines=("**{team:orange}** scores, and {coach:1} says so.",),
            at=0.0,
        ))

        response = await self.client.get(
            f"/api/room/{self.game.game_id}/log.txt",
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "text/plain")
        text = await response.text()
        self.assertIn("**Orange** scores, and", text)
        self.assertNotIn("{team:", text)
        self.assertNotIn("<img", text)


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

    def test_python_m_webapp_is_wired_to_the_web_files(self) -> None:
        """
        `python3 -m webapp` runs `server.main`, which serves over the
        web app's own files and never the bot's -- asserted on the
        constants, since nothing here may start a server.
        """
        self.assertNotEqual(storage.WEB_GAMES_FILE, storage.GAMES_FILE)

        served = mock.AsyncMock()
        with mock.patch.object(server, "serve", served), \
             mock.patch.object(server, "load_dotenv"), \
             mock.patch.object(server, "configure_logging"):
            sys.modules.pop("webapp.__main__", None)
            importlib.import_module("webapp.__main__")
        served.assert_awaited_once_with()

        defaults = {
            name: parameter.default
            for name, parameter in inspect.signature(
                server.serve,
            ).parameters.items()
        }
        self.assertEqual(defaults["games_file"], storage.WEB_GAMES_FILE)
        self.assertEqual(defaults["rooms_file"], WEB_ROOMS_FILE)
        self.assertEqual(defaults["chat_file"], WEB_CHAT_FILE)
        self.assertEqual(defaults["journal_file"], WEB_JOURNAL_FILE)
        self.assertEqual(defaults["secret_file"], keys.WEB_SECRET_FILE)
        self.assertEqual(keys.WEB_SECRET_FILE.parent, storage.DATA_FOLDER)
        self.assertNotIn(storage.GAMES_FILE, defaults.values())

        built = []

        class Built(Exception):
            pass

        def build(path):
            built.append(path)
            raise Built

        kept = mock.Mock()
        with mock.patch.object(server, "build_service", build), \
             mock.patch.object(keys, "keep_secret_in", kept):
            with self.assertRaises(Built):
                asyncio.run(server.serve())
        self.assertEqual(built, [storage.WEB_GAMES_FILE])
        kept.assert_called_once_with(keys.WEB_SECRET_FILE)

    def test_it_batches_for_the_walk_in_and_nothing_else(self) -> None:
        """Discord's economy is the cog's; the web app has no rate
        limit to batch for. The one boundary it draws is the walk-in,
        which the log words the challenge on (step 8 of
        docs/web-app-next.md); it stops nowhere and carries every
        answer the default way."""
        with tempfile.TemporaryDirectory() as directory:
            service = server.build_service(Path(directory) / "web.json")

        default = GameService(None, {}).batching
        self.assertIs(service.batching, server.WEB_BATCHING)
        self.assertEqual(
            service.batching.own_message,
            frozenset({FollowOnStep.AUTO_RESOLVE_CHALLENGER}),
        )
        self.assertEqual(service.batching.stop_after, default.stop_after)
        self.assertEqual(service.batching.speaks_lines, default.speaks_lines)
        self.assertIs(type(service.batching), type(default))


class CoachingOnTheBoardTests(unittest.TestCase):
    """
    The Coaching Choice played on the board (step 6 of
    docs/web-app-redesign.md): a substitute is a bench meeple put on
    the player it replaces, a zone change one player on another, a move
    a player on a space, a formation a tile, Done the whistle -- each
    sent as the page sends it, checked against what was offered, and
    through the service to kickoff.
    """

    def setUp(self) -> None:
        ENGINE.rng.seed(11)

    def begun(self, game, match):
        game.match_state = match.to_dict()
        service = GameService(
            ENGINE, {game.game_id: game}, save=lambda games: None,
        )
        service.begin(game.game_id)
        return service

    def offered(self, service, game, number):
        match = service.load(game)
        prompt = pending_prompt(ENGINE, game, match)
        return match, prompt, controls_for(
            ENGINE, game, match, prompt, Viewer(number),
        )

    def press(self, service, game, offered, control) -> None:
        """One control, as the page sends it: its own action, which must
        be one this viewer was handed."""
        self.assertFalse(control["disabled"], control["label"])
        self.assertTrue(_was_offered(offered, control["action"]), control["label"])
        result = service.apply_action(
            game.game_id, Action.from_dict(control["action"]),
        )
        self.assertFalse(result.refused, result.refusal)

    def first(self, offered, choice, test=lambda control: True):
        return next(
            control
            for group in offered
            for control in group["controls"]
            if control["action"]["choice"] == choice
            and not control["disabled"]
            and test(control)
        )

    def test_the_lit_line_names_no_player_to_pick_up(self) -> None:
        """The board lights every player a move may start from and the
        how-lines say what to do with them, so the lit line lists none
        of them (the author, 2026-09-26): only the window's allowance,
        the options' and not the page's."""
        fixture = case("setup coaching")
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        offered = controls_for(
            ENGINE, fixture.game, fixture.match, prompt, Viewer(1),
        )
        lines = [
            line["text"]
            for line in lit_line(
                ENGINE, fixture.game, fixture.match, prompt, Viewer(1), offered,
            )
        ]
        self.assertEqual(lines, [f"{prompt.options.allowance}."])

    def test_the_spreadable_note_is_split_off_the_ask(self) -> None:
        """The reminder `prompts._window` appends is handed back apart,
        for the box to say under the whistle; an ask without it is
        handed back whole."""
        fixture = case("setup coaching")
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        self.assertEqual(
            present.split_footnote(
                ENGINE, fixture.game, fixture.match, prompt, prompt.ask,
            ),
            (prompt.ask, ""),
        )
        with mock.patch.object(
            ENGINE, "spreadable_note", return_value=SPREADABLE_NOTE,
        ):
            self.assertEqual(
                present.split_footnote(
                    ENGINE, fixture.game, fixture.match, prompt,
                    f"{prompt.ask}\n{SPREADABLE_NOTE}",
                ),
                (prompt.ask, SPREADABLE_NOTE),
            )

    def test_the_setup_reaches_kickoff_through_the_board(self) -> None:
        service = self.begun(build_game(), build_match())
        game = service.game(GAME_ID)
        pressed = []
        for number, moves in ((1, ("substitute", "formation")),
                              (2, ("swap", "reposition"))):
            for choice in moves:
                match, prompt, offered = self.offered(service, game, number)
                self.assertIs(prompt.kind, PromptKind.COACHING_HUB)
                side = TeamSide(prompt.side)
                layout = board_layout(
                    ENGINE, game, match, card_url="/c/{card}", goal_url="/g/{side}",
                )
                control = self.first(offered, choice)
                if control.get("first"):
                    # Picked up first: the bench for a substitute, a
                    # fielded player otherwise -- both drawn by the page.
                    board = next(
                        one for one in layout["team_boards"]
                        if one["side"] == side.value
                    )
                    first = control["first"]["id"]
                    if choice == "substitute":
                        self.assertIn(first, [one["id"] for one in board["bench"]])
                    else:
                        self.assertIn(first, match.setup_for_side(side).field_players)
                else:
                    self.assertEqual(control["place"]["at"], "formation")
                self.press(service, game, offered, control)
                pressed.append(choice)
            match, prompt, offered = self.offered(service, game, number)
            self.press(service, game, offered, self.first(offered, "done"))
        match, prompt, _ = self.offered(service, game, 1)
        self.assertEqual(
            pressed, ["substitute", "formation", "swap", "reposition"],
        )
        self.assertIsNot(prompt.kind, PromptKind.COACHING_HUB)
        self.assertIsNone(match.pending_setup_stage)
        self.assertIsNone(match.pending_coaching_side)

    def test_the_tutorial_reaches_its_first_turn_through_the_page(self) -> None:
        """The tutorial opens no setup window -- the script deals the
        standard shape -- so what stands before its first turn is the
        welcome, answered on the note."""
        from test_driver_full_game import (
            build_tutorial_game,
            build_tutorial_match,
        )

        game, match = build_tutorial_game(), build_tutorial_match()
        service = self.begun(game, match)
        for _ in range(10):
            match, prompt, offered = self.offered(service, game, 1)
            if prompt.kind not in (
                PromptKind.TUTORIAL_CONTINUE, PromptKind.COACHING_HUB,
            ):
                break
            control = next(
                control
                for group in offered
                for control in group["controls"]
                if not control["disabled"]
            )
            self.assertIn(control["place"]["at"], ("note", "whistle"))
            self.press(service, game, offered, control)
        self.assertNotIn(
            prompt.kind,
            (PromptKind.TUTORIAL_CONTINUE, PromptKind.COACHING_HUB),
        )


if __name__ == "__main__":
    unittest.main()

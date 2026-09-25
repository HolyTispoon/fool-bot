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
- **A turn taken on Discord reaches a page that did not ask for it**,
  through `GameService.listeners`.
"""

from __future__ import annotations

import json
import unittest

from aiohttp.test_utils import TestClient, TestServer

from d12ball.components import TeamSide
from d12ball.prompts import Action, PromptKind, asked_sides, pending_prompt
from gamesaves.d12ball.service import GameService
from webapp import keys
from webapp.present import CONTROLS, Viewer, controls_for, render_text
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
            if kind is PromptKind.GAME_OVER:
                # A finished game asks nothing: the rematch under it
                # opens a new game, which is not an action on this one.
                continue
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
        self.key = keys.key_for(self.game.game_id, 1)

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

    async def state(self, key: str = None) -> dict:
        response = await self.client.get(
            f"/api/game/{self.game.game_id}",
            params={"key": key if key is not None else self.key},
        )
        self.assertEqual(response.status, 200)
        return await response.json()

    async def press(self, action: dict, *, key: str = None, since: int = 0):
        return await self.client.post(
            f"/api/game/{self.game.game_id}/action",
            params={"key": key if key is not None else self.key,
                    "since": str(since)},
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
        theirs = await self.state(key="not-a-key")

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

        response = await self.press(self.live(state)["action"], key="not-a-key")

        self.assertEqual(response.status, 409)
        self.assertEqual(self.game.match_state, before)

    async def test_a_turn_taken_elsewhere_reaches_the_page(self) -> None:
        """
        The other coach is on Discord: their click goes through the
        service, and the journal is fed by the service
        (`GameService.listeners`), so the page sees what was said
        without having asked for it.
        """
        self.client, self.game = await self.open("coaching hub")
        state = await self.state()
        action = Action.from_dict(self.live(state)["action"])

        self.service.apply_action(self.game.game_id, action)
        caught_up = await self.client.get(
            f"/api/game/{self.game.game_id}",
            params={"key": self.key, "since": str(state["latest"])},
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


class KeyTests(unittest.TestCase):
    """Who is on the other end of a request."""

    def setUp(self) -> None:
        self.game_id = "g1"

    def test_a_key_names_the_coach_it_was_made_for(self) -> None:
        for player_number in (1, 2):
            with self.subTest(player_number):
                self.assertEqual(
                    keys.player_number_for(
                        self.game_id, keys.key_for(self.game_id, player_number),
                    ),
                    player_number,
                )

    def test_the_two_coaches_of_a_game_have_different_keys(self) -> None:
        self.assertNotEqual(
            keys.key_for(self.game_id, 1), keys.key_for(self.game_id, 2),
        )

    def test_a_key_is_for_one_game(self) -> None:
        self.assertIsNone(
            keys.player_number_for("g2", keys.key_for(self.game_id, 1)),
        )

    def test_no_key_is_nobody(self) -> None:
        self.assertIsNone(keys.player_number_for(self.game_id, None))
        self.assertIsNone(keys.player_number_for(self.game_id, ""))
        self.assertIsNone(keys.player_number_for(self.game_id, "0" * 16))

    def test_a_link_carries_the_key(self) -> None:
        link = keys.link_for(self.game_id, 2)

        self.assertIn(self.game_id, link)
        self.assertIn(keys.key_for(self.game_id, 2), link)


if __name__ == "__main__":
    unittest.main()

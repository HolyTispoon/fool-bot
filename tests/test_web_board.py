"""
The web page's board and pictures: `webapp/board.py`, `webapp/pictures.py`
and the routes that serve them.

What it is watching for:

- **The layout is the position.** Every card, meeple and ball the page
  is handed is where the match has it -- the visitors' cards over each
  zone and the home side's under it, each space's occupants split by
  side, the ball on one space, the benches as the team boards hold
  them. The page lays this out and decides nothing, so a layout that
  disagreed with the match would be a page drawing the wrong game.
- **The range bands and space codes are the renderer's**, asked of
  the same functions the PNG asks, never worked out here.
- **A picture route serves only what it names**: a card this game
  holds, a maneuver that exists, a bundled emoji -- and nothing a
  request could spell to walk out of the folder.
- **A button is coloured in Discord's four**, and a maneuver card is
  red for the offense and green for the defense, as the Discord view
  and the printed cards have them.
"""

from __future__ import annotations

import unittest

from aiohttp.test_utils import TestClient, TestServer

from d12ball.components import Zone
from d12ball.prompts import pending_prompt
from d12ball.render import shooting_range_bands, space_code
from gamelocks import GameLocks
from webapp import keys
from webapp.board import ZONES, board_layout
from webapp.present import STYLES, Viewer, controls_for
from webapp.server import WebApp
from prompt_fixtures import CASES, ENGINE
from test_web_app import case, service_over

CARD_URL = "/card/{card}.png"
GOAL_URL = "/goal/{side}.png"


def layout_for(name: str):
    fixture = case(name)
    return fixture, board_layout(
        ENGINE,
        fixture.game,
        fixture.match,
        card_url=CARD_URL,
        goal_url=GOAL_URL,
    )


class LayoutTests(unittest.TestCase):
    """The board the page is handed, against the match it read."""

    def setUp(self) -> None:
        ENGINE.rng.seed(11)
        self.fixture, self.layout = layout_for("kickoff")
        self.match = self.fixture.match

    def test_each_zone_carries_its_cards_on_the_side_that_fields_them(self) -> None:
        for zone, drawn in zip(ZONES, self.layout["zones"]):
            with self.subTest(zone.value):
                self.assertEqual(drawn["zone"], zone.value)
                self.assertEqual(
                    [card["id"] for card in drawn["home"]],
                    list(self.match.home.zones.get(zone, [])),
                )
                self.assertEqual(
                    [card["id"] for card in drawn["visiting"]],
                    list(self.match.visiting.zones.get(zone, [])),
                )
                self.assertEqual(
                    drawn["spaces"], len(self.match.board.spaces[zone]),
                )

    def test_every_space_holds_who_the_match_has_on_it(self) -> None:
        board = self.match.board
        spaces = iter(self.layout["spaces"])
        for zone in ZONES:
            for index, occupants in enumerate(board.spaces[zone]):
                drawn = next(spaces)
                with self.subTest(zone=zone.value, space=index):
                    self.assertEqual(drawn["code"], space_code(zone, index, board))
                    self.assertEqual(
                        sorted(
                            meeple["id"]
                            for side in ("home", "visiting")
                            for meeple in drawn[side]
                        ),
                        sorted(occupants),
                    )
                    for meeple in drawn["home"]:
                        self.assertIn(meeple["id"], self.match.home.field_players)
                    for meeple in drawn["visiting"]:
                        self.assertIn(
                            meeple["id"], self.match.visiting.field_players,
                        )
        self.assertEqual(
            len(self.layout["spaces"]), board.layout.board_size,
        )

    def test_the_ball_is_on_one_space_and_it_is_the_match_s(self) -> None:
        carrying = [
            (index, space["ball"])
            for index, space in enumerate(self.layout["spaces"])
            if space["ball"] is not None
        ]
        self.assertEqual(len(carrying), 1)
        index, ball = carrying[0]
        drawn = self.layout["spaces"][index]
        self.assertEqual(drawn["zone"], self.match.ball.zone.value)
        self.assertEqual(ball["speed"], self.match.ball.speed)
        self.assertEqual(ball["side"], self.match.ball.possession.value)

    def test_the_bands_are_the_renderer_s(self) -> None:
        self.assertEqual(
            [(band["first"], band["last"]) for band in self.layout["bands"]],
            [(first, last) for _, first, last in shooting_range_bands(self.match)],
        )
        self.assertEqual(
            [band["side"] for band in self.layout["bands"]].count(None),
            [side for side, _, _ in shooting_range_bands(self.match)].count(0),
        )

    def test_the_team_boards_are_home_then_visitors_as_the_bot_draws_them(
        self,
    ) -> None:
        home, visiting = self.layout["team_boards"]
        self.assertEqual(home["side"], "home")
        self.assertEqual(visiting["side"], "visiting")
        self.assertEqual(
            [card["id"] for card in home["bench"]],
            list(self.match.home.team_board.bench),
        )
        self.assertEqual(
            [card["id"] for card in visiting["back_bench"]],
            list(self.match.visiting.team_board.back_bench),
        )

    def test_a_card_carries_the_marks_the_match_puts_on_it(self) -> None:
        card_id = self.match.home.zones[Zone.MIDFIELD][0]
        self.match.exhaustion[card_id] = 2
        self.match.injured.add(card_id)
        layout = board_layout(
            ENGINE,
            self.fixture.game,
            self.match,
            card_url=CARD_URL,
            goal_url=GOAL_URL,
        )
        card = next(
            one
            for zone in layout["zones"]
            for one in zone["home"]
            if one["id"] == card_id
        )

        self.assertEqual(card["exhaustion"], 2)
        self.assertTrue(card["injured"])
        # The picture is drawn with the marks, so its address says them.
        self.assertTrue(
            card["image"].startswith(f"/card/{card_id}.png?x=2&e=0&i=1&c=0&s="),
        )


class StyleTests(unittest.TestCase):
    """What colour a button is."""

    def setUp(self) -> None:
        ENGINE.rng.seed(11)

    def test_every_control_is_one_of_discord_s_four_colours(self) -> None:
        for entry in CASES:
            if not entry.asked or entry.ai:
                continue
            with self.subTest(entry.name):
                fixture = entry.build()
                prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
                for player_number in (1, 2):
                    for group in controls_for(
                        ENGINE, fixture.game, fixture.match, prompt,
                        Viewer(player_number),
                    ):
                        for control in group["controls"]:
                            if control["type"] == "button":
                                self.assertIn(control["style"], STYLES)

    def test_a_maneuver_card_is_red_for_the_offense_and_green_for_the_defense(
        self,
    ) -> None:
        fixture = case("maneuver picks")
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        seen = set()
        for player_number in (1, 2):
            for group in controls_for(
                ENGINE, fixture.game, fixture.match, prompt,
                Viewer(player_number),
            ):
                for control in group["controls"]:
                    side = control["card"]["side"]
                    seen.add(side)
                    self.assertEqual(
                        control["card"]["key"],
                        control["action"]["arguments"]["maneuver_key"],
                    )
                    self.assertEqual(
                        control["style"],
                        "danger" if side == "offense" else "success",
                    )
        self.assertEqual(seen, {"offense", "defense"})


class PictureRouteTests(unittest.IsolatedAsyncioTestCase):
    """The pictures a page draws the board with, over a real client."""

    async def asyncSetUp(self) -> None:
        ENGINE.rng.seed(11)
        fixture = case("kickoff")
        self.game = fixture.game
        self.match = fixture.match
        self.web = WebApp(service_over(fixture), GameLocks())
        self.client = TestClient(TestServer(self.web.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def png(self, path: str, **params) -> bytes:
        response = await self.client.get(path, params=params)
        self.assertEqual(response.status, 200, path)
        self.assertEqual(response.content_type, "image/png")
        body = await response.read()
        self.assertTrue(body.startswith(b"\x89PNG"))
        return body

    async def test_the_state_carries_the_board_the_page_draws(self) -> None:
        response = await self.client.get(
            f"/api/game/{self.game.game_id}",
            params={"key": keys.key_for(self.game.game_id, 1)},
        )
        state = await response.json()

        self.assertEqual(
            len(state["board"]["layout"]["spaces"]),
            self.match.board.layout.board_size,
        )
        self.assertTrue(state["game"]["title"].startswith("PBD"))

    async def test_a_card_this_game_holds_is_served_both_faces(self) -> None:
        card_id = self.match.home.zones[Zone.MIDFIELD][0]
        base = f"/api/game/{self.game.game_id}/card/{card_id}.png"

        await self.png(base)
        await self.png(base, x="2", e="1", c="1")
        await self.png(base, face="full")

    async def test_both_goals_are_served(self) -> None:
        for side in ("home", "visiting"):
            await self.png(f"/api/game/{self.game.game_id}/goal/{side}.png")
        response = await self.client.get(
            f"/api/game/{self.game.game_id}/goal/middle.png",
        )
        self.assertEqual(response.status, 404)

    async def test_a_card_nobody_in_this_game_holds_is_not_found(self) -> None:
        response = await self.client.get(
            f"/api/game/{self.game.game_id}/card/nobody.png",
        )

        self.assertEqual(response.status, 404)

    async def test_a_maneuver_card_is_served_for_either_side(self) -> None:
        key = ENGINE.maneuver_catalog.offense[0].key
        base = f"/api/game/{self.game.game_id}/maneuver/{key}.png"

        await self.png(base, side="offense")
        await self.png(base, side="defense", size="full")
        missing = await self.client.get(
            f"/api/game/{self.game.game_id}/maneuver/nothing.png",
        )
        self.assertEqual(missing.status, 404)

    async def test_only_a_bundled_emoji_is_served(self) -> None:
        await self.png("/emoji/exhausted.png")
        for name in ("..%2Fgame.py", "nothing.png", "EXHAUSTED.png"):
            with self.subTest(name):
                response = await self.client.get(f"/emoji/{name}")
                self.assertEqual(response.status, 404)


class ChatTests(unittest.IsolatedAsyncioTestCase):
    """
    The chat beside the log (step 4 of docs/web-app-next.md, in
    memory): people talking, which is not an action on the game.
    """

    async def asyncSetUp(self) -> None:
        ENGINE.rng.seed(11)
        fixture = case("kickoff")
        self.game = fixture.game
        self.web = WebApp(service_over(fixture), GameLocks())
        self.client = TestClient(TestServer(self.web.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def say(self, text: str, key: str = "", since: int = 0):
        return await self.client.post(
            f"/api/game/{self.game.game_id}/chat",
            params={"key": key, "chat_since": str(since)},
            json={"text": text},
        )

    async def test_a_coach_talks_under_their_name_and_an_observer_as_one(
        self,
    ) -> None:
        coach = keys.key_for(self.game.game_id, 1)
        before = dict(self.game.match_state)

        await self.say("good luck", key=coach)
        response = await self.say("  watching  ")
        state = await response.json()

        self.assertEqual(
            [(one["who"], one["text"]) for one in state["chat"]],
            [
                (self.web._coach(self.game, 1)["name"], "good luck"),
                ("Observer", "watching"),
            ],
        )
        self.assertIsNotNone(state["chat"][0]["colour"])
        self.assertIsNone(state["chat"][1]["colour"])
        # Talking is not an action on the game.
        self.assertEqual(self.game.match_state, before)

    async def test_a_message_is_handed_over_as_text_it_was_written_in(self) -> None:
        response = await self.say("<b>{team:orange}</b> **not bold**")
        said = (await response.json())["chat"][0]["text"]

        self.assertEqual(said, "<b>{team:orange}</b> **not bold**")

    async def test_nothing_said_is_refused(self) -> None:
        response = await self.say("   ")

        self.assertEqual(response.status, 400)

    async def test_the_poll_hands_over_only_what_is_new(self) -> None:
        await self.say("one")
        await self.say("two")
        response = await self.client.get(
            f"/api/game/{self.game.game_id}", params={"chat_since": "1"},
        )
        state = await response.json()

        self.assertEqual([one["text"] for one in state["chat"]], ["two"])
        self.assertEqual(state["chat_latest"], 2)

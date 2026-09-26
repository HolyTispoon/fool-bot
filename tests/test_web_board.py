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

from d12ball.components import TeamSide, Zone
from d12ball.prompts import pending_prompt
from d12ball.render import shooting_range_bands, space_code
from gamelocks import GameLocks
from webapp.board import FAN_MEEPLE_WIDTH, FAN_STEPS, ZONES, board_layout
from webapp.present import STYLES, Viewer, controls_for
from webapp.server import WebApp
from prompt_fixtures import CASES, ENGINE
from test_web_app import as_coach, case, service_over

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


class FanTests(unittest.TestCase):
    """
    A crowded space, as `board.py` lays it out for the page: who is in
    front, which way the fan leans, how far each piece steps, and the
    order the names are listed in -- read off the layout, never off
    the HTML, so the page can only place what it is handed.
    """

    def setUp(self) -> None:
        ENGINE.rng.seed(11)
        self.fixture = case("kickoff")
        self.match = self.fixture.match

    def crowd(self, side: TeamSide, count: int, *, ball: bool) -> dict:
        """`count` of `side`'s fielded players on the first midfield
        space, the ball there with them when `ball` is set, and the
        space as the page is handed it."""
        board = self.match.board
        players = list(self.match.setup_for_side(side).field_players)[:count]
        for zone in Zone:
            for occupants in board.spaces[zone]:
                for player in players:
                    if player in occupants:
                        occupants.remove(player)
        # Whoever else stood there steps off, so the space holds
        # exactly the fan asked for.
        target = board.spaces[Zone.MIDFIELD][0]
        board.spaces[Zone.MIDFIELD][-1].extend(target)
        target[:] = players
        if ball:
            self.match.ball.zone = Zone.MIDFIELD
            self.match.ball.space_index = 0
            self.match.ball.possession = side
        layout = board_layout(
            ENGINE,
            self.fixture.game,
            self.match,
            card_url=CARD_URL,
            goal_url=GOAL_URL,
        )
        first = sum(
            len(self.match.board.spaces[zone]) for zone in ZONES[:1]
        )
        return layout["spaces"][first]

    def test_each_count_steps_by_the_design_s_numbers(self) -> None:
        for count in (2, 3, 4):
            for side in TeamSide:
                with self.subTest(count=count, side=side.value):
                    self.setUp()
                    drawn = self.crowd(side, count, ball=False)["fans"][side.value]
                    across, down = FAN_STEPS[count]
                    self.assertEqual(drawn["step"], [across, down])
                    xs = [piece["x"] for piece in drawn["pieces"]]
                    ys = [piece["y"] for piece in drawn["pieces"]]
                    self.assertEqual(
                        sorted({abs(b - a) for a, b in zip(xs, xs[1:])}),
                        [across],
                    )
                    self.assertEqual(
                        sorted({abs(b - a) for a, b in zip(ys, ys[1:])}),
                        [down],
                    )
                    self.assertEqual(
                        drawn["width"], (count - 1) * across + FAN_MEEPLE_WIDTH,
                    )

    def test_home_leans_up_and_right_and_the_visitors_down_and_left(self) -> None:
        for side, rightward, downward in (
            (TeamSide.HOME, True, False),
            (TeamSide.VISITING, False, True),
        ):
            with self.subTest(side.value):
                self.setUp()
                pieces = self.crowd(side, 3, ball=False)["fans"][side.value]["pieces"]
                back, front = pieces[0], pieces[-1]
                self.assertEqual(front["x"] > back["x"], rightward)
                self.assertEqual(front["y"] > back["y"], downward)
                self.assertTrue(front["front"])
                self.assertEqual(
                    [piece["front"] for piece in pieces].count(True), 1,
                )

    def test_the_ball_s_holder_is_the_front_piece(self) -> None:
        for side in TeamSide:
            with self.subTest(side.value):
                self.setUp()
                players = list(self.match.setup_for_side(side).field_players)[:4]
                # The first of them on the board, which is the back of
                # the fan unless the ball says otherwise.
                self.match.ball_carrier_id = players[0]
                space = self.crowd(side, 4, ball=True)
                pieces = space["fans"][side.value]["pieces"]
                self.assertEqual(space["ball"]["holder"], players[0])
                self.assertEqual(pieces[-1]["id"], players[0])
                self.assertTrue(pieces[-1]["front"])
                self.assertEqual(
                    [piece["id"] for piece in pieces[:-1]], players[1:],
                )

    def test_the_names_run_front_first(self) -> None:
        drawn = self.crowd(TeamSide.HOME, 4, ball=False)["fans"]["home"]
        self.assertEqual(
            drawn["names"],
            [piece["id"] for piece in reversed(drawn["pieces"])],
        )

    def test_a_fan_of_more_than_four_is_no_wider_than_four(self) -> None:
        home = self.crowd(TeamSide.HOME, 4, ball=False)["fans"]["home"]
        self.setUp()
        more = self.crowd(TeamSide.HOME, 5, ball=False)["fans"]["home"]
        if len(more["pieces"]) < 5:
            self.skipTest("the fixture fields fewer than five")
        self.assertAlmostEqual(more["width"], home["width"])

    def test_a_loose_ball_names_no_holder(self) -> None:
        midfield = self.match.board.spaces[Zone.MIDFIELD]
        index = len(midfield) - 1
        midfield[0].extend(midfield[index])
        midfield[index].clear()
        self.match.ball.zone = Zone.MIDFIELD
        self.match.ball.space_index = index
        layout = board_layout(
            ENGINE, self.fixture.game, self.match,
            card_url=CARD_URL, goal_url=GOAL_URL,
        )
        ball = next(space["ball"] for space in layout["spaces"] if space["ball"])
        self.assertIsNone(ball["holder"])


class FieldTests(unittest.TestCase):
    """What the field around the meeples is handed."""

    def setUp(self) -> None:
        ENGINE.rng.seed(11)
        self.fixture, self.layout = layout_for("kickoff")
        self.match = self.fixture.match

    def test_the_kickoff_space_is_the_model_s(self) -> None:
        marked = [
            (space["zone"], index)
            for index, space in enumerate(self.layout["spaces"])
            if space["kickoff"]
        ]
        flat = self.match.board.flat_index(
            Zone.MIDFIELD, self.match.kickoff_space_for(TeamSide.HOME),
        )
        self.assertEqual(marked, [(Zone.MIDFIELD.value, flat)])

    def test_the_end_zones_are_tinted_for_the_side_defending_them(self) -> None:
        colours = {
            space["zone"]: space["tint"] for space in self.layout["spaces"]
        }
        self.assertIsNone(colours[Zone.MIDFIELD.value])
        self.assertEqual(
            colours[Zone.HOME_GOAL.value],
            self.layout["jumbotron"]["home"]["colour"],
        )
        self.assertEqual(
            colours[Zone.VISITORS_GOAL.value],
            self.layout["jumbotron"]["visiting"]["colour"],
        )

    def test_a_band_is_lit_only_where_the_model_says_the_ball_may_shoot(
        self,
    ) -> None:
        for index in range(self.match.board.layout.board_size):
            zone, space_index = self.match.board.position_at_flat_index(index)
            self.match.ball.zone = zone
            self.match.ball.space_index = space_index
            layout = board_layout(
                ENGINE, self.fixture.game, self.match,
                card_url=CARD_URL, goal_url=GOAL_URL,
            )
            with self.subTest(space=index):
                lit = [band["side"] for band in layout["bands"] if band["lit"]]
                if self.match.can_attempt_score():
                    self.assertEqual(lit, [self.match.ball.possession.value])
                else:
                    self.assertEqual(lit, [])

    def test_a_piece_carries_its_marks_as_the_emoji(self) -> None:
        card_id = self.match.home.zones[Zone.MIDFIELD][0]
        self.match.exhaustion[card_id] = 2
        self.match.injured.add(card_id)
        layout = board_layout(
            ENGINE, self.fixture.game, self.match,
            card_url=CARD_URL, goal_url=GOAL_URL,
        )
        piece = next(
            one
            for space in layout["spaces"]
            for one in space["home"]
            if one["id"] == card_id
        )
        self.assertEqual(piece["exhaustion"], {"count": 2, "emoji": "exhaust"})
        self.assertEqual(piece["condition"], "injured")


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
            headers=as_coach(self.game.player_1_id),
        )
        state = await response.json()

        self.assertEqual(
            len(state["board"]["layout"]["spaces"]),
            self.match.board.layout.board_size,
        )
        self.assertTrue(state["game"]["title"].startswith("PBW"))

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

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
- **The answer is the thing on the board**: every control names an
  object the board draws -- a meeple on the field or a bench, a space,
  the ball, a goal, a tile -- or one the question box draws, or is the
  one neutral control, and none carries a colour.
"""

from __future__ import annotations

import unittest

from aiohttp.test_utils import TestClient, TestServer

from d12ball.components import MatchPeriod, PlayerRole, TeamSide, Zone
from d12ball.prompts import PromptKind, pending_prompt
from d12ball.render import shooting_range_bands, space_code
from gamelocks import GameLocks
from webapp.board import (
    FAN_MEEPLE_WIDTH,
    FAN_STEPS,
    NARROW_FAN_STEPS,
    NARROW_MEEPLE_WIDTH,
    ZONES,
    board_layout,
)
from webapp.present import CONTROLS, NEUTRAL, Asked, Viewer, controls_for
from webapp.server import WebApp
from prompt_fixtures import CASES, ENGINE
from roster import benched, field_players
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

    def test_the_narrow_fan_is_the_same_fan_at_the_phone_s_steps(self) -> None:
        """A phone held upright draws each space's `narrow_fans`: the
        same pieces in the same order, front and names, leaning the
        same way, at `NARROW_FAN_STEPS` -- the page lays out neither."""
        for count in (1, 2, 3, 4):
            for side in TeamSide:
                with self.subTest(count=count, side=side.value):
                    self.setUp()
                    space = self.crowd(side, count, ball=False)
                    wide = space["fans"][side.value]
                    narrow = space["narrow_fans"][side.value]
                    strip = lambda fan: [
                        (piece["id"], piece["front"]) for piece in fan["pieces"]
                    ]
                    self.assertEqual(strip(narrow), strip(wide))
                    self.assertEqual(narrow["names"], wide["names"])
                    self.assertEqual(narrow["step"], list(NARROW_FAN_STEPS[count]))
                    if count > 1:
                        for fan in (wide, narrow):
                            back, front = fan["pieces"][0], fan["pieces"][-1]
                            self.assertEqual(
                                front["x"] > back["x"], side is TeamSide.HOME,
                            )

    def test_a_narrow_four_fan_fits_a_phone_s_space(self) -> None:
        """No meeple leaves its space on a phone either: a four-fan is
        no wider than a piece and a few pixels, and no taller than the
        lane `app.css` gives the narrow field (78px, half of a 180px
        space less its number)."""
        space = self.crowd(TeamSide.HOME, 4, ball=False)
        geometry = board_layout(
            ENGINE, self.fixture.game, self.match,
            card_url=CARD_URL, goal_url=GOAL_URL,
        )["narrow_meeple"]
        self.assertEqual(geometry["width"], NARROW_MEEPLE_WIDTH)
        tall = NARROW_MEEPLE_WIDTH * geometry["box"][3] / geometry["box"][2]
        drawn = space["narrow_fans"]["home"]
        self.assertLessEqual(drawn["width"], NARROW_MEEPLE_WIDTH + 4)
        self.assertLessEqual(max(p["y"] for p in drawn["pieces"]) + tall, 78)

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


class JumbotronTests(unittest.TestCase):
    """
    The bar across the top of the play area (step 2 of
    docs/web-app-redesign.md): every value it shows is the match's,
    and a time-out tile is lit only where the turn put to this viewer
    carries the time out.
    """

    def setUp(self) -> None:
        ENGINE.rng.seed(11)

    def bar(self, fixture) -> dict:
        return board_layout(
            ENGINE, fixture.game, fixture.match,
            card_url=CARD_URL, goal_url=GOAL_URL,
        )["jumbotron"]

    def test_at_kickoff_the_clock_is_empty_and_the_kicking_side_has_the_ball(
        self,
    ) -> None:
        fixture = case("kickoff")
        bar = self.bar(fixture)

        self.assertEqual((bar["minute"], bar["half"]), ("00", "1st half"))
        self.assertEqual(
            bar["track"], {"length": 30, "halftime": 15, "filled": 0},
        )
        self.assertFalse(bar["last_possession"])
        self.assertEqual(bar["note"], "")
        for side in ("home", "visiting"):
            with self.subTest(side):
                self.assertEqual(
                    bar[side]["possession"],
                    fixture.match.ball.possession == TeamSide(side),
                )
        self.assertEqual(bar["home"]["time_out"], "held")
        self.assertEqual(bar["visiting"]["time_out"], "held")

    def test_mid_half_the_track_fills_to_the_minute_and_the_ball_is_marked(
        self,
    ) -> None:
        fixture = case("plain turn")
        fixture.match.scoreboard.time = 7

        bar = self.bar(fixture)

        self.assertEqual(bar["minute"], "07")
        self.assertEqual(bar["track"]["filled"], 7)
        side = fixture.match.ball.possession.value
        other = "visiting" if side == "home" else "home"
        self.assertTrue(bar[side]["possession"])
        self.assertFalse(bar[other]["possession"])

    def test_last_possession_is_the_scoreboard_s_flag(self) -> None:
        fixture = case("plain turn")
        board = fixture.match.scoreboard
        board.time, board.last_possession = 16, True

        bar = self.bar(fixture)

        self.assertTrue(bar["last_possession"])
        self.assertEqual(bar["track"]["filled"], 16)

    def test_a_spent_time_out_is_the_half_s_own_count(self) -> None:
        # Home called it: its window opened declared, which charged the
        # half's time out; the visitors still hold theirs.
        bar = self.bar(case("time-out window"))

        self.assertEqual(bar["home"]["time_out"], "spent")
        self.assertEqual(bar["visiting"]["time_out"], "held")

    def test_the_note_names_halftime_the_shootout_and_the_result(self) -> None:
        self.assertEqual(self.bar(case("halftime coaching"))["note"], "Halftime")
        self.assertEqual(self.bar(case("shootout order"))["note"], "Shootout")
        self.assertEqual(
            self.bar(case("full-time coaching"))["note"], "Full time",
        )

        over = case("game over")
        board = over.match.scoreboard
        board.home_score, board.visiting_score = 2, 1
        self.assertEqual(self.bar(over)["note"], "Final \u00b7 2 : 1")

        # A shootout's goals are on the scoreboard as well; the note
        # reports the whistle and the shootout apart, as the full-time
        # summary does.
        board.home_score, board.visiting_score = 3, 2
        over.match.shootout_goals = {"home": 1, "visiting": 0}
        self.assertEqual(
            self.bar(over)["note"], "Final \u00b7 2 : 2, shootout 1 : 0",
        )

        over.game.abandoned = True
        self.assertEqual(self.bar(over)["note"], "Abandoned")

    def test_the_second_half_is_named_and_the_track_stops_at_its_end(self) -> None:
        fixture = case("plain turn")
        board = fixture.match.scoreboard
        board.period, board.time = MatchPeriod.SECOND_HALF, 33

        bar = self.bar(fixture)

        self.assertEqual(bar["half"], "2nd half")
        self.assertEqual(bar["track"]["filled"], 30)

    def tile(self, fixture, player_number):
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        return [
            control
            for group in controls_for(
                ENGINE, fixture.game, fixture.match, prompt,
                Viewer(player_number),
            )
            for control in group["controls"]
            if (control.get("place") or {}).get("at") == "time_out_tile"
        ]

    def test_the_tile_is_lit_for_the_coach_the_turn_is_put_to_only(
        self,
    ) -> None:
        fixture = case("plain turn")
        side = fixture.match.ball.possession
        mine = ENGINE.side_player_number(fixture.game, side)
        theirs = 2 if mine == 1 else 1

        placed = self.tile(fixture, mine)

        self.assertEqual(len(placed), 1)
        self.assertEqual(
            placed[0]["place"], {"at": "time_out_tile", "side": side.value},
        )
        self.assertEqual(placed[0]["action"]["choice"], "time_out")
        self.assertEqual(self.tile(fixture, theirs), [])

    def test_no_tile_is_lit_where_the_turn_offers_no_time_out(self) -> None:
        fixture = case("plain turn")
        fixture.match.scoreboard.last_possession = True
        mine = ENGINE.side_player_number(
            fixture.game, fixture.match.ball.possession,
        )

        self.assertEqual(self.tile(fixture, mine), [])


class ObjectTests(unittest.TestCase):
    """What a control lights, and that nothing is a coloured button
    (step 4 of docs/web-app-redesign.md)."""

    #: The objects the question box draws rather than the board.
    IN_THE_BOX = {"die", "face", "whistle", "note", "rematch", "card", "formation"}

    def setUp(self) -> None:
        ENGINE.rng.seed(11)

    def controls(self):
        for entry in CASES:
            if not entry.asked or entry.ai:
                continue
            fixture = entry.build()
            prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
            for player_number in (1, 2):
                for group in controls_for(
                    ENGINE, fixture.game, fixture.match, prompt,
                    Viewer(player_number),
                ):
                    for control in group["controls"]:
                        yield entry.name, fixture, control

    def test_every_control_names_an_object_or_is_neutral(self) -> None:
        places = set()
        for name, _, control in self.controls():
            with self.subTest(name, label=control["label"]):
                if control.get("place"):
                    places.add(control["place"]["at"])
                    self.assertIsNone(control["style"])
                    self.assertTrue(control["place"]["at"])
                else:
                    self.assertEqual(control["style"], NEUTRAL)
        # Every object the prompt table names is lit by some fixture.
        self.assertTrue({
            "player", "space", "ball", "goal", "die", "face", "whistle",
            "note", "rematch", "card", "time_out_tile", "bench", "formation",
        } <= places, places)

    def test_no_control_carries_a_colour(self) -> None:
        for name, _, control in self.controls():
            with self.subTest(name, label=control["label"]):
                self.assertIn(control["style"], (None, NEUTRAL))
                self.assertNotIn(
                    control["style"],
                    ("primary", "secondary", "success", "danger"),
                )

    def test_every_lit_object_is_one_the_board_draws(self) -> None:
        """A meeple lit is on the field or a bench, a space lit is one
        of the layout's, and a goal or a tile belongs to a side."""
        for name, fixture, control in self.controls():
            if not control.get("place"):
                continue
            first = (control["first"],) if control.get("first") else ()
            for place in (control["place"], *control.get("also", ()), *first):
                if place["at"] in self.IN_THE_BOX | {"ball"}:
                    continue
                self.assert_drawn(name, fixture, place)

    def assert_drawn(self, name, fixture, place) -> None:
        """One lit object, against the layout the page draws."""
        with self.subTest(name, place=place):
            layout = board_layout(
                ENGINE, fixture.game, fixture.match,
                card_url=CARD_URL, goal_url=GOAL_URL,
            )
            if place["at"] == "player":
                drawn = {
                    piece["id"]
                    for space in layout["spaces"]
                    for side in ("home", "visiting")
                    for piece in space[side]
                } | {
                    card["id"]
                    for board in layout["team_boards"]
                    for card in board["bench"] + board["back_bench"]
                }
                self.assertIn(place["id"], drawn)
            elif place["at"] == "space":
                self.assertIn(
                    (place["zone"], place["space_index"]),
                    {
                        (space["zone"], space["index"])
                        for space in layout["spaces"]
                    },
                )
            else:
                self.assertIn(place["side"], ("home", "visiting"))

    def test_a_maneuver_card_is_the_card_it_plays(self) -> None:
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
                        control["place"],
                        {"at": "card", "key": control["card"]["key"], "side": side},
                    )
        self.assertEqual(seen, {"offense", "defense"})

    def test_a_distance_lights_the_space_the_prompt_says_it_lands_on(
        self,
    ) -> None:
        fixture = case("high pass")
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        options = prompt.options
        placed = {
            control["action"]["arguments"]["distance"]: control["place"]
            for number in (1, 2)
            for group in controls_for(
                ENGINE, fixture.game, fixture.match, prompt, Viewer(number),
            )
            for control in group["controls"]
            if not control["action"]["arguments"].get("runner")
        }
        self.assertTrue(placed)
        for distance, place in placed.items():
            zone, index = options.landing(distance)
            self.assertEqual(
                place,
                {"at": "space", "zone": zone.value, "space_index": index},
            )

    def built(self, name: str, kind, options, fixture=None):
        """A builder handed options the fixtures never reach, the way
        the wire writes them."""
        fixture = fixture or case(name)
        if callable(options):
            options = options(fixture)
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        wire = {**prompt.to_dict(), "kind": kind.value, "options": options}
        side = fixture.match.ball.possession
        asked = Asked(ENGINE, fixture.game, fixture.match, wire, Viewer(1), (side,))
        return fixture, [
            control
            for group in CONTROLS[kind](asked)
            if group is not None
            for control in group["controls"]
        ]

    def test_a_pass_with_nowhere_to_go_is_put_out_past_the_far_end(self) -> None:
        fixture, controls = self.built(
            "high pass",
            PromptKind.SETUP_PASS_CHOICE,
            {
                "shape": "distance", "distances": [], "railed": None,
                "may_pass_out": True, "runner_id": None,
                "runner_distances": [], "landings": [],
            },
        )
        side = fixture.match.ball.possession
        far = TeamSide.VISITING if side is TeamSide.HOME else TeamSide.HOME
        self.assertEqual(len(controls), 1)
        self.assertEqual(
            controls[0]["place"], {"at": "out_of_play", "side": far.value},
        )
        self.assertEqual(controls[0]["action"]["arguments"], {})

    def test_two_receivers_on_one_space_light_the_space_and_ask_which(
        self,
    ) -> None:
        def two_on_one(fixture):
            receivers = field_players(
                fixture.match, fixture.match.ball.possession,
            )[:2]
            return {
                "shape": "low_pass",
                "passes": [{"distance": 1, "receiver_ids": list(receivers)}],
            }

        fixture, controls = self.built(
            "low pass", PromptKind.LOW_PASS_CHOICE, two_on_one,
        )
        receivers = field_players(
            fixture.match, fixture.match.ball.possession,
        )[:2]
        zone, index = fixture.match.ball_destination(
            fixture.match.ball.possession, 1,
        )
        (control,) = controls
        self.assertEqual(control["type"], "chooser")
        self.assertEqual(
            control["place"],
            {"at": "space", "zone": zone.value, "space_index": index},
        )
        self.assertEqual(
            [one["value"] for one in control["fields"][0]["choices"]],
            list(receivers),
        )

    def test_a_pickup_says_what_it_charges_each_candidate(self) -> None:
        fixture = case("ball recovery")
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        costs = dict(zip(prompt.options.player_ids, prompt.options.costs))
        chips = {
            control["place"]["id"]: control["cost"]
            for number in (1, 2)
            for group in controls_for(
                ENGINE, fixture.game, fixture.match, prompt, Viewer(number),
            )
            for control in group["controls"]
        }
        self.assertEqual(set(chips), set(costs))
        for player_id, cost in chips.items():
            self.assertEqual(cost["count"], costs[player_id])

    def lit_by(self, name: str, choice: str):
        fixture = case(name)
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        (control,) = [
            control
            for number in (1, 2)
            for group in controls_for(
                ENGINE, fixture.game, fixture.match, prompt, Viewer(number),
            )
            for control in group["controls"]
            if control["action"]["choice"] == choice
        ]
        return fixture, prompt, control

    def test_a_set_up_shot_lights_the_goal_and_the_shooter(self) -> None:
        # The author, 2026-09-26: "Setup attempt should light up the
        # goal and the shooter."
        fixture, prompt, control = self.lit_by("set-up attempt", "take")
        side = fixture.match.ball.possession
        other = TeamSide.VISITING if side is TeamSide.HOME else TeamSide.HOME
        self.assertEqual(control["place"], {"at": "goal", "side": other.value})
        self.assertEqual(
            control["also"], [{"at": "player", "id": prompt.player_id}],
        )

    def test_a_coaching_offer_lights_the_bench(self) -> None:
        # The author, 2026-09-26: "Coaching should light up the bench."
        fixture, prompt, control = self.lit_by("coaching offer", "declare")
        self.assertEqual(
            control["place"],
            {"at": "bench", "side": TeamSide(prompt.side).value},
        )
        _, _, decline = self.lit_by("coaching offer", "decline")
        self.assertEqual(decline["style"], NEUTRAL)

    def test_the_shot_lights_the_goal_the_side_attacks(self) -> None:
        fixture = case("plain turn")
        side = fixture.match.ball.possession
        mine = ENGINE.side_player_number(fixture.game, side)
        other = (
            TeamSide.VISITING if side is TeamSide.HOME else TeamSide.HOME
        )
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        by_choice = {
            control["action"]["choice"]: control["place"]
            for group in controls_for(
                ENGINE, fixture.game, fixture.match, prompt, Viewer(mine),
            )
            for control in group["controls"]
        }
        self.assertEqual(by_choice["maneuver"], {"at": "ball"})
        if "shoot" in by_choice:
            self.assertEqual(
                by_choice["shoot"], {"at": "goal", "side": other.value},
            )


class SidelineTests(unittest.TestCase):
    """
    The sideline under the field (step 6 of docs/web-app-redesign.md):
    each side's bench and back bench, the record's own two rows, with
    every benched player the meeple the field draws -- and the
    Coaching Choice's moves as the two things each is made of.
    """

    def setUp(self) -> None:
        ENGINE.rng.seed(11)

    def test_a_benched_player_is_the_piece_the_field_draws(self) -> None:
        fixture, layout = layout_for("coaching hub")
        field = {
            piece["id"]: piece
            for space in layout["spaces"]
            for side in ("home", "visiting")
            for piece in space[side]
        }
        some = next(iter(field.values()))
        for board in layout["team_boards"]:
            setup = fixture.match.setup_for_side(TeamSide(board["side"]))
            self.assertEqual(
                [entry["id"] for entry in board["bench"]],
                list(setup.team_board.bench),
            )
            for entry in board["bench"] + board["back_bench"]:
                with self.subTest(entry["id"]):
                    self.assertEqual(entry["meeple"]["id"], entry["id"])
                    self.assertEqual(set(entry["meeple"]), set(some))
                    self.assertNotIn(entry["id"], field)

    def test_an_injured_player_on_the_back_bench_carries_the_mark(self) -> None:
        fixture = case("coaching hub")
        match = fixture.match
        hurt = benched(match, PlayerRole.STRIKER)
        match.home.team_board.bench.remove(hurt)
        match.home.team_board.back_bench.append(hurt)
        match.injured.add(hurt)
        match.exhaustion[hurt] = 2
        layout = board_layout(
            ENGINE, fixture.game, match, card_url=CARD_URL, goal_url=GOAL_URL,
        )
        home = next(one for one in layout["team_boards"] if one["side"] == "home")
        self.assertNotIn(hurt, [entry["id"] for entry in home["bench"]])
        (entry,) = [one for one in home["back_bench"] if one["id"] == hurt]
        self.assertTrue(entry["injured"])
        self.assertEqual(entry["meeple"]["condition"], "injured")
        self.assertEqual(
            entry["meeple"]["exhaustion"], {"count": 2, "emoji": "exhaust"},
        )

    def hub(self, name="coaching hub"):
        fixture = case(name)
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        side = TeamSide(prompt.side)
        controls = [
            control
            for group in controls_for(
                ENGINE, fixture.game, fixture.match, prompt, Viewer(1),
            )
            for control in group["controls"]
        ]
        return fixture, prompt, side, controls

    def test_a_substitute_is_a_bench_meeple_put_on_the_player_it_replaces(
        self,
    ) -> None:
        fixture, prompt, side, controls = self.hub()
        options = prompt.options
        pairs = {
            (control["first"]["id"], control["place"]["id"])
            for control in controls
            if control["action"]["choice"] == "substitute"
        }
        self.assertEqual(
            pairs,
            {
                (incoming, outgoing)
                for incoming in options.incoming_ids
                for outgoing in options.outgoing_ids
            },
        )
        for control in controls:
            if control["action"]["choice"] != "substitute":
                continue
            arguments = control["action"]["arguments"]
            self.assertEqual(control["first"]["id"], arguments["incoming_player_id"])
            self.assertEqual(control["place"]["id"], arguments["outgoing_player_id"])
            self.assertIsNone(control["first_chip"])

    def test_a_zone_change_and_a_move_start_from_a_fielded_player(self) -> None:
        fixture, prompt, side, controls = self.hub()
        setup = fixture.match.setup_for_side(side)
        swaps = {
            (swap.player_id, other)
            for swap in prompt.options.swaps
            for other in swap.partner_ids
        }
        seen = set()
        for control in controls:
            choice = control["action"]["choice"]
            arguments = control["action"]["arguments"]
            if choice == "swap":
                seen.add((control["first"]["id"], control["place"]["id"]))
                self.assertEqual(control["first"]["id"], arguments["player_id"])
                self.assertEqual(control["place"]["id"], arguments["other_player_id"])
            elif choice == "reposition":
                player = control["first"]["id"]
                self.assertEqual(player, arguments["player_id"])
                self.assertEqual(
                    control["place"]["zone"], setup.assigned_zone(player).value,
                )
                self.assertEqual(
                    control["place"]["space_index"], arguments["space_index"],
                )
        self.assertEqual(seen, swaps)

    def test_a_formation_tile_draws_the_ruleset_s_counts(self) -> None:
        fixture, prompt, side, controls = self.hub()
        tiles = [
            control for control in controls
            if control["action"]["choice"] == "formation"
        ]
        self.assertEqual(
            [tile["label"] for tile in tiles],
            [formation.value for formation in prompt.options.formations],
        )
        for tile in tiles:
            shape = ENGINE.formation_shape(
                fixture.match, tile["action"]["arguments"]["formation"],
            )
            self.assertEqual(
                tile["shape"],
                [shape.own_goal, shape.midfield, shape.opponent_goal],
            )
            self.assertEqual(
                tile["disabled"],
                tile["label"] == prompt.options.current_formation.value,
            )

    def test_the_window_before_the_shootout_moves_nobody(self) -> None:
        """Full time's window is a substitution and nothing else
        (`offers_positioning`), so nothing on the field starts a move."""
        fixture, prompt, side, controls = self.hub("full-time coaching")
        self.assertEqual(
            {control["action"]["choice"] for control in controls},
            {"substitute", "done"},
        )


class TeamsTabTests(unittest.TestCase):
    """
    The Teams tab (step 10 of docs/web-app-redesign.md): both rosters
    as rows, the field, the bench and the back bench as the record
    holds them, and every number the one `board.py` hands the field
    and the sideline -- the tab adds nothing to a number.
    """

    def setUp(self) -> None:
        ENGINE.rng.seed(11)

    def test_the_rows_are_the_record_s_three_lists(self) -> None:
        fixture, layout = layout_for("coaching hub")
        for roster in layout["rosters"]:
            setup = fixture.match.setup_for_side(TeamSide(roster["side"]))
            self.assertEqual(
                [row["id"] for row in roster["rows"]],
                [
                    *setup.field_players,
                    *setup.team_board.bench,
                    *setup.team_board.back_bench,
                ],
            )
            self.assertEqual(
                [row["where"] for row in roster["rows"]][len(setup.field_players):],
                ["bench"] * len(setup.team_board.bench)
                + ["back bench"] * len(setup.team_board.back_bench),
            )

    def test_the_numbers_are_board_py_s(self) -> None:
        fixture, layout = layout_for("kickoff")
        cards = {
            card["id"]: card
            for zone in layout["zones"]
            for side in ("home", "visiting")
            for card in zone[side]
        }
        cards.update(
            (entry["id"], entry)
            for board in layout["team_boards"]
            for entry in board["bench"] + board["back_bench"]
        )
        codes = {
            piece["id"]: space["code"]
            for space in layout["spaces"]
            for side in ("home", "visiting")
            for piece in space[side]
        }
        for roster in layout["rosters"]:
            for row in roster["rows"]:
                with self.subTest(row["id"]):
                    card = cards[row["id"]]
                    self.assertEqual(
                        (row["offense"], row["defense"], row["exhaustion"]),
                        (card["offense"], card["defense"], card["exhaustion"]),
                    )
                    if row["id"] in codes:
                        self.assertEqual(row["where"], codes[row["id"]])

    def test_an_injured_player_s_row_and_the_ball(self) -> None:
        fixture = case("coaching hub")
        match = fixture.match
        hurt = benched(match, PlayerRole.STRIKER)
        match.home.team_board.bench.remove(hurt)
        match.home.team_board.back_bench.append(hurt)
        match.injured.add(hurt)
        match.exhaustion[hurt] = 2
        layout = board_layout(
            ENGINE, fixture.game, match, card_url=CARD_URL, goal_url=GOAL_URL,
        )
        home = next(one for one in layout["rosters"] if one["side"] == "home")
        (row,) = [one for one in home["rows"] if one["id"] == hurt]
        self.assertEqual(row["where"], "back bench")
        self.assertEqual(row["marks"]["condition"], "injured")
        self.assertEqual(
            row["marks"]["exhaustion"], {"count": 2, "emoji": "exhaust"},
        )
        holders = [
            space["ball"]["holder"]
            for space in layout["spaces"]
            if space["ball"] and space["ball"]["holder"]
        ]
        with_ball = [
            row["id"]
            for roster in layout["rosters"]
            for row in roster["rows"]
            if row["ball"]
        ]
        self.assertEqual(with_ball, holders)


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

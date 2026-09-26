"""
The reading room over HTTP: the rules, the two rulebooks and the
player aids -- step 11 of docs/web-app-next.md ("The rules and the
player aids" in docs/design/web-app.md).

Nothing printed is tested (CLAUDE.md), so neither a picture nor a book
is looked at here: every renderer is patched to hand back fixed bytes,
and what is watched is the routes and what the page is told --

- **every route answers**, with its content type, and to anybody: an
  observer, and nobody at all, may open every aid;
- **which aids a room gets is the model's**: the room's state carries
  `maneuver_reference_tier`, `species_abilities_apply` and
  `personal_abilities_apply` as the engine answers them, and they
  change with the game's mode;
- **the rules are headed with the Charter's numbers**: every heading
  the Charter build numbers is a `RulesSection` with that number, which
  is the slug agreement between `rules_doc` and `rulebooks`;
- **a book is set once and served inline**, and set again when its
  source changes.
"""

from __future__ import annotations

import unittest
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

from d12ball import rulebooks
from d12ball.components import MANEUVER_TIER_BASIC, MANEUVER_TIER_GAMBIT
from d12ball.game import GameMode
from d12ball.rules_doc import load_rules_document
from gamelocks import GameLocks
from gamesaves.d12ball.service import GameService
from prompt_fixtures import ENGINE
from test_web_app import as_coach, case
from webapp import aids
from webapp.rooms import Rooms
from webapp.server import WebApp


WATCHER = 303
PNG = b"\x89PNG not a picture"
PDF = b"%PDF-1.4 not a book"


class Harness(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        ENGINE.rng.seed(7)
        self.games = {}
        self.service = GameService(ENGINE, self.games, save=lambda games: None)
        self.web = WebApp(self.service, GameLocks(), rooms=Rooms())
        self.web.watch()
        self.client = TestClient(TestServer(self.web.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.addAsyncCleanup(self.web.stop)
        # No picture is drawn and no book is set: the routes are the
        # thing tested, never what they serve.
        for target in (
            "webapp.aids.maneuver_reference_png",
            "webapp.aids.role_reference_png",
            "webapp.aids.species_face_png",
            "webapp.pictures.player_card_png",
        ):
            patcher = mock.patch(target, return_value=PNG)
            patcher.start()
            self.addCleanup(patcher.stop)

    def file(self, fixture):
        game = fixture.game
        game.guild_id = None
        game.channel_id = None
        game.match_state = fixture.match.to_dict()
        self.games[game.game_id] = game
        return game

    async def get(self, path: str, coach_id=None):
        headers = {} if coach_id is None else as_coach(coach_id)
        return await self.client.get(path, headers=headers)

    async def state(self, game, coach_id) -> dict:
        response = await self.get(f"/api/game/{game.game_id}", coach_id)
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()


class RouteTests(Harness):
    async def answers(self, path: str, content_type: str, coach_id=None):
        response = await self.get(path, coach_id)
        if response.status != 200:
            self.fail(f"{path}: {response.status} {await response.text()}")
        self.assertEqual(response.content_type, content_type, path)
        return response

    async def test_every_aid_the_front_door_offers_answers(self) -> None:
        response = await self.answers("/api/aids", "application/json")
        offered = await response.json()
        self.assertEqual(
            [one["tier"] for one in offered["maneuvers"]],
            [MANEUVER_TIER_BASIC, MANEUVER_TIER_GAMBIT],
        )
        self.assertEqual(len(offered["species"]), aids.SPECIES_FACE_COUNT)
        urls = [
            *(one["url"] for one in offered["maneuvers"]),
            offered["roles"],
            *(one["url"] for one in offered["species"]),
        ]
        for team in offered["teams"]:
            # Both faces offered for every team, with no game to ask.
            self.assertEqual(
                [face["face"] for face in team["faces"]],
                [aids.FACE_FRONT, aids.FACE_ADVANCED],
            )
            for face in team["faces"]:
                urls.extend(face["cards"])
        self.assertEqual(
            {team["key"] for team in offered["teams"]},
            {team.value for team in ENGINE.player_catalog.teams},
        )
        for url in urls:
            with self.subTest(url):
                response = await self.answers(url, "image/png")
                self.assertEqual(await response.read(), PNG)

    async def test_an_aid_nobody_draws_is_not_found(self) -> None:
        team = next(iter(ENGINE.player_catalog.teams))
        player = ENGINE.player_catalog.teams[team].players[0].player_id
        for path in (
            "/aids/maneuvers/nonsense.png",
            "/aids/species/0.png",
            f"/aids/species/{aids.SPECIES_FACE_COUNT + 1}.png",
            "/aids/team/nonsense/x.png",
            f"/aids/team/{team.value}/nobody.png",
            "/books/plan.pdf",
            "/rules/figures/nothing.png",
        ):
            with self.subTest(path):
                self.assertEqual((await self.get(path)).status, 404)
        bad_face = await self.get(
            f"/aids/team/{team.value}/{player}.png?face=back",
        )
        self.assertEqual(bad_face.status, 400)

    async def test_the_rules_page_and_its_search(self) -> None:
        response = await self.answers("/rules", "text/html")
        page = await response.text()
        document = load_rules_document()
        self.assertIn(document.sections[0].slug, page)
        found = await (await self.answers(
            "/api/rules?q=time%20out", "application/json",
        )).json()
        # The answer /d12ball rules_search offers, with its numbers.
        self.assertEqual(
            [one["slug"] for one in found["sections"]],
            [one.slug for one in document.search("time out")],
        )
        self.assertTrue(any(one["number"] for one in found["sections"]))

    async def test_the_rules_figure_is_served(self) -> None:
        names = sorted(aids.figure_names())
        if not names:
            self.skipTest("no figures in this checkout")
        await self.answers(f"/rules/figures/{names[0]}", "image/png")

    async def test_a_missing_rules_file_is_an_error_and_a_503(self) -> None:
        with mock.patch(
            "webapp.server.load_rules_document", side_effect=OSError("gone"),
        ), self.assertLogs("webapp.server", level="ERROR"):
            for path in ("/rules", "/api/rules?q=ball"):
                with self.subTest(path):
                    self.assertEqual((await self.get(path)).status, 503)


class BookTests(Harness):
    async def test_a_book_is_set_once_and_served_inline(self) -> None:
        with mock.patch.object(
            rulebooks, "book_bytes", return_value=PDF,
        ) as setter:
            for name in aids.BOOK_NAMES:
                with self.subTest(name):
                    for _ in range(2):
                        response = await self.get(f"/books/{name}.pdf")
                        self.assertEqual(response.status, 200)
                        self.assertEqual(
                            response.content_type, "application/pdf",
                        )
                        self.assertTrue(
                            response.headers["Content-Disposition"]
                            .startswith("inline"),
                        )
                        self.assertEqual(await response.read(), PDF)
            self.assertEqual(setter.call_count, len(aids.BOOK_NAMES))
            self.assertEqual(
                [call.args[0].name for call in setter.call_args_list],
                list(aids.BOOK_NAMES),
            )

    async def test_an_edited_source_is_set_again(self) -> None:
        with mock.patch.object(
            rulebooks, "book_bytes", side_effect=[b"%PDF old", b"%PDF new"],
        ), mock.patch.object(aids, "book_stamp", side_effect=[1, 2]):
            first = await self.get("/books/charter.pdf")
            second = await self.get("/books/charter.pdf")
        self.assertEqual(await first.read(), b"%PDF old")
        self.assertEqual(await second.read(), b"%PDF new")


class RoomAidsTests(Harness):
    MODES = (
        # mode, tutorial, tier, species, advanced cards
        (GameMode.TRAINING, False, MANEUVER_TIER_BASIC, False, False),
        (GameMode.BASIC, False, MANEUVER_TIER_BASIC, True, False),
        (GameMode.ADVANCED, False, MANEUVER_TIER_GAMBIT, True, True),
        (GameMode.ADVANCED, True, MANEUVER_TIER_GAMBIT, False, False),
    )

    async def test_the_room_carries_the_models_three_answers(self) -> None:
        game = self.file(case("smooth"))
        for mode, tutorial, tier, species, advanced in self.MODES:
            with self.subTest(mode=mode, tutorial=tutorial):
                game.mode = mode
                game.tutorial = tutorial
                room = (await self.state(game, game.player_1_id))["aids"]
                self.assertEqual(
                    room["maneuver_tier"],
                    ENGINE.maneuver_reference_tier(game),
                )
                self.assertEqual(
                    room["species_abilities"],
                    ENGINE.species_abilities_apply(game),
                )
                self.assertEqual(
                    room["advanced_cards"],
                    ENGINE.personal_abilities_apply(game),
                )
                self.assertEqual(
                    (room["maneuver_tier"], room["species_abilities"],
                     room["advanced_cards"]),
                    (tier, species, advanced),
                )
                self.assertEqual(
                    [one["tier"] for one in room["maneuvers"]], [tier],
                )
                self.assertEqual(bool(room["species"]), species)
                face = aids.FACE_ADVANCED if advanced else aids.FACE_FRONT
                for team in room["teams"]:
                    self.assertEqual(
                        [one["face"] for one in team["faces"]], [face],
                    )

    async def test_an_advanced_game_without_the_gambits_gets_the_basic_hexagon(
        self,
    ) -> None:
        game = self.file(case("smooth"))
        game.mode = GameMode.ADVANCED
        game.advanced_maneuvers = False
        room = (await self.state(game, game.player_1_id))["aids"]
        self.assertEqual(room["maneuver_tier"], MANEUVER_TIER_BASIC)

    async def test_each_seat_sees_its_own_team_first(self) -> None:
        game = self.file(case("smooth"))
        teams = [game.player_1_team.value, game.player_2_team.value]
        for coach, expected in (
            (game.player_1_id, teams),
            (game.player_2_id, teams[::-1]),
        ):
            with self.subTest(coach=coach):
                room = (await self.state(game, coach))["aids"]
                self.assertEqual(
                    [team["key"] for team in room["teams"]], expected,
                )
                self.assertEqual(
                    [team["yours"] for team in room["teams"]], [True, False],
                )

    async def test_an_observer_may_open_every_aid(self) -> None:
        game = self.file(case("smooth"))
        room = (await self.state(game, WATCHER))["aids"]
        self.assertEqual(
            [team["key"] for team in room["teams"]],
            [game.player_1_team.value, game.player_2_team.value],
        )
        self.assertFalse(any(team["yours"] for team in room["teams"]))
        urls = [one["url"] for one in room["maneuvers"]]
        urls += [room["roles"]] + [one["url"] for one in room["species"]]
        for team in room["teams"]:
            urls.extend(team["faces"][0]["cards"])
        for url in urls:
            with self.subTest(url):
                response = await self.get(url, WATCHER)
                self.assertEqual(response.status, 200)

    async def test_the_maneuver_pick_links_to_the_hexagon(self) -> None:
        game = self.file(case("maneuver picks"))
        prompt = (await self.state(game, game.player_1_id))["prompt"]
        self.assertEqual(
            prompt["reference"],
            f"/aids/maneuvers/{ENGINE.maneuver_reference_tier(game)}.png",
        )
        other = self.file(case("smooth"))
        prompt = (await self.state(other, other.player_1_id))["prompt"]
        self.assertIsNone(prompt["reference"])


class CharterNumberTests(unittest.TestCase):
    """The page heads each rules section with the Charter's number."""

    def test_every_heading_the_charter_numbers_is_a_numbered_section(
        self,
    ) -> None:
        document = load_rules_document()
        page = aids.rules_page(document)
        numbered = {
            section["slug"]: section["number"] for section in page.sections
        }
        blocks = rulebooks.parse_markdown(document.text)
        numbers = rulebooks.number_blocks(blocks).headings
        headings = [
            block for block in blocks
            if isinstance(block, rulebooks.Heading) and block.level in (2, 3)
            and block.slug in numbers
            and not numbers[block.slug].startswith("Appendix")
        ]
        self.assertTrue(headings)
        for heading in headings:
            with self.subTest(heading.text):
                self.assertIn(heading.slug, numbered)
                self.assertEqual(numbered[heading.slug], numbers[heading.slug])

    def test_nothing_the_charter_leaves_unnumbered_is_numbered(self) -> None:
        document = load_rules_document()
        page = aids.rules_page(document)
        for section in page.sections:
            if section["level"] != 2:
                continue
            title = section["title"]
            if title.startswith(("Part ", "Appendix ")) or (
                section["slug"] in rulebooks.FRONT_MATTER_SECTIONS
            ):
                with self.subTest(title):
                    self.assertIsNone(section["number"])


class InlineTests(unittest.TestCase):
    def test_the_rules_are_escaped_before_they_are_marked_up(self) -> None:
        link = aids._link_resolver({"time-out": "13"})
        self.assertEqual(
            aids.inline_html("<b> **bold** `a*b*` [time out](#time-out)", link),
            "&lt;b&gt; <strong>bold</strong> <code>a*b*</code> "
            '<a href="#time-out">time out (13)</a>',
        )


if __name__ == "__main__":
    unittest.main()

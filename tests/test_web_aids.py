"""
The reading room over HTTP: the rules, the Learn to Play and the player
aids -- step 11 of docs/web-app-next.md, redrawn as the Rules tab and
the Reading Room in step 10 of docs/web-app-redesign.md ("The rules and
the player aids" in docs/design/web-app.md).

Nothing printed is tested (CLAUDE.md), so no picture is looked at here:
every renderer is patched to hand back fixed bytes, and what is watched
is the routes and what the page is told --

- **every route answers**, with its content type, and to anybody: an
  observer, and nobody at all, may open every aid;
- **which aids a room gets is the model's**: the room's state carries
  `maneuver_reference_tier`, `species_abilities_apply` and
  `special_abilities_apply` as the engine answers them, and they
  change with the game's mode;
- **the rules are headed with the Charter's numbers** and grouped by
  its Laws: every heading the Charter build numbers is a `RulesSection`
  with that number, which is the slug agreement between `rules_doc` and
  `rulebooks`, and the Rules tab's Laws are the ones the build numbers;
- **the Rules tab shows the living rules as they stand**: a heading
  read through `rules_doc` is found in what the tab and the Reading
  Room are handed;
- **a refusal's Law is the model's**, linked by its heading;
- **no PDF anywhere**.
"""

from __future__ import annotations

import html
import unittest
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

from d12ball import rulebooks
from d12ball.cards import time_cost
from d12ball.components import (
    MANEUVER_TIER_BASIC,
    MANEUVER_TIER_GAMBIT,
    MANEUVER_TIER_WORDS,
    MANEUVER_TIERS,
)
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
            "webapp.pictures.maneuver_card_png",
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


class NoPdfTests(Harness):
    """No PDF anywhere (the author, reviewing the redesign): the books
    are read in the page, and nothing the page links is a PDF."""

    async def test_no_book_is_served(self) -> None:
        for name in ("charter", "learn-to-play"):
            with self.subTest(name):
                self.assertEqual(
                    (await self.get(f"/books/{name}.pdf")).status, 404,
                )

    async def test_nothing_the_pages_link_is_a_pdf(self) -> None:
        pages = [await (await self.get("/rules")).text()]
        for name in ("game.html", "index.html", "aids.js", "app.js"):
            pages.append(await (await self.get(f"/static/{name}")).text())
        pages.append(await (await self.get("/api/aids")).text())
        game = self.file(case("smooth"))
        pages.append(await (await self.get(
            f"/api/game/{game.game_id}", game.player_1_id,
        )).text())
        for page in pages:
            self.assertNotIn(".pdf", page)


class CharterTests(Harness):
    """The Rules tab and the Reading Room read the living rules."""

    async def test_the_tab_lists_the_laws_the_charter_numbers(self) -> None:
        found = await (await self.get("/api/rules/charter")).json()
        document = load_rules_document()
        numbers = aids.charter_numbers(document)
        laws = [
            slug for slug, number in numbers.items()
            if number.isdigit()
        ]
        self.assertEqual([law["slug"] for law in found["laws"]], laws)
        self.assertEqual(
            [law["number"] for law in found["laws"]],
            [str(n) for n in range(1, len(laws) + 1)],
        )
        for law in found["laws"]:
            for section in law["sections"]:
                self.assertEqual(section["number"], numbers[section["slug"]])
        self.assertTrue(
            all(one["label"].startswith("Appendix") for one in found["appendices"])
        )

    async def test_a_heading_of_the_living_rules_is_in_the_page(self) -> None:
        """Done when: the Rules tab shows the current living rules."""
        document = load_rules_document()
        heading = next(
            section for section in document.sections if section.level == 3
        )
        found = await (await self.get("/api/rules/charter")).json()
        sections = {
            one["slug"]: one["title"]
            for law in found["laws"]
            for one in law["sections"]
        }
        self.assertIn(heading.slug, sections)
        self.assertEqual(sections[heading.slug], heading.title)
        room = await (await self.get("/rules")).text()
        self.assertIn(f'id="{heading.slug}"', room)
        self.assertIn(heading.title, room)

    async def test_the_reading_room_renders(self) -> None:
        response = await self.get("/rules")
        self.assertEqual(response.status, 200)
        page = await response.text()
        for column in ("reading-contents", "reading-text", "reading-refs"):
            self.assertIn(column, page)
        found = aids.charter(load_rules_document())
        for law in found["laws"]:
            self.assertIn(f'id="{law["slug"]}"', page)
            self.assertIn(f'data-rule="{law["slug"]}"', page)
        # The References column: every maneuver's effect and the roles.
        for table in aids.maneuver_rows(ENGINE.maneuver_catalog, ENGINE.player_catalog, MANEUVER_TIERS):
            for row in table["rows"]:
                self.assertIn(html.escape(row["effect"]), page)
        for row in aids.roles(ENGINE.player_catalog):
            self.assertIn(row["ability"].replace("'", "&#x27;"), page)
        # Both hexagons, and each condensed row's link reaches its card.
        for tier in MANEUVER_TIERS:
            self.assertIn(f'src="/aids/maneuvers/{tier}.png"', page)
        for table in aids.maneuver_rows(ENGINE.maneuver_catalog, ENGINE.player_catalog, MANEUVER_TIERS):
            for row in table["rows"]:
                self.assertIn(f'href="#ref-card-{row["key"]}"', page)
                self.assertIn(f'id="ref-card-{row["key"]}"', page)

    async def test_the_learn_to_play_is_in_the_page(self) -> None:
        book = await (await self.get("/api/rules/learn")).json()
        self.assertIn("Learn to Play", book["title"])
        self.assertTrue(book["contents"])
        self.assertIn("/rules/figures/", book["html"])
        # Its citations link into the Charter by the number the build gives.
        numbers = aids.charter_numbers(load_rules_document())
        self.assertIn(
            f'data-rule="{next(s for s, n in numbers.items() if n == "6.4")}"',
            book["html"],
        )
        self.assertNotIn("<script", book["html"])

    async def test_a_missing_learn_to_play_is_an_error_and_a_503(self) -> None:
        with mock.patch(
            "webapp.aids.cached_learn_to_play", side_effect=OSError("gone"),
        ), self.assertLogs("webapp.server", level="ERROR"):
            self.assertEqual((await self.get("/api/rules/learn")).status, 503)


class CitationTests(Harness):
    """A refusal cites its Law: the model's slug, linked by its heading."""

    def test_a_citation_names_the_heading_and_its_law(self) -> None:
        document = load_rules_document()
        cited = aids.citation(document, "how-many-substitutions")
        numbers = aids.charter_numbers(document)
        self.assertEqual(cited["number"], numbers["how-many-substitutions"])
        self.assertEqual(cited["law"], "coaching-choice")
        self.assertEqual(cited["law_number"], numbers["coaching-choice"])
        self.assertIsNone(aids.citation(document, None))
        self.assertIsNone(aids.citation(document, "no-such-heading"))

    async def test_a_refused_click_carries_its_law(self) -> None:
        from gamesaves.d12ball.service import GameResult

        game = self.file(case("smooth"))
        state = await self.state(game, game.player_1_id)
        control = next(
            control["action"]
            for group in state["prompt"]["controls"]
            for control in group["controls"]
            if not control["disabled"]
        )
        refused = GameResult(
            refusal="Not that one.", refusal_law="winning-the-toss",
        )
        with mock.patch.object(
            self.service, "apply_action", return_value=refused,
        ):
            response = await self.client.post(
                f"/api/game/{game.game_id}/action",
                headers=as_coach(game.player_1_id),
                json={"action": control},
            )
        answered = await response.json()
        self.assertEqual(answered["refusal"], "Not that one.")
        self.assertEqual(answered["refusal_law"]["slug"], "winning-the-toss")
        self.assertEqual(
            answered["refusal_law"]["number"],
            aids.charter_numbers(load_rules_document())["winning-the-toss"],
        )


class ReferenceTests(Harness):
    async def test_the_maneuvers_table_is_every_card(self) -> None:
        offered = await (await self.get("/api/aids")).json()
        tables = offered["maneuver_rows"]
        self.assertEqual(
            [table["side"] for table in tables], ["offense", "defense"],
        )
        catalog = ENGINE.maneuver_catalog
        for table in tables:
            with self.subTest(table["side"]):
                self.assertEqual(
                    [row["key"] for row in table["rows"]],
                    [one.key for one in catalog.side(table["side"])],
                )

    def test_the_maneuvers_table_is_the_cards_own_data(self) -> None:
        catalog = ENGINE.maneuver_catalog
        tables = aids.maneuver_rows(catalog, ENGINE.player_catalog, (MANEUVER_TIER_BASIC,))
        for table in tables:
            opposing = "defense" if table["side"] == "offense" else "offense"
            self.assertEqual(len(table["rows"]), 3)
            for row in table["rows"]:
                with self.subTest(row["key"]):
                    card = catalog.definition(row["key"])
                    self.assertEqual(card.tier, MANEUVER_TIER_BASIC)
                    self.assertFalse(row["gambit"])
                    self.assertEqual(row["effect"], card.effect)
                    self.assertEqual(row["time"], f"TIME · {time_cost(card)}")
                    self.assertEqual(row["time_cost"], time_cost(card))
                    # Only the tiers shown, and the rank the card beats.
                    beaten = [
                        one for one in catalog.for_tier(opposing, MANEUVER_TIER_BASIC)
                        if one.rank == card.defeats_rank
                    ]
                    self.assertEqual(row["beats"], beaten[0].name)
        both = aids.maneuver_rows(catalog, ENGINE.player_catalog, MANEUVER_TIERS)
        low_pass = next(
            row for row in both[0]["rows"] if row["key"] == "low_pass"
        )
        self.assertEqual(len(low_pass["beats"].split(" / ")), 2)
        # An advanced card's tag is the tier's word, not "gambit".
        for row in both[0]["rows"] + both[1]["rows"]:
            with self.subTest(tag=row["key"]):
                self.assertEqual(
                    row["tier_word"],
                    MANEUVER_TIER_WORDS[catalog.definition(row["key"]).tier],
                )
                if row["gambit"]:
                    self.assertEqual(row["tier_word"], "advanced")

    def test_each_maneuver_carries_its_whole_card(self) -> None:
        """The References hold everything the printed card says, since
        the hand's pill leaves its foot and ability rows to a hover
        (the author, 2026-10-01): the rank, what it beats, ties and
        loses to -- the catalog's own reading -- and its role rows."""
        from d12ball.cards import role_abilities

        catalog = ENGINE.maneuver_catalog
        outcomes = {"Beats": "offense", "Ties": "tie", "Loses to": "defense"}
        for table in aids.maneuver_rows(
            catalog, ENGINE.player_catalog, MANEUVER_TIERS,
        ):
            opposing = "defense" if table["side"] == "offense" else "offense"
            for row in table["rows"]:
                with self.subTest(row["key"]):
                    card = catalog.definition(row["key"])
                    self.assertEqual(
                        row["rank"], f"{table['side'][0].upper()}{card.rank}",
                    )
                    self.assertEqual(
                        [one["said"] for one in row["matchups"]], list(outcomes),
                    )
                    for one in row["matchups"]:
                        self.assertEqual(len(one["names"]), 2)
                        for name in one["names"]:
                            other = next(
                                m for m in catalog.side(opposing) if m.name == name
                            )
                            offense, defense = (
                                (card.key, other.key) if table["side"] == "offense"
                                else (other.key, card.key)
                            )
                            winner = catalog.resolve(offense, defense)
                            said = one["said"]
                            if table["side"] == "defense" and said != "Ties":
                                said = "Loses to" if said == "Beats" else "Beats"
                            self.assertEqual(winner, outcomes[said])
                    self.assertEqual(
                        [(one["who"].upper(), one["text"]) for one in row["abilities"]],
                        role_abilities(ENGINE.player_catalog, card),
                    )
                    self.assertEqual(
                        row["diagram"], f"/aids/maneuver-diagram/{card.key}.png",
                    )

    def test_the_tables_are_the_cards_own_data(self) -> None:
        roles = aids.roles(ENGINE.player_catalog)
        self.assertEqual(
            [(row["offense"], row["defense"], row["ability"]) for row in roles],
            [
                (profile.offense, profile.defense, profile.short_ability)
                for profile in ENGINE.player_catalog.role_profiles.values()
            ],
        )
        self.assertEqual(len(aids.species_rows()), 4)


class RoomAidsTests(Harness):
    MODES = (
        # mode, tutorial, tier, species, advanced cards
        (GameMode.TRAINING, False, MANEUVER_TIER_BASIC, False, False),
        (GameMode.STANDARD, False, MANEUVER_TIER_BASIC, True, False),
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
                    ENGINE.special_abilities_apply(game),
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
                self.assertEqual(bool(room["species_rows"]), species)
                self.assertEqual(
                    sorted({
                        row["tier"]
                        for table in room["maneuver_rows"]
                        for row in table["rows"]
                    }),
                    [MANEUVER_TIER_BASIC] if tier == MANEUVER_TIER_BASIC
                    else sorted([MANEUVER_TIER_BASIC, tier]),
                )
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

    async def test_the_maneuver_pick_shows_the_cards_back(self) -> None:
        game = self.file(case("maneuver picks"))
        prompt = (await self.state(game, game.player_1_id))["prompt"]
        self.assertEqual(
            prompt["reference"],
            f"/api/game/{game.game_id}/maneuver-back.png?size=full",
        )
        response = await self.get(prompt["reference"], game.player_1_id)
        self.assertEqual(response.status, 200)
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
        blocks = rulebooks.parse_markdown(rulebooks.unnumber(document.text))
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
        link = aids._link_resolver({"13-time-out": "time-out"})
        self.assertEqual(
            aids.inline_html("<b> **bold** `a*b*` [time out](#13-time-out) (13)", link),
            "&lt;b&gt; <strong>bold</strong> <code>a*b*</code> "
            '<a href="#time-out">time out</a> (13)',
        )


if __name__ == "__main__":
    unittest.main()

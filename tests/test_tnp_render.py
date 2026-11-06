"""
TNP's pictures (step 3 of docs/tnp-bot.md): each renders to a PNG of
the size its layout gives. Nothing here checks how a picture looks --
that is looked at, through `scripts/render_tnp_sample.py`
(docs/design/tnp.md, "The pictures").
"""

import io
import unittest

from PIL import Image

from tnp.briefs import DEFENSE, BoardBrief, MapBrief, Pile, opening_board, opening_map
from tnp.catalog import catalog
from tnp.render import (
    BATTLE_WIDTH, BOARD_WIDTH, PILE_HEADING, PILE_PITCH, render_battle, render_board, render_map,
)
from tnp_battles import fight, stage


def picture(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


class TnpMapPictureTests(unittest.TestCase):
    def test_the_opening_map(self) -> None:
        image = picture(render_map(catalog(), opening_map(catalog())))
        self.assertEqual(image.format, "PNG")
        self.assertEqual(image.size, (1627, 1282))

    def test_revealed_piles_add_a_row_of_cards_a_three(self) -> None:
        piles = tuple(Pile("blue", "8", "A", {"mercenary": 2}) for _ in range(4))
        brief = MapBrief(
            controllers={"8": "blue"}, resources=opening_map(catalog()).resources,
            stranded={"8": ("blue",)}, revealed=piles + (Pile("green", "9", DEFENSE, {"worker": 1}),),
            caption="Turn 2 · March",
        )
        self.assertEqual(picture(render_map(catalog(), brief)).size, (1627, 1282 + PILE_HEADING + 2 * PILE_PITCH))


class TnpBoardPictureTests(unittest.TestCase):
    def test_each_seats_opening_board(self) -> None:
        for seat in ("blue", "green"):
            with self.subTest(seat=seat):
                image = picture(render_board(catalog(), opening_board(catalog(), seat)))
                self.assertEqual(image.width, BOARD_WIDTH)
                self.assertGreater(image.height, 1000)

    def test_a_board_with_everything_built_and_queued(self) -> None:
        everything = frozenset(catalog().facilities) | frozenset(catalog().upgrades)
        brief = BoardBrief(
            seat="green", pool={"materials": 1, "gems": 1}, built=everything,
            queued_units={"tank": 2}, supply_left={"tank": 1},
        )
        self.assertEqual(picture(render_board(catalog(), brief)).width, BOARD_WIDTH)

    def test_the_opening_board_is_the_setup_of_tnp_3(self) -> None:
        brief = opening_board(catalog(), "blue")
        self.assertEqual(brief.built, frozenset({"barracks", "base_defenses"}))
        self.assertEqual(brief.pool["materials"], 5)
        self.assertEqual(brief.pool["gold"], 0)
        self.assertEqual(brief.supply_left["worker"], catalog().units["worker"].supply - 3)
        self.assertEqual(brief.supply_left["tank"], catalog().units["tank"].supply)


class TnpBattlePictureTests(unittest.TestCase):
    def test_a_battle_part_way_and_over(self) -> None:
        engine, match = stage({"tank": 2, "mercenary": 3}, {"mercenary": 4, "worker": 2}, seed=3)
        self.assertEqual(picture(render_battle(engine.catalog, match.battle)).width, BATTLE_WIDTH)
        fight(engine, match)
        self.assertIsNotNone(match.battle.outcome)
        self.assertEqual(picture(render_battle(engine.catalog, match.battle)).width, BATTLE_WIDTH)

    def test_a_base_battle_with_its_base_cards(self) -> None:
        engine, match = stage(
            {"tank": 3}, {"smart_mines": 2},
            territory="green_base",
            structures={"facilities": ["barracks", "factory", "base_defenses"], "upgrades": []},
            emergency={"pool": {"materials": 0, "gold": 0}, "supply_room": {}},
        )
        fight(engine, match)
        self.assertEqual(picture(render_battle(engine.catalog, match.battle)).width, BATTLE_WIDTH)


if __name__ == "__main__":
    unittest.main()

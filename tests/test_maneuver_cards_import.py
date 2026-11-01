"""
`scripts/import_d12ball_maneuver_cards.py`, the 2.1 tab's importer: a
card is keyed by its Index, an Advanced row is skipped, a blank Mode or
Time is filled and said, and a rank whose specials do not name each of
the six roles once is refused. See docs/design/rules-and-data.md.
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import import_d12ball_maneuver_cards as importer  # noqa: E402

BASIC_KEYS = importer.read_basic_keys(importer.DEFAULT_CATALOG)

SPECIALS = {
    1: ("WG", "MF or SK", "PM", "FB or DD"),
    2: ("SK", "MF or PM", "FB or DD", "WG"),
    3: ("FB or DD", "PM", "MF", "WG or SK"),
}
NAMES = {
    ("offense", 1): ("P", "Pass"), ("offense", 2): ("B", "Dribble"),
    ("offense", 3): ("H", "High Ball"), ("defense", 1): ("F", "Deflect"),
    ("defense", 2): ("S", "Steal"), ("defense", 3): ("R", "Pressure"),
}


def tab(rows_override=None) -> list[dict]:
    rows = []
    for (side, rank), (letter, maneuver) in NAMES.items():
        for number, roles in enumerate(SPECIALS[rank], start=1):
            rows.append({
                "Index": f"{letter}{number}",
                "Rank": f"{side[0].upper()}{rank}",
                "Maneuver": maneuver,
                "Name": f"Card {letter}{number}",
                "Type": side.title(),
                "Effect": f"The {maneuver} effect. ",
                "Special": f"If player is {roles}, something.",
                "Mode": "" if number > 1 else "Basic",
                "Time": "",
                "Spec": "",
            })
        rows.append({
            "Index": f"{letter}5", "Rank": f"{side[0].upper()}{rank}",
            "Maneuver": maneuver, "Name": "Advanced", "Type": side.title(),
            "Effect": "x", "Special": "", "Mode": "Advanced", "Time": "1",
            "Spec": "All",
        })
    for index, change in (rows_override or {}).items():
        next(row for row in rows if row["Index"] == index).update(change)
    return rows


class ImportTests(unittest.TestCase):

    def test_twenty_four_cards_keyed_by_index(self) -> None:
        cards, notes = importer.import_cards(tab(), BASIC_KEYS)
        self.assertEqual(len(cards), 24)
        self.assertEqual(cards[0]["index"], "P1")
        self.assertEqual(cards[0]["maneuver"], "low_pass")
        self.assertEqual(cards[1]["roles"], ["midfielder", "striker"])
        # The spaces at an Effect's end are the import's to drop.
        self.assertEqual(cards[0]["effect"], "The Pass effect.")
        self.assertTrue(any(note.startswith("Skipped:") for note in notes))
        self.assertTrue(any("Time -> 1" in note for note in notes))
        self.assertTrue(any("Mode -> Basic" in note for note in notes))

    def test_a_rank_naming_a_role_twice_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "six roles"):
            importer.import_cards(
                tab({"P1": {"Special": "If passer is MF, something."}}),
                BASIC_KEYS,
            )

    def test_a_special_that_names_no_role_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not read"):
            importer.import_cards(
                tab({"F2": {"Special": "Defender may follow."}}), BASIC_KEYS,
            )

    def test_a_rank_whose_effects_differ_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "Effect differs"):
            importer.import_cards(tab({"S3": {"Effect": "Other."}}), BASIC_KEYS)

    def test_the_committed_data_is_the_tabs_import(self) -> None:
        import json
        data = json.loads(importer.DEFAULT_OUTPUT.read_text())
        self.assertEqual(len(data["cards"]), 24)
        self.assertEqual(
            [card["index"] for card in data["cards"]][:4],
            ["P1", "P2", "P3", "P4"],
        )


if __name__ == "__main__":
    unittest.main()

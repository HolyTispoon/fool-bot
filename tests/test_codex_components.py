"""
The Codex save format, which is the contract from step 2 on
(docs/design/codex.md, "The saved fields"): every field of every saved
class is in its table, a match round-trips, an older save's missing
field comes back as its fallback, and `validate` checks a match against
itself.
"""

from __future__ import annotations

import json
import unittest

from codex import tokens
from codex.cards import catalog
from codex.components import MatchState, unsaved_fields
from codex.formatting import plain_text

from codex_positions import begin, built, new_game, put


class SavedFieldTests(unittest.TestCase):
    def test_every_field_is_saved(self) -> None:
        """A field in no table is dropped by the first restart."""
        self.assertEqual(unsaved_fields(), {})

    def test_a_match_round_trips_through_json(self) -> None:
        engine, game, match = new_game()
        begin(engine, game, match)
        put(match, 1, "iron_man", patrol="elite", damage=1)
        built(match, 2, "tech1", finished=False)
        saved = match.to_dict()
        loaded = MatchState.from_dict(json.loads(json.dumps(saved)))
        self.assertEqual(loaded.to_dict(), saved)
        loaded.validate(catalog())

    def test_a_missing_field_reads_as_its_fallback(self) -> None:
        engine, game, match = new_game()
        saved = match.to_dict()
        for name in ("attacking", "journal", "turn_snapshots", "events", "winner"):
            saved.pop(name)
        player = saved["players"][0]
        for name in ("tech_confirmed", "reshuffled_this_phase", "add_on", "buildings"):
            player.pop(name)
        player["heroes"][0].pop("armor")
        loaded = MatchState.from_dict(saved)
        self.assertEqual((loaded.journal, loaded.turn_snapshots, loaded.attacking), ([], [], None))
        self.assertEqual(loaded.player(1).buildings, {"tech1": None, "tech2": None, "tech3": None})
        self.assertEqual(loaded.player(1).hero.armor, 0)
        loaded.validate(catalog())

    def test_a_save_older_than_the_standard_game_is_a_team_of_one(self) -> None:
        """Step 10's fields, each with its fallback: `spec` and `hero` as
        a team of one, no `deck_color` the neutral deck, and a hero named
        `hero` alone -- an attack standing half-resolved, a tower's
        detection, an effect's source and target -- read as the side's
        first hero, `hero:<slug>`."""
        engine, game, match = new_game()
        saved = match.to_dict()
        for player in saved["players"]:
            player["spec"] = player.pop("specs")[0]
            player["hero"] = player.pop("heroes")[0]
            player.pop("deck_color")
        saved["attacking"] = "hero"
        saved["combat"] = {"attacker": "hero", "defender": "hero", "stage": "sparkshot",
                           "obliterated": [], "sparks": ["hero"], "overpower": None}
        saved["players"][1]["add_on"] = {"slug": "tower", "hp": 4, "detected": "hero"}
        saved["resolving"] = [{"kind": "effect", "effect": "spark", "seat": 1,
                               "source": "hero", "taken": ["2:hero"], "part": 0}]
        loaded = MatchState.from_dict(saved)
        self.assertEqual(loaded.player(1).specs, ("bashing",))
        self.assertEqual([hero.slug for hero in loaded.player(2).heroes], ["river_montoya"])
        self.assertEqual(loaded.player(1).deck_color, "neutral")
        active, other = (loaded.player(loaded.active).heroes[0].slug,
                         loaded.opponent(loaded.active).heroes[0].slug)
        self.assertEqual(loaded.attacking, f"hero:{active}")
        self.assertEqual((loaded.combat["attacker"], loaded.combat["defender"], loaded.combat["sparks"]),
                         (f"hero:{active}", f"hero:{other}", [f"hero:{other}"]))
        self.assertEqual(loaded.player(2).add_on.detected, "hero:troq_bashar")
        self.assertEqual(loaded.resolving[0]["source"], "hero:troq_bashar")
        self.assertEqual(loaded.resolving[0]["taken"], ["2:hero:river_montoya"])
        loaded.validate(catalog())

    def test_the_saved_lists_are_copies(self) -> None:
        engine, game, match = new_game()
        saved = match.to_dict()
        saved["players"][0]["hand"].append("spark")
        self.assertNotEqual(len(match.player(1).hand), len(saved["players"][0]["hand"]))


class ValidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine, self.game, self.match = new_game()

    def assertInvalid(self, needle: str) -> None:
        with self.assertRaises(ValueError) as raised:
            self.match.validate(catalog())
        self.assertIn(needle, str(raised.exception))

    def test_ids_are_unique(self) -> None:
        put(self.match, 1, "iron_man")
        put(self.match, 2, "tenderfoot").id = 1
        self.assertInvalid("share an id")

    def test_slugs_are_cards(self) -> None:
        self.match.player(1).hand.append("not_a_card")
        self.assertInvalid("not a card")

    def test_one_patroller_a_slot(self) -> None:
        put(self.match, 1, "iron_man", patrol="elite")
        put(self.match, 1, "tenderfoot", patrol="elite")
        self.assertInvalid("two patrollers")

    def test_no_count_below_zero(self) -> None:
        self.match.player(2).gold = -1
        self.assertInvalid("below zero")


class OpeningTests(unittest.TestCase):
    def test_the_opening_position(self) -> None:
        """Five cards each from the ten starters, a codex of twenty-four,
        a base at 20, four workers for the first player and five for the
        second (UMR p. 3)."""
        engine, game, match = new_game(first=2)
        for player in match.players:
            self.assertEqual(len(player.hand), 5)
            self.assertEqual(len(player.deck), 5)
            self.assertEqual(sorted(player.hand + player.deck),
                             sorted(catalog().starting_deck("neutral")))
            self.assertEqual(sum(player.codex.values()), 24)
            self.assertEqual(player.base_hp, 20)
            self.assertFalse(player.hero.in_play)
        self.assertEqual((match.player(2).workers, match.player(1).workers), (4, 5))
        self.assertEqual(match.active, 2)
        match.validate(catalog())


class TokenTests(unittest.TestCase):
    def test_the_narration_tokens(self) -> None:
        line = f"{tokens.player(1)} plays {tokens.card('iron_man')} for {tokens.gold(3)}; {tokens.hero('troq_bashar')}"
        self.assertEqual(
            tokens.find(line),
            [("player", ("1",)), ("card", ("iron_man",)), ("gold", ("3",)), ("hero", ("troq_bashar",))],
        )
        self.assertEqual(plain_text(line), "Player 1 plays Iron Man for (3); Troq Bashar")


if __name__ == "__main__":
    unittest.main()

"""
`codex.effects.UNIMPLEMENTED` is pinned: the exact set the last step
left, so a card can leave it only in the commit that gives it a handler
(docs/codex-bot.md, decision 7) -- and the keyword table beside it is
read off the texts.

**Step 5 shrank it to the triggers, the spells and the grants, and step
6 emptied it**: every card of the basic set with text now plays it --
its keywords through `codex.keywords`, its spells, triggers and
abilities through `codex.effects.EFFECTS` and `TEXT`, its static text
through the engine's grants and costs. `test_every_card_with_text_is_handled`
says where each one's text lives, so a card the next spec brings with
text the engine has not met fails here until it is handled or listed.
"""

from __future__ import annotations

import unittest

from codex import effects, keywords
from codex.cards import Hero, catalog
from codex.engine import RulesEngine
from codex.flow import resolve

from codex_positions import begin, new_game

#: The cards step 5 took out of it, each with the keyword that is the
#: whole of its text -- and the tower, whose text is its own.
STEP_5_PLAYED = {
    "timely_messenger": "Haste",
    "helpful_turtle": "Healing",
    "fruit_ninja": "Frenzy",
    "revolver_ocelot": "Sparkshot",
    "eggship": "Flying",
    "harvest_reaper": "Overpower",
    "backstabber": "Invisible",
    "cloud_sprite": "Flying",
    "leaping_lizard": "Anti-air",
    "tower": "Anti-air",
}


def _has_text(slug: str) -> bool:
    card = catalog().by_slug(slug)
    if isinstance(card, Hero):
        return any(band.text for band in card.bands)
    return bool(card.text)


#: Where each card's text that is not a keyword lives, from step 6: the
#: tables of `codex.effects` the engine and the flow read.
def _handled(slug: str) -> list[str]:
    found = []
    if slug in effects.TEXT or any(
        isinstance(key, tuple) and key[0] == slug for key in effects.TEXT
    ):
        found.append("TEXT")
    for name in (
        "GRANTS_VIRTUOSO_HASTE", "GRANTS_SWIFT_STRIKE", "GUIDES", "MAESTROS",
        "ATK_PER_DAMAGE", "UPKEEP_SELF_DAMAGE", "UPKEEP_DRAW", "CHANNELING",
    ):
        if slug in getattr(effects, name):
            found.append(name)
    if any(key[0] == slug for key in effects.TECH_0_DISCOUNT):
        found.append("TECH_0_DISCOUNT")
    card = catalog().by_slug(slug)
    if effects.FLAGBEARER in (getattr(card, "subtype", None) or ""):
        found.append("FLAGBEARER")
    if slug == effects.DANCER:
        found.append("stop_the_music")
    return found


class UnimplementedTests(unittest.TestCase):
    def test_the_set_is_empty(self) -> None:
        """Step 6 leaves nothing in it: the basic game is the basic game."""
        self.assertEqual(effects.UNIMPLEMENTED, frozenset())

    def test_every_card_with_text_is_handled(self) -> None:
        """Every card of the basic set with text plays it: each line is a
        keyword the engine reads, or the card is in one of the tables a
        handler reads. Nothing is ignored, silently or otherwise."""
        for slug in sorted(effects.BASIC_SET):
            if not _has_text(slug):
                continue
            with self.subTest(card=slug):
                card = catalog().by_slug(slug)
                lines = (
                    [line for band in card.bands for line in band.text]
                    if isinstance(card, Hero) else list(card.text)
                )
                if slug in STEP_5_PLAYED or all(keywords.read_keywords([line]) for line in lines):
                    continue
                self.assertTrue(_handled(slug), f"{slug} has text nothing plays")

    def test_every_part_is_carried_out(self) -> None:
        """Each `Part.does` the table uses is a handler in
        `codex.flow.resolve.DOES`, and each `Part.choose` a filter the
        engine answers."""
        engine = RulesEngine()
        _, game, match = new_game()
        begin(engine, game, match)
        for effect in effects.EFFECTS.values():
            for part in effect.parts:
                with self.subTest(effect=effect.key, does=part.does):
                    self.assertIn(part.does, resolve.DOES)
                    if part.choose is not None:
                        engine.target_candidates(match, 1, part.choose)
        for rows in effects.TEXT.values():
            for _, effect in rows:
                self.assertIn(effect, effects.EFFECTS)

    def test_what_step_5_took_out_is_keywords_alone(self) -> None:
        """A card left the set when its whole text became code: for nine
        of the ten that is the keyword it is printed with, and for the
        tower its own detection and damage."""
        for slug, keyword in STEP_5_PLAYED.items():
            with self.subTest(card=slug):
                self.assertNotIn(slug, effects.UNIMPLEMENTED)
                self.assertIn(keyword, [name for name, _ in keywords.keywords(slug)])
                if slug == "tower":
                    continue
                for line in catalog().by_slug(slug).text:
                    self.assertTrue(
                        keywords.read_keywords([line]),
                        f"{slug} still has text that is not a keyword: {line}",
                    )

    def test_the_basic_set_is_thirty_six_cards_and_its_pieces(self) -> None:
        self.assertEqual(
            len(effects.STARTERS | effects.BASHING | effects.FINESSE | effects.HEROES), 36,
        )
        for slug in effects.BASIC_SET:
            catalog().by_slug(slug)

    def test_the_four_textless_cards_are_not_vanilla_by_omission(self) -> None:
        engine = RulesEngine()
        for slug in ("tenderfoot", "older_brother", "iron_man", "regularsized_rhinoceros"):
            self.assertNotIn(slug, effects.UNIMPLEMENTED)
            self.assertTrue(engine.is_vanilla(slug))
        self.assertFalse(engine.is_vanilla("trojan_duck"))


class KeywordTests(unittest.TestCase):
    def test_keywords_are_read_off_the_texts(self) -> None:
        self.assertEqual(keywords.keywords("eggship"), (("Flying", None),))
        self.assertEqual(keywords.keywords("fruit_ninja"), (("Frenzy", 1),))
        self.assertEqual(keywords.keywords("trojan_duck"), (("Obliterate", 2),))
        self.assertEqual(keywords.keywords("harmony"), (("Channeling", None),))
        self.assertEqual(keywords.keywords("brick_thief"), (("Resist", 1),))
        self.assertEqual(keywords.keywords("tenderfoot"), ())

    def test_an_effect_that_mentions_a_keyword_is_not_one(self) -> None:
        """Sneaky Pig has haste; its stealth is an arrives effect."""
        self.assertEqual(keywords.keywords("sneaky_pig"), (("Haste", None),))

    def test_a_heros_keywords_come_with_its_band(self) -> None:
        self.assertEqual(keywords.keyword_table()[("troq_bashar", 8)], (("Readiness", None),))


if __name__ == "__main__":
    unittest.main()

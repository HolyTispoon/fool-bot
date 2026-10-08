"""
`codex.effects.UNIMPLEMENTED` is pinned: the exact set step 2 leaves, so
a card can leave it only in the commit that gives it a handler
(docs/codex-bot.md, decision 7) -- and the keyword table beside it is
read off the texts.
"""

from __future__ import annotations

import unittest

from codex import effects, keywords
from codex.cards import Hero, catalog
from codex.engine import RulesEngine

#: Step 2's vanilla engine: every card of the basic set with text.
STEP_2_UNIMPLEMENTED = frozenset({
    "timely_messenger", "brick_thief", "helpful_turtle",
    "granfalloon_flagbearer", "fruit_ninja", "spark", "bloom", "wither",
    "wrecking_ball", "the_boot", "intimidate", "final_smash",
    "revolver_ocelot", "hired_stomper", "sneaky_pig", "eggship",
    "harvest_reaper", "trojan_duck",
    "harmony", "discord", "two_step", "appel_stomp", "nimble_fencer",
    "starcrossed_starlet", "grounded_guide", "maestro", "backstabber",
    "cloud_sprite", "leaping_lizard", "blademaster",
    "troq_bashar", "river_montoya",
    "dancer", "angry_dancer", "tower", "surplus",
})


def _has_text(slug: str) -> bool:
    card = catalog().by_slug(slug)
    if isinstance(card, Hero):
        return any(band.text for band in card.bands)
    return bool(card.text)


class UnimplementedTests(unittest.TestCase):
    def test_the_set_is_pinned(self) -> None:
        self.assertEqual(effects.UNIMPLEMENTED, STEP_2_UNIMPLEMENTED)

    def test_it_is_every_card_of_the_set_with_text(self) -> None:
        """Nothing with text is played silently: every card of the basic
        set that has text is in the set, until a handler takes it out."""
        with_text = {slug for slug in effects.BASIC_SET if _has_text(slug)}
        self.assertEqual(with_text, effects.UNIMPLEMENTED)

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
        self.assertTrue(engine.is_vanilla("trojan_duck"))


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

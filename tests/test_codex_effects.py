"""
`codex.effects.UNIMPLEMENTED` is pinned: the exact set the last step
left, so a card can leave it only in the commit that gives it a handler
(docs/codex-bot.md, decision 7) -- and the keyword table beside it is
read off the texts.

**Step 5 shrank it to the triggers, the spells and the grants.** Every
card whose text is keywords alone plays in full now, and so does the
tower, whose detection and damage are the board's rather than a
keyword's; what is left is step 6's.
"""

from __future__ import annotations

import unittest

from codex import effects, keywords
from codex.cards import Hero, catalog
from codex.engine import RulesEngine

#: What step 5 leaves: the cards whose text is a trigger, a spell, a
#: static grant, an upkeep effect or a hero's band.
STEP_5_UNIMPLEMENTED = frozenset({
    "brick_thief", "granfalloon_flagbearer", "spark", "bloom", "wither",
    "wrecking_ball", "the_boot", "intimidate", "final_smash",
    "hired_stomper", "sneaky_pig", "trojan_duck",
    "harmony", "discord", "two_step", "appel_stomp", "nimble_fencer",
    "starcrossed_starlet", "grounded_guide", "maestro", "blademaster",
    "troq_bashar", "river_montoya",
    "dancer", "angry_dancer", "surplus",
})

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


class UnimplementedTests(unittest.TestCase):
    def test_the_set_is_pinned(self) -> None:
        self.assertEqual(effects.UNIMPLEMENTED, STEP_5_UNIMPLEMENTED)

    def test_nothing_with_text_is_played_silently(self) -> None:
        """Every card of the basic set that has text is either in the set
        or has a handler: the two together are exactly the cards with
        text, so nothing is ignored without saying so."""
        with_text = {slug for slug in effects.BASIC_SET if _has_text(slug)}
        self.assertEqual(with_text, effects.UNIMPLEMENTED | set(STEP_5_PLAYED))

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

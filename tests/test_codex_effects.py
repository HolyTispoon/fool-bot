"""
`codex.effects.UNIMPLEMENTED` is pinned: the exact set the last step
left, so a card can leave it only in the commit that gives it a handler
(docs/codex-bot.md, decision 7) -- and the keyword table beside it is
read off the texts.

**Step 5 shrank it to the triggers, the spells and the grants, step 6
emptied it, and step 10 filled it with red and green**, played for their
numbers: every card of the basic set with text plays it --
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
        "ENGINE_RULES", "CANT_ATTACK", "CANT_PATROL", "ATTACKING_BUILDINGS_ATK",
        "UNSTOPPABLE_BY_TECH_0", "UNATTACKABLE_BY_TECH_0", "STEALTH_ATTACKING_UNITS",
        "INVISIBLE_WITH_HERO", "WHILE_PATROLLING", "READIES_ONCE",
        "FREE_HIRE", "LESS_PER_GREEN_UNIT", "FREE_UNITS", "FREE_SPELLS",
        "GROWS_ON_ARRIVAL", "BLOOD_RUNES", "ON_ANY_DEATH", "DIES_ON_YOUR_TURN",
        "GRANTS_DIES", "STEALS_ON_PATROLLER_KILL", "TRASHES_WORKER_ON_BASE_DAMAGE",
        "ON_DAMAGING_A_BUILDING", "GROWTH_RUNES", "AFTER_COMBAT", "ATTACHING",
        "UNIT_GRANTS", "HERO_GRANTS", "ATTACHED_UNIT_GRANTS",
        "UPKEEP_GOLD", "UPKEEP_GREEN_GOLD", "UPKEEP_CHOICE", "JOINS_THE_STRONGER",
        "RETURNS_IF_IDLE", "RETURNS_AT_END",
        # Purple and black's (step 12).
        "ATK_CEILING", "CANT_BE_SACRIFICED", "UNSTOPPABLE_BY_RUNED", "DEMONS_UNSTOPPABLE",
        "UNSTOPPABLE_ATTACKING_HEROES", "UNTARGETABLE_BY_BUFFS", "INVISIBLE_COLOR",
        "RUNE_DAMAGE", "ALL_OTHER_UNITS", "CORPSE_RUNES", "SKELETON_ON_DEATH",
        "ON_DAMAGING_A_BASE", "SHACKLED", "NO_HIGH_TECH_UNITS", "VOIDBLOCKERS", "DRAW_MORE",
        "NO_OPPOSING_LEVELS", "CANT_LEAVE_WITH_GOLD", "TRASHED_BY_TECH_II", "PER_TIME_RUNE",
        "SECOND_CHANCES", "SENTRIES", "SLOWTIME", "GOLGORTS", "REMEMBERERS",
        "UPKEEP_SACRIFICE", "PLAGUE_UPKEEP", "SELF_BASE_UPKEEP",
        # White and blue's (step 13).
        "DREAMSCAPE", "ILLUSION_GUARDS", "RETELLERS", "RETURNS_WHEN_TARGETED",
        "LONG_RANGE_AT_ONE", "UNSTOPPABLE_ATTACKING_BASE", "UNSTOPPABLE_ATTACKING_BUILDINGS",
        "UNSTOPPABLE_BY_WEAK", "UNSTOPPABLE_WITH_NINJA", "UNATTACKABLE_WITH_CUTE_ANIMAL", "LIBERTY",
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
    if slug == effects.MIMIC:
        found.append("MIMICKED")
    if any(key[0] == slug for key in effects.BAND_GRANTS):
        found.append("BAND_GRANTS")
    if slug in (effects.HOTTER_FIRE, effects.FAIRIE_DRAGON):
        found.append("the engine's damage bonus and feather runes")
    if any(key[0] == slug for key in effects.KILL_BONUSES):
        found.append("KILL_BONUSES")
    if any(key[0] == slug for key in effects.FLYING_ON_OWN_TURN):
        found.append("FLYING_ON_OWN_TURN")
    if any(key[0] == slug for key in effects.UNSTOPPABLE_BY_LONE_PATROLLER):
        found.append("UNSTOPPABLE_BY_LONE_PATROLLER")
    if effects.ILLUSION in (getattr(card, "subtype", None) or "").split():
        # "(Illusions die when targeted ...)": the subtype, which the
        # engine reads (`RulesEngine.is_illusion`).
        found.append("ILLUSION")
    return found


#: What step 13 has still to land: every white and blue card, hero and
#: token whose text is more than keywords the engine reads, written out
#: so each commit that gives one its handler takes it out here too.
REMAINING = frozenset({
    "aged_sensei", "air_hammer", "arrest", "arresting_constable", "bigby_hayes",
    "birds_nest", "boot_camp", "brave_knight", "building_inspector",
    "censorship_council", "community_service", "debilitator_alpha",
    "doubling_barbarbarian", "drill_sergeant", "earthquake", "elite_training",
    "entangling_vines", "eyes_of_the_chancellor", "flagstone_garrison",
    "flagstone_spy", "focus_master", "foxs_den_school", "foxs_den_students",
    "free_speech", "general_onimaru", "generals_hammer", "grappling_hook",
    "grave_stormborne", "guardian_of_the_gates", "heros_monument", "hidden_ninja",
    "injunction", "insurance_agent", "inverse_power_ninja",
    "jade_fox_dens_headmistress", "jail", "jefferson_degrey_ghostly_diplomat",
    "judgment_day", "jurisdiction", "lawbringer_gryphon", "lawful_search",
    "martial_mastery", "mind_control", "mindparry_monk", "morningstar_pass",
    "mythmaking", "oathkeeper_of_kor_mountain", "patriot_gryphon",
    "porkhand_magistrate", "rambasa_twin", "reputable_newsman", "reversal",
    "safe_attacking", "scribe", "senseis_advice", "setsuki_hiruki", "shuriken_hail",
    "sirus_quince", "snapback", "sparring_partner", "speed_of_the_fox",
    "tax_collector", "the_art_of_war", "thunderclap", "training_grounds",
    "true_power_of_storms", "versatile_style", "whitestar_grappler",
    "young_lightning_dragon",
})


#: The white and blue cards whose whole text is keywords the engine
#: reads, so they play in full from step 13's first commit.
STEP_13_PLAYED = {
    "fox_primus": ("Frenzy", "Anti-air"),
    "fox_viper": ("Sparkshot",),
    "flying_fox": ("Flying",),
    "glorious_ninja": ("Haste", "Swift strike"),
    "vigor_adept": ("Frenzy", "Readiness"),
    "porcupine": ("Deathtouch",),
    "savior_monk": ("Healing",),
    "fuzz_cuddles": ("Healing",),
    "bird": ("Flying",),
    "soldier": ("Sparkshot",),
}


#: The purple and black cards whose whole text is keywords the engine
#: reads, so they play in full from step 12's first commit.
STEP_12_PLAYED = {
    "argonaut": ("Readiness",),
    "stinger": ("Flying",),
    "horror": ("Deathtouch",),
}


#: The red and green cards whose whole text is keywords the engine
#: reads, so they play in full from step 10.
STEP_10_PLAYED = {
    "mad_man": ("Haste",),
    "nautical_dog": ("Frenzy",),
    "centaur": ("Overpower",),
    "chameleon": ("Stealth",),
    "huntress": ("Sparkshot", "Anti-air"),
    "barkcoat_bear": ("Resist", "Overpower"),
    "hunter": ("Anti-air",),
}


def _handled_now() -> list[str]:
    """The white and blue cards with unread text a commit of step 13 has
    already given their handlers."""
    return sorted(slug for slug in (effects.WHITE | effects.BLUE) - effects.UNIMPLEMENTED
                  if _lines(slug) and _handled(slug))


def _lines(slug: str) -> list[str]:
    card = catalog().by_slug(slug)
    if isinstance(card, Hero):
        return [line for band in card.bands for line in band.text]
    return list(card.text)


class UnimplementedTests(unittest.TestCase):
    def test_unimplemented_is_pinned(self) -> None:
        """Step 11 emptied the set step 10 filled with red and green's
        text, and step 12 emptied it again of purple's and black's; step
        13 fills it a last time with white's and blue's, played for their
        numbers, and empties it commit by commit."""
        self.assertEqual(effects.UNIMPLEMENTED, REMAINING)
        self.assertTrue(effects.UNIMPLEMENTED <= effects.WHITE | effects.BLUE)

    def test_unimplemented_is_exactly_the_pairs_unread_text(self) -> None:
        """Every white or blue card with text the keyword table does not
        read whole is listed until it is handled, and none other."""
        unread = set()
        for slug in effects.WHITE | effects.BLUE:
            lines = _lines(slug)
            if lines and not all(keywords.read_keywords([line]) for line in lines):
                unread.add(slug)
        self.assertEqual(unread - effects.UNIMPLEMENTED, set(_handled_now()))

    def test_white_and_blues_keyword_cards_play_in_full(self) -> None:
        for slug, printed in STEP_13_PLAYED.items():
            with self.subTest(card=slug):
                self.assertNotIn(slug, effects.UNIMPLEMENTED)
                self.assertEqual(tuple(name for name, _ in keywords.keywords(slug)), printed)

    def test_purple_and_blacks_keyword_cards_play_in_full(self) -> None:
        for slug, printed in STEP_12_PLAYED.items():
            with self.subTest(card=slug):
                self.assertNotIn(slug, effects.UNIMPLEMENTED)
                self.assertEqual(tuple(name for name, _ in keywords.keywords(slug)), printed)

    def test_the_landed_set_is_the_basic_set_and_red_and_green(self) -> None:
        cards = catalog()
        for color in ("red", "green"):
            group = effects.RED if color == "red" else effects.GREEN
            self.assertTrue(set(cards.starting_deck(color)) <= group)
            for hero in cards.heroes.values():
                if (hero.color or "").lower() == color:
                    self.assertIn(hero.slug, group)
                    self.assertTrue(set(cards.codex_for(hero.spec)) <= group)
        self.assertEqual(len(effects.RED), 10 + 36 + 3 + 1)
        self.assertEqual(len(effects.GREEN), 10 + 36 + 3 + 5)
        self.assertEqual(
            effects.LANDED_SET,
            effects.BASIC_SET | effects.RED | effects.GREEN | effects.BORROWED_TOKENS
            | effects.PURPLE | effects.BLACK | effects.WHITE | effects.BLUE,
        )

    def test_purple_and_black_landed(self) -> None:
        """Step 12: each colour's ten starters, its three specs'
        thirty-six, its three heroes and its tokens."""
        cards = catalog()
        for color, group, tokens in (("purple", effects.PURPLE, 2), ("black", effects.BLACK, 4)):
            self.assertTrue(set(cards.starting_deck(color)) <= group)
            for hero in cards.heroes.values():
                if (hero.color or "").lower() == color:
                    self.assertIn(hero.slug, group)
                    self.assertTrue(set(cards.codex_for(hero.spec)) <= group)
            self.assertEqual(len(group), 10 + 36 + 3 + tokens)
        self.assertEqual(effects.BORROWED_TOKENS, {"shark", "water_elemental"})

    def test_white_and_blue_landed(self) -> None:
        """Step 13: each colour's ten starters, its three specs'
        thirty-six, its three heroes and its tokens -- the Bird, the Ninja
        and Daigo for white; the Mirror Illusion, the Soldier, the Shark
        and the Water Elemental for blue -- and so every card the data
        holds is landed, and every colour."""
        from codex.cards import LANDED_COLORS

        cards = catalog()
        for color, group, tokens in (("white", effects.WHITE, 3), ("blue", effects.BLUE, 4)):
            self.assertTrue(set(cards.starting_deck(color)) <= group)
            for hero in cards.heroes.values():
                if (hero.color or "").lower() == color:
                    self.assertIn(hero.slug, group)
                    self.assertTrue(set(cards.codex_for(hero.spec)) <= group)
            self.assertEqual(len(group), 10 + 36 + 3 + tokens)
        self.assertTrue(effects.BORROWED_TOKENS <= effects.BLUE)
        printed = {slug for slug, card in cards.cards.items() if card.kind == "card"}
        self.assertEqual((printed | set(cards.heroes)) - effects.LANDED_SET, set())
        self.assertEqual(set(LANDED_COLORS),
                         {"neutral", "red", "green", "purple", "black", "white", "blue"})

    def test_red_and_greens_keyword_cards_play_in_full(self) -> None:
        for slug, printed in STEP_10_PLAYED.items():
            with self.subTest(card=slug):
                self.assertNotIn(slug, effects.UNIMPLEMENTED)
                self.assertEqual(tuple(name for name, _ in keywords.keywords(slug)), printed)

    def test_a_keyword_line_is_read_whole_or_not_at_all(self) -> None:
        """Step 11: deathtouch, long-range, ephemeral, boost and
        untargetable are read, and a line of keywords joined by commas is
        read whole -- but a line with anything else in it is read as
        nothing, so a sentence is never half-read as a keyword."""
        self.assertEqual(keywords.read_keywords(["Untargetable, deathtouch"]),
                         (("Untargetable", None), ("Deathtouch", None)))
        self.assertEqual(
            keywords.read_keywords(["Flying, haste, long-range, resist 2 (Opponents ...)"]),
            (("Flying", None), ("Haste", None), ("Long-range", None), ("Resist", 2)),
        )
        self.assertEqual(keywords.read_keywords(["Boost {gold:4} (You may pay ...)"]), (("Boost", 4),))
        self.assertEqual(keywords.read_keywords(["Haste, ephemeral"]), (("Haste", None), ("Ephemeral", None)))
        for line in ("Flying but can't attack.", "Arrives: Gets stealth this turn",
                     "Destroy a tech 0 unit, return a tech I unit to its owner's hand."):
            self.assertEqual(keywords.read_keywords([line]), ())
        self.assertEqual(keywords.keywords("shark"), (("Haste", None), ("Ephemeral", None)))

    def test_every_card_with_text_is_handled(self) -> None:
        """Every landed card with text plays it or is listed: each line is
        a keyword the engine reads, the card is in one of the tables a
        handler reads, or it is in `UNIMPLEMENTED`. Nothing is ignored
        silently."""
        for slug in sorted(effects.LANDED_SET - effects.UNIMPLEMENTED):
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
                    if part.does not in resolve.STRUCTURAL:
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

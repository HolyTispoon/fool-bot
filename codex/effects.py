"""
What each card's text does -- and, until step 6, the list of the cards
whose text the engine does not do yet.

**`UNIMPLEMENTED` is the vanilla engine's honesty** (docs/codex-bot.md,
decision 7, and docs/design/codex.md, "The vanilla engine"). Every card
of the basic set is played for its cost and its numbers from step 2 on;
a card whose text the engine does not honour is named here, the flow
says so in the line that plays it, and `tests/test_codex_effects.py`
pins the exact set -- so a card leaves it only in the commit that gives
it a handler, and nothing is ever ignored silently. In step 2 it is
every card of the set with text: the starters but Tenderfoot and Older
Brother, both specs but Iron Man and the Rhinoceros, the two heroes'
bands, the two tokens and the two add-ons.

The handlers -- arrives, attacks, upkeep, static and ability text, each
beside the sentence it was built from -- come in steps 5 and 6.
"""

#: The basic set (UMR p. 3): the ten neutral starters, Bashing's and
#: Finesse's twelve, the two heroes, the two tokens Harmony makes, the
#: two add-ons and the base's buildings.
STARTERS = frozenset({
    "tenderfoot", "older_brother", "timely_messenger", "brick_thief",
    "helpful_turtle", "granfalloon_flagbearer", "fruit_ninja",
    "spark", "bloom", "wither",
})
BASHING = frozenset({
    "wrecking_ball", "the_boot", "intimidate", "final_smash", "iron_man",
    "regularsized_rhinoceros", "revolver_ocelot", "hired_stomper",
    "sneaky_pig", "eggship", "harvest_reaper", "trojan_duck",
})
FINESSE = frozenset({
    "harmony", "discord", "two_step", "appel_stomp", "nimble_fencer",
    "starcrossed_starlet", "grounded_guide", "maestro", "backstabber",
    "cloud_sprite", "leaping_lizard", "blademaster",
})
HEROES = frozenset({"troq_bashar", "river_montoya"})
TOKENS = frozenset({"dancer", "angry_dancer"})
ADD_ONS = frozenset({"tower", "surplus"})
BUILDINGS = frozenset({"base", "tech_i_building", "tech_ii_building", "tech_iii_building"})
BASIC_SET = STARTERS | BASHING | FINESSE | HEROES | TOKENS | ADD_ONS | BUILDINGS

#: Every slug of the basic set whose text the engine plays for its
#: numbers alone. Written out rather than computed, so the commit that
#: takes a card out of it is the commit that gives it a handler.
UNIMPLEMENTED = frozenset({
    # The starters with text.
    "timely_messenger", "brick_thief", "helpful_turtle",
    "granfalloon_flagbearer", "fruit_ninja", "spark", "bloom", "wither",
    # Bashing, all but Iron Man and the Rhinoceros.
    "wrecking_ball", "the_boot", "intimidate", "final_smash",
    "revolver_ocelot", "hired_stomper", "sneaky_pig", "eggship",
    "harvest_reaper", "trojan_duck",
    # Finesse, every card.
    "harmony", "discord", "two_step", "appel_stomp", "nimble_fencer",
    "starcrossed_starlet", "grounded_guide", "maestro", "backstabber",
    "cloud_sprite", "leaping_lizard", "blademaster",
    # The heroes' bands.
    "troq_bashar", "river_montoya",
    # The tokens and the add-ons.
    "dancer", "angry_dancer", "tower", "surplus",
})

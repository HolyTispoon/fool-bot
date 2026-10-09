"""
What each card's text does -- the table the engine reads -- and the
list of the cards whose text the engine does not do yet: empty from
step 6 to step 9, and red and green's since step 10.

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

**Step 6 emptied it.** Every card of the basic set now does what it
says: its keywords through `codex.keywords`, and the rest through the
tables below -- `EFFECTS`, what a spell, a trigger or an ability does,
part by part, each part naming what it may choose (`Part.choose`) and
what it does to it (`Part.does`); `TEXT`, which card has which of them
(a hero's by the band that prints it, read the way its keywords are);
and the static grants and costs the engine asks about in
`RulesEngine`. Each row is beside the sentence it was built from. The
handlers that carry a part out are `codex.flow.resolve`'s: this module
is data, imported by the engine, and decides nothing by itself
(docs/design/codex.md, "Targeting and the effects").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

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
#: The add-ons: the basic game's two, the standard game's four (step 10).
ADD_ONS = frozenset({"tower", "surplus", "heroes_hall", "tech_lab"})
BUILDINGS = frozenset({"base", "tech_i_building", "tech_ii_building", "tech_iii_building"})
BASIC_SET = STARTERS | BASHING | FINESSE | HEROES | TOKENS | ADD_ONS | BUILDINGS

#: Red, landed at step 10 (docs/codex-bot.md): its ten starters, the
#: twelve of Anarchy, Blood and Fire, its three heroes and its token.
RED = frozenset({
    "bamstamper_lizzo", "bloodburn", "bloodlust", "bloodrage_ogre",
    "bombaster", "burning_volley", "calypso_vystari", "captain_zane",
    "captured_bugblatter", "careless_musketeer", "chameleon_lizzo",
    "chaos_mirror", "charge", "cinderblast_dragon", "crash_bomber",
    "crashbarrow", "desperation", "detonate", "disguised_monkey",
    "doubleshot_archer", "drakk_ramhorn", "ember_sparks", "fire_dart",
    "firebat", "firehouse", "flame_arrow", "gunpoint_taxman", "hotter_fire",
    "jaina_stormborne", "kidnapping", "land_octopus", "lobber", "mad_man",
    "makeshift_rambaster", "marauder", "maximum_anarchy",
    "molting_firebird", "nautical_dog", "ogre_recruiter", "pillage",
    "pirate", "pirate_gunship", "pirategang_commander", "rickety_mine",
    "sanatorium", "scorch", "shoddy_glider", "steam_tank",
    "surprise_attack", "war_drums"
})

#: Green, landed with red: its ten starters, the twelve of Balance,
#: Feral and Growth, its three heroes and its five tokens.
GREEN = frozenset({
    "argagarg_garg", "artisan_mantis", "barkcoat_bear", "beast",
    "behind_the_ferns", "blooming_ancient", "blooming_elm",
    "calamandra_moss", "centaur", "chameleon", "circle_of_life", "dinosize",
    "dothram_horselord", "fairie_dragon", "feral_strike", "ferocity",
    "final_showdown", "forests_favor", "frog", "galina_glimmer",
    "gemscout_owl", "giant_panda", "gigadon", "guargum_eternal_sentinel",
    "hunter", "huntress", "ironbark_treant", "master_midori",
    "merfolk_prospector", "might_of_leaf_and_claw", "moments_peace",
    "moss_ancient", "murkwood_allies", "nature_reclaims",
    "oversized_rhinoceros", "playful_panda", "polymorph_squirrel",
    "potent_basilisk", "predator_tiger", "rampaging_elephant",
    "rampant_growth", "rich_earth", "spirit_of_the_panda", "spore_shambler",
    "squirrel", "stalking_tiger", "stampede", "tiger_cub", "tiny_basilisk",
    "tyrannosaurus_rex", "verdant_tree", "wandering_mimic", "wisp",
    "young_treant"
})

#: **Every card the engine reads** -- the keyword table and the
#: static tables below are read over it, and the lobby offers the
#: heroes of `codex.cards.LANDED_COLORS`, the same colours. Each pair's
#: step adds its two.
LANDED_SET = BASIC_SET | RED | GREEN

#: Every landed slug whose text the engine plays for its numbers alone.
#: Written out rather than computed, so the commit that takes a card out
#: of it is the commit that gives it a handler.
#:
#: **Empty from step 6 to step 9**: step 5 took the basic set's keywords
#: out, and step 6 its triggers, spells, static grants, heroes' bands,
#: tokens and the surplus. **Step 10 landed red and green** played for
#: their numbers: a card whose whole text is keywords the engine reads
#: plays in full -- Mad Man, Nautical Dog, Centaur, Chameleon, Huntress,
#: Barkcoat Bear and the Hunter token -- and every other red or green
#: card with text is here, the six heroes' bands with them; their
#: keywords play meanwhile (Chameleon Lizzo's haste, say), their other
#: text waits for step 11. The heroes' hall's and the tech lab's text is
#: the engine's own (`RulesEngine.hero_limit`, `chosen_specs`).
UNIMPLEMENTED: frozenset = frozenset({
    # Red.
    "bamstamper_lizzo", "bloodburn", "bloodlust", "bloodrage_ogre",
    "bombaster", "burning_volley", "calypso_vystari", "captain_zane",
    "captured_bugblatter", "careless_musketeer", "chameleon_lizzo",
    "chaos_mirror", "charge", "cinderblast_dragon", "crash_bomber",
    "crashbarrow", "desperation", "detonate", "disguised_monkey",
    "doubleshot_archer", "drakk_ramhorn", "ember_sparks", "fire_dart",
    "firebat", "firehouse", "flame_arrow", "gunpoint_taxman", "hotter_fire",
    "jaina_stormborne", "kidnapping", "land_octopus", "lobber",
    "makeshift_rambaster", "marauder", "maximum_anarchy",
    "molting_firebird", "ogre_recruiter", "pillage", "pirate_gunship",
    "pirategang_commander", "rickety_mine", "sanatorium", "scorch",
    "shoddy_glider", "steam_tank", "surprise_attack", "war_drums",
    # Green.
    "argagarg_garg", "artisan_mantis", "behind_the_ferns",
    "blooming_ancient", "blooming_elm", "calamandra_moss", "circle_of_life",
    "dinosize", "dothram_horselord", "fairie_dragon", "feral_strike",
    "ferocity", "final_showdown", "forests_favor", "galina_glimmer",
    "gemscout_owl", "giant_panda", "gigadon", "guargum_eternal_sentinel",
    "ironbark_treant", "master_midori", "merfolk_prospector",
    "might_of_leaf_and_claw", "moments_peace", "moss_ancient",
    "murkwood_allies", "nature_reclaims", "playful_panda",
    "polymorph_squirrel", "potent_basilisk", "predator_tiger",
    "rampaging_elephant", "rampant_growth", "rich_earth",
    "spirit_of_the_panda", "spore_shambler", "stalking_tiger", "stampede",
    "tiny_basilisk", "tyrannosaurus_rex", "verdant_tree", "wandering_mimic",
    "young_treant",
})


# -- What a text does, part by part ------------------------------------------


@dataclass(frozen=True)
class Part:
    """
    One part of an effect, resolved in order. `choose` is what it may
    choose -- a key `RulesEngine.target_candidates` answers -- or `None`
    for a part that chooses nothing; `does` is what happens to it, a key
    `codex.flow.resolve.DOES` carries out; `amount` its number; `says`
    the part in words, for the question that asks it. A part with
    `choose` is **targeted** ({target}) where the card prints the
    symbol, which is what resist and the flagbearer answer to.
    """

    does: str
    choose: Optional[str] = None
    amount: int = 0
    says: str = ""
    targeted: bool = True


@dataclass(frozen=True)
class Effect:
    """
    A spell's, a trigger's or an ability's text, as its parts. `whole`
    marks one that is played only where every part can resolve -- Two
    Step, whose two partners are one effect: "Sacrifice this spell if
    either partner leaves play" has no meaning for a Two Step with one
    (UMR p. 22, the Card FAQ; the author, 2026-10-08) -- where every other
    effect does as much as it can.
    """

    key: str
    parts: tuple[Part, ...]
    whole: bool = False


def _effect(key: str, *parts: Part, whole: bool = False) -> Effect:
    return Effect(key, parts, whole)


EFFECTS: dict[str, Effect] = {effect.key: effect for effect in (
    # "Deal 1 damage to a patroller."
    _effect("spark", Part("damage", "patroller", 1, "deal 1 damage to a patroller")),
    # "Put a +1/+1 rune on a friendly unit or hero that doesn't have a
    # +1/+1 rune."
    _effect("bloom", Part("plus_rune", "friendly_unbloomed", 1,
                          "put a +1/+1 rune on a friendly unit or hero without one")),
    # "Put a -1/-1 rune on a unit or hero."
    _effect("wither", Part("minus_rune", "unit_or_hero", 1,
                           "put a -1/-1 rune on a unit or hero")),
    # "Deal 2 damage to a building."
    _effect("wrecking_ball", Part("damage", "building", 2, "deal 2 damage to a building")),
    # "Destroy a tech 0 or tech I unit. (Heroes aren't units.)"
    _effect("the_boot", Part("destroy", "unit_tech_0_1", 0, "destroy a tech 0 or tech I unit")),
    # "Give a unit or hero -4 ATK this turn."
    _effect("intimidate", Part("weaken", "unit_or_hero", 4, "give a unit or hero -4 ATK this turn")),
    # "Destroy a tech 0 unit, return a tech I unit to its owner's hand,
    # and gain control of a tech II unit." Three parts, each chosen as
    # it resolves (Sirlin, 2016-03-19).
    _effect(
        "final_smash",
        Part("destroy", "unit_tech_0", 0, "destroy a tech 0 unit"),
        Part("return", "unit_tech_1", 0, "return a tech I unit to its owner's hand"),
        Part("steal", "unit_tech_2", 0, "gain control of a tech II unit"),
    ),
    # "Give all of an opponent's tech 0 and I units -2/-1 until end of
    # turn." No {target}: every one of them.
    _effect("discord", Part("discord", None, 0, targeted=False)),
    # "Two of your units become dance partners if they aren't partnered
    # already. While you control both, they each get +2/+2." Two of them,
    # or it is not played (`Effect.whole`).
    _effect(
        "two_step",
        Part("partner", "own_unpartnered", 0, "choose a dance partner"),
        Part("partner", "own_unpartnered", 0, "choose the second dance partner"),
        whole=True,
    ),
    # "Sideline a patroller (move it out of the patrol zone), draw a
    # card, then you may put Appel Stomp on top of your draw pile."
    _effect(
        "appel_stomp",
        Part("sideline", "patroller", 0, "sideline a patroller"),
        Part("draw", None, 1, targeted=False),
    ),
    # Harmony's text is what it does in play (`harmony_dancer`,
    # `stop_the_music`); playing it does nothing else.
    _effect("harmony"),
    # "Arrives or attacks: Deal 1 damage to a building and repair 1
    # damage from another building."
    _effect(
        "brick_thief",
        Part("damage", "building", 1, "deal 1 damage to a building"),
        Part("repair", "other_building", 1, "repair 1 damage from another building"),
    ),
    # "Arrives: Deal 3 damage to a unit. (Heroes aren't units.)"
    _effect("hired_stomper", Part("damage", "unit", 3, "deal 3 damage to a unit")),
    # "Arrives or attacks: Deal 4 damage to a building."
    _effect("trojan_duck", Part("damage", "building", 4, "deal 4 damage to a building")),
    # "Arrives: Gets stealth this turn."
    _effect("sneaky_pig", Part("stealth", None, 0, targeted=False)),
    # Troq at 5: "Attacks: Deal 1 damage to that opponent's base." Its
    # {target} is the base, which has no resist and is no flagbearer, so
    # nothing is asked (Sirlin, 2016-03-03: the base of whoever controls
    # what he attacks).
    _effect("troq_bashar", Part("base_damage", None, 1, targeted=False)),
    # River at 3: "{exhaust} -> Sideline a tech 0 or tech I patroller."
    _effect("river_montoya", Part("sideline", "patroller_tech_0_1", 0,
                                  "sideline a tech 0 or tech I patroller")),
    # What Maestro grants each Virtuoso: "{exhaust} -> Deal 2 damage to a
    # building."
    _effect("maestro", Part("damage", "building", 2, "deal 2 damage to a building")),
    # Harmony, whenever its owner plays a spell: "summon a 0/1 neutral
    # Dancer token (limit: 3)."
    _effect("harmony_dancer", Part("dancer", None, 0, targeted=False)),
    # "Sacrifice Harmony -> Stop the music." (Your Dancers will flip
    # over!)
    _effect("stop_the_music", Part("stop_music", None, 0, targeted=False)),
)}


#: When each text happens: `play` for a spell's own text, `arrives` and
#: `attacks` for a unit's or hero's triggers, `ability` for an action it
#: offers. A hero's rows are keyed `(slug, first level of the band)`,
#: since a band's text is the hero's only from that level on -- read the
#: way its keywords are (`hero_rows`).
TEXT: dict = {
    "spark": (("play", "spark"),),
    "bloom": (("play", "bloom"),),
    "wither": (("play", "wither"),),
    "wrecking_ball": (("play", "wrecking_ball"),),
    "the_boot": (("play", "the_boot"),),
    "intimidate": (("play", "intimidate"),),
    "final_smash": (("play", "final_smash"),),
    "discord": (("play", "discord"),),
    "two_step": (("play", "two_step"),),
    "appel_stomp": (("play", "appel_stomp"),),
    "harmony": (("play", "harmony"),),
    "brick_thief": (("arrives", "brick_thief"), ("attacks", "brick_thief")),
    "hired_stomper": (("arrives", "hired_stomper"),),
    "trojan_duck": (("arrives", "trojan_duck"), ("attacks", "trojan_duck")),
    "sneaky_pig": (("arrives", "sneaky_pig"),),
    ("troq_bashar", 5): (("attacks", "troq_bashar"),),
    ("river_montoya", 3): (("ability", "river_montoya"),),
}


def rows(slug: str, level: Optional[int] = None) -> tuple[tuple[str, str], ...]:
    """
    What `slug`'s text does, as `(when, effect)` rows: a card's own, or
    a hero's from every band it has reached at `level`.
    """
    if level is None:
        return TEXT.get(slug, ())
    found = []
    for key, entries in TEXT.items():
        if isinstance(key, tuple) and key[0] == slug and key[1] <= level:
            found.extend(entries)
    return tuple(found)


def triggers(slug: str, when: str, level: Optional[int] = None) -> tuple[str, ...]:
    """The effects `slug` triggers `when` -- "arrives" or "attacks"."""
    return tuple(effect for moment, effect in rows(slug, level) if moment == when)


# -- The static texts the engine reads ---------------------------------------
#
# Each is asked of `RulesEngine` and answered there from the cards in
# play; these say which card does what, so a later spec adds a row.

#: "Your virtuosos have haste." -- Nimble Fencer, herself included
#: (Sirlin, 2016-03-04).
GRANTS_VIRTUOSO_HASTE = frozenset({"nimble_fencer"})
#: "Your units and heroes have swift strike." -- Blademaster, while he
#: is in play under your control (Sirlin, 2016-03-04).
GRANTS_SWIFT_STRIKE = frozenset({"blademaster"})
#: "Your other units get +1 ATK. Your Virtuosos get +2/+1, instead." --
#: Grounded Guide, stacking (Sirlin, 2016-03-02).
GUIDES = frozenset({"grounded_guide"})
#: "Your virtuosos cost 0 to play and gain '{exhaust} -> Deal 2 damage to
#: a building.'" -- Maestro.
MAESTROS = frozenset({"maestro"})
#: "This gets +1 ATK for each damage on her." -- Star-Crossed Starlet.
ATK_PER_DAMAGE = frozenset({"starcrossed_starlet"})
#: "Upkeep: This takes 1 damage." -- Star-Crossed Starlet.
UPKEEP_SELF_DAMAGE = frozenset({"starcrossed_starlet"})
#: "Upkeep: Draw a card." -- the surplus.
UPKEEP_DRAW = frozenset({"surplus"})
#: "Whenever an opponent plays a spell or ability that can {target} a
#: flagbearer, it must {target} a flagbearer at least once." -- read off
#: the subtype, as the rulings' "flagbearer" is.
FLAGBEARER = "Flagbearer"
#: The subtype Nimble Fencer, Grounded Guide and Maestro name.
VIRTUOSO = "Virtuoso"
#: River at 5: "Your tech 0 units cost 1 less to play." -- to 0 at the
#: least (Sirlin, 2016-03-02).
TECH_0_DISCOUNT = {("river_montoya", 5): 1}
#: The add-ons whose text is a rule the engine answers by itself: the
#: heroes' hall's "You may have an additional hero in play"
#: (`RulesEngine.hero_limit`) and the tech lab's "Unlock an additional
#: spec" (`RulesEngine.chosen_specs`, `spec_choices`).
ENGINE_RULES = frozenset({"heroes_hall", "tech_lab"})
#: The ongoing spells with channeling, and the hero spec each needs.
CHANNELING = {"harmony": "finesse", "two_step": "finesse"}
#: Two Step's partners' bonus, while both are held.
PARTNER_BONUS = (2, 2)
#: Harmony's Dancers: the token, its flip, and the limit -- the
#: `General` rulings' Limit X: a summon that would pass three stops at
#: three.
DANCER = "dancer"
ANGRY_DANCER = "angry_dancer"
DANCER_LIMIT = 3
HARMONY = "harmony"
TWO_STEP = "two_step"
APPEL_STOMP = "appel_stomp"

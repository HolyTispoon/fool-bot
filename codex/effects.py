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

#: The tokens of another colour that red and green summon: Surprise
#: Attack's Sharks and Argagarg's Water Elemental, both blue. Landed with
#: the cards that make them, so their keywords are read.
BORROWED_TOKENS = frozenset({"shark", "water_elemental"})

#: **Every card the engine reads** -- the keyword table and the
#: static tables below are read over it, and the lobby offers the
#: heroes of `codex.cards.LANDED_COLORS`, the same colours. Each pair's
#: step adds its two.
LANDED_SET = BASIC_SET | RED | GREEN | BORROWED_TOKENS

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
    "bloodlust", "bloodrage_ogre", "chameleon_lizzo", "chaos_mirror",
    "drakk_ramhorn", "hotter_fire", "kidnapping", "land_octopus",
    "war_drums",
    # Green.
    "behind_the_ferns", "blooming_elm", "calamandra_moss",
    "dothram_horselord", "fairie_dragon", "ferocity", "final_showdown",
    "galina_glimmer", "gemscout_owl", "master_midori",
    "might_of_leaf_and_claw", "moss_ancient", "polymorph_squirrel",
    "spirit_of_the_panda",
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

    Step 11 gave a part the shapes red and green ask for:

    - `building`: what it deals to a building where that differs from
      `amount` -- Fire Dart's "3 damage to a unit or 2 damage to a
      building".
    - `most` and `least`: how many things it chooses, one at a time --
      "up to two" is `most=2, least=0`, "you may" `least=0` -- each pick
      done as it is chosen, a **Done** offered once `least` are chosen.
      `most=0` is "as many as the damage": Burning Volley.
    - `does="divide"`: the picks share `amount` damage, at least 1 each
      (the Card FAQ), split by the caster once they are chosen
      (`DIVIDE_DAMAGE`).
    - `does="mode"` with `modes`: "choose one", asked (`MODE_CHOICE`) --
      or both, where the frame was boosted -- and `only` on the parts
      that belong to one mode.
    - `when="boosted"`: a part done only where the card was boosted.
    - `token`: the token a summoning part makes.
    """

    does: str
    choose: Optional[str] = None
    amount: int = 0
    says: str = ""
    targeted: bool = True
    building: Optional[int] = None
    most: int = 1
    least: int = 1
    only: Optional[str] = None
    modes: tuple = ()
    when: Optional[str] = None
    token: Optional[str] = None


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
    #: "... then trash this card": the spell leaves the game once it has
    #: resolved instead of going to the discard (Detonate, Nature
    #: Reclaims; UMR p. 13).
    trash_after: bool = False
    #: The whole text in a few words, for a button that offers it; the
    #: first part's `says` where it is empty.
    says: str = ""


def _effect(key: str, *parts: Part, whole: bool = False, trash_after: bool = False,
            says: str = "") -> Effect:
    return Effect(key, parts, whole, trash_after, says)


@dataclass(frozen=True)
class Cost:
    """
    What an ability action costs (UMR p. 7), all of it paid as it is
    used and none of it unless all of it can be (UMR p. 8): exhausting
    its card -- which arrival fatigue forbids without haste -- gold,
    sacrificing its card, runes off its card (`plus` for +1/+1 runes, or
    a named rune, "blood"), cards discarded from the hand. `needs_spell`
    is Calypso Vystari's "If you played a spell this turn", which the
    Card FAQ reads as a condition of using it at all.
    """

    exhaust: bool = False
    gold: int = 0
    sacrifice: bool = False
    runes: tuple = ()
    discard: int = 0
    needs_spell: bool = False


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

    # -- Red and green: the costs and the resources (step 11) --------------
    # Merfolk Prospector: "{exhaust} -> Gain {gold:1}."
    _effect("merfolk_prospector", Part("gain_gold", None, 1, "gain 1 gold", targeted=False)),
    # Rickety Mine: "{exhaust} -> Gain {gold:3} and flip a coin. Heads:
    # Phew! Tails: Sacrifice Rickety Mine and your base takes 2 damage."
    _effect(
        "rickety_mine",
        Part("gain_gold", None, 3, "gain 3 gold", targeted=False),
        Part("coin", None, 2, targeted=False),
        says="gain 3 gold and flip a coin",
    ),
    # Pillage: "Deal 1 damage to a base. Steal {gold:1} from that player.
    # If you have a Pirate, instead deal 2 damage and steal {gold:2}."
    _effect("pillage", Part("pillage", "base", 1,
                            "deal 1 damage to a base and steal 1 gold from that player")),
    # Detonate: "Trash a worker or building card (not add-on), then trash
    # this card."
    _effect("detonate", Part("trash", "worker_or_building_card", 0,
                             "trash a worker or a building card"), trash_after=True),
    # Nature Reclaims: "Trash an upgrade, ongoing spell, or building card
    # (not add-on), then trash this card."
    _effect("nature_reclaims", Part("trash", "upgrade_spell_or_building_card", 0,
                                    "trash an upgrade, an ongoing spell or a building card"),
            trash_after=True),
    # Desperation: "If your hand is empty, trash this card and draw three
    # cards. Discard your hand at the end of the main phase."
    _effect("desperation", Part("desperation", None, 3, targeted=False)),
    # -- Red and green: the spells, the triggers and the abilities ---------
    # (step 11). Each row beside the sentence it was built from.

    # Fire Dart: "Deal 3 damage to a unit or 2 damage to a building."
    _effect("fire_dart", Part("damage", "unit_or_building", 3,
                              "deal 3 damage to a unit or 2 damage to a building", building=2)),
    # Flame Arrow: "Deal 4 damage to a unit or hero or 3 damage to a building."
    _effect("flame_arrow", Part("damage", "unit_hero_or_building", 4,
                                "deal 4 damage to a unit or hero or 3 damage to a building",
                                building=3)),
    # Scorch: "Deal 2 damage to a patroller or building."
    _effect("scorch", Part("damage", "patroller_or_building", 2,
                           "deal 2 damage to a patroller or building")),
    # Ember Sparks: "Deal 3 damage divided as you choose among one, two,
    # or three patrollers and/or buildings."
    _effect("ember_sparks", Part("divide", "patroller_or_building", 3,
                                 "choose a patroller or building to share 3 damage", most=3)),
    # Burning Volley: "Deal 5 damage divides as you choose among any
    # number of units, heroes, and/or buildings."
    _effect("burning_volley", Part("divide", "unit_hero_or_building", 5,
                                   "choose a unit, hero or building to share 5 damage", most=0)),
    # Firebat: "{gold:1}, {exhaust} -> Deal 2 damage to a patroller or building."
    _effect("firebat", Part("damage", "patroller_or_building", 2,
                            "deal 2 damage to a patroller or building")),
    # Lobber: "{exhaust} -> Deal 1 damage to a building."
    _effect("lobber", Part("damage", "building", 1, "deal 1 damage to a building")),
    # Bombaster: "{gold:1}, Sacrifice Bombaster -> Deal 2 damage to a
    # patrolling unit."
    _effect("bombaster", Part("damage", "patrolling_unit", 2, "deal 2 damage to a patrolling unit")),
    # Careless Musketeer: "{exhaust} -> Deal 1 damage to a unit or building
    # and 1 damage to your base."
    _effect(
        "careless_musketeer",
        Part("damage", "unit_or_building", 1, "deal 1 damage to a unit or building"),
        Part("own_base_damage", None, 1, targeted=False),
        says="deal 1 damage to a unit or building and 1 to your base",
    ),
    # Firehouse: "{exhaust} -> Deal 2 damage to a unit, hero, or building.
    # If you destroy it that way, ready this."
    _effect("firehouse", Part("damage_ready", "unit_hero_or_building", 2,
                              "deal 2 damage to a unit, hero or building")),
    # Bloodburn: "{exhaust}, remove two blood runes -> Deal 1 damage to a
    # unit or building."
    _effect("bloodburn", Part("damage", "unit_or_building", 1, "deal 1 damage to a unit or building")),
    # Calypso Vystari: "{exhaust} -> If you played a spell this turn,
    # sideline a patroller."
    _effect("calypso_vystari", Part("sideline", "patroller", 0, "sideline a patroller")),
    # Jaina at 4: "{exhaust} -> Deal 1 damage to a patrolling unit or
    # building. {target}"
    _effect("jaina_stormborne", Part("damage", "patrolling_unit_or_building", 1,
                                     "deal 1 damage to a patrolling unit or building")),
    # Jaina at 7: "{exhaust} -> Deal 3 damage to a unit or building. {target}"
    _effect("jaina_stormborne_max", Part("damage", "unit_or_building", 3,
                                         "deal 3 damage to a unit or building")),
    # Captain Zane at 6: "Max level: Shove a patroller to an empty slot in
    # its patrol zone, then deal 1 damage to it. {target}" -- the slot
    # anywhere empty, and the damage alone where none is (his rulings).
    _effect(
        "captain_zane",
        Part("shove", "patroller", 0, "shove a patroller"),
        Part("shove_slot", "empty_slot", 0, "choose the empty slot it is shoved to", targeted=False),
        Part("damage_shoved", None, 1, targeted=False),
    ),
    # Drakk at 1: "Dies: Deal 1 damage to each opponent's base. {target}"
    _effect("drakk_ramhorn", Part("base_damage", None, 1, targeted=False)),
    # Argagarg at 1: "Arrives: Summon a 0/1 green Wisp token."
    _effect("argagarg_wisp", Part("token", None, 1, targeted=False, token="wisp")),
    # Argagarg at 3: "{exhaust} -> Give a unit +1 ATK/+1 armor this turn. {target}"
    _effect("argagarg_garg", Part("buff", "unit", 1, "give a unit +1 ATK and +1 armor this turn")),
    # Argagarg at 5: "Max Level: Summon a 3/3 blue Water Elemental token
    # with anti-air."
    _effect("argagarg_garg_max", Part("token", None, 1, targeted=False, token="water_elemental")),
    # Calamandra at 1: "Discard two cards -> Calamandra gets stealth this
    # turn." The two cards are hers to choose, from her controller's hand.
    _effect(
        "calamandra_moss",
        Part("discard", "hand_card", 0, "discard a card", targeted=False, most=2, least=2),
        Part("stealth", None, 0, targeted=False),
        says="get stealth this turn",
    ),
    # Calamandra at 5: "{gold:4}, {exhaust} -> Search your codex for a
    # tiger unit and put it into play." -- free, and needing no building
    # (her ruling).
    _effect("calamandra_moss_max", Part("put_into_play", "codex_tiger", 0,
                                        "put a tiger from your codex into play", targeted=False)),
    # Spore Shambler: "Arrives: Put two +1/+1 runes on this." and "{gold:1}
    # or {exhaust}, then remove a +1/+1 rune -> Put a +1/+1 rune on
    # another unit." -- one ability, two ways to pay.
    _effect("spore_shambler", Part("runes_on_self", None, 2, targeted=False)),
    _effect("spore_shambler_gold", Part("plus_rune", "other_unit", 1,
                                        "put a +1/+1 rune on another unit")),
    _effect("spore_shambler_exhaust", Part("plus_rune", "other_unit", 1,
                                           "put a +1/+1 rune on another unit")),
    # Blooming Ancient: "Remove a +1/+1 rune -> Put a +1/+1 rune on another
    # unit." (Its arrival runes are the arrival's: `GROWS_ON_ARRIVAL`.)
    _effect("blooming_ancient", Part("plus_rune", "other_unit", 1, "put a +1/+1 rune on another unit")),
    # Blooming Elm: "{exhaust} -> Put three +1/+1 runes on a unit or one on
    # a hero if that unit or hero doesn't have any +1/+1 runes."
    _effect("blooming_elm", Part("elm_runes", "unit_or_hero", 3,
                                 "put three +1/+1 runes on a unit, or one on a hero, without any")),
    # Verdant Tree: "{exhaust} -> Your tech buildings build instantly this turn."
    _effect("verdant_tree", Part("instant_build", None, 0, "build your tech buildings instantly this turn",
                                 targeted=False)),
    # Sanatorium: "{gold:1}, {exhaust} -> Draw a card. Put up to two tech
    # 0, I and/or II units from your hand into play. Those units gain haste
    # and ephemeral."
    _effect(
        "sanatorium",
        Part("draw", None, 1, targeted=False),
        Part("sanatorium", "hand_unit_tech_0_2", 0,
             "put a tech 0, I or II unit from your hand into play", targeted=False, most=2, least=0),
        says="draw a card and put up to two units from your hand into play",
    ),
    # Bamstamper Lizzo: "Arrives: Deal 3 damage to a unit." -- mandatory,
    # its own units and itself included (its ruling).
    _effect("bamstamper_lizzo", Part("damage", "unit", 3, "deal 3 damage to a unit")),
    # Artisan Mantis: "Arrives: Repair 3 damage from a building."
    _effect("artisan_mantis", Part("repair", "other_building", 3, "repair 3 damage from a building",
                                   targeted=False)),
    # Potent Basilisk: "Arrives: You may destroy an upgrade or ongoing spell."
    _effect("potent_basilisk", Part("destroy_card", "upgrade_or_ongoing", 0,
                                    "destroy an upgrade or ongoing spell", least=0)),
    # Pirategang Commander: "Arrives: Summon three 2/2 red Pirate tokens."
    _effect("pirategang_commander", Part("token", None, 3, targeted=False, token="pirate")),
    # Pirategang Commander's units: "Dies: deal 1 damage to each opposing
    # base. {target}"
    _effect("pirategang_dies", Part("base_damage", None, 1, targeted=False)),
    # Moss Ancient: "Arrives or attacks: Summons three 1/1 green Squirrel tokens."
    _effect("moss_ancient", Part("token", None, 3, targeted=False, token="squirrel")),
    # Playful Panda, Giant Panda: "Arrives: Exhausted. Summon a 0/1 green
    # Wisp token."
    _effect("panda", Part("exhaust_self", None, 0, targeted=False),
            Part("token", None, 1, targeted=False, token="wisp")),
    # Young Treant: "Arrives: Draw a card."
    _effect("young_treant", Part("draw", None, 1, targeted=False)),
    # Fairie Dragon: "Arrives: You may put a feather rune on a tech I or II unit."
    _effect("fairie_dragon", Part("feather", "unit_tech_1_2", 0,
                                  "put a feather rune on a tech I or II unit", least=0)),
    # Tyrannosaurus Rex: "Arrives: Destroy up to two units, upgrades,
    # and/or workers." -- in any mix, a worker trashed (its rulings).
    _effect("tyrannosaurus_rex", Part("destroy_any", "unit_upgrade_or_workers", 0,
                                      "destroy a unit, an upgrade or a worker", most=2, least=0)),
    # Disguised Monkey: "Arrives: Gets stealth this turn"
    _effect("disguised_monkey", Part("stealth", None, 0, targeted=False)),
    # Marauder: "Arrives: If you boosted, trash a worker." -- any player's
    # (its ruling).
    _effect("marauder", Part("trash", "workers", 0, "trash a worker", targeted=False, when="boosted")),
    # Cinderblast Dragon: "Arrives or attacks: You may play a non-ultimate
    # Fire spell from your hand or codex for free. (Then discard the spell.)"
    _effect("cinderblast_dragon", Part("free_spell", "fire_spell", 0,
                                       "play a non-ultimate Fire spell from your hand or codex, free",
                                       targeted=False, least=0)),
    # Doubleshot Archer: "Attacks: Deal 3 damage to that opponent's base."
    _effect("doubleshot_archer", Part("base_damage", None, 3, targeted=False)),
    # Ogre Recruiter: "Attacks: If this survives the combat, gain control
    # of a tech 0 or tech I unit." -- after the damage (`AFTER_COMBAT`).
    _effect("ogre_recruiter", Part("steal", "unit_tech_0_1", 0, "gain control of a tech 0 or tech I unit")),
    # Molting Firebird: "Damages a building: Deal 1 damage to every unit and
    # hero that opponent controls."
    _effect("molting_firebird", Part("firebird", None, 1, targeted=False)),
    # Crash Bomber: "Dies on your turn: Deal 1 damage to a patroller or
    # building." / "Dies on another player's turn: Deal 1 damage to that
    # player's base."
    _effect("crash_bomber", Part("damage", "patroller_or_building", 1,
                                 "deal 1 damage to a patroller or building")),
    _effect("crash_bomber_away", Part("active_base_damage", None, 1, targeted=False)),
    # Captured Bugblatter: "Whenever a unit dies on an opponent's turn, their
    # base takes 1 damage. Whenever a unit dies on your turn, deal 1 damage
    # to an opponent's base." -- the one opponent's base, either way.
    _effect("captured_bugblatter", Part("base_damage", None, 1, targeted=False)),
    # Maximum Anarchy: "Destroy all units and heroes."
    _effect("maximum_anarchy", Part("anarchy", None, 0, targeted=False)),
    # Bloodlust: "Give up to two units and/or heroes +1 ATK and haste this
    # turn. They each take 1 damage at end of turn."
    _effect("bloodlust", Part("bloodlust", "unit_or_hero", 1,
                              "give a unit or hero +1 ATK and haste this turn", most=2, least=0)),
    # Charge: "Give one of your units haste and +1 ATK this turn."
    _effect("charge", Part("charge", "own_unit", 1, "give one of your units haste and +1 ATK this turn")),
    # Kidnapping: "Gain control of an opposing tech 0, I, or II unit until
    # end of turn. Ready it and it gets haste until end of turn."
    _effect("kidnapping", Part("kidnap", "opposing_unit_tech_0_2", 0,
                               "gain control of an opposing tech 0, I or II unit until the end of the turn")),
    # Surprise Attack: "Summon two 3/1 blue Shark tokens with haste and ephemeral."
    _effect("surprise_attack", Part("token", None, 2, targeted=False, token="shark")),
    # Moment's Peace: "Until your next turn, your units can't patrol and
    # opposing units can't attack you."
    _effect("moments_peace", Part("peace", None, 0, targeted=False)),
    # Circle of Life: "Sacrifice a green unit. If you do, put a green unit
    # one tech higher that costs 5 or less from your codex into play."
    _effect(
        "circle_of_life",
        Part("circle_sacrifice", "own_green_unit", 0, "sacrifice a green unit", targeted=False),
        Part("put_into_play", "codex_circle", 0,
             "put a green unit one tech higher, costing 5 or less, from your codex into play",
             targeted=False),
    ),
    # Feral Strike: "Choose one: Fetch up to two units from your codex,
    # reveal them, then put them in your hand; or put up to two units from
    # your hand into play if you have tech buildings of the same tech level
    # as them. If you boosted, choose both."
    _effect(
        "feral_strike",
        Part("mode", modes=(("fetch", "fetch up to two units from your codex"),
                            ("put", "put up to two units from your hand into play")),
             says="choose one"),
        Part("fetch", "codex_unit", 0, "fetch a unit from your codex", targeted=False,
             most=2, least=0, only="fetch"),
        Part("put_into_play", "hand_unit_built", 0, "put a unit from your hand into play",
             targeted=False, most=2, least=0, only="put"),
    ),
    # Murkwood Allies: "Choose one: Summon a 4/4 green Beast token; or summon
    # four 1/1 green Frog tokens. If you boosted, choose both."
    _effect(
        "murkwood_allies",
        Part("mode", modes=(("beast", "summon a 4/4 Beast"), ("frogs", "summon four 1/1 Frogs")),
             says="choose one"),
        Part("token", None, 1, targeted=False, token="beast", only="beast"),
        Part("token", None, 4, targeted=False, token="frog", only="frogs"),
    ),
    # Stampede: "Your units get +3 ATK / +3 armor this turn. Excess combat
    # damage they would deal to units and heroes hits that opponent's base."
    _effect("stampede", Part("stampede", None, 3, targeted=False)),
    # Ferocity: "Your units get armor piercing and swift strike until your
    # next upkeep."
    _effect("ferocity", Part("ferocity", None, 0, targeted=False)),
    # Dinosize: "Give a unit or hero +6 ATK / +6 armor this turn."
    _effect("dinosize", Part("buff", "unit_or_hero", 6, "give a unit or hero +6 ATK and +6 armor this turn")),
    # Rampant Growth: "Give a unit or hero +2 ATK / +2 armor this turn."
    _effect("rampant_growth", Part("buff", "unit_or_hero", 2,
                                   "give a unit or hero +2 ATK and +2 armor this turn")),
    # Forest's Favor: Bloom's own words.
    _effect("forests_favor", Part("plus_rune", "friendly_unbloomed", 1,
                                  "put a +1/+1 rune on a friendly unit or hero without one")),
    # Final Showdown: "Attach to your Balance hero." ... "Summon two 3/3
    # green Hunter tokens with anti-air for an opponent, so that it's fair."
    _effect(
        "final_showdown",
        Part("attach", "own_balance_hero", 0, "attach to your Balance hero"),
        Part("token_for_opponent", None, 2, targeted=False, token="hunter"),
    ),
    # Spirit of the Panda: "Attach to a unit." -- any player's (the Card FAQ).
    _effect("spirit_of_the_panda", Part("attach", "unit", 0, "attach to a unit")),
    # The ongoing spells whose text is what they grant in play: Behind
    # the Ferns, War Drums, and the upgrade Hotter Fire's.
    _effect("behind_the_ferns"),
    _effect("war_drums"),
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
    # Red and green (step 11).
    "merfolk_prospector": (("ability", "merfolk_prospector"),),
    "rickety_mine": (("ability", "rickety_mine"),),
    "pillage": (("play", "pillage"),),
    "detonate": (("play", "detonate"),),
    "nature_reclaims": (("play", "nature_reclaims"),),
    "desperation": (("play", "desperation"),),
    # The spells.
    "fire_dart": (("play", "fire_dart"),),
    "flame_arrow": (("play", "flame_arrow"),),
    "scorch": (("play", "scorch"),),
    "ember_sparks": (("play", "ember_sparks"),),
    "burning_volley": (("play", "burning_volley"),),
    "maximum_anarchy": (("play", "maximum_anarchy"),),
    "bloodlust": (("play", "bloodlust"),),
    "charge": (("play", "charge"),),
    "kidnapping": (("play", "kidnapping"),),
    "surprise_attack": (("play", "surprise_attack"),),
    "moments_peace": (("play", "moments_peace"),),
    "circle_of_life": (("play", "circle_of_life"),),
    "feral_strike": (("play", "feral_strike"),),
    "murkwood_allies": (("play", "murkwood_allies"),),
    "stampede": (("play", "stampede"),),
    "ferocity": (("play", "ferocity"),),
    "dinosize": (("play", "dinosize"),),
    "rampant_growth": (("play", "rampant_growth"),),
    "forests_favor": (("play", "forests_favor"),),
    "final_showdown": (("play", "final_showdown"),),
    "spirit_of_the_panda": (("play", "spirit_of_the_panda"),),
    "behind_the_ferns": (("play", "behind_the_ferns"),),
    "war_drums": (("play", "war_drums"),),
    # The arrives, attacks and dies triggers.
    "bamstamper_lizzo": (("arrives", "bamstamper_lizzo"),),
    "artisan_mantis": (("arrives", "artisan_mantis"),),
    "potent_basilisk": (("arrives", "potent_basilisk"),),
    "pirategang_commander": (("arrives", "pirategang_commander"),),
    "moss_ancient": (("arrives", "moss_ancient"), ("attacks", "moss_ancient")),
    "playful_panda": (("arrives", "panda"),),
    "giant_panda": (("arrives", "panda"),),
    "young_treant": (("arrives", "young_treant"),),
    "spore_shambler": (("arrives", "spore_shambler"), ("ability", "spore_shambler_gold"),
                       ("ability", "spore_shambler_exhaust")),
    "fairie_dragon": (("arrives", "fairie_dragon"),),
    "tyrannosaurus_rex": (("arrives", "tyrannosaurus_rex"),),
    "disguised_monkey": (("arrives", "disguised_monkey"),),
    "marauder": (("arrives", "marauder"),),
    "cinderblast_dragon": (("arrives", "cinderblast_dragon"), ("attacks", "cinderblast_dragon")),
    "doubleshot_archer": (("attacks", "doubleshot_archer"),),
    # The abilities.
    "bloodburn": (("ability", "bloodburn"),),
    "bombaster": (("ability", "bombaster"),),
    "careless_musketeer": (("ability", "careless_musketeer"),),
    "calypso_vystari": (("ability", "calypso_vystari"),),
    "firebat": (("ability", "firebat"),),
    "firehouse": (("ability", "firehouse"),),
    "lobber": (("ability", "lobber"),),
    "sanatorium": (("ability", "sanatorium"),),
    "blooming_ancient": (("ability", "blooming_ancient"),),
    "blooming_elm": (("ability", "blooming_elm"),),
    "verdant_tree": (("ability", "verdant_tree"),),
    # The heroes' bands.
    ("jaina_stormborne", 4): (("ability", "jaina_stormborne"),),
    ("jaina_stormborne", 7): (("ability", "jaina_stormborne_max"),),
    ("captain_zane", 6): (("max_level", "captain_zane"),),
    ("drakk_ramhorn", 1): (("dies", "drakk_ramhorn"),),
    ("argagarg_garg", 1): (("arrives", "argagarg_wisp"),),
    ("argagarg_garg", 3): (("ability", "argagarg_garg"),),
    ("argagarg_garg", 5): (("max_level", "argagarg_garg_max"),),
    ("calamandra_moss", 1): (("ability", "calamandra_moss"),),
    ("calamandra_moss", 5): (("ability", "calamandra_moss_max"),),
}

#: What each ability action costs (`Cost`), by its effect.
COSTS: dict[str, Cost] = {
    "river_montoya": Cost(exhaust=True),
    "maestro": Cost(exhaust=True),
    "stop_the_music": Cost(sacrifice=True),
    "merfolk_prospector": Cost(exhaust=True),
    "rickety_mine": Cost(exhaust=True),
    "bloodburn": Cost(exhaust=True, runes=("blood", 2)),
    "bombaster": Cost(gold=1, sacrifice=True),
    "careless_musketeer": Cost(exhaust=True),
    "calypso_vystari": Cost(exhaust=True, needs_spell=True),
    "firebat": Cost(gold=1, exhaust=True),
    "firehouse": Cost(exhaust=True),
    "lobber": Cost(exhaust=True),
    "sanatorium": Cost(gold=1, exhaust=True),
    "spore_shambler_gold": Cost(gold=1, runes=("plus", 1)),
    "spore_shambler_exhaust": Cost(exhaust=True, runes=("plus", 1)),
    "blooming_ancient": Cost(runes=("plus", 1)),
    "blooming_elm": Cost(exhaust=True),
    "verdant_tree": Cost(exhaust=True),
    "jaina_stormborne": Cost(exhaust=True),
    "jaina_stormborne_max": Cost(exhaust=True),
    "argagarg_garg": Cost(exhaust=True),
    "calamandra_moss": Cost(discard=2),
    "calamandra_moss_max": Cost(gold=4, exhaust=True),
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
CHANNELING = {
    "harmony": "finesse", "two_step": "finesse",
    "behind_the_ferns": "feral", "war_drums": "blood",
}
#: The ongoing spells without it, which attach to what they choose and
#: are sacrificed when it leaves play (UMR p. 15): Spirit of the Panda to
#: a unit, Final Showdown to its Balance hero.
ATTACHING = frozenset({"spirit_of_the_panda", "final_showdown"})
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

# -- Red and green's static texts (step 11) ------------------------------------

#: "Can't attack" -- Young Treant; Gemscout Owl's "Flying but can't
#: attack."
CANT_ATTACK = frozenset({"young_treant", "gemscout_owl"})
#: "Can't patrol." -- Makeshift Rambaster, Land Octopus.
CANT_PATROL = frozenset({"makeshift_rambaster", "land_octopus"})
#: "+X ATK when attacking buildings." -- read as the attack's damage is
#: dealt, never as the attack is declared (Behind the Ferns' ruling).
ATTACKING_BUILDINGS_ATK = {"makeshift_rambaster": 2, "steam_tank": 4}
#: "... is unstoppable by tech 0 units" -- it ignores tech 0 patrollers
#: when attacking: Predator Tiger, Tiny Basilisk.
UNSTOPPABLE_BY_TECH_0 = frozenset({"predator_tiger", "tiny_basilisk"})
#: "Tiny Basilisk is unattackable ... by tech 0 units."
UNATTACKABLE_BY_TECH_0 = frozenset({"tiny_basilisk"})
#: "Stealth while attacking a unit." -- Stalking Tiger.
STEALTH_ATTACKING_UNITS = frozenset({"stalking_tiger"})
#: "... is invisible while you have a Feral hero." -- the spec whose hero
#: in play under its controller makes it invisible.
INVISIBLE_WITH_HERO = {"stalking_tiger": "feral"}
#: Ironbark Treant's "-2 ATK / +2 armor while patrolling" -- on the
#: opponents' turns only, and only while in the patrol zone (its
#: rulings): (ATK, armor).
WHILE_PATROLLING = {"ironbark_treant": (-2, 2)}
#: "The first time Rampaging Elephant exhausts each turn, ready him."
READIES_ONCE = frozenset({"rampaging_elephant"})
#: Wandering Mimic: "As long as a unit or hero with flying is in play,
#: Wandering Mimic has flying. The same is true for overpower, haste,
#: sparkshot, untargetable, and stealth." -- never from another Mimic
#: (the Card FAQ).
MIMIC = "wandering_mimic"
MIMICKED = ("Flying", "Overpower", "Haste", "Sparkshot", "Untargetable", "Stealth")
#: Master Midori at 8: "During your turn: Flying".
FLYING_ON_OWN_TURN = {("master_midori", 8)}

#: Rich Earth: "You may hire workers for free." -- the card still goes,
#: and still once a turn (its rulings).
FREE_HIRE = frozenset({"rich_earth"})
#: Gigadon: "costs {gold:1} less to play for each green unit you have" --
#: to play it from the hand alone; to anything that reads its cost it is
#: still 9 (its rulings).
LESS_PER_GREEN_UNIT = {"gigadon": 1}
#: Pirategang Commander: "You may play tech I or II Blood units for free
#: and without any tech buildings." -- the spec and tech levels it frees.
FREE_UNITS = {"pirategang_commander": ("blood", (1, 2))}
#: Guargum: "You may play Growth spells for free and without having a
#: Growth Hero." -- an ultimate too, and the turn he arrives (his ruling).
FREE_SPELLS = {"guargum_eternal_sentinel": "growth"}
#: The coin a journal records beside the shuffles it replays (Rickety
#: Mine): `[COIN, "heads"]`. No slug begins with "@".
COIN = "@coin"
#: A Pirate, for Pillage's "If you have a Pirate".
PIRATE = "Pirate"

#: "Whenever another unit or hero of yours arrives, put a +1/+1 rune on
#: this." -- Blooming Ancient.
GROWS_ON_ARRIVAL = frozenset({"blooming_ancient"})
#: "Whenever a unit dies, put a blood rune on this (limit: 4)." -- Bloodburn.
BLOOD_RUNES = {"bloodburn": 4}
#: "Whenever a unit dies ..., [that opponent's] base takes 1 damage." --
#: Captured Bugblatter, itself included (its ruling).
ON_ANY_DEATH = {"captured_bugblatter": "captured_bugblatter"}
#: Crash Bomber's two dies effects: on its controller's turn, and on
#: another's.
DIES_ON_YOUR_TURN = {"crash_bomber": "crash_bomber"}
DIES_ON_THEIR_TURN = {"crash_bomber": "crash_bomber_away"}
#: Pirategang Commander: "Your units have 'Dies: deal 1 damage to each
#: opposing base.'"
GRANTS_DIES = {"pirategang_commander": "pirategang_dies"}
#: The fights' own triggers, read where combat damage is dealt
#: (`codex.flow.combat`): Gunpoint Taxman's "kills a patroller: steal
#: {gold:1}", Predator Tiger's "deals combat damage to a base: trash a
#: worker at that base", Molting Firebird's "Damages a building:",
#: Might of Leaf and Claw's growth rune, Ogre Recruiter's control after
#: the damage, and Captain Zane's kills at 4.
STEALS_ON_PATROLLER_KILL = {"gunpoint_taxman": 1}
TRASHES_WORKER_ON_BASE_DAMAGE = frozenset({"predator_tiger"})
ON_DAMAGING_A_BUILDING = {"molting_firebird": "molting_firebird"}
GROWTH_RUNES = frozenset({"might_of_leaf_and_claw"})
AFTER_COMBAT = {"ogre_recruiter": "ogre_recruiter"}
KILL_BONUSES = {("captain_zane", 4): {"scavenger": "gold", "technician": "card"}}

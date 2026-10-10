"""
What each card's text does -- the table the engine reads -- and the
list of the cards whose text the engine does not do yet: empty from
step 6 to step 9, red and green's in step 10, and empty again since
step 11.

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

**Step 11 emptied it again** for red and green: the same tables, grown
by the costs (`COSTS`), the static grants and their order, the upkeep's
and the end of the turn's, and the tokens (docs/design/codex.md, "Red
and green").
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

#: Purple, landed at step 12 (docs/codex-bot.md): its ten starters, the
#: twelve of Past, Present and Future, its three heroes and its two
#: tokens, the Stinger and the Mech.
PURPLE = frozenset({
    "argonaut", "assimilate", "battle_suits", "chronofixer", "double_time",
    "ebbflow_archon", "fading_argonaut", "forgotten_fighter", "gilded_glaxx",
    "hardened_mox", "hive", "hyperion", "immortal", "knight_of_the_conclave",
    "max_geiger", "mech", "nebula", "neo_plexus", "now", "nullcraft", "octavian",
    "omegacron", "origin_story", "plasmodium", "promise_of_payment",
    "prynn_pasternaak", "ready_or_not", "reaver", "rememberer",
    "research__development", "rewind", "second_chances", "seer", "sentry",
    "shimmer_ray", "slowtime_generator", "stewardess_of_the_undone", "stinger",
    "temporal_distortion", "temporal_research", "time_spiral", "tinkerer",
    "tricycloid", "undo", "unphase", "vir_garbarean", "void_star", "vortoss_emblem",
    "warp_gate_disciple", "xenostalker", "yesterdays_golgort"
})

#: Black, landed with purple: its ten starters, the twelve of
#: Demonology, Disease and Necromancy, its three heroes and its four
#: tokens -- the Skeleton, the Zombie, the Horror and the Warlock.
BLACK = frozenset({
    "abomination", "banefire_golem", "blackhand_dozer", "blackhand_resurrector",
    "bone_collector", "carrion_curse", "corpse_catapult", "crypt_crawler",
    "cursed_crow", "cursed_ghoul", "dark_pact", "death_and_decay", "death_rites",
    "deteriorate", "doom_grasp", "gargoyle", "garth_torken", "gorgon", "graveyard",
    "hooded_executioner", "horror", "jandra_the_negator", "lichs_bargain",
    "lord_of_shadows", "metamorphosis", "necromancer", "nether_drain", "orpal_gloor",
    "pestering_haunt", "plague_lab", "plague_lord", "plague_spitter",
    "poisonblade_rogue", "sacrifice_the_weak", "shadow_blade",
    "shrine_of_forbidden_knowledge", "sickness", "skeletal_archery", "skeletal_lord",
    "skeleton", "skeleton_javelineer", "soul_stone", "spreading_plague",
    "summon_skeletons", "terras_q_the_shackled", "thieving_imp", "twilight_baron",
    "vandy_anadrose", "voidblocker", "warlock", "wight", "zarramonde_the_obliterator",
    "zombie"
})

#: White, landed at step 13 (docs/codex-bot.md): its ten starters, the
#: twelve of Discipline, Ninjutsu and Strength, its three heroes and its
#: three tokens -- the Bird, the Ninja and Daigo Stormborne.
WHITE = frozenset({
    "aged_sensei", "ardras_boulder", "bird", "birds_nest", "colossus",
    "daigo_stormborne", "doubling_barbarbarian", "earthquake", "entangling_vines",
    "flying_fox", "focus_master", "fox_primus", "fox_viper", "foxs_den_school",
    "foxs_den_students", "fuzz_cuddles", "garus_rook", "glorious_ninja",
    "grappling_hook", "grave_stormborne", "heros_monument", "hidden_ninja",
    "inverse_power_ninja", "jade_fox_dens_headmistress",
    "jefferson_degrey_ghostly_diplomat", "martial_mastery", "masked_raccoon",
    "mindparry_monk", "morningstar_flagbearer", "morningstar_pass", "mythmaking",
    "ninja", "oathkeeper_of_kor_mountain", "porcupine", "rambasa_twin", "reversal",
    "safe_attacking", "savior_monk", "senseis_advice", "setsuki_hiruki",
    "shuriken_hail", "smoker", "snapback", "sparring_partner", "speed_of_the_fox",
    "thunderclap", "training_grounds", "true_power_of_storms", "versatile_style",
    "vigor_adept", "whitestar_grappler", "young_lightning_dragon"
})

#: Blue, landed with white: its ten starters, the twelve of Law, Peace
#: and Truth, its three heroes and its four tokens -- the Mirror
#: Illusion, the Soldier, and the Shark and the Water Elemental red and
#: green borrowed (`BORROWED_TOKENS`).
BLUE = frozenset({
    "air_hammer", "arrest", "arresting_constable", "bigby_hayes", "bluecoat_musketeer",
    "boot_camp", "brave_knight", "building_inspector", "censorship_council",
    "community_service", "debilitator_alpha", "dreamscape", "drill_sergeant",
    "elite_training", "eyes_of_the_chancellor", "flagstone_garrison", "flagstone_spy",
    "free_speech", "general_onimaru", "generals_hammer", "guardian_of_the_gates",
    "hallucination", "injunction", "insurance_agent", "jail", "judgment_day",
    "jurisdiction", "justice_juggernaut", "lawbringer_gryphon", "lawful_search",
    "liberty_gryphon", "macciatus_the_whisperer", "manufactured_truth", "mind_control",
    "mirror_illusion", "overeager_cadet", "patriot_gryphon", "porkhand_magistrate",
    "reputable_newsman", "reteller_of_truths", "scribe", "shark", "sirus_quince",
    "soldier", "spectral_aven", "spectral_flagbearer", "spectral_hound",
    "spectral_roc", "spectral_tiger", "tax_collector", "the_art_of_war",
    "traffic_director", "water_elemental"
})

#: The tokens of another colour that red and green summon: Surprise
#: Attack's Sharks and Argagarg's Water Elemental, both blue. Landed with
#: the cards that make them, so their keywords are read -- and part of
#: `BLUE` once blue landed (step 13).
BORROWED_TOKENS = frozenset({"shark", "water_elemental"})

#: **Every card the engine reads** -- the keyword table and the
#: static tables below are read over it, and the lobby offers the
#: heroes of `codex.cards.LANDED_COLORS`, the same colours. Each pair's
#: step adds its two.
LANDED_SET = BASIC_SET | RED | GREEN | BORROWED_TOKENS | PURPLE | BLACK | WHITE | BLUE

#: Every landed slug whose text the engine plays for its numbers alone.
#: Written out rather than computed, so the commit that takes a card out
#: of it is the commit that gives it a handler.
#:
#: **Empty**: from step 6 to step 9 -- step 5 took the basic set's
#: keywords out, and step 6 its triggers, spells, static grants, heroes'
#: bands, tokens and the surplus -- and again since step 11. Step 10
#: landed red and green played for their numbers, with every red or
#: green card with text here; step 11 gave each its handler, commit by
#: commit -- the keywords, the costs and the resources, the spells, the
#: triggers and the abilities, the static grants and the printed
#: overrides, the upkeep, the end of the turn and the tokens
#: (docs/design/codex.md, "Red and green"). The heroes' hall's and the
#: tech lab's text is the engine's own (`RulesEngine.hero_limit`,
#: `chosen_specs`).
#:
#: **Step 12 fills it again** with purple and black, played for their
#: numbers: every purple or black card, hero and token with text that is
#: more than keywords the engine reads -- the six heroes' bands among
#: them. Argonaut's readiness, the Stinger's flying and the Horror's
#: deathtouch are read whole, and play in full. Step 12 emptied it again.
#:
#: **Step 13 fills it a last time** with white and blue, played for their
#: numbers: every white or blue card, hero and token with text that is
#: more than keywords the engine reads -- the six heroes' bands among
#: them. Fox Primus, Fox Viper, Flying Fox, Glorious Ninja, Vigor Adept,
#: Porcupine, Savior Monk, Fuzz Cuddles, the Bird and the Soldier are
#: read whole, and play in full.
UNIMPLEMENTED: frozenset = frozenset({
    "aged_sensei", "air_hammer", "arrest", "arresting_constable", "bigby_hayes",
    "birds_nest", "bluecoat_musketeer", "boot_camp", "brave_knight",
    "building_inspector", "censorship_council", "colossus", "community_service",
    "daigo_stormborne", "debilitator_alpha", "doubling_barbarbarian", "dreamscape",
    "drill_sergeant", "earthquake", "elite_training", "entangling_vines",
    "eyes_of_the_chancellor", "flagstone_garrison", "flagstone_spy", "focus_master",
    "foxs_den_school", "foxs_den_students", "free_speech", "garus_rook",
    "general_onimaru", "generals_hammer", "grappling_hook", "grave_stormborne",
    "guardian_of_the_gates", "hallucination", "heros_monument", "hidden_ninja",
    "injunction", "insurance_agent", "inverse_power_ninja",
    "jade_fox_dens_headmistress", "jail", "jefferson_degrey_ghostly_diplomat",
    "judgment_day", "jurisdiction", "justice_juggernaut", "lawbringer_gryphon",
    "lawful_search", "liberty_gryphon", "macciatus_the_whisperer",
    "manufactured_truth", "martial_mastery", "masked_raccoon", "mind_control",
    "mindparry_monk", "morningstar_flagbearer", "morningstar_pass", "mythmaking",
    "oathkeeper_of_kor_mountain", "patriot_gryphon", "porkhand_magistrate",
    "rambasa_twin", "reputable_newsman", "reteller_of_truths", "reversal",
    "safe_attacking", "scribe", "senseis_advice", "setsuki_hiruki", "shuriken_hail",
    "sirus_quince", "smoker", "snapback", "sparring_partner", "spectral_aven",
    "spectral_flagbearer", "spectral_hound", "spectral_roc", "spectral_tiger",
    "speed_of_the_fox", "tax_collector", "the_art_of_war", "thunderclap",
    "traffic_director", "training_grounds", "true_power_of_storms", "versatile_style",
    "whitestar_grappler", "young_lightning_dragon"
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

    Step 12 added `follows`: a part that acts on what an earlier part of
    the same frame chose -- Time Spiral's add or remove, Omegacron's rune
    -- and so is done only where something was chosen, and never makes
    a spell playable by itself.
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
    follows: bool = False


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
    #: "Once-per-turn" (step 12): used at most once each turn.
    once: bool = False
    #: Skeletal Lord's "Exhaust five of your Skeletons": ready Skeletons of
    #: its controller's, arrival fatigue no bar (its ruling).
    skeletons: int = 0


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
    # Chaos Mirror: "Swap the printed ATK of two units and/or heroes until
    # end of turn." -- no {target}.
    _effect("chaos_mirror", Part("mirror", "unit_or_hero", 0,
                                 "choose a unit or hero whose printed ATK is swapped",
                                 targeted=False, most=2, least=2)),
    # Polymorph: Squirrel: "Transform a unit into a 1/1 green Squirrel
    # with no abilities until your next upkeep."
    _effect("polymorph_squirrel", Part("polymorph", "unit", 0,
                                       "transform a unit into a 1/1 Squirrel with no abilities")),
    # Spirit of the Panda's granted "Attacks: Gain {gold:1}." -- to the
    # attacker's controller (the Card FAQ).
    _effect("panda_gold", Part("gain_gold", None, 1, targeted=False)),
    # Final Showdown's hero "draws a card when he attacks".
    _effect("showdown_draw", Part("draw", None, 1, targeted=False)),
    # Land Octopus: "Upkeep: Sacrifice two workers or Land Octopus." --
    # the two workers trashed (its ruling), and only where it has two.
    _effect(
        "land_octopus",
        Part("mode", modes=(("workers", "sacrifice two workers"), ("itself", "sacrifice Land Octopus")),
             says="choose one"),
        Part("trash_workers", None, 2, targeted=False, only="workers"),
        Part("sacrifice_self", None, 0, targeted=False, only="itself"),
    ),
    # The ongoing spells whose text is what they grant in play: Behind
    # the Ferns, War Drums, and the upgrade Hotter Fire's.
    _effect("behind_the_ferns"),
    _effect("war_drums"),

    # -- Purple and black: the forms of death (step 12) --------------------
    # Sacrifice the Weak: "Each player sacrifices their weakest unit." --
    # the lowest tech, then the least ATK; its caster chooses a tie, and
    # what can't be sacrificed is passed over (its rulings).
    _effect(
        "sacrifice_the_weak",
        Part("sacrifice", "weakest_own_to_sacrifice", 0, "choose your weakest unit to sacrifice",
             targeted=False),
        Part("sacrifice", "weakest_opposing_to_sacrifice", 0,
             "choose their weakest unit, which they sacrifice", targeted=False),
    ),
    # Hooded Executioner: "If you boosted, destroy each opponent's weakest
    # unit." -- indestructible units passed over (its rulings).
    _effect("hooded_executioner", Part("destroy", "weakest_opposing_to_destroy", 0,
                                       "choose their weakest unit to destroy", targeted=False,
                                       when="boosted")),
    # Death Rites: "Whenever one of your units dies this turn, destroy one of
    # an opponent's lowest tech units." -- the trigger set on its caster.
    _effect("death_rites", Part("rites", None, 0, targeted=False)),
    _effect("death_rites_destroy", Part("destroy", "lowest_opposing_to_destroy", 0,
                                        "choose one of their lowest tech units to destroy",
                                        targeted=False)),
    # Doom Grasp: "Sacrifice a unit. If you do, destroy a tech 0, I, or II
    # unit or hero." -- the sacrifice no {target}, the destroy one.
    _effect(
        "doom_grasp",
        Part("sacrifice", "own_unit_to_sacrifice", 0, "sacrifice one of your units",
             targeted=False),
        Part("destroy", "unit_or_hero_tech_0_2", 0, "destroy a tech 0, I or II unit or hero",
             follows=True),
    ),
    # Spreading Plague: "Destroy all tech 0, I, or II units and heroes that
    # have -1/-1 runes."
    _effect("spreading_plague", Part("plague", None, 0, targeted=False)),
    # Death and Decay: "Give all an opponent's units and heroes -3/-3 this
    # turn. Deal 3 damage to all their buildings."
    _effect("death_and_decay", Part("decay", None, 3, targeted=False)),
    # Shadow Blade: "Deal 3 damage to a patroller. If it dies from Shadow
    # Blade, its controller discards a card at random."
    _effect("shadow_blade", Part("shadow_blade", "patroller", 3, "deal 3 damage to a patroller")),
    # Soul Stone: "Attach to a unit."
    _effect("soul_stone", Part("attach", "unit", 0, "attach to a unit")),
    # Poisonblade Rogue: "Attacks: Gets armor piercing and deals damage to
    # units and heroes in the form of -1/-1 runes this turn."
    _effect("poisonblade_rogue", Part("poison", None, 0, targeted=False)),
    # The Graveyard: "{exhaust} -> Play a buried unit. (You still pay for it
    # and must meet the tech reqs for it.)" -- and boost it, which playing
    # allows (the boost ruling).
    _effect(
        "graveyard",
        Part("pick_buried", "buried_playable", 0, "choose a buried unit to play", targeted=False),
        Part("mode", modes=(("plain", "play it"), ("boosted", "play it boosted")),
             says="boost it or not", follows=True),
        Part("play_buried", None, 0, targeted=False, follows=True),
        says="play a buried unit",
    ),

    # -- Black's effects (step 12, commit 4) -------------------------------
    # Thieving Imp: "Arrives: An opponent discards a card at random."
    _effect("thieving_imp", Part("random_discard", None, 0, targeted=False)),
    # Plague Lab: "Arrives: Put a -1/-1 rune on all of an opponent's units."
    _effect("plague_lab", Part("runes_on_opposing", None, 1, targeted=False)),
    # Plague Lab: "{gold:2}, {exhaust} -> For any number of cards with
    # runes, add another rune of a kind already there." -- one rune a card,
    # of a kind it has, never a card in the future (its rulings, the FAQ).
    _effect("plague_lab_runes", Part("lab_rune", "runed_card", 0,
                                     "add another rune of a kind already on a card",
                                     targeted=False, most=99, least=0),
            says="add another rune to any number of cards with runes"),
    # Plague Lord: "Arrives or attacks: Put a -1/-1 rune on each opposing
    # unit and hero."
    _effect("plague_lord", Part("runes_on_opposing", None, 1, targeted=False, token="heroes")),
    # Cursed Ghoul: "Arrives: Put a -1/-1 rune on a unit."
    _effect("cursed_ghoul", Part("minus_rune", "unit", 1, "put a -1/-1 rune on a unit")),
    # Skeleton Javelineer: "Arrives: Put a javelin rune on this." and
    # "Remove a javelin rune -> This gets long-range this turn."
    _effect("skeleton_javelineer", Part("rune_on_self", None, 1, targeted=False, token="javelin")),
    _effect("skeleton_javelineer_throw", Part("keyword_self", None, 0, targeted=False,
                                              token="Long-range"),
            says="get long-range this turn"),
    # Zarramonde: "Arrives: If you played Zarramonde from your hand, destroy
    # a unit, hero, worker, upgrade, or ongoing spell."
    _effect("zarramonde_the_obliterator", Part("destroy_any", "anything_destroyable", 0,
                                               "destroy a unit, hero, worker, upgrade or ongoing spell",
                                               targeted=False, when="from_hand")),
    # Terras Q: "Arrives: Summon four 0/1 black Warlock tokens for an
    # opponent." -- each remembering the Terras Q that made it.
    _effect("terras_q_the_shackled", Part("token_for_opponent", None, 4, targeted=False,
                                          token="warlock")),
    # Bone Collector: "Attacks: Summon a 1/1 black Skeleton token."
    _effect("bone_collector", Part("token", None, 1, targeted=False, token="skeleton")),
    # Gorgon: "Dies: Draw a card."
    _effect("gorgon", Part("draw", None, 1, targeted=False)),
    # Jandra: "Dies from combat damage: Destroy all your units except for
    # Demons."
    _effect("jandra_the_negator", Part("negate", None, 0, targeted=False)),
    # Blackhand Dozer: "Dies: Active player destroys one of your lowest tech
    # units." -- asked of the active player, whoever's the Dozer was.
    _effect("blackhand_dozer", Part("destroy", "lowest_against_to_destroy", 0,
                                    "choose one of their lowest tech units to destroy",
                                    targeted=False)),
    # Necromancer: "Whenever another non-token unit of yours dies, summon a
    # 1/1 black Skeleton token."
    _effect("necromancer", Part("token", None, 1, targeted=False, token="skeleton")),
    # Cursed Crow: "Damages a base: Defending player discards a card at
    # random." -- the base itself, not a building's 2 (its ruling).
    _effect("cursed_crow", Part("random_discard", None, 0, targeted=False)),
    # Deteriorate: "Give a unit -1/-1 this turn."
    _effect("deteriorate", Part("debuff", "unit", 1, "give a unit -1/-1 this turn")),
    # Sickness: "Put a -1/-1 rune on up to two units and/or heroes." -- one
    # or two (its ruling).
    _effect("sickness", Part("minus_rune", "unit_or_hero", 1,
                             "put a -1/-1 rune on a unit or hero", most=2, least=1)),
    # Summon Skeletons: "Summon two 1/1 black Skeleton tokens."
    _effect("summon_skeletons", Part("token", None, 2, targeted=False, token="skeleton")),
    # Dark Pact: "Deal 2 damage to a base, then that player draws 2 cards."
    _effect("dark_pact", Part("dark_pact", "base", 2, "deal 2 damage to a base")),
    # Carrion Curse: "Look at an opponent's hand. Choose up to two non-unit
    # cards for them to discard." -- the hand pictured to the caster alone.
    _effect("carrion_curse", Part("curse_discard", "opponent_hand_nonunit", 0,
                                  "choose a non-unit card of theirs to discard",
                                  targeted=False, most=2, least=0)),
    # Nether Drain: "One hero loses two levels and can't level up this
    # turn. Another hero gains two levels." -- any player's heroes.
    _effect(
        "nether_drain",
        Part("drain", "hero_in_play", 2, "choose a hero to lose two levels"),
        Part("gain_levels", "other_hero_in_play", 2, "choose another hero to gain two levels"),
    ),
    # Lich's Bargain: "Sacrifice a worker. Your base takes 4 damage. Summon
    # three black tokens: a 1/1 Skeleton, a 2/2 Zombie, a 3/3 Horror with
    # deathtouch"
    _effect(
        "lichs_bargain",
        Part("sacrifice", "own_workers", 0, "sacrifice a worker", targeted=False),
        Part("own_base_damage", None, 4, targeted=False),
        Part("token", None, 1, targeted=False, token="skeleton"),
        Part("token", None, 1, targeted=False, token="zombie"),
        Part("token", None, 1, targeted=False, token="horror"),
    ),
    # Metamorphosis: "Sacrifice all units you control. Your non-Demon heroes
    # level to max and become Demons. Put two +1/+1 runes on each, they get
    # readiness, and are invisible until they leave play."
    _effect("metamorphosis", Part("metamorphosis", None, 2, targeted=False)),
    # Garth at 1: "{gold:1} -> Summon a 1/1 black Skeleton token.
    # Once-per-turn."
    _effect("garth_torken", Part("token", None, 1, "summon a Skeleton", targeted=False,
                                 token="skeleton")),
    # Garth at 4: "Sacrifice a Skeleton -> Draw a card."
    _effect(
        "garth_torken_draw",
        Part("sacrifice", "own_skeleton", 0, "sacrifice a Skeleton", targeted=False),
        Part("draw", None, 1, targeted=False, follows=True),
        says="draw a card",
    ),
    # Garth at 7: "Max Level: You may put a tech I or II unit that costs
    # {gold:5} or less from your discard pile into play if you meet the tech
    # reqs for it." -- free (his rulings), the discard pictured to him.
    _effect("garth_torken_max", Part("put_into_play", "discard_tech_1_2_cheap", 0,
                                     "put a tech I or II unit costing 5 or less from your discard "
                                     "pile into play", targeted=False, least=0)),
    # Orpal at 4: "Sacrifice a non-Demon unit -> Put a -1/-1 rune on a unit.
    # {target} Once-per-turn."
    _effect(
        "orpal_gloor",
        Part("sacrifice", "own_non_demon_to_sacrifice", 0, "sacrifice a non-Demon unit",
             targeted=False),
        Part("minus_rune", "unit", 1, "put a -1/-1 rune on a unit", follows=True),
        says="put a -1/-1 rune on a unit",
    ),
    # Orpal at 6: "The first time a unit with a -1/-1 rune dies each turn,
    # the active player puts a -1/-1 rune on two units friendly to the dead
    # unit. {target}"
    _effect("orpal_gloor_max", Part("minus_rune", "units_of_against", 1,
                                    "put a -1/-1 rune on a unit friendly to the dead unit",
                                    most=2, least=2)),
    # Vandy at 3: "{gold:1}, {exhaust}, Discard a card -> Fetch a
    # Demonology spell from your codex, reveal it, then put it in your hand."
    _effect(
        "vandy_anadrose",
        Part("discard", "hand_card", 0, "discard a card", targeted=False, most=1, least=1),
        Part("fetch", "codex_demonology_spell", 0, "fetch a Demonology spell from your codex",
             targeted=False),
        says="fetch a Demonology spell",
    ),
    # Vandy at 5: "Max Level: Give +2/+2 to one friendly and one opposing
    # tech 0 or I unit. They lose +2/+2 and die at your next upkeep.
    # {target}" -- mandatory as far as it goes (her rulings).
    _effect(
        "vandy_anadrose_max",
        Part("doom_buff", "own_unit_tech_0_1", 2, "give one of your tech 0 or I units +2/+2"),
        Part("doom_buff", "opposing_unit_tech_0_1", 2, "give an opposing tech 0 or I unit +2/+2"),
    ),
    # Gargoyle: "{gold:1} -> Until your next upkeep, Gargoyle isn't
    # indestructible, gains flying, +3 ATK, and it can attack and patrol.
    # Once-per-turn."
    _effect("gargoyle", Part("gargoyle", None, 3, targeted=False),
            says="lose indestructible and gain flying, +3 ATK, attack and patrol"),
    # Corpse Catapult: "{exhaust}, Remove two corpse runes -> Deal 6 damage
    # to a building."
    _effect("corpse_catapult", Part("damage", "building", 6, "deal 6 damage to a building")),
    # Crypt Crawler: "{gold:1} -> A flier loses flying this turn."
    _effect("crypt_crawler", Part("ground", "flier", 0, "make a flier lose flying this turn")),
    # Skeletal Lord: "Exhaust five of your Skeletons -> Put a unit from your
    # hand into play." -- no requirements, fatigued Skeletons too (its
    # rulings).
    _effect(
        "skeletal_lord",
        Part("exhaust_skeletons", None, 5, targeted=False),
        Part("put_into_play", "hand_unit", 0, "put a unit from your hand into play",
             targeted=False),
        says="put a unit from your hand into play",
    ),
    # Blackhand Resurrector: "{exhaust}, Sacrifice Blackhand Resurrector ->
    # Summon a hero from your command zone that died previously this game.
    # It arrives at max level."
    _effect("blackhand_resurrector", Part("resurrect", "dead_hero", 0,
                                          "summon a hero that died this game, at max level",
                                          targeted=False)),

    # -- Purple's effects (step 12, commit 5) -----------------------------
    # Max Geiger at 3: "{exhaust}, Discard a card -> Draw a card."
    _effect(
        "max_geiger",
        Part("discard", "hand_card", 0, "discard a card", targeted=False, most=1, least=1),
        Part("draw", None, 1, targeted=False),
        says="draw a card",
    ),
    # Max Geiger at 5: "Max Level: You may trash a friendly unit then return
    # it to play. {target}" -- fresh, under the same controller, with
    # arrival fatigue (his rulings).
    _effect("max_geiger_max", Part("geiger", "own_unit", 0, "trash a friendly unit and return it",
                                   least=0)),
    # Prynn at 1: "Attacks: Put a time rune on this."
    _effect("prynn_pasternaak", Part("time_rune_self", None, 1, targeted=False)),
    # Prynn at 7: "Remove two time runes -> Trash a unit. {target}" -- at two
    # runes she may, and dies at once, not from fading (her rulings).
    _effect(
        "prynn_pasternaak_max",
        Part("prynn_trash", "unit", 0, "trash a unit"),
        Part("fade_check", None, 0, targeted=False),
        says="trash a unit",
    ),
    # Vir at 1: "{gold:0} -> Look at the top card of your draw pile." --
    # pictured to him alone; nothing on an empty pile (his rulings).
    _effect("vir_garbarean", Part("look", "deck_top", 0, "look at the top card of your draw pile",
                                  targeted=False, least=0),
            says="look at the top card of your draw pile"),
    # Vir at 1: "{gold:1} -> Exchange the top card of your draw pile with a
    # card from your hand."
    _effect("vir_garbarean_exchange", Part("exchange", "hand_card_with_deck", 0,
                                           "choose a card from your hand to put on top",
                                           targeted=False),
            says="exchange the top card of your draw pile with a card from your hand"),
    # Vir at 5: "{exhaust} -> Play the top card of your draw pile. (You still
    # pay for it and must meet the reqs for it.)"
    _effect(
        "vir_garbarean_play",
        Part("pick_top", "deck_top_playable", 0, "play the top card of your draw pile",
             targeted=False),
        Part("mode", modes=(("plain", "play it"), ("boosted", "play it boosted")),
             says="boost it or not", follows=True),
        Part("play_top", None, 0, targeted=False, follows=True),
        says="play the top card of your draw pile",
    ),
    # Vir at 7: "Max Level: Summon a 6/7 purple Mech token with forecast 2
    # that's untargetable."
    _effect("vir_garbarean_max", Part("token", None, 1, targeted=False, token="mech")),
    # Forgotten Fighter: "Return a patrolling tech 0 or I unit with 2 ATK or
    # less to its owner's hand."
    _effect("forgotten_fighter", Part("return", "patrolling_weak_unit", 0,
                                      "return a patrolling tech 0 or I unit with 2 ATK or less")),
    # Undo: "Return a tech 0, I, or II unit to its owner's hand."
    _effect("undo", Part("return", "unit_tech_upto_2", 0, "return a tech 0, I or II unit")),
    # Stewardess of the Undone: "Arrives: You may return a tech 0 unit to
    # its owner's hand."
    _effect("stewardess_of_the_undone", Part("return", "unit_tech_0", 0, "return a tech 0 unit",
                                             least=0)),
    # Origin Story: "Return a hero to its command zone." -- no death, its
    # levels and runes gone, and no summoning runes (the author,
    # 2026-10-09).
    _effect("origin_story", Part("to_command_zone", "hero_in_play", 0,
                                 "return a hero to its command zone")),
    # Assimilate: "Gain control of an upgrade, ongoing spell, or building
    # card (not add-on)."
    _effect("assimilate", Part("steal", "opposing_upgrade_spell_or_building_card", 0,
                               "gain control of an upgrade, ongoing spell or building card")),
    # Temporal Distortion: "Return a tech I or II unit of yours to its
    # owner's hand. If you do, you may put a unit of the same tech level and
    # the same cost or less from your codex into play. (Even if you don't
    # meet the tech reqs for it.)"
    _effect(
        "temporal_distortion",
        Part("distort", "own_unit_tech_1_2", 0, "return a tech I or II unit of yours",
             targeted=False),
        Part("put_into_play", "codex_distortion", 0,
             "put a unit of that tech level costing no more from your codex into play",
             targeted=False, least=0, follows=True),
    ),
    # Ready or Not: "Ready one of your units. Opposing exhausted units don't
    # ready during their next ready step."
    _effect(
        "ready_or_not",
        Part("ready", "own_unit", 0, "ready one of your units"),
        Part("hold_down", None, 0, targeted=False),
    ),
    # Rewind: "Return all tech 0, I, and II units to their owner's hands."
    _effect("rewind", Part("rewind", None, 0, targeted=False)),
    # Research & Development: "Draw five cards."
    _effect("research__development", Part("draw", None, 5, targeted=False)),
    # Now: "Give a unit or hero haste this turn."
    _effect("now", Part("keyword", "unit_or_hero", 0, "give a unit or hero haste this turn",
                        token="Haste")),
    # Unphase: "Make a unit or hero invisible until your next upkeep."
    _effect("unphase", Part("unphase", "unit_or_hero", 0,
                            "make a unit or hero invisible until your next upkeep")),
    # Hive: "Arrives: Summon five 1/1 purple Stinger tokens with flying." and
    # "{gold:1} -> Re-summon a lost Stinger (limit: 5 per Hive.)"
    _effect("hive", Part("stingers", None, 5, targeted=False)),
    _effect("hive_resummon", Part("stingers", None, 1, targeted=False),
            says="re-summon a lost Stinger"),
    # The Stingers past five a Hive, sacrificed -- the active player choosing
    # which (Hive's rulings).
    _effect("hive_excess", Part("sacrifice", "stingers_of_against", 0,
                                "choose a Stinger to sacrifice", targeted=False, most=99, least=99)),
    # Ebbflow Archon: "Remove a time rune -> Return a unit to its owner's
    # hand or a hero to its command zone."
    _effect(
        "ebbflow_archon",
        Part("bounce", "unit_or_hero", 0, "return a unit to its owner's hand or a hero to its command zone"),
        Part("fade_check", None, 0, targeted=False),
        says="return a unit or a hero",
    ),
    # Nebula: "{gold:0} -> Destroy a tech 0, I, or II unit. Once-per-turn."
    _effect("nebula", Part("destroy", "unit_tech_upto_2", 0, "destroy a tech 0, I or II unit")),
    # Octavian: "{gold:8}, {exhaust} -> Ready Octavian and disable up to eight
    # units and/or heroes."
    _effect(
        "octavian",
        Part("ready_self", None, 0, targeted=False),
        Part("disable", "unit_or_hero", 0, "disable a unit or hero", most=8, least=0),
        says="ready it and disable up to eight units and heroes",
    ),
    # Reaver: "{gold:1}, {exhaust}, Discard a card -> Choose one: Trash 2
    # workers. Deal 6 damage to up to 2 units and/or heroes."
    _effect(
        "reaver",
        Part("discard", "hand_card", 0, "discard a card", targeted=False, most=1, least=1),
        Part("mode", modes=(("workers", "trash 2 workers"),
                            ("damage", "deal 6 damage to up to 2 units and heroes")),
             says="choose one"),
        Part("trash", "workers", 0, "trash a worker", targeted=False, most=2, least=2,
             only="workers"),
        Part("damage", "unit_or_hero", 6, "deal 6 damage to a unit or hero", targeted=False,
             most=2, least=1, only="damage"),
        says="trash 2 workers, or deal 6 to up to 2 units and heroes",
    ),
    # Rememberer: "Whenever you remove a time rune from Rememberer, you may
    # put a unit with fading from your discard pile into play if you meet
    # the tech requirements for it."
    _effect("rememberer", Part("put_into_play", "discard_fading_unit", 0,
                               "put a unit with fading from your discard pile into play",
                               targeted=False, least=0)),
    # Tricycloid: "Arrives: Put three time runes on this." and "Remove a time
    # rune -> Deal 1 damage to a unit, hero, or building."
    _effect("tricycloid", Part("time_rune_self", None, 3, targeted=False)),
    _effect("tricycloid_shot", Part("damage", "unit_hero_or_building", 1,
                                    "deal 1 damage to a unit, hero or building"),
            says="deal 1 damage to a unit, hero or building"),
    # Void Star: "{gold:4} -> Gets +4 ATK until your next upkeep.
    # Once-per-turn."
    _effect("void_star", Part("void_star", None, 4, targeted=False), says="get +4 ATK"),
    # Vortoss Emblem: "Attach to a unit. That unit is a flagbearer."
    _effect("vortoss_emblem", Part("attach", "unit", 0, "attach to a unit")),
    # Warp Gate Disciple: "{gold:1}, {exhaust} -> Put a tech I or II unit from
    # your codex into play. (You don't have to meet the tech reqs for it.)"
    _effect("warp_gate_disciple", Part("put_into_play", "codex_tech_1_2_unit", 0,
                                       "put a tech I or II unit from your codex into play",
                                       targeted=False)),
    # Xenostalker: "Attacks: Deal 1 damage to up to four patrollers without
    # flying."
    _effect("xenostalker", Part("damage", "ground_patroller", 1,
                                "deal 1 damage to a patroller without flying", most=4, least=0)),
    # Hyperion: "Attacks: Draw a card."
    _effect("hyperion", Part("draw", None, 1, targeted=False)),

    # -- The upkeep, the extra turn and the debt (step 12, commit 6) --------
    # Promise of Payment: "The next card you play this turn costs {gold:0}.
    # Pay its gold cost during your next upkeep or lose the game."
    _effect("promise_of_payment", Part("promise", None, 0, targeted=False)),
    # Double Time: "Take an extra turn after this one, then trash this
    # card." -- as it resolves from the future.
    _effect("double_time", Part("extra_turn", None, 0, targeted=False), trash_after=True),
    # Banefire Golem: "Upkeep: Sacrifice a unit. If you do, deal 1 damage to
    # each opposing unit, hero, and building." -- itself where nothing else,
    # mandatory (its ruling).
    _effect(
        "banefire_golem",
        Part("sacrifice", "own_unit_to_sacrifice", 0, "sacrifice one of your units", targeted=False),
        Part("banefire", None, 1, targeted=False, follows=True),
    ),

    # -- Purple and black: time (step 12) ----------------------------------
    # Time Spiral: "Add or remove a time rune from a card (or forcasted
    # card) with at least one time rune." -- any player's (its ruling), no
    # {target}. The card first, then which.
    _effect(
        "time_spiral",
        Part("time_target", "timed", 0, "choose a card with a time rune", targeted=False),
        Part("mode", modes=(("add", "add a time rune"), ("remove", "remove a time rune")),
             says="add or remove", follows=True),
        Part("time_rune", None, 0, targeted=False, follows=True),
        says="add or remove a time rune",
    ),
    # Tinkerer: "{exhaust} -> Add or remove a time rune from a card (or
    # forcasted card) with at least one time rune."
    _effect(
        "tinkerer",
        Part("time_target", "timed", 0, "choose a card with a time rune", targeted=False),
        Part("mode", modes=(("add", "add a time rune"), ("remove", "remove a time rune")),
             says="add or remove", follows=True),
        Part("time_rune", None, 0, targeted=False, follows=True),
        says="add or remove a time rune",
    ),
    # Seer: "Arrives: You may add or remove a time rune from a card (or
    # forcasted card) with at least one time rune."
    _effect(
        "seer",
        Part("time_target", "timed", 0, "choose a card with a time rune", targeted=False, least=0),
        Part("mode", modes=(("add", "add a time rune"), ("remove", "remove a time rune")),
             says="add or remove", follows=True),
        Part("time_rune", None, 0, targeted=False, follows=True),
    ),
    # Shimmer Ray: "Discard a card -> Add a time rune to this." -- in the
    # main phase alone (its ruling): an ability action.
    _effect(
        "shimmer_ray",
        Part("discard", "hand_card", 0, "discard a card", targeted=False, most=1, least=1),
        Part("time_rune_self", None, 1, targeted=False),
        says="add a time rune to it",
    ),
    # Omegacron: "Sacrifice a unit, hero, worker, or upgrade -> Remove a
    # time rune from Omegacron while it's forecasted." -- the one ability
    # used from the future.
    _effect(
        "omegacron",
        Part("sacrifice", "own_sacrificable", 0, "sacrifice a unit, hero, worker or upgrade",
             targeted=False),
        Part("time_rune_self", None, -1, targeted=False, follows=True),
        says="remove a time rune from it",
    ),
    # Temporal Research: "Draw a card. If you have 3 or more time runes,
    # draw another card. If you have 10 or more time runes, draw another
    # card." -- every time rune on what its caster controls, the future
    # included (its rulings).
    _effect(
        "temporal_research",
        Part("draw", None, 1, targeted=False),
        Part("research", None, 0, targeted=False),
    ),
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
    "chaos_mirror": (("play", "chaos_mirror"),),
    "polymorph_squirrel": (("play", "polymorph_squirrel"),),
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
    # Purple and black (step 12). `future_ability` is an ability used
    # while the card is in the future: Omegacron's alone.
    "time_spiral": (("play", "time_spiral"),),
    "tinkerer": (("ability", "tinkerer"),),
    "seer": (("arrives", "seer"),),
    "shimmer_ray": (("ability", "shimmer_ray"),),
    "omegacron": (("future_ability", "omegacron"),),
    "temporal_research": (("play", "temporal_research"),),
    "sacrifice_the_weak": (("play", "sacrifice_the_weak"),),
    "hooded_executioner": (("arrives", "hooded_executioner"),),
    "death_rites": (("play", "death_rites"),),
    "doom_grasp": (("play", "doom_grasp"),),
    "spreading_plague": (("play", "spreading_plague"),),
    "death_and_decay": (("play", "death_and_decay"),),
    "shadow_blade": (("play", "shadow_blade"),),
    "soul_stone": (("play", "soul_stone"),),
    "poisonblade_rogue": (("attacks", "poisonblade_rogue"),),
    "graveyard": (("ability", "graveyard"),),
    # Black's (commit 4).
    "thieving_imp": (("arrives", "thieving_imp"),),
    "plague_lab": (("arrives", "plague_lab"), ("ability", "plague_lab_runes")),
    "plague_lord": (("arrives", "plague_lord"), ("attacks", "plague_lord")),
    "cursed_ghoul": (("arrives", "cursed_ghoul"),),
    "skeleton_javelineer": (("arrives", "skeleton_javelineer"),
                            ("ability", "skeleton_javelineer_throw")),
    "zarramonde_the_obliterator": (("arrives", "zarramonde_the_obliterator"),),
    "terras_q_the_shackled": (("arrives", "terras_q_the_shackled"),),
    "bone_collector": (("attacks", "bone_collector"),),
    "gorgon": (("dies", "gorgon"),),
    "jandra_the_negator": (("dies_from_combat", "jandra_the_negator"),),
    "blackhand_dozer": (("dies", "blackhand_dozer"),),
    "deteriorate": (("play", "deteriorate"),),
    "sickness": (("play", "sickness"),),
    "summon_skeletons": (("play", "summon_skeletons"),),
    "dark_pact": (("play", "dark_pact"),),
    "carrion_curse": (("play", "carrion_curse"),),
    "nether_drain": (("play", "nether_drain"),),
    "lichs_bargain": (("play", "lichs_bargain"),),
    "metamorphosis": (("play", "metamorphosis"),),
    "gargoyle": (("ability", "gargoyle"),),
    "corpse_catapult": (("ability", "corpse_catapult"),),
    "crypt_crawler": (("ability", "crypt_crawler"),),
    "skeletal_lord": (("ability", "skeletal_lord"),),
    "blackhand_resurrector": (("ability", "blackhand_resurrector"),),
    ("garth_torken", 1): (("ability", "garth_torken"),),
    ("garth_torken", 4): (("ability", "garth_torken_draw"),),
    ("garth_torken", 7): (("max_level", "garth_torken_max"),),
    ("orpal_gloor", 4): (("ability", "orpal_gloor"),),
    ("vandy_anadrose", 3): (("ability", "vandy_anadrose"),),
    ("vandy_anadrose", 5): (("max_level", "vandy_anadrose_max"),),
    # Purple's (commit 5).
    ("max_geiger", 3): (("ability", "max_geiger"),),
    ("max_geiger", 5): (("max_level", "max_geiger_max"),),
    ("prynn_pasternaak", 1): (("attacks", "prynn_pasternaak"),),
    ("prynn_pasternaak", 7): (("ability", "prynn_pasternaak_max"),),
    ("vir_garbarean", 1): (("ability", "vir_garbarean"), ("ability", "vir_garbarean_exchange")),
    ("vir_garbarean", 5): (("ability", "vir_garbarean_play"),),
    ("vir_garbarean", 7): (("max_level", "vir_garbarean_max"),),
    "forgotten_fighter": (("play", "forgotten_fighter"),),
    "undo": (("play", "undo"),),
    "stewardess_of_the_undone": (("arrives", "stewardess_of_the_undone"),),
    "origin_story": (("play", "origin_story"),),
    "assimilate": (("play", "assimilate"),),
    "temporal_distortion": (("play", "temporal_distortion"),),
    "ready_or_not": (("play", "ready_or_not"),),
    "rewind": (("play", "rewind"),),
    "research__development": (("play", "research__development"),),
    "now": (("play", "now"),),
    "unphase": (("play", "unphase"),),
    "vortoss_emblem": (("play", "vortoss_emblem"),),
    "hive": (("arrives", "hive"), ("ability", "hive_resummon")),
    "ebbflow_archon": (("ability", "ebbflow_archon"),),
    "nebula": (("ability", "nebula"),),
    "octavian": (("ability", "octavian"),),
    "reaver": (("ability", "reaver"),),
    "tricycloid": (("arrives", "tricycloid"), ("ability", "tricycloid_shot")),
    "void_star": (("ability", "void_star"),),
    "warp_gate_disciple": (("ability", "warp_gate_disciple"),),
    "xenostalker": (("attacks", "xenostalker"),),
    "promise_of_payment": (("play", "promise_of_payment"),),
    "double_time": (("play", "double_time"),),
    "hyperion": (("attacks", "hyperion"),),
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
    # Purple and black (step 12).
    "tinkerer": Cost(exhaust=True),
    "shimmer_ray": Cost(discard=1),
    "omegacron": Cost(),
    "graveyard": Cost(exhaust=True),
    # Black's (commit 4).
    "plague_lab_runes": Cost(gold=2, exhaust=True),
    "skeleton_javelineer_throw": Cost(runes=("javelin", 1)),
    "gargoyle": Cost(gold=1, once=True),
    "corpse_catapult": Cost(exhaust=True, runes=("corpse", 2)),
    "crypt_crawler": Cost(gold=1),
    "skeletal_lord": Cost(skeletons=5),
    "blackhand_resurrector": Cost(exhaust=True, sacrifice=True),
    "garth_torken": Cost(gold=1, once=True),
    "garth_torken_draw": Cost(),
    "orpal_gloor": Cost(once=True),
    "vandy_anadrose": Cost(gold=1, exhaust=True, discard=1),
    # Purple's (commit 5).
    "max_geiger": Cost(exhaust=True, discard=1),
    "prynn_pasternaak_max": Cost(runes=("time", 2)),
    "vir_garbarean": Cost(),
    "vir_garbarean_exchange": Cost(gold=1),
    "vir_garbarean_play": Cost(exhaust=True),
    "hive_resummon": Cost(gold=1),
    "ebbflow_archon": Cost(runes=("time", 1)),
    "nebula": Cost(once=True),
    "octavian": Cost(gold=8, exhaust=True),
    "reaver": Cost(gold=1, exhaust=True, discard=1),
    "tricycloid_shot": Cost(runes=("time", 1)),
    "void_star": Cost(gold=4, once=True),
    "warp_gate_disciple": Cost(gold=1, exhaust=True),
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


def printing_band(effect: str) -> Optional[tuple[str, int]]:
    """The hero band that prints `effect`, as `(hero slug, first level of
    the band)`; None for a card's own text."""
    for key, entries in TEXT.items():
        if isinstance(key, tuple) and any(name == effect for _, name in entries):
            return key
    return None


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

# -- The grants, in the order they came (step 11) -------------------------------
#
# What a card in play, or a hero's band, gives its controller's units and
# heroes, read off the position each time and applied in the order each
# came to be (`RulesEngine._profile`; the Card FAQ, Behind the Ferns and
# Master Midori).

#: A card's grant to its controller's units, by the card: Grounded
#: Guide's +1 ATK (+2/+1 to a Virtuoso) to the others, Blademaster's swift
#: strike, Nimble Fencer's haste to Virtuosos, War Drums' +X ATK, Behind
#: the Ferns' stealth to 3 ATK or less, Blooming Elm's overpower to a unit
#: with +1/+1 runes, Might of Leaf and Claw's +5/+5 from five growth
#: runes, Pirate-Gang Commander's "Dies:" line, Moss Ancient's haste and
#: invisibility to Squirrels.
UNIT_GRANTS = {
    **{slug: "guide" for slug in GUIDES},
    **{slug: "swift_strike" for slug in GRANTS_SWIFT_STRIKE},
    **{slug: "virtuoso_haste" for slug in GRANTS_VIRTUOSO_HASTE},
    "war_drums": "war_drums",
    "behind_the_ferns": "behind_the_ferns",
    "blooming_elm": "rune_overpower",
    "might_of_leaf_and_claw": "growth",
    "pirategang_commander": "dies",
    "moss_ancient": "squirrels",
}
#: An attached spell's grant to the unit it is on: Spirit of the Panda's
#: +2/+2 and "Attacks: Gain {gold:1}."
ATTACHED_UNIT_GRANTS = {"spirit_of_the_panda": "panda"}
#: A hero's band's grant to its controller's units: Midori's +1/+1 to
#: units with no abilities, Calamandra's resist 1, Drakk's frenzy 1.
BAND_GRANTS = {
    ("master_midori", 5): "no_abilities",
    ("calamandra_moss", 3): "resist",
    ("drakk_ramhorn", 4): "frenzy",
}
#: A card's grant to its controller's heroes: Blooming Elm's overpower,
#: Might of Leaf and Claw's +5/+5, Final Showdown's to the hero it is
#: attached to.
HERO_GRANTS = {
    "blooming_elm": "rune_overpower",
    "might_of_leaf_and_claw": "growth",
    "final_showdown": "showdown",
}
FERNS_ATK = 3
GROWTH_THRESHOLD = 5
GROWTH_BONUS = 5
PANDA_BONUS = 2
SHOWDOWN_BONUS = 3
SQUIRREL = "Squirrel"
#: Polymorph: Squirrel's 1/1, and a feather rune's 3/1.
SQUIRREL_STATS = (1, 1)
FEATHER_STATS = (3, 1)
FAIRIE_DRAGON = "fairie_dragon"
#: Drakk at 6: "The first unit that arrives from your hand each turn gets
#: haste." -- for good (his rulings).
FIRST_FROM_HAND_HASTE = ("drakk_ramhorn", 6)
#: Hotter Fire: "Your red spells and abilities that deal damage deal 1
#: damage more." -- each copy (its rulings).
HOTTER_FIRE = "hotter_fire"
#: Stampede's "Your units get +3 ATK / +3 armor this turn" and Ferocity's
#: "Your units get armor piercing and swift strike until your next
#: upkeep" -- continuous, on every unit the caster controls while they
#: last (`PlayerState.lasting`; the author, 2026-10-09).
STAMPEDE_BONUS = 3
FEROCITY_KEYWORDS = ("Armor piercing", "Swift strike")
#: Red and green's upkeep (step 11): Gemscout Owl's "Upkeep: Gain
#: {gold:1}", Galina Glimmer's "Upkeep: Gain {gold:1} for every two of your
#: green units", Land Octopus's "Upkeep: Sacrifice two workers or Land
#: Octopus." -- the effect that asks it -- and Dothram Horselord's side.
UPKEEP_GOLD = frozenset({"gemscout_owl"})
UPKEEP_GREEN_GOLD = frozenset({"galina_glimmer"})
UPKEEP_CHOICE = {"land_octopus": "land_octopus"}
JOINS_THE_STRONGER = frozenset({"dothram_horselord"})
#: The end of the turn's own (step 11): Bloodrage Ogre's return, on its
#: controller's turn where it neither arrived nor attacked; Chameleon
#: Lizzo's, on any.
RETURNS_IF_IDLE = frozenset({"bloodrage_ogre"})
RETURNS_AT_END = frozenset({"chameleon_lizzo"})
#: What Polymorph: Squirrel makes a unit.
POLYMORPH_INTO = "squirrel"
#: The attacks lines an attached spell gives what it is on.
ATTACHED_ATTACKS = {"spirit_of_the_panda": "panda_gold", "final_showdown": "showdown_draw"}

# -- Purple and black's static texts (step 12) --------------------------------

#: "Can't have more than 1 ATK." -- Pestering Haunt, after everything
#: else is added.
ATK_CEILING = {"pestering_haunt": 1}
#: "Can't be sacrificed." -- ignored completely when choosing what to
#: sacrifice (its ruling); an indestructible card can't be either (UMR
#: p. 17), which the engine reads off the keyword.
CANT_BE_SACRIFICED = frozenset({"pestering_haunt"})
#: Cursed Ghoul: "Unstoppable by units with -1/-1 runes."
UNSTOPPABLE_BY_RUNED = frozenset({"cursed_ghoul"})
#: Shrine of Forbidden Knowledge: "Your Demons are unstoppable by units."
DEMONS_UNSTOPPABLE = frozenset({"shrine_of_forbidden_knowledge"})
DEMON = "Demon"
#: Wight: "Unstoppable when attacking heroes. Deathtouch when attacking
#: heroes." -- it may ignore the patrol zone to attack a hero, and its
#: combat damage to the hero it attacks is deathtouch.
UNSTOPPABLE_ATTACKING_HEROES = frozenset({"wight"})
WHEN_ATTACKING_HEROES = {"wight": ("Deathtouch",)}
#: Nullcraft: "Can't be the {target} of Buff or Debuff spells." -- a
#: spell whose subtype says Buff or Debuff, or both (its ruling).
UNTARGETABLE_BY_BUFFS = frozenset({"nullcraft"})
BUFF_SUBTYPES = ("Buff", "Debuff")
#: Battle Suits: "Your non-token Soldiers and Mystics get +1 ATK." -- the
#: subtypes it reads.
SUITED = ("Soldier", "Mystic")
#: Lord of Shadows: "Your black units are invisible." -- himself included
#: (his ruling).
INVISIBLE_COLOR = {"lord_of_shadows": "black"}
UNIT_GRANTS.update({
    "battle_suits": "battle_suits",
    "lord_of_shadows": "black_invisible",
})
#: Pestering Haunt's "can't patrol" beside red and green's.
CANT_PATROL = CANT_PATROL | {"pestering_haunt"}

# -- The forms of death (step 12, commit 3) -------------------------------------

#: What a random choice a journal records looks like beside the shuffles:
#: `[PICK, slug]` -- a card discarded at random (Thieving Imp, Cursed Crow,
#: Shadow Blade), a unit Second Chances returns. No slug begins with "@".
PICK = "@pick"
#: "Deals damage to units and heroes in the form of -1/-1 runes." --
#: Plague Spitter's, Orpal Gloor's from his first band, and Poisonblade
#: Rogue's while it attacks (a modifier of the turn).
RUNE_DAMAGE = frozenset({"plague_spitter"})
RUNE_DAMAGE_BANDS = {("orpal_gloor", 1)}
#: Blackhand Dozer: "Damage you deal can reduce opposing bases' HP to 6,
#: but not lower." -- any damage its controller deals, on any turn (its
#: ruling and the Card FAQ).
BASE_FLOOR = {"blackhand_dozer": 6}
#: The Graveyard: "Whenever your non-token units die, bury them here.
#: Sacrifice Graveyard when four or more units are buried in it."
GRAVEYARD = "graveyard"
GRAVEYARD_LIMIT = 4
#: Soul Stone: "Attached unit gets +1/+1. If it would die, instead remove
#: all damage from it and sacrifice all Soul Stones on it."
SOUL_STONE = "soul_stone"
ATTACHING = ATTACHING | {SOUL_STONE}
ATTACHED_UNIT_GRANTS = {**ATTACHED_UNIT_GRANTS, SOUL_STONE: "soul_stone"}
#: Death Rites: "Whenever one of your units dies this turn, destroy one of
#: an opponent's lowest tech units." -- a this-turn trigger on its caster.
DEATH_RITES = "death_rites"

# -- Black's static texts (step 12, commit 4) -------------------------------------

#: Abomination: "All other units get -1/-1." -- both sides, stacking, two
#: giving each other -1/-1 (its ruling).
ALL_OTHER_UNITS = {"abomination": (-1, -1)}
#: Corpse Catapult: "Whenever one of your units dies, put a corpse rune on
#: this."
CORPSE_RUNES = frozenset({"corpse_catapult"})
#: Necromancer: "Whenever another non-token unit of yours dies, summon a
#: 1/1 black Skeleton token."
SKELETON_ON_DEATH = frozenset({"necromancer"})
#: Cursed Crow: "Damages a base: Defending player discards a card at
#: random."
ON_DAMAGING_A_BASE = {"cursed_crow": "cursed_crow"}
#: Gargoyle: "Can't attack or patrol." -- until its own ability frees it.
CANT_ATTACK = CANT_ATTACK | {"gargoyle"}
CANT_PATROL = CANT_PATROL | {"gargoyle"}
#: Terras Q: "Terras Q can't attack or patrol while any of those tokens are
#: in play." -- the four his arrival made, by lineage (`made_by`).
SHACKLED = frozenset({"terras_q_the_shackled"})
#: Twilight Baron: "You can't play tech II or III units."
NO_HIGH_TECH_UNITS = frozenset({"twilight_baron"})
#: Voidblocker: "Whenever an opponent attacks Voidblocker, they exhaust
#: another of their ready units or heroes."
VOIDBLOCKERS = frozenset({"voidblocker"})
_effect_voidblocker = _effect("voidblocker", Part("exhaust", "own_ready_other", 0,
                                                  "exhaust another of your ready units or heroes",
                                                  targeted=False))
EFFECTS[_effect_voidblocker.key] = _effect_voidblocker
#: Shrine of Forbidden Knowledge: "Draw/Discard phase: Card draw +1, hand
#: size +1" -- each Shrine (the Card FAQ: two, +2 and a hand of seven).
DRAW_MORE = frozenset({"shrine_of_forbidden_knowledge"})
#: Skeletal Lord's +1/+1 and Skeletal Archery's long-range and anti-air,
#: to their controller's Skeletons.
SKELETON = "Skeleton"
UNIT_GRANTS.update({
    "skeletal_lord": "skeletons",
    "skeletal_archery": "skeleton_archery",
})
#: Orpal at 6, once a turn: the first unit with a -1/-1 rune to die.
ORPAL_MAX = ("orpal_gloor", 6)
#: Metamorphosis's grants to a hero, until it leaves play.
METAMORPHOSIS_KEYWORDS = ("Readiness", "Invisible")

# -- Purple's static texts (step 12, commit 5) ------------------------------------

#: Chronofixer: "Opposing heroes can't level up." -- by any means (its
#: rulings).
NO_OPPOSING_LEVELS = frozenset({"chronofixer"})
#: Gilded Glaxx: "While you have gold in your gold pile, you can't
#: sacrifice Gilded Glaxx and he can't leave play unless he dies from
#: combat damage."
CANT_LEAVE_WITH_GOLD = frozenset({"gilded_glaxx"})
#: Hardened Mox: "When you have a tech II unit (even a forecasted one),
#: trash Hardened Mox."
TRASHED_BY_TECH_II = frozenset({"hardened_mox"})
#: Ebbflow Archon's "Gets -1/-1 for each time rune on it", Tricycloid's
#: "+1/+1".
PER_TIME_RUNE = {"ebbflow_archon": -1, "tricycloid": 1}
#: Nebula: "Your other units are invisible."
UNIT_GRANTS.update({"nebula": "others_invisible"})
#: Second Chances: "Whenever one of your non-token units leaves play from
#: something other than combat damage, return it to play. Once-per-turn."
SECOND_CHANCES = frozenset({"second_chances"})
#: Sentry: "Prevent the first damage per turn that a spell or ability would
#: deal to one of your patrollers."
SENTRIES = frozenset({"sentry"})
#: Slowtime Generator: "Each player's workers can't produce more than
#: {gold:4} total during their upkeep."
SLOWTIME = {"slowtime_generator": 4}
#: Yesterday's Golgort: "Whenever you deal combat damage to a building, put
#: a time rune on this." -- any card or effect of its controller's, spells
#: included (the Card FAQ).
GOLGORTS = frozenset({"yesterdays_golgort"})
#: Vortoss Emblem: "Attach to a unit. That unit is a flagbearer."
VORTOSS_EMBLEM = "vortoss_emblem"
ATTACHING = ATTACHING | {VORTOSS_EMBLEM}
#: Rewind: "Your max level Past hero can cast this no matter when she
#: arrived or maxed."
ANY_TIME_ULTIMATES = frozenset({"rewind"})
#: Hive: "limit: 5 per Hive", and the Stinger.
HIVE = "hive"
STINGER = "stinger"
STINGERS_PER_HIVE = 5
#: Rememberer: "Whenever you remove a time rune from Rememberer".
REMEMBERERS = frozenset({"rememberer"})
#: Prynn at 4: "Dies from fading: Opponents skip their next draw/discard
#: step (they keep their hand cards)."; at 7, "Leaves: Return all cards to
#: play that Pasternaak trashed."
PRYNN = "prynn_pasternaak"
PRYNN_FADES = ("prynn_pasternaak", 4)
PRYNN_RETURNS = ("prynn_pasternaak", 7)

# -- The upkeep's own (step 12, commit 6) ------------------------------------------

#: Banefire Golem: "Upkeep: Sacrifice a unit." -- the effect it asks.
UPKEEP_SACRIFICE = {"banefire_golem": "banefire_golem"}
#: Plague Lord: "Upkeep: Each player's base takes 1 damage for each -1/-1
#: rune on their units and heroes." -- its controller's upkeep alone, its
#: own base included (its ruling).
PLAGUE_UPKEEP = frozenset({"plague_lord"})
#: Shrine of Forbidden Knowledge: "Upkeep: Your base takes 1 damage."
SELF_BASE_UPKEEP = {"shrine_of_forbidden_knowledge": 1}

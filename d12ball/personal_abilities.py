"""
The personal abilities: which player holds which, and the numbers each
one changes. The rules are Law 21 of docs/living-rules.md ("Personal
abilities"); how they are wired is "Personal abilities" in
docs/design/species-abilities.md.

**The sheet carries a sentence, not a key**, so this table is the one
place a player is tied to the ability the engine plays for them. Each
row keeps the sheet's sentence beside its key, and a test compares the
two against `players.json`: when the author rewords or moves an
ability on the sheet, the import changes the sentence, the test fails,
and the row is looked at again rather than quietly playing the old
ability. Nothing else may key a rule on a player id.

A row is keyed on the catalog id; a card fielded on the second side
(`duplicate_card_id`) is the same person and is resolved to it by
`RulesEngine.has_personal_ability`.

The advanced skill scores are not here: they are data the import
carries on `PlayerDefinition.advanced_skills`, and
`RulesEngine.skills` reads them.
"""

from __future__ import annotations

from enum import Enum


class PersonalAbility(str, Enum):
    ALWAYS_BLAZES = "always_blazes"            # Blazebulk
    WIDE_IGNITION = "wide_ignition"            # Sizzifizik
    BRIGHT_BURN = "bright_burn"                # Brightburn
    HIGH_DRAIN_THRESHOLD = "high_drain_threshold"  # Bulwark
    CHEAP_OVERDRIVE = "cheap_overdrive"        # Voltus
    BOOST = "boost"                            # Gearclaw
    EFFICIENT_RUN = "efficient_run"            # Strider
    OVERDRIVE_UPGRADE = "overdrive_upgrade"    # Synapse
    ADJACENT_PULL = "adjacent_pull"            # Noxar
    FREE_PULL = "free_pull"                    # Quillon
    STRONG_PULL = "strong_pull"                # Spectra
    FULL_BLOCK = "full_block"                  # Goopkeeper
    PRESSURE_SHOT = "pressure_shot"            # Acidel


#: Catalog id -> (the ability, the sheet's sentence it was built from).
PERSONAL_ABILITIES: dict[str, tuple[PersonalAbility, str]] = {
    "blazebulk_defender": (
        PersonalAbility.ALWAYS_BLAZES,
        "Always Blazes (no burn).",
    ),
    "sizzifizik_playmaker": (
        PersonalAbility.WIDE_IGNITION,
        "Ignites on 5-8.",
    ),
    "brightburn_striker": (
        PersonalAbility.BRIGHT_BURN,
        "When burns: opponent does not upgrade maneuver, remove 1 "
        "exhaustion.",
    ),
    "bulwark_fullback": (
        PersonalAbility.HIGH_DRAIN_THRESHOLD,
        "Is only Drained with 10+",
    ),
    "voltus_defender": (
        PersonalAbility.CHEAP_OVERDRIVE,
        "Overdrive costs 2 drain.",
    ),
    "gearclaw_playmaker": (
        PersonalAbility.BOOST,
        "Boost: gain 1 drain for +3.",
    ),
    "strider_midfielder": (
        PersonalAbility.EFFICIENT_RUN,
        "Recharges 2 when stays put. Cost -1 when runs back.",
    ),
    "synapse_playmaker": (
        PersonalAbility.OVERDRIVE_UPGRADE,
        "When wins with overdrive, resolve maneuver as a gambit.",
    ),
    "noxar_striker": (
        PersonalAbility.ADJACENT_PULL,
        "Can Mind Pull adjacent spaces.",
    ),
    "quillon_playmaker": (
        PersonalAbility.FREE_PULL,
        "Does not get exhausted for Mind Pull.",
    ),
    "spectra_midfielder": (
        PersonalAbility.STRONG_PULL,
        "+3 for Mind Pull.",
    ),
    "goopkeeper_fullback": (
        PersonalAbility.FULL_BLOCK,
        "Contributes full block against score attempts when not on the "
        "ball.",
    ),
    "acidel_striker": (
        PersonalAbility.PRESSURE_SHOT,
        "Gets a scoring opportunity instead of own goal when successfully "
        "pressuring into  the goal zone.",
    ),
}

#: The three sheet sentences that describe an advanced skill score
#: rather than an ability: `advanced_skills` carries the numbers, so
#: nothing here plays them.
ADVANCED_SKILL_SENTENCES: dict[str, str] = {
    "flux_defender": "High offensive skill.",
    "hellguard_fullback": "High defensive skill.",
    "tachyon_striker": "High defensive skill.",
}

# The numbers, beside the ones they replace in d12ball/components.py.
SIZZIFIZIK_IGNITE_FACES = (5, 6, 7, 8)
BULWARK_DRAINED_AT = 10
VOLTUS_OVERDRIVE_DRAIN_COST = 2
BOOST_DRAIN_COST = 1
BOOST_BONUS = 3
STRIDER_CHARGE_UP = 2
STRIDER_RUN_BACK_DISCOUNT = 1
SPECTRA_PULL_BONUS = 3
BRIGHTBURN_BURN_RECOVERY = 1

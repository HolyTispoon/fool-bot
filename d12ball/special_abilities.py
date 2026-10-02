"""
The special abilities: which player holds which, and the numbers each
one changes. The rules are Law 21 of docs/living-rules.md ("Special
abilities"); how they are wired is "Special abilities" in
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
`RulesEngine.has_special_ability`.

The advanced skill scores are not here: they are data the import
carries on `PlayerDefinition.advanced_skills`, and
`RulesEngine.skills` reads them.
"""

from __future__ import annotations

from enum import Enum


class SpecialAbility(str, Enum):
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
    FREE_BURST = "free_burst"                  # Emberdash
    DEFENSIVE_GAMBITS = "defensive_gambits"    # Dravox
    OFFENSIVE_GAMBITS = "offensive_gambits"    # Hexis
    RUN_ON = "run_on"                          # Quantor
    CLEAR_SHOT = "clear_shot"                  # Flickerwing
    LIGHTS_THE_BALL = "lights_the_ball"        # Inferno
    INJURY_IGNITION = "injury_ignition"        # Kindlefinger
    FORCES_THE_TEST = "forces_the_test"        # Scorchit
    CHARGES_ON_THE_BALL = "charges_on_the_ball"  # Pulsar
    DEFENSIVE_THROW = "defensive_throw"        # Umbrik
    LONG_SET_UP = "long_set_up"                # Vorix
    FLY = "fly"                                # Zenith
    SHOOTS_OFF_ANY_PASS = "shoots_off_any_pass"  # Zytheris
    JOINS_THE_BALL = "joins_the_ball"          # Glompex
    WINS_CONTESTS = "wins_contests"            # Slitheron
    SMOOTH = "smooth"                          # Shpritz
    SPEED_ROLLS = "speed_rolls"                # Zorch
    MERGES_HARDER = "merges_harder"            # Viscor


#: Catalog id -> (the ability, the sheet's sentence it was built from).
SPECIAL_ABILITIES: dict[str, tuple[SpecialAbility, str]] = {
    "blazebulk_defender": (
        SpecialAbility.ALWAYS_BLAZES,
        "Always Blazes (no burn).",
    ),
    "sizzifizik_playmaker": (
        SpecialAbility.WIDE_IGNITION,
        "Ignites on 5-8.",
    ),
    "brightburn_striker": (
        SpecialAbility.BRIGHT_BURN,
        "When burns: opponent does not upgrade maneuver, clear 1 "
        "exhaustion.",
    ),
    "bulwark_fullback": (
        SpecialAbility.HIGH_DRAIN_THRESHOLD,
        "Is only drained at 10.",
    ),
    "voltus_defender": (
        SpecialAbility.CHEAP_OVERDRIVE,
        "Overdrive drains 2.",
    ),
    "gearclaw_playmaker": (
        SpecialAbility.BOOST,
        "Boost: drain 1 for +3 (once per roll).",
    ),
    "strider_midfielder": (
        SpecialAbility.EFFICIENT_RUN,
        "Charge-up 2 when stays put. Max 1 drain when runs back.",
    ),
    "synapse_playmaker": (
        SpecialAbility.OVERDRIVE_UPGRADE,
        "When wins a skill test while using overdrive, resolve as "
        "successful gambit.",
    ),
    "noxar_striker": (
        SpecialAbility.ADJACENT_PULL,
        "Can Mind Pull adjacent spaces.",
    ),
    "quillon_playmaker": (
        SpecialAbility.FREE_PULL,
        "Does not  exhaust for Mind Pull.",
    ),
    "spectra_midfielder": (
        SpecialAbility.STRONG_PULL,
        "Mind Pulls on 9+.",
    ),
    "goopkeeper_fullback": (
        SpecialAbility.FULL_BLOCK,
        "Counts as 'on the ball' when standing between the ball and the "
        "goal during score attempts.",
    ),
    "acidel_striker": (
        SpecialAbility.PRESSURE_SHOT,
        "When successfully pressuring into the goal zone: scoring "
        "opportunity instead of own goal.",
    ),
    "emberdash_playmaker": (
        SpecialAbility.FREE_BURST,
        "Dribble up to 3, Burst with no exhaustion.",
    ),
    "dravox_defender": (
        SpecialAbility.DEFENSIVE_GAMBITS,
        "Defensive gambits succeed when won on a skill test.",
    ),
    "hexis_playmaker": (
        SpecialAbility.OFFENSIVE_GAMBITS,
        "Offensive gambits succeed when won on a skill test.",
    ),
    "flickerwing_winger": (
        SpecialAbility.CLEAR_SHOT,
        "When attempting to score, only defenders on the ball contribute "
        "their skill scores.",
    ),
    "inferno_defender": (
        SpecialAbility.LIGHTS_THE_BALL,
        "When receives the ball, ball speed to 12.",
    ),
    "kindlefinger_striker": (
        SpecialAbility.INJURY_IGNITION,
        "Can iginite on injury test: when blazes clear 1 exhaustion and "
        "when burns exhaust 1.",
    ),
    "scorchit_midfielder": (
        SpecialAbility.FORCES_THE_TEST,
        "When their maneuver loses on rank, may exhaust 2 to force a "
        "skill test while rival doesn't exhaust. Subseuqent ties "
        "exhaust as normal.",
    ),
    "pulsar_striker": (
        SpecialAbility.CHARGES_ON_THE_BALL,
        "Charge-up when receives the ball.",
    ),
    "umbrik_fullback": (
        SpecialAbility.DEFENSIVE_THROW,
        "Uses dSkill for high pass skill tests and when avoiding own "
        "goals.",
    ),
    "vorix_defender": (
        SpecialAbility.LONG_SET_UP,
        "When high passing for 3: speed ball to 12 and set up a scoring "
        "opportunity without contest.",
    ),
    "zenith_winger": (
        SpecialAbility.FLY,
        "Fly: if not injured or in possession, after turnover can move "
        "anywhere, exhausting per space. Does not run back if Flying.",
    ),
    "zytheris_striker": (
        SpecialAbility.SHOOTS_OFF_ANY_PASS,
        "Gets a scoring opportunity when receiving any pass.",
    ),
    "glompex_midfielder": (
        SpecialAbility.JOINS_THE_BALL,
        "After a maneuver is challenged, if Glomplex is adjacent to the "
        "ball they may exhaust 1 to move to the ball's space and Merge.",
    ),
    "slitheron_striker": (
        SpecialAbility.WINS_CONTESTS,
        "Auto wins contests for ball including high pass and loose ball.",
    ),
    "shpritz_winger": (
        SpecialAbility.SMOOTH,
        "Smooth (teammate sharing space may handover ball handling).",
    ),
    "viscor_defender": (
        SpecialAbility.MERGES_HARDER,
        "Gain +3 when Merging.",
    ),
    "zorch_playmaker": (
        SpecialAbility.SPEED_ROLLS,
        "Adds a ball speed modifier to all rolls (speed divided by 2 "
        "rounded up).",
    ),
    "quantor_winger": (
        SpecialAbility.RUN_ON,
        "Before resolving High Pass or Cross, drain 3 to move to the "
        "pass's target space. Quantor gains possession without contest.",
    ),
}

#: The sheet sentences that describe an advanced skill score
#: rather than an ability: `advanced_skills` carries the numbers, so
#: nothing here plays them.
ADVANCED_SKILL_SENTENCES: dict[str, str] = {
    "flux_defender": "High offensive skill.",
    "hellguard_fullback": "High defensive skill.",
    "tachyon_striker": "High defensive skill.",
    "ozul_playmaker": "High offensive and defensive skills.",
    "gurgoth_defender": "High offensive and defensive skills.",
}

#: The condition Flickerwing's sentence opens with. A reminder shown at
#: a score attempt drops it -- it only appears when Flickerwing is
#: attempting to score, so the condition says nothing there (the author,
#: 2026-09-30). Everywhere else -- the roster, the card -- prints the
#: sheet's whole sentence.
CLEAR_SHOT_CONDITION = "When attempting to score, "
#: Goopkeeper's, at the other end of the sentence, dropped for the same
#: reason (the author, 2026-09-30).
FULL_BLOCK_CONDITION = " during score attempts."


def without_shot_condition(sentence: str) -> str:
    """
    A sentence with the score attempt's condition taken off --
    `CLEAR_SHOT_CONDITION` off its front, the rest capitalised, or
    `FULL_BLOCK_CONDITION` off its end, the full stop kept. A sentence
    that carries neither comes back whole, so a reworded sheet shows
    its own words rather than a cut one; `SPECIAL_ABILITIES`' test
    fails on the rewording anyway.
    """
    if sentence.startswith(CLEAR_SHOT_CONDITION):
        rest = sentence[len(CLEAR_SHOT_CONDITION):]
        return rest[:1].upper() + rest[1:]
    if sentence.endswith(FULL_BLOCK_CONDITION):
        return sentence[:-len(FULL_BLOCK_CONDITION)] + "."
    return sentence


# The numbers, beside the ones they replace in d12ball/components.py.
SIZZIFIZIK_IGNITE_FACES = (5, 6, 7, 8)
BULWARK_DRAINED_AT = 10
VOLTUS_OVERDRIVE_DRAIN_COST = 2
BOOST_DRAIN_COST = 1
BOOST_BONUS = 3
STRIDER_CHARGE_UP = 2
STRIDER_RUN_BACK_MAXIMUM = 1
SPECTRA_PULL_MINIMUM = 9
EMBERDASH_ADVANCE_MAX = 3
QUANTOR_RUN_DRAIN = 3
BRIGHTBURN_BURN_RECOVERY = 1
INFERNO_BALL_SPEED = 12
KINDLEFINGER_TOKEN = 1
SCORCHIT_FORCED_TEST_TOKENS = 2
PULSAR_CHARGE_UP = 1
VORIX_PASS_DISTANCE = 3
VORIX_BALL_SPEED = 12
GLOMPEX_JOIN_COST = 1
VISCOR_MERGE_BONUS = 3

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
    SMOOTH = "smooth"                          # Spritz
    FREE_TESTS = "free_tests"                  # Zorch
    MERGES_HARDER = "merges_harder"            # Viscor


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
        "When burns: opponent does not upgrade maneuver, clear 1 "
        "exhaustion.",
    ),
    "bulwark_fullback": (
        PersonalAbility.HIGH_DRAIN_THRESHOLD,
        "Is only drained at 10.",
    ),
    "voltus_defender": (
        PersonalAbility.CHEAP_OVERDRIVE,
        "Overdrive drains 2.",
    ),
    "gearclaw_playmaker": (
        PersonalAbility.BOOST,
        "*Boost*: drain 1 for +3 on a roll.",
    ),
    "strider_midfielder": (
        PersonalAbility.EFFICIENT_RUN,
        "Charge-up 2 when stays put. Max 1 drain when runs back.",
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
        "Mind Pulls succeds on 8+.",
    ),
    "goopkeeper_fullback": (
        PersonalAbility.FULL_BLOCK,
        "Counts as 'on the ball' when standing between the ball and the "
        "goal during score attempts.",
    ),
    "acidel_striker": (
        PersonalAbility.PRESSURE_SHOT,
        "When successfully pressuring into the goal zone: scoring "
        "opportunity instead of own goal.",
    ),
    "emberdash_playmaker": (
        PersonalAbility.FREE_BURST,
        "Dribble Advance up to 3 or Dribble Burst with no exhaustion.",
    ),
    "dravox_defender": (
        PersonalAbility.DEFENSIVE_GAMBITS,
        "Resolves defensive gambit's bonuses when winning with skill test.",
    ),
    "hexis_playmaker": (
        PersonalAbility.OFFENSIVE_GAMBITS,
        "Resolves offensive gambit's bonuses when winning with skill test.",
    ),
    "flickerwing_winger": (
        PersonalAbility.CLEAR_SHOT,
        "When attempting a scoring opportunity, only defender on the ball "
        "contribute their skill scores.",
    ),
    "inferno_defender": (
        PersonalAbility.LIGHTS_THE_BALL,
        "When receives the ball, ball speed to 12.",
    ),
    "kindlefinger_striker": (
        PersonalAbility.INJURY_IGNITION,
        "Can iginite on injury test: when blazes clear 1 exhaustion and "
        "when burns add 1 exhaustion.",
    ),
    "scorchit_midfielder": (
        PersonalAbility.FORCES_THE_TEST,
        "May force a skill test even when their maneuver is on the losing "
        "side but gains 2 exhaustion while opponent gains none "
        "(additional tests due to ties add 1 exhaustion per player as "
        "normal).",
    ),
    "pulsar_striker": (
        PersonalAbility.CHARGES_ON_THE_BALL,
        "Charge-up when receives the ball.",
    ),
    "umbrik_fullback": (
        PersonalAbility.DEFENSIVE_THROW,
        "Uses dSkill for attempting to avoid an own goal and for skill "
        "tests when attempting to high pass.",
    ),
    "vorix_defender": (
        PersonalAbility.LONG_SET_UP,
        "When successfully high passes for 3: speed ball to 12 and set up "
        "a scoring opportunity without contest.",
    ),
    "zenith_winger": (
        PersonalAbility.FLY,
        "Fly: before runback, if not injured or in possession can be "
        "moved anywhere on the board gaining exhaustion as normal. Does "
        "not run back if moved by Fly.",
    ),
    "zytheris_striker": (
        PersonalAbility.SHOOTS_OFF_ANY_PASS,
        "Gets a scoring opportunity when receiving any pass.",
    ),
    "glompex_midfielder": (
        PersonalAbility.JOINS_THE_BALL,
        "Before selecting a maneuver, if Glomplex is in a space adjacent "
        "to the ball they may add 1 exhaustion to move to the ball's "
        "space and Merge.",
    ),
    "slitheron_striker": (
        PersonalAbility.WINS_CONTESTS,
        "Auto wins contests for high pass and loose ball.",
    ),
    "spritz_winger": (
        PersonalAbility.SMOOTH,
        "Smooth (eammate sharing space may handover ball handling.)",
    ),
    "viscor_defender": (
        PersonalAbility.MERGES_HARDER,
        "+3 when Merging.",
    ),
    "zorch_playmaker": (
        PersonalAbility.FREE_TESTS,
        "Does not add exhaustion when rolling skill tests (including "
        "after ties).",
    ),
    "quantor_winger": (
        PersonalAbility.RUN_ON,
        "Before resolving High Pass or Setup Pass, drain 3 to move "
        "Quantor to the target space of the pass. Quantor gains "
        "possession without contest.",
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

# The numbers, beside the ones they replace in d12ball/components.py.
SIZZIFIZIK_IGNITE_FACES = (5, 6, 7, 8)
BULWARK_DRAINED_AT = 10
VOLTUS_OVERDRIVE_DRAIN_COST = 2
BOOST_DRAIN_COST = 1
BOOST_BONUS = 3
STRIDER_CHARGE_UP = 2
STRIDER_RUN_BACK_MAXIMUM = 1
SPECTRA_PULL_MINIMUM = 8
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

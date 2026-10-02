"""
**Which ability a coach is reminded of beside which part of which roll**
-- the bearings. The skill test's attack, a shot's wall, the one
rolling an injury check: each is a `Bearing`, naming the species whose
ability reaches it, the special abilities that act on it (Law 21) and
the skill it adds. `BEARINGS` is the one table, and both frontends
read it -- the web page's situation window (`webapp/present.py`) and
the bot's matchup images (`dice_brief.challenge_side`) -- so the two
remind a coach of the same abilities at the same roll.

**Wording alone, never whether an ability fires**: whether a player
holds one is `RulesEngine.has_species_ability` /
`has_special_ability`, asked by `special_bears`. It was the web
page's until 2026-10-02, when the bot drew the same reminders (see
"The special ability on a matchup" in docs/design/board-image.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, Optional

from d12ball.components import SPECIES_CYBORG, SPECIES_FIRE_DEMON
from d12ball.special_abilities import SpecialAbility

if TYPE_CHECKING:
    from d12ball.engine import RulesEngine
    from d12ball.game import D12BallGame


@dataclass(frozen=True)
class Bearing:
    """
    What bears on one part of a roll -- the player rolling a skill test's
    attack, a shot's wall, the one rolling an injury check: the species
    whose ability reaches it, the special abilities that act on it, and
    the skill it adds, if any. **Which reminder goes with which roll,
    never whether an ability fires**: whether a player holds one is
    `has_species_ability` / `has_special_ability`, asked below.
    """

    species: tuple[str, ...] = ()
    special: frozenset = frozenset()
    skill: Optional[str] = None
    # A maneuver's skill test: the one roll a species' "In a skill
    # test" sentence is about (`species_ability_reminder`).
    skill_test: bool = False


#: The special abilities any roll a Cyborg makes can carry: Voltus's
#: cheap Overdrive and Gearclaw's Boost, spent on the die (Law 21).
_ON_THE_DIE = frozenset({
    SpecialAbility.CHEAP_OVERDRIVE, SpecialAbility.BOOST,
})
#: The ignites a Fire Demon's own die can carry in a skill test and on
#: a shot -- Blazebulk's, Sizzifizik's, Brightburn's burn (Law 21).
_IGNITES = frozenset({
    SpecialAbility.ALWAYS_BLAZES, SpecialAbility.WIDE_IGNITION,
    SpecialAbility.BRIGHT_BURN,
})

#: What bears on each part of each roll a coach is shown
#: (the author, 2026-09-28: only what applies to the roll). Volatile
#: reaches a skill test and the shooter's die, never an injury check or
#: an own-goal roll (Law 20.2.3); Overdrive any d12 a Cyborg rolls (Law
#: 20.3.5). A special ability is here where it changes the roll's
#: number, whether it is rolled, or what winning it means -- and on the
#: maneuver challenge also what a maneuver does once it has won, since
#: the coach is choosing one there (the author, 2026-09-28): Emberdash's
#: dribble, Vorix's set-up and Acidel's pressure, each on the attack
#: alone. Quantor's run on is never here: it is for a teammate's pass,
#: so it does not apply to a roll Quantor is in (the author,
#: 2026-09-28). Bulwark's drain threshold applies to every roll he is
#: in (`ALWAYS_BEARS`). Zorch
#: adds the speed modifier to every roll but the shot, which adds it
#: already (`speed_roll_bonus`). Merge is not here: it is a number
#: another player adds, the model's own line in the side's modifiers
#: (`merge_bonus`); and a Mind Pull is the Telekinetics' ability
#: already, which the window says.
#: The special abilities named on every roll the player is in: Bulwark
#: is only Drained at 10, which is what his tokens mean on any of them
#: (the author, 2026-09-28).
ALWAYS_BEARS = frozenset({SpecialAbility.HIGH_DRAIN_THRESHOLD})

BEARINGS: Mapping[str, Bearing] = {
    "skill_test_attack": Bearing(
        (SPECIES_FIRE_DEMON, SPECIES_CYBORG),
        _ON_THE_DIE | _IGNITES | {
            SpecialAbility.OVERDRIVE_UPGRADE,
            SpecialAbility.OFFENSIVE_GAMBITS,
            SpecialAbility.FORCES_THE_TEST,
            SpecialAbility.DEFENSIVE_THROW,
            SpecialAbility.SPEED_ROLLS,
            # What an attacking card does once won -- the dribble, the
            # High Pass, the Pressure into the goal zone -- since the
            # coach is choosing it (the author, 2026-09-28).
            SpecialAbility.FREE_BURST,
            SpecialAbility.LONG_SET_UP,
            SpecialAbility.PRESSURE_SHOT,
        },
        "offense",
        skill_test=True,
    ),
    "skill_test_defence": Bearing(
        (SPECIES_FIRE_DEMON, SPECIES_CYBORG),
        _ON_THE_DIE | _IGNITES | {
            SpecialAbility.OVERDRIVE_UPGRADE,
            SpecialAbility.DEFENSIVE_GAMBITS,
            SpecialAbility.FORCES_THE_TEST,
            SpecialAbility.SPEED_ROLLS,
        },
        "defense",
        skill_test=True,
    ),
    # A contest for the ball -- a loose ball's, or a long High Pass's:
    # the same dice as a skill test's, and Slitheron's win without one
    # is the reason there was no roll when a contest is skipped.
    "contest_attack": Bearing(
        (SPECIES_FIRE_DEMON, SPECIES_CYBORG),
        _ON_THE_DIE | _IGNITES | {
            SpecialAbility.SPEED_ROLLS, SpecialAbility.WINS_CONTESTS,
        },
        "offense",
    ),
    "contest_defence": Bearing(
        (SPECIES_FIRE_DEMON, SPECIES_CYBORG),
        _ON_THE_DIE | _IGNITES | {
            SpecialAbility.SPEED_ROLLS, SpecialAbility.WINS_CONTESTS,
        },
        "defense",
    ),
    # A scoring opportunity offered off a pass: whatever bears on the
    # shot, and the ability that offered it (Zytheris).
    "set_up": Bearing(
        (SPECIES_FIRE_DEMON, SPECIES_CYBORG),
        _ON_THE_DIE | _IGNITES | {
            SpecialAbility.CLEAR_SHOT, SpecialAbility.SHOOTS_OFF_ANY_PASS,
        },
        "offense",
    ),
    "shot_attack": Bearing(
        (SPECIES_FIRE_DEMON, SPECIES_CYBORG),
        _ON_THE_DIE | _IGNITES | {SpecialAbility.CLEAR_SHOT},
        "offense",
    ),
    "shot_defence": Bearing(
        (), frozenset({SpecialAbility.FULL_BLOCK}), "defense",
    ),
    "injury": Bearing(
        (SPECIES_CYBORG,),
        _ON_THE_DIE | {
            SpecialAbility.INJURY_IGNITION, SpecialAbility.SPEED_ROLLS,
        },
    ),
    "own_goal": Bearing(
        (SPECIES_CYBORG,),
        _ON_THE_DIE | {
            SpecialAbility.DEFENSIVE_THROW, SpecialAbility.SPEED_ROLLS,
        },
        "offense",
    ),
    "mind_pull": Bearing(
        (),
        frozenset({
            SpecialAbility.STRONG_PULL, SpecialAbility.FREE_PULL,
            SpecialAbility.ADJACENT_PULL,
        }),
    ),
    # An Ooze Merging into a side (Law 20.5): Slimey is what the badge
    # and the band already say, so only Viscor's 3 more.
    "merge": Bearing((), frozenset({SpecialAbility.MERGES_HARDER})),
}


def special_bears(
    engine: RulesEngine,
    game: D12BallGame,
    player_id: str,
    bearing: Bearing,
) -> bool:
    """Whether a player's special line applies to this roll: an ability
    the bearing names, or -- for the players whose line is an advanced
    skill score ("High defensive skill.") -- a raised score in the skill
    this roll adds, read as the game plays it against the role's."""
    if any(
        engine.has_special_ability(game, player_id, ability)
        for ability in bearing.special | ALWAYS_BEARS
    ):
        return True
    if bearing.skill is None:
        return False
    return (
        engine.skills(game, player_id).of(bearing.skill)
        != engine.skills(None, player_id).of(bearing.skill)
    )


def special_reminder(
    engine: RulesEngine,
    game: Optional[D12BallGame],
    player_id: str,
    bearing: Bearing,
) -> str:
    """A player's special ability as this part of this roll reminds of
    it -- `special_ability_reminder`, the card's own sentence -- where
    it bears (`special_bears`), and `""` anywhere else, outside an
    advanced game included."""
    if game is None:
        return ""
    text = engine.special_ability_reminder(game, player_id)
    if not text or not special_bears(engine, game, player_id, bearing):
        return ""
    return text

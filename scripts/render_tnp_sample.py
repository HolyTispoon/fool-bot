#!/usr/bin/env python3
"""Render The New Project's pictures to files, without running the bot.

    python3 scripts/render_tnp_sample.py --out /tmp/tnp

writes, into the folder named:

- `map-opening.png` -- map 3.3 at setup, every territory neutral;
- `map-midgame.png` -- a map part-way through a game's March: territories
  held by both seats, tokens harvested, a Stranded token, and the piles
  revealed so far;
- `board-blue-opening.png`, `board-green-opening.png` -- each seat's
  player board at setup;
- `board-green-midgame.png` -- a board with a Factory built, an Airport
  and units queued, and upgrades built and bought;
- `battle-territory-round3.png` and `battle-base-round3.png` -- a battle
  for a territory and an attack on a base, each fought through
  `tnp.flow.driver.apply` to round 3 with a seeded `engine.rng`.

The mid-game map and board are staged by hand, since the turn that
would produce them is step 4's. Look at what it draws: nothing rendered
is tested for how it looks (docs/design/tnp.md, "The pictures").
"""

import argparse
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tnp.battle import DAMAGE  # noqa: E402
from tnp.briefs import (  # noqa: E402
    FACE_DOWN, SHOWN, BoardBrief, DeploySpot, DeploymentBrief, MapBrief, Pile, SpotsBrief,
    opening_board, opening_map,
)
from tnp.components import MatchState  # noqa: E402
from tnp.engine import RulesEngine  # noqa: E402
from tnp.flow import battle as fight  # noqa: E402
from tnp.flow import driver  # noqa: E402
from tnp.prompts import Action, PendingPrompt, PromptKind, pending  # noqa: E402
from tnp.render import (  # noqa: E402
    render_attack, render_battle, render_board, render_deployment, render_map, render_spots,
)


def midgame_map(engine: RulesEngine) -> MapBrief:
    opening = opening_map(engine.catalog)
    resources = {slug: dict(left) for slug, left in opening.resources.items()}
    resources["14"]["blue_minerals"] = 6
    resources["12"]["orange_minerals"] = 7
    resources["4"]["orange_minerals"] = 8
    resources["7"]["gems"] = 0
    return MapBrief(
        controllers={"10": "blue", "14": "blue", "13": "blue", "8": "blue", "7": "blue",
                     "11": "green", "12": "green", "15": "green", "9": "green", "4": "green"},
        resources=resources,
        stranded={"7": ("blue",)},
        revealed=(
            Pile("blue", "2", "A", {"mercenary": 3, "worker": 2}),
            Pile("green", "3", "A", {"jeep": 2, "worker": 2}),
            Pile("green", "9", "defense", {"mercenary": 2}),
            Pile("blue", "9", "B", {"tank": 2, "mercenary": 2}),
        ),
        caption="Turn 5 · March, attack B",
    )


def midgame_board(engine: RulesEngine) -> BoardBrief:
    catalog = engine.catalog
    have = {"worker": 5, "mercenary": 6, "stealth_sniper": 2, "jeep": 2, "tank": 1}
    queued = {"tank": 2, "stealth_sniper": 1}
    return BoardBrief(
        seat="green",
        pool={"materials": 2, "gold": 1, "blue_minerals": 3, "orange_minerals": 0, "gems": 1},
        built=frozenset({"barracks", "base_defenses", "factory", "barracks_upgrade", "stealth_upgrade"}),
        queued=frozenset({"airport", "cyborg_upgrade"}),
        queued_units=queued,
        supply_left={
            slug: unit.supply - have.get(slug, 0) - queued.get(slug, 0)
            for slug, unit in catalog.units.items()
        },
        caption="Turn 5 · Infrastructure",
    )


def midgame_deployment() -> DeploymentBrief:
    """Blue's attack board mid-plan: both attacks aimed, one defense, the
    base empty, attack A being changed."""
    return DeploymentBrief(
        seat="blue",
        attacks=(
            DeploySpot("A", "3", None, True, {"worker": 2}, FACE_DOWN),
            DeploySpot("B", "5", "green", False, {"mercenary": 2, "jeep": 1}, FACE_DOWN),
        ),
        defenses=(
            DeploySpot("1", "14", "blue", None, {"mercenary": 1}, FACE_DOWN),
            DeploySpot("2"), DeploySpot("3"),
        ),
        base=DeploySpot("base"),
        at_base={"worker": 1, "mercenary": 1},
        queued={"worker": 2},
        picked="A",
        caption="Turn 2 · Infrastructure and Deployment",
    )


def march_spots() -> SpotsBrief:
    """Both deployment boards after Blue's attack A: it shown, everything
    else face down or empty."""
    return SpotsBrief(seats=(
        ("blue", (
            DeploySpot("A", "3", "blue", None, {"worker": 1}, SHOWN),
            DeploySpot("B", state=FACE_DOWN),
            DeploySpot("1", state=FACE_DOWN), DeploySpot("2"), DeploySpot("3"),
            DeploySpot("base"),
        )),
        ("green", (
            DeploySpot("A", state=FACE_DOWN), DeploySpot("B", state=FACE_DOWN),
            DeploySpot("1", state=FACE_DOWN), DeploySpot("2", state=FACE_DOWN), DeploySpot("3"),
            DeploySpot("base", "green_base", "green", None, {}, FACE_DOWN),
        )),
    ), caption="Turn 2 · March")


def answer(prompt: PendingPrompt, chooser: random.Random) -> Action:
    """A legal answer to any battle question, with some variety: a
    flanking slot where one is offered, otherwise any slot; fight on;
    the shooter's best target."""
    options, kind = prompt.options, prompt.kind
    if kind is PromptKind.CHOOSE_ROLE:
        return Action(kind, "attack")
    if kind is PromptKind.EMERGENCY_DEFENSE:
        return Action(kind, "none")
    if kind is PromptKind.REPOSITION_FLANKERS:
        return Action(kind, "keep")
    if kind is PromptKind.PLACE_FORCE:
        force = options.forces[0]
        flanks = [slot for slot in force.slots if slot.startswith("flank")]
        slot = flanks[0] if flanks else chooser.choice(force.slots)
        return Action(kind, "", {"force": force.force, "slot": slot})
    if kind is PromptKind.DECLARE_RETREAT:
        return Action(kind, "fight")
    if kind is PromptKind.CHOOSE_TARGET:
        shooter = options.forces[0]
        best = max(shooter.targets, key=lambda one: one.dice)
        return Action(kind, "", {"force": shooter.force, "target": best.target})
    if kind is PromptKind.REPAIR:
        return Action(kind, "decline")
    if kind is PromptKind.SPLASH:
        return Action(kind, "splash", {"force": options.forces[0]})
    if kind is PromptKind.DESTROY:
        return Action(kind, "", {"thing": options.things[0]})
    raise AssertionError(kind)


def battle_to_round_three(engine: RulesEngine, territory: str, forces, **opened) -> MatchState:
    """A battle opened and fought until round 3's damage is part-way
    rolled -- a hit scored and not yet taken off -- or until it ends."""
    match = MatchState()
    result = fight.begin_battle(engine, match, territory, forces, **opened)
    driver.advance(engine, None, match, result)
    chooser = random.Random(3)
    for _ in range(2000):
        battle = match.battle
        if battle.outcome is not None:
            break
        if battle.round == 3 and battle.phase == DAMAGE and battle.hits:
            break
        prompt = pending(engine, None, match)
        if not isinstance(prompt, PendingPrompt):
            break
        run = driver.apply(engine, None, match, answer(prompt, chooser))
        if isinstance(run, driver.Refusal):
            raise SystemExit(f"refused: {run.reason}")
    return match


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True, help="the folder to write the pictures into")
    parser.add_argument("--seed", type=int, default=4, help="the battles' engine.rng seed")
    arguments = parser.parse_args()
    out = arguments.out
    out.mkdir(parents=True, exist_ok=True)

    engine = RulesEngine(rng=random.Random(arguments.seed))
    catalog = engine.catalog
    pictures = {
        "map-opening.png": render_map(catalog, opening_map(catalog)),
        "map-midgame.png": render_map(catalog, midgame_map(engine)),
        # March's attacks, each its own picture: one pile, and a battle's two.
        "attack-A-2.png": render_attack(catalog, midgame_map(engine), "2", "A"),
        "attack-B-9.png": render_attack(catalog, midgame_map(engine), "9", "B"),
        "board-blue-opening.png": render_board(catalog, opening_board(catalog, "blue")),
        "board-green-opening.png": render_board(catalog, opening_board(catalog, "green")),
        "board-green-midgame.png": render_board(catalog, midgame_board(engine)),
        "deployment-blue-midplan.png": render_deployment(catalog, midgame_deployment()),
        "spots-march.png": render_spots(catalog, march_spots()),
    }

    territory = battle_to_round_three(
        engine, "8",
        {"blue": {"mercenary": 7, "tank": 2, "jeep": 2, "worker": 2, "stealth_sniper": 2},
         "green": {"mercenary": 7, "cyborg_soldier": 3, "stealth_sniper": 2, "jeep": 2, "worker": 2}},
        attacker="blue", held_by="green", paths_home={"blue": True, "green": True},
    )
    pictures["battle-territory-round3.png"] = render_battle(catalog, territory.battle)

    base = battle_to_round_three(
        RulesEngine(rng=random.Random(arguments.seed + 1)), "green_base",
        {"blue": {"mercenary": 6, "tank": 3, "cyborg_soldier": 2},
         "green": {"mercenary": 4, "smart_mines": 3, "rocket_launcher": 2}},
        paths_home={"blue": True, "green": True},
        structures={"facilities": ["barracks", "factory", "base_defenses"],
                    "upgrades": ["barracks_upgrade", "stealth_upgrade"]},
    )
    pictures["battle-base-round3.png"] = render_battle(catalog, base.battle)

    for name, data in pictures.items():
        (out / name).write_bytes(data)
        print(out / name)


if __name__ == "__main__":
    main()

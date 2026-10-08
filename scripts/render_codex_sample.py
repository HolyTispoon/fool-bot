#!/usr/bin/env python3
"""Render the Codex bot's pictures to files, without running the bot.

The opening position of Bashing against Finesse in both layouts, a
staged position from the middle of a game (units in play, exhausted and
just arrived, patrollers, damage, a building under construction, the
tower, the hero levelled) -- stacked, from each seat in turn, since the
stacked board is seen from the active player's side -- the first
player's hand, their codex through every view, and the tech picker's
codex with two picks marked:

    python3 scripts/render_codex_sample.py --out /tmp/codex

or a real saved game, so a board someone reported can be reproduced:

    python3 scripts/render_codex_sample.py --list-games
    python3 scripts/render_codex_sample.py --game <game_id> --out /tmp/codex

Look at what it draws: nothing rendered is tested for how it looks
(docs/design/codex.md, "The board on Discord").
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from codex.components import AddOnState, BuildingState, MatchState  # noqa: E402
from codex.engine import RulesEngine  # noqa: E402
from codex.game import BOARD_LAYOUTS  # noqa: E402
from codex.render import render_board, render_codex, render_hand  # noqa: E402
from gamesaves.codex.storage import load_games  # noqa: E402


def staged(engine: RulesEngine) -> MatchState:
    """A position from the middle of a game, with something in every
    place the mat has."""
    match = engine.new_match(("bashing", "finesse"), first=1)
    match.turn, match.phase = 9, "main"
    one, two = match.player(1), match.player(2)
    one.gold, one.workers, one.base_hp = 3, 8, 14
    two.gold, two.workers, two.base_hp = 1, 7, 17
    one.hero.zone, one.hero.level, one.hero.damage = "play", 5, 1
    two.hero.summoning_runes = 2
    one.buildings["tech1"] = BuildingState(hp=5, under_construction=False)
    one.buildings["tech2"] = BuildingState(hp=5, under_construction=True)
    two.buildings["tech1"] = BuildingState(hp=3, under_construction=False)
    one.add_on = AddOnState("tower", 4, under_construction=False)
    two.add_on = AddOnState("surplus", 2, under_construction=False)

    def put(seat, slug, *, patrol=None, damage=0, exhausted=False, arrived=False, plus=0):
        card = match.new_instance(slug, seat)
        card.patrol_slot, card.damage = patrol, damage
        card.exhausted, card.arrived_this_turn, card.plus_runes = exhausted, arrived, plus
        return card

    put(1, "iron_man", exhausted=True, damage=2)
    put(1, "revolver_ocelot")
    put(1, "older_brother", arrived=True)
    put(1, "brick_thief", plus=1)
    put(2, "nimble_fencer", patrol="squad_leader")
    put(2, "starcrossed_starlet", patrol="elite", damage=1)
    put(2, "tenderfoot", patrol="lookout")
    put(2, "helpful_turtle")
    one.discard = ["spark", "wither", "bloom"]
    two.discard = ["timely_messenger"]
    match.validate(engine.catalog)
    return match


def write(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    print(f"{path}  ({len(data) / 1024:.0f} KiB)")


def render_all(engine: RulesEngine, match: MatchState, names: dict, out: Path, stem: str,
               layouts=BOARD_LAYOUTS) -> None:
    for layout in layouts:
        write(out / f"{stem}-board-{layout}.webp", render_board(match, layout, names, engine.catalog))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "codex-samples")
    parser.add_argument("--game", help="a saved game's id, from data/codex_games.json")
    parser.add_argument("--list-games", action="store_true")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    engine = RulesEngine(seed=args.seed)
    if args.list_games:
        for game_id, game in load_games().items():
            print(game_id, game.game_number, game.status.value, game.player_1_name, game.player_2_name)
        return

    args.out.mkdir(parents=True, exist_ok=True)
    if args.game:
        game = load_games()[args.game]
        match = MatchState.from_dict(game.match_state)
        names = {1: game.player_1_name or "Player 1", 2: game.player_2_name or "Player 2"}
        render_all(engine, match, names, args.out, f"game-{game.game_number}", (game.board_layout,))
        return

    names = {1: "perrytom", 2: "opponent"}
    opening = engine.new_match(("bashing", "finesse"), first=1)
    render_all(engine, opening, names, args.out, "opening")
    midgame = staged(engine)
    render_all(engine, midgame, names, args.out, "midgame")
    # The stacked board turns round with the turn: the same position
    # from the other seat.
    midgame.active = 2
    render_all(engine, midgame, names, args.out, "midgame-seat-2", ("stacked",))

    rows = engine.hand_rows(opening, 1)
    write(args.out / "hand-opening.png", render_hand(
        [row.slug for row in rows], [row.allowed for row in rows], [row.cost for row in rows],
        engine.catalog,
    ))
    middle = staged(engine)
    middle.player(1).hand = ["iron_man", "spark", "trojan_duck", "older_brother", "wither"]
    rows = engine.hand_rows(middle, 1)
    write(args.out / "hand-midgame.png", render_hand(
        [row.slug for row in rows], [row.allowed for row in rows], [row.cost for row in rows],
        engine.catalog,
    ))
    middle.player(1).codex["iron_man"] = 0
    for view in engine.codex_views(middle.player(1)):
        rows = engine.codex_remaining(middle, 1, view)
        write(args.out / f"codex-{view}.png", render_codex(
            [slug for slug, _ in rows], [count for _, count in rows], engine.catalog,
        ))
    # The tech picker (`TechChoiceView`): the whole codex, the picks
    # framed and counted -- here two copies of one card.
    rows = engine.codex_counts(middle.player(1))
    picks = {"revolver_ocelot": 2}
    write(args.out / "tech-picker.png", render_codex(
        [slug for slug, _ in rows], [count for _, count in rows], engine.catalog,
        [picks.get(slug, 0) for slug, _ in rows],
    ))


if __name__ == "__main__":
    main()

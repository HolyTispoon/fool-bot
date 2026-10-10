#!/usr/bin/env python3
"""Render the Codex bot's pictures to files, without running the bot.

The opening position of Bashing against Finesse in both layouts, a
staged position from the middle of a game (units in play, exhausted and
just arrived, patrollers, damage, a building under construction, the
tower, the hero levelled) -- stacked, from each seat in turn, since the
stacked board is seen from the active player's side -- a position with
every other state on the design canvas's states board, the second
player's side alone as a target prompt pictures it, the first player's
hand, their codex through every view, and the tech picker's codex with
two picks marked; and beside them a standard game's -- red against
green, three heroes a side, the specs chosen at Tech II and on a tech
lab, a heroes' hall -- board, hand and codex, every view of its
seventy-two cards (`standard-*`); purple against black's states
(`purple-black-*`) and white against blue's (`white-blue-*`):

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
from codex.render import render_board, render_codex, render_hand, render_side  # noqa: E402
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


def staged_effects(engine: RulesEngine) -> MatchState:
    """What step 6 puts on the table (docs/design/codex.md, "Targeting
    and the effects"): Harmony in play with a Dancer and an Angry
    Dancer, Two Step and its two partners, a hero with a +1/+1 rune and
    a unit with a -1/-1."""
    match = staged(engine)
    one, two = match.player(1), match.player(2)
    two.hero.summoning_runes = 0
    two.hero.zone, two.hero.level = "play", 3
    two.hero.plus_runes = 1
    match.new_instance("harmony", 2)
    match.new_instance("dancer", 2)
    angry = match.new_instance("dancer", 2)
    angry.slug, angry.flipped = "angry_dancer", True
    turtle = next(card for card in two.play if card.slug == "helpful_turtle")
    fencer = next(card for card in two.play if card.slug == "nimble_fencer")
    step = match.new_instance("two_step", 2)
    step.attached = [turtle.id, fencer.id]
    brother = next(card for card in one.play if card.slug == "older_brother")
    brother.minus_runes = 1
    match.validate(engine.catalog)
    return match


def staged_states(engine: RulesEngine) -> MatchState:
    """Every state on the design canvas's states board that the other
    two positions do not show (docs/codex-bot.md, step 7): a tech
    building built and damaged, under construction, destroyed and not
    built; the base untouched and nearly down; the add-on slot empty
    and a damaged Surplus; a patroller with damage over its slot; a
    hero on the field at level 1, and one at level 3, damaged and
    summoned this turn; a unit ready, one with a +1/+1 rune and damage,
    a token arrived this turn, and one exhausted."""
    match = engine.new_match(("bashing", "finesse"), first=1)
    match.turn, match.phase = 7, "main"
    one, two = match.player(1), match.player(2)
    one.gold, one.workers = 2, 6
    two.gold, two.workers, two.base_hp = 5, 7, 4
    one.hero.zone, one.hero.level = "play", 1
    two.hero.zone, two.hero.level, two.hero.damage = "play", 3, 2
    two.hero.arrived_this_turn = True
    one.buildings["tech1"] = BuildingState(hp=2, under_construction=False)
    one.buildings["tech2"] = BuildingState(hp=5, under_construction=True)
    two.buildings["tech1"] = BuildingState(hp=0, under_construction=False, destroyed=True)
    two.add_on = AddOnState("surplus", 0, under_construction=False)
    two.add_on.hp = engine.catalog.building("surplus").hp - 2

    def put(seat, slug, *, patrol=None, damage=0, exhausted=False, arrived=False, plus=0):
        card = match.new_instance(slug, seat)
        card.patrol_slot, card.damage = patrol, damage
        card.exhausted, card.arrived_this_turn, card.plus_runes = exhausted, arrived, plus
        return card

    put(1, "granfalloon_flagbearer", patrol="scavenger", damage=2)
    put(1, "older_brother")
    put(1, "tenderfoot", plus=1, damage=2)
    put(1, "dancer", arrived=True)
    put(1, "brick_thief", exhausted=True)
    put(2, "helpful_turtle", patrol="squad_leader")
    put(2, "spectral_aven", exhausted=True)
    match.validate(engine.catalog)
    return match


def staged_standard(engine: RulesEngine) -> MatchState:
    """A standard game in its middle (docs/codex-bot.md, step 10): red
    (Fire, Anarchy, Blood) against green (Feral, Growth, Balance), two of
    the first side's heroes in play and the third in the command zone,
    its tech II's spec Fire and a heroes' hall built; the other side's
    tech II Feral, and a tech lab unlocking Growth -- and from step 11 a
    Bloodburn with blood runes, a growth rune and a polymorphed unit."""
    match = engine.new_match(
        (("fire", "anarchy", "blood"), ("feral", "growth", "balance")),
        first=1, decks=("red", "green"),
    )
    match.turn, match.phase = 11, "main"
    one, two = match.player(1), match.player(2)
    one.gold, one.workers, one.base_hp = 6, 9, 15
    two.gold, two.workers, two.base_hp = 2, 8, 12
    jaina, zane, drakk = one.heroes
    jaina.zone, jaina.level, jaina.damage = "play", 4, 1
    zane.zone, zane.level, zane.arrived_this_turn = "play", 1, True
    drakk.summoning_runes = 1
    calamandra = two.heroes[0]
    calamandra.zone, calamandra.level, calamandra.patrol_slot = "play", 3, "squad_leader"
    for player, spec in ((one, "fire"), (two, "feral")):
        player.buildings["tech1"] = BuildingState(hp=5, under_construction=False)
        player.buildings["tech2"] = BuildingState(hp=5, under_construction=False)
        player.tech2_spec = spec
        player.constructed_once = True
    one.add_on = AddOnState("heroes_hall", 4, under_construction=False)
    two.add_on = AddOnState("tech_lab", 3, under_construction=False, spec="growth")

    def put(seat, slug, *, patrol=None, damage=0, exhausted=False, arrived=False):
        card = match.new_instance(slug, seat)
        card.patrol_slot, card.damage = patrol, damage
        card.exhausted, card.arrived_this_turn = exhausted, arrived
        return card

    put(1, "nautical_dog", exhausted=True)
    put(1, "mad_man", arrived=True)
    put(1, "bombaster", damage=1)
    put(2, "tiger_cub", patrol="elite")
    put(2, "ironbark_treant", patrol="lookout")
    put(2, "merfolk_prospector", exhausted=True)
    # Step 11's states: Bloodburn's blood runes, a growth rune, and a
    # unit Polymorph: Squirrel has turned, drawn as the Squirrel.
    put(1, "bloodburn").runes["blood"] = 2
    put(2, "young_treant").runes["growth"] = 1
    put(2, "spore_shambler").printed = {"polymorph": 1}
    one.discard = ["scorch", "charge"]
    match.validate(engine.catalog)
    return match


def staged_purple_black(engine: RulesEngine) -> MatchState:
    """Purple (Past, Present, Future) against black (Demonology, Disease,
    Necromancy) in a standard game's middle (docs/codex-bot.md, step 12):
    a card fading with its time runes, two in the future greyed with
    theirs, Prynn with hers, a disabled unit exhausted and one ready, and
    a Graveyard with three units buried."""
    match = engine.new_match(
        (("past", "present", "future"), ("demonology", "disease", "necromancy")),
        first=1, decks=("purple", "black"),
    )
    match.turn, match.phase = 12, "main"
    one, two = match.player(1), match.player(2)
    one.gold, one.workers, one.base_hp = 4, 9, 16
    two.gold, two.workers, two.base_hp = 3, 9, 13
    prynn = one.hero_of("prynn_pasternaak")
    prynn.zone, prynn.level, prynn.time_runes = "play", 5, 2
    garth = two.hero_of("garth_torken")
    garth.zone, garth.level = "play", 3
    for player, spec in ((one, "future"), (two, "necromancy")):
        player.buildings["tech1"] = BuildingState(hp=5, under_construction=False)
        player.buildings["tech2"] = BuildingState(hp=5, under_construction=False)
        player.tech2_spec = spec
        player.constructed_once = True

    def put(seat, slug, *, patrol=None, exhausted=False, arrived=False):
        card = match.new_instance(slug, seat)
        card.patrol_slot, card.exhausted, card.arrived_this_turn = patrol, exhausted, arrived
        return card

    put(1, "fading_argonaut").time_runes = 2
    put(1, "neo_plexus", patrol="squad_leader")
    put(1, "argonaut", exhausted=True).disabled = True
    put(2, "skeleton", patrol="elite").minus_runes = 0
    put(2, "hooded_executioner").disabled = True
    graveyard = put(2, "graveyard")
    graveyard.buried = [{"slug": "argonaut", "owner": 1}, {"slug": "skeleton", "owner": 2},
                        {"slug": "neo_plexus", "owner": 1}]
    for slug, runes in (("reaver", 1), ("double_time", 3)):
        card = match.new_instance(slug, 1)
        one.play.remove(card)
        card.time_runes = runes
        one.future.append(card)
    match.validate(engine.catalog)
    return match


def staged_white_blue(engine: RulesEngine) -> MatchState:
    """White (Discipline, Ninjutsu, Strength) against blue (Law, Peace,
    Truth) in a standard game's middle (docs/codex-bot.md, step 13): a
    Jail holding a unit, Reputable Newsman with his number, Oathkeeper
    with his oath, a Mirror Illusion copying a unit, Justice Juggernaut
    with its crumbling rune and Grave Stormborne with his sword rune."""
    match = engine.new_match(
        (("discipline", "ninjutsu", "strength"), ("law", "peace", "truth")),
        first=1, decks=("white", "blue"),
    )
    match.turn, match.phase = 14, "main"
    one, two = match.player(1), match.player(2)
    one.gold, one.workers, one.base_hp = 5, 10, 15
    two.gold, two.workers, two.base_hp = 2, 9, 12
    grave = one.hero_of("grave_stormborne")
    grave.zone, grave.level, grave.runes = "play", 7, {"sword": 1}
    quince = two.hero_of("sirus_quince")
    quince.zone, quince.level = "play", 3
    for player, spec in ((one, "strength"), (two, "law")):
        for building in ("tech1", "tech2", "tech3"):
            player.buildings[building] = BuildingState(hp=5, under_construction=False)
        player.tech2_spec = spec
        player.constructed_once = True

    def put(seat, slug, *, patrol=None, exhausted=False, arrived=False):
        card = match.new_instance(slug, seat)
        card.patrol_slot, card.exhausted, card.arrived_this_turn = patrol, exhausted, arrived
        return card

    put(1, "oathkeeper_of_kor_mountain", patrol="squad_leader").oath = "draw"
    put(1, "fox_viper", patrol="elite")
    put(1, "morningstar_pass")
    jail = put(2, "jail")
    jail.jailed = {"slug": "colossus", "owner": 1, "controller": 1, "boosted": False}
    put(2, "reputable_newsman").number = 3
    put(2, "justice_juggernaut").runes = {"crumbling": 1}
    mirror = put(2, "mirror_illusion")
    mirror.copy_of = "fox_primus"
    put(2, "spectral_roc", patrol="squad_leader")
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
    render_all(engine, staged_effects(engine), names, args.out, "effects")
    states = staged_states(engine)
    render_all(engine, states, names, args.out, "states")
    states.active = 2
    render_all(engine, states, names, args.out, "states-seat-2", ("stacked",))
    # A target prompt's picture: the opponent's side alone, upright.
    write(args.out / "midgame-side-2.webp", render_side(staged(engine), 2, names[2], engine.catalog))

    rows = engine.hand_rows(opening, 1)
    write(args.out / "hand-opening.webp", render_hand(
        [row.slug for row in rows], [row.allowed for row in rows], [row.cost for row in rows],
        engine.catalog,
    ))
    middle = staged(engine)
    middle.player(1).hand = ["iron_man", "spark", "trojan_duck", "older_brother", "wither"]
    rows = engine.hand_rows(middle, 1)
    write(args.out / "hand-midgame.webp", render_hand(
        [row.slug for row in rows], [row.allowed for row in rows], [row.cost for row in rows],
        engine.catalog,
    ))
    middle.player(1).codex["iron_man"] = 0
    for view in engine.codex_views(middle.player(1)):
        rows = engine.codex_remaining(middle, 1, view)
        write(args.out / f"codex-{view}.webp", render_codex(
            [slug for slug, _ in rows], [count for _, count in rows], engine.catalog,
            None, engine.codex_row_starts(rows, view),
        ))
    # The tech picker (`TechChoiceView`): the whole codex, the picks
    # framed and counted -- here two copies of one card.
    rows = engine.codex_counts(middle.player(1))
    picks = {"revolver_ocelot": 2}
    write(args.out / "tech-picker.webp", render_codex(
        [slug for slug, _ in rows], [count for _, count in rows], engine.catalog,
        [picks.get(slug, 0) for slug, _ in rows],
    ))

    # Step 12: purple against black -- time runes, the future, disabled
    # cards and a Graveyard's buried count.
    render_all(engine, staged_purple_black(engine), names, args.out, "purple-black")

    # Step 13: white against blue -- a Jail's prisoner, Reputable
    # Newsman's number, Oathkeeper's oath, a copy, crumbling and sword runes.
    render_all(engine, staged_white_blue(engine), names, args.out, "white-blue")

    # The standard game: three heroes a side, a codex of seventy-two.
    standard = staged_standard(engine)
    render_all(engine, standard, names, args.out, "standard")
    standard.active = 2
    render_all(engine, standard, names, args.out, "standard-seat-2", ("stacked",))
    standard.active = 1
    standard.player(1).hand = ["scorch", "nautical_dog", "bloodburn", "charge", "careless_musketeer"]
    rows = engine.hand_rows(standard, 1)
    write(args.out / "standard-hand.webp", render_hand(
        [row.slug for row in rows], [row.allowed for row in rows], [row.cost for row in rows],
        engine.catalog,
    ))
    for view in engine.codex_views(standard.player(1)):
        rows = engine.codex_remaining(standard, 1, view)
        write(args.out / f"standard-codex-{view.replace(':', '-')}.webp", render_codex(
            [slug for slug, _ in rows], [count for _, count in rows], engine.catalog,
            None, engine.codex_row_starts(rows, view),
        ))


if __name__ == "__main__":
    main()

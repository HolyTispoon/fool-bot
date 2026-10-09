"""
A turn's phases that are nobody's choice: the ready phase and the
upkeep (`begin_turn`), the draw (`draw_phase`) and the end of the turn
(`begin_tech`), with the draw itself (`draw_cards`) that the
technician's card shares (UMR p. 5) -- and a concession (`concede`),
which ends the game from outside any phase.

Each step takes `(engine, game, match)`, changes the match, and returns
a `StepResult` in the model's voice with tokens; it sends nothing and
saves nothing (docs/design/model-discord-split.md, principle 4). **Nothing
hidden is said**: a draw is a count, a tech choice is a count, a hired
worker's card is never named.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from codex import effects, history, tokens
from codex.formatting import deck_name
from codex.components import MatchState
from codex.engine import GOLD_CAP, SQUAD_LEADER_ARMOR
from codex.flow.result import FollowOn, FollowOnStep, Headline, StepResult
from codex.game import RuleRefusal
from codex.prompts import pending, tech_is_owed

if TYPE_CHECKING:
    from codex.engine import RulesEngine
    from codex.game import CodexGame


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def draw_cards(engine: "RulesEngine", match: MatchState, seat: int, count: int,
               result: StepResult) -> int:
    """
    `seat` draws up to `count` cards off the top of their deck, shuffling
    the discard pile into an empty deck once a phase (UMR p. 5); each
    shuffle's order goes into `result.drawn` for the journal. Returns
    how many were drawn, which is fewer only when both piles run out.
    """
    player = match.player(seat)
    drawn = 0
    for _ in range(count):
        if not player.deck:
            if player.reshuffled_this_phase or not player.discard:
                break
            player.deck = engine.shuffle(player.discard)
            player.discard = []
            player.reshuffled_this_phase = True
            result.drawn.append(list(player.deck))
            result.narration.append(
                f"{tokens.player(seat)} shuffles their discard pile into their deck."
            )
        player.hand.append(player.deck.pop())
        drawn += 1
    return drawn


def gain_gold(match: MatchState, seat: int, amount: int) -> int:
    """Gold to `seat`, to the cap of 20 (UMR p. 5); what was gained."""
    player = match.player(seat)
    before = player.gold
    player.gold = min(GOLD_CAP, player.gold + amount)
    return player.gold - before


def damage_base(match: MatchState, seat: int, amount: int, result: StepResult,
                by: Optional[int] = None) -> None:
    """Damage onto `seat`'s base; at 0 it is destroyed and the game ends
    (UMR p. 2)."""
    player = match.player(seat)
    player.base_hp = max(0, player.base_hp - amount)
    if player.base_hp == 0 and match.winner is None:
        match.winner = 2 if seat == 1 else 1
        match.record_event("base_destroyed", loser=seat, winner=match.winner)
        text = f"{tokens.player(seat)}'s base is destroyed. {tokens.player(match.winner)} wins!"
        result.narration.append(f"**{text}**")
        result.headlines = (*result.headlines, Headline(text, seat=match.winner))


def concede(engine: "RulesEngine", game: "CodexGame", match: MatchState,
            seat: int) -> StepResult:
    """
    `seat` gives the game up, whoever's turn it is: the other player
    wins, as if `seat`'s base had been destroyed, and the game waits on
    `GAME_OVER`. Refused once the game is over. **Not an action the
    journal records** -- nothing is undone past a finished game
    (`codex.history.undo_targets`) -- so the service calls it as a door
    of its own, as it calls the undos.
    """
    if seat not in (1, 2):
        raise RuleRefusal("Only one of the game's two players can concede it.")
    if match.winner is not None:
        raise RuleRefusal("This game is already over.")
    match.winner = 2 if seat == 1 else 1
    match.conceded = seat
    match.record_event("conceded", loser=seat, winner=match.winner)
    text = f"{tokens.player(seat)} concedes. {tokens.player(match.winner)} wins!"
    return StepResult(
        narration=[f"**{text}**"],
        board_changed=True,
        headlines=(Headline(text, seat=match.winner),),
        next=pending(engine, game, match),
    )


def begin_turn(engine: "RulesEngine", game: "CodexGame", match: MatchState,
               lead_in: str = "") -> StepResult:
    """
    The ready phase and the upkeep (UMR p. 5), then the turn-start
    snapshot. Refused while the active player's tech choice still waits
    on its confirmation: the ready phase is where it is settled.
    """
    seat = match.active
    player = match.active_player
    if tech_is_owed(match, seat):
        raise RuleRefusal(
            "The turn cannot begin until the tech choice is confirmed.", cite="UMR p. 5",
        )
    # No line opens the turn: a frontend heads the turn with whose it is
    # (the Discord turn message's "**Turn 7** -- @perrytom (Bashing)"),
    # and a line of the model's saying it again was the same words twice
    # (the author, 2026-10-08). The turn's end is the model's to say.
    result = StepResult(narration=[lead_in] if lead_in else [], board_changed=True)

    # Ready.
    match.enter_phase("ready")
    if player.tech_owed:
        picks = list(player.tech_choice or ())
        for slug in picks:
            player.codex[slug] -= 1
            player.discard.append(slug)
        if picks:
            result.narration.append(
                f"{tokens.player(seat)} puts {_plural(len(picks), 'tech card')} "
                "into their discard pile."
            )
        player.tech_choice = None
        player.tech_owed = False
        player.tech_confirmed = False
    for card in player.play:
        card.exhausted = False
        card.arrived_this_turn = False
        card.patrol_slot = None
    for hero in player.heroes:
        hero.exhausted = False
        hero.arrived_this_turn = False
        hero.patrol_slot = None
    player.hired_this_turn = False
    # Readiness attacks once a turn and a tower detects once a turn
    # (UMR p. 9, 17), so both are new each turn, on both sides.
    for side in match.players:
        for body in (*side.play, *side.heroes):
            body.attacked_this_turn = False
        if side.add_on is not None:
            side.add_on.detected = None
    # Armor refreshes at the start of every turn (UMR p. 10); only the
    # other player's patrollers are standing in their slots now.
    for side in match.players:
        for body in (*side.play, *side.heroes):
            body.armor = SQUAD_LEADER_ARMOR if body.patrol_slot == "squad_leader" else 0
    for hero in player.heroes:
        hero.max_level_since_turn_began = (
            hero.in_play and hero.level == engine.hero_card(hero).max_level
        )

    # Upkeep.
    match.enter_phase("upkeep")
    gained = gain_gold(match, seat, player.workers)
    collected = (
        f"{tokens.player(seat)} collects {tokens.gold(gained)} from "
        f"{_plural(player.workers, 'worker')}"
    )
    if gained < player.workers:
        # Said where it bites, so a short income is not read as a slip
        # (the author, 2026-10-08).
        collected += f" and hits the gold cap: {tokens.gold(player.gold)}."
    else:
        collected += f": {tokens.gold(player.gold)}."
    result.narration.append(collected)
    # One summoning rune off each hero (UMR p. 5).
    for hero in player.heroes:
        if not hero.in_play and hero.summoning_runes:
            hero.summoning_runes -= 1
            result.narration.append(
                f"{tokens.hero(hero.slug)} loses a summoning rune "
                f"({hero.summoning_runes} left)."
            )
    if engine.upkeep_order_matters(player):
        # The active player orders their upkeep effects (Starlet's
        # ruling): asked, and the main phase opens on the answer.
        match.resolving.append({"kind": "upkeep_order", "seat": seat})
        result.next = pending(engine, game, match)
        return result
    _upkeep_effects(engine, match, engine.upkeep_effects(player), result)
    return _open_main(engine, game, match, result)


def finish_upkeep(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                  first: str) -> StepResult:
    """The answer to `UPKEEP_ORDER`: the upkeep effects with `first`
    before the other, then the main phase."""
    seat = match.active
    player = match.active_player
    if not match.resolving or match.resolving[0].get("kind") != "upkeep_order":
        raise RuleRefusal("The upkeep is not waiting on its order.")
    due = engine.upkeep_effects(player)
    if first not in due or first not in ("healing", "starlet"):
        raise RuleRefusal("That is not one of the upkeep effects to order.", cite="starcrossed_starlet")
    match.resolving.pop(0)
    rest = [name for name in due if name not in ("healing", "starlet")]
    second = "starlet" if first == "healing" else "healing"
    result = StepResult(board_changed=True)
    _upkeep_effects(engine, match, (*rest, first, second), result)
    return _open_main(engine, game, match, result)


def _upkeep_effects(engine: "RulesEngine", match: MatchState, order, result: StepResult) -> None:
    """
    The upkeep effects, in `order` (UMR p. 5): the surplus's card,
    healing X -- damage chits off every friendly unit and hero, and
    nothing else (UMR p. 17; the healing ruling) -- and each Star-Crossed
    Starlet's 1 damage to herself, which can kill her.
    """
    from codex.flow import board

    seat = match.active
    player = match.active_player
    for effect in order:
        if effect == "draw":
            if draw_cards(engine, match, seat, 1, result):
                result.narration.append(
                    f"{tokens.player(seat)} draws a card from their {tokens.card('surplus')}."
                )
        elif effect == "healing":
            healing = engine.healing(player)
            healed = 0
            bodies = [*player.play, *player.heroes_in_play]
            for body in bodies:
                taken = min(body.damage, healing)
                body.damage -= taken
                healed += taken
            if healed:
                result.narration.append(
                    f"{tokens.player(seat)} heals {healing} damage from each of their "
                    "units and heroes."
                )
        elif effect == "starlet":
            for card in list(player.play):
                if card.slug in effects.UPKEEP_SELF_DAMAGE:
                    card.damage += 1
                    result.narration.append(f"{tokens.card(card.slug)} takes 1 damage.")
            board.settle(engine, match, result)


def _open_main(engine: "RulesEngine", game: "CodexGame", match: MatchState,
               result: StepResult) -> StepResult:
    """The main phase opens: the turn-start snapshot is taken here, once
    the upkeep is done."""
    match.enter_phase("main")
    match.record_event("turn_began")
    history.snapshot(match)
    result.next = pending(engine, game, match)
    return result


def draw_phase(engine: "RulesEngine", game: "CodexGame", match: MatchState,
               lead_in: str = "") -> StepResult:
    """The hand to the discard face-down, then two more drawn than were
    discarded, to at most five (UMR p. 5)."""
    seat = match.active
    player = match.active_player
    result = StepResult(narration=[lead_in] if lead_in else [], board_changed=True)
    discarded = len(player.hand)
    player.discard.extend(player.hand)
    player.hand = []
    owed = engine.draw_count(discarded)
    # The count goes first, though it is only known after the draw: a
    # reshuffle the draw needed is said beneath it.
    at = len(result.narration)
    drawn = draw_cards(engine, match, seat, owed, result)
    result.narration.insert(
        at, f"{tokens.player(seat)} discards {discarded} and draws {drawn}.",
    )
    match.enter_phase("tech")
    result.next = FollowOn(FollowOnStep.BEGIN_TECH)
    return result


def begin_tech(engine: "RulesEngine", game: "CodexGame", match: MatchState,
               lead_in: str = "") -> StepResult:
    """
    The end of the turn: buildings under construction are finished, the
    turn's effects end, the player whose turn it was owes their tech
    choice -- offered now and open until their next turn begins -- and
    the turn passes, said in its own line: "**End of turn 3** --
    perrytom (Bashing).", the player and their deck as the turn's
    heading names them (`codex.formatting.turn_heading`).
    """
    seat = match.active
    player = match.active_player
    result = StepResult(narration=[lead_in] if lead_in else [], board_changed=True)
    for name, building in player.buildings.items():
        if building is not None and building.under_construction and not building.destroyed:
            building.under_construction = False
            result.narration.append(f"{tokens.player(seat)}'s {_TECH_NAMES[name]} building is finished.")
    if player.add_on is not None and player.add_on.under_construction:
        player.add_on.under_construction = False
        result.narration.append(
            f"{tokens.player(seat)}'s {tokens.card(player.add_on.slug)} is finished."
        )
    # This turn's effects end (Intimidate, Discord, Sneaky Pig's
    # stealth), on both sides, heroes too.
    for side in match.players:
        for body in (*side.play, *side.heroes):
            body.modifiers = [m for m in body.modifiers if m.get("until") != "end_of_turn"]
    minimum, maximum = engine.tech_bounds(player)
    player.tech_owed = maximum > 0
    player.tech_choice = None
    player.tech_confirmed = False
    # The model says the turn is over (the event log already records
    # which, as every event does): a frontend closes the turn on this
    # step (`FollowOnStep.BEGIN_TECH`), never by comparing turn numbers
    # of its own.
    result.narration.append(
        f"**End of turn {match.turn}** -- {tokens.player(seat)} "
        f"({deck_name(player.specs)})."
    )
    match.record_event("turn_ended")
    match.attacking = None
    match.active = 2 if seat == 1 else 1
    match.turn += 1
    match.enter_phase("ready")
    result.next = pending(engine, game, match)
    return result


_TECH_NAMES = {"tech1": "Tech I", "tech2": "Tech II", "tech3": "Tech III"}

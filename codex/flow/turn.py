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
    player.spells_played = 0
    player.arrived_from_hand = False
    # Moment's Peace holds "until your next turn" (step 11).
    player.peace = False
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
            change = effects.WHILE_PATROLLING.get(getattr(body, "slug", ""))
            if change is not None and body.patrol_slot is not None and side.seat != seat:
                # Ironbark Treant's +2 armor, new on each opponent's turn
                # while it patrols (its rulings); it stacks with the squad
                # leader's (UMR p. 16).
                body.armor += change[1]
    for hero in player.heroes:
        hero.max_level_since_turn_began = (
            hero.in_play and hero.level == engine.hero_card(hero).max_level
        )

    # Upkeep.
    match.enter_phase("upkeep")
    _until_upkeep_ends(engine, match, seat, result)
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
    # The upkeep effects (UMR p. 5), a frame at the foot of the stack
    # while they run, so a question one asks -- Land Octopus's choice, a
    # death's target, the order itself -- stands where a restart finds it.
    match.resolving.append(upkeep_frame(engine, match, seat))
    return carry_on_upkeep(engine, game, match, result)


def _until_upkeep_ends(engine: "RulesEngine", match: MatchState, seat: int,
                       result: StepResult) -> None:
    """What lasts "until your next upkeep" ends as it opens: Polymorph:
    Squirrel's transformation and Ferocity's armor piercing and swift
    strike, whoever's units they are on."""
    from codex.flow import board

    for side in match.players:
        for card in side.play:
            if card.printed and card.printed.get("polymorph") == seat:
                card.printed = {k: v for k, v in card.printed.items() if k != "polymorph"} or None
                result.narration.append(f"{tokens.card(card.slug)} is itself again.")
            card.modifiers = [
                m for m in card.modifiers
                if not (m.get("until") == "upkeep" and m.get("seat") == seat)
            ]
        side.lasting = [
            lasting for lasting in side.lasting
            if not (lasting.get("until") == "upkeep" and lasting.get("seat") == seat)
        ]
    board.settle(engine, match, result)


UPKEEP = "upkeep_order"


def upkeep_frame(engine: "RulesEngine", match: MatchState, seat: int) -> dict:
    """
    The upkeep's frame: `due`, the effects still to run, the ones that
    need nothing ordered first in a fixed order, then -- `ordered` -- the
    ones whose order changes something, asked (`UPKEEP_ORDER`). **The
    order is asked only where it changes something**: a death or a
    sacrifice among the effects due beside what it would change --
    Star-Crossed Starlet's damage and healing (her ruling), and either
    of Starlet's or Land Octopus's beside Dothram Horselord, whose side
    a death can change (step 11). Pure gains -- the surplus's card, the
    Owl's and Galina's gold -- resolve unasked.
    """
    due = list(engine.upkeep_effects(match.player(seat)))
    ordered = list(engine.upkeep_ordered(due))
    first = [name for name in due if name not in ordered]
    return {"kind": UPKEEP, "seat": seat, "due": first + ordered, "ordered": ordered}


def _legacy_upkeep(engine: "RulesEngine", match: MatchState, frame: dict) -> None:
    """A frame saved before step 11 asked healing against Starlet and
    held nothing else: what it owes is read again off the position."""
    if "due" not in frame:
        rebuilt = upkeep_frame(engine, match, frame["seat"])
        frame.update(due=rebuilt["due"], ordered=rebuilt["ordered"])


def upkeep_asks(match: MatchState) -> Optional[list]:
    """The effects the upkeep asks the order of now, or `None`: two or
    more of the ordered ones still due, the next one among them."""
    frame = match.resolving[0] if match.resolving else None
    if frame is None or frame.get("kind") != UPKEEP:
        return None
    if "due" not in frame:
        return ["healing", "starlet"]
    left = [name for name in frame["due"] if name in frame["ordered"]]
    if len(left) >= 2 and frame["due"] and frame["due"][0] in left:
        return left
    return None


def carry_on_upkeep(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                    result: StepResult) -> StepResult:
    """
    Run the upkeep on from where it stands: whatever an effect set off
    first (the frames in front of the upkeep's), then the next effect due
    -- or the question of which goes next -- and, with nothing left, the
    main phase.
    """
    from codex.flow import resolve

    while True:
        frame = next((one for one in match.resolving if one.get("kind") == UPKEEP), None)
        if frame is None:
            return _open_main(engine, game, match, result)
        # What an effect set off resolves before the next effect runs.
        match.resolving.remove(frame)
        match.resolving.append(frame)
        if match.resolving[0] is not frame:
            resolve.run(engine, match, result)
            if match.winner is not None:
                match.resolving = []
                result.next = pending(engine, game, match)
                return result
            if match.resolving and match.resolving[0] is not frame:
                result.next = pending(engine, game, match)
                return result
        _legacy_upkeep(engine, match, frame)
        if not frame["due"]:
            match.resolving.remove(frame)
            continue
        if upkeep_asks(match) is not None:
            result.next = pending(engine, game, match)
            return result
        name = frame["due"].pop(0)
        _upkeep_effect(engine, match, frame["seat"], name, result)


def finish_upkeep(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                  first: str) -> StepResult:
    """The answer to `UPKEEP_ORDER`: `first` runs next, of the effects
    whose order is asked, then the upkeep goes on -- asking again where
    two or more are still due."""
    asks = upkeep_asks(match)
    if asks is None:
        raise RuleRefusal("The upkeep is not waiting on its order.")
    if first not in asks:
        raise RuleRefusal("That is not one of the upkeep effects to order.", cite="starcrossed_starlet")
    frame = match.resolving[0]
    _legacy_upkeep(engine, match, frame)
    frame["due"].remove(first)
    frame["due"].insert(0, first)
    # Chosen: it runs now, whatever is ordered after it.
    frame["ordered"] = [name for name in frame["ordered"] if name != first]
    result = StepResult(board_changed=True)
    return carry_on_upkeep(engine, game, match, result)


def _upkeep_effect(engine: "RulesEngine", match: MatchState, seat: int, name: str,
                   result: StepResult) -> None:
    """
    One upkeep effect (UMR p. 5): the surplus's card; healing X -- damage
    chits off every friendly unit and hero, and nothing else (UMR p. 17;
    the healing ruling); each Star-Crossed Starlet's 1 damage to herself,
    which can kill her; and red and green's (step 11): Gemscout Owl's
    gold, Galina Glimmer's gold for every two green units (herself
    counted, rounded down), Land Octopus's choice -- two workers or
    itself -- and Dothram Horselord joining the side with more total ATK.
    """
    from codex.flow import board, resolve

    player = match.player(seat)
    kind, _, ident = name.partition(":")
    if kind == "draw":
        if draw_cards(engine, match, seat, 1, result):
            result.narration.append(
                f"{tokens.player(seat)} draws a card from their {tokens.card('surplus')}."
            )
    elif kind == "healing":
        healing = engine.healing(player)
        healed = 0
        bodies = [card for card in player.play if engine.catalog.cards[card.slug].is_unit]
        for body in [*bodies, *player.heroes_in_play]:
            taken = min(body.damage, healing)
            body.damage -= taken
            healed += taken
        if healed:
            result.narration.append(
                f"{tokens.player(seat)} heals {healing} damage from each of their "
                "units and heroes."
            )
    elif kind == "starlet":
        for card in list(player.play):
            if engine.text_slug(card) in effects.UPKEEP_SELF_DAMAGE:
                card.damage += 1
                result.narration.append(f"{tokens.card(card.slug)} takes 1 damage.")
        board.settle(engine, match, result)
    elif kind == "owl":
        owls = sum(1 for card in player.play if engine.text_slug(card) in effects.UPKEEP_GOLD)
        gained = gain_gold(match, seat, owls)
        result.narration.append(
            f"{tokens.player(seat)} gains {tokens.gold(gained)} from "
            f"{tokens.card('gemscout_owl')}."
        )
    elif kind == "galina":
        green = sum(
            1 for card in player.play
            if engine.catalog.cards[card.slug].is_unit and engine.color_of(card) == "green"
        )
        gained = gain_gold(match, seat, green // 2)
        result.narration.append(
            f"{tokens.player(seat)} gains {tokens.gold(gained)} from "
            f"{tokens.card('galina_glimmer')}: {green} green units."
        )
    elif kind == "octopus":
        card = player.instance(int(ident))
        if card is not None:
            match.resolving.insert(0, resolve.frame(
                effects.UPKEEP_CHOICE[card.slug], seat, tokens.card(card.slug),
                source=card.ref, origin=card.slug,
            ))
    elif kind == "dothram":
        card = player.instance(int(ident))
        if card is not None:
            _dothram(engine, match, card, result)
    board.settle(engine, match, result)


def _dothram(engine: "RulesEngine", match: MatchState, card, result: StepResult) -> None:
    """
    Dothram Horselord: "If a player has more total ATK than each other
    player, Dothram Horselord joins their forces." -- every unit and hero
    each player has in play, his own ATK on his side (his ruling).
    """
    from codex.flow import board

    totals = {player.seat: engine.total_atk(match, player.seat) for player in match.players}
    ahead = max(totals, key=totals.get)
    if any(totals[seat] >= totals[ahead] for seat in totals if seat != ahead):
        result.narration.append(
            f"{tokens.card(card.slug)} stays: no player has more total ATK than the other "
            f"({totals[1]} and {totals[2]})."
        )
        return
    if ahead == card.controller:
        result.narration.append(
            f"{tokens.card(card.slug)} stays with {tokens.player(ahead)}, who has the most total ATK "
            f"({totals[ahead]})."
        )
        return
    board.gain_control(match, card, ahead)
    result.narration.append(
        f"{tokens.card(card.slug)} joins {tokens.player(ahead)}'s forces: they have the most total "
        f"ATK ({totals[ahead]} to {totals[2 if ahead == 1 else 1]})."
    )


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
    end_of_turn(engine, match, result)
    from codex.flow import resolve

    if not resolve.run(engine, match, result):
        # A death at the end of the turn asks something -- Crash Bomber's
        # target on its controller's turn: asked, and the turn ends on
        # the answer (`pending` names BEGIN_TECH once the stack is empty).
        result.next = pending(engine, game, match)
        return result
    result.next = FollowOn(FollowOnStep.BEGIN_TECH)
    return result


def end_of_turn(engine: "RulesEngine", match: MatchState, result: StepResult) -> None:
    """
    What happens at the end of the turn, after the draw phase and before
    the buildings finish (step 11), on both sides, in this order: every
    ephemeral unit dies ("Destroy this card at the end of any turn,
    including any opponent's turn", UMR p. 16); Bloodrage Ogre returns to
    its owner's hand where it neither arrived nor attacked this turn --
    on its controller's turn alone, after the draw (its rulings);
    Chameleon Lizzo returns, if still in play, at the end of any turn;
    Bloodlust's 1 damage to each it was given to; and a kidnapped unit
    goes back to whoever had it (Kidnapping's Card FAQ). This turn's
    modifiers and printed values go after, in `begin_tech`.
    """
    from codex.flow import board

    dying = [
        (card.controller, card.ref) for side in match.players for card in side.play
        if engine.has_keyword(card, "Ephemeral", match)
    ]
    if dying:
        board.destroy(engine, match, dying, result)
        board.settle(engine, match, result)
    for side in match.players:
        for card in list(side.play):
            slug = engine.text_slug(card)
            idle = (
                slug in effects.RETURNS_IF_IDLE and card.controller == match.active
                and not card.arrived_this_turn and not card.attacked_this_turn
            )
            if idle or slug in effects.RETURNS_AT_END:
                result.narration.append(
                    f"{tokens.card(card.slug)} returns to {tokens.player(card.owner)}'s hand."
                )
                board.leave_play(engine, match, card, "hand")
                match.record_event("returned", slug=card.slug, owner=card.owner)
    for side in match.players:
        for body in (*side.play, *side.heroes_in_play):
            lust = sum(1 for m in body.modifiers if m.get("kind") == "bloodlust")
            if lust:
                landed = board.take_damage(body, lust)
                name = tokens.hero(body.slug) if not hasattr(body, "ref") else tokens.card(body.slug)
                result.narration.append(f"{name} takes {landed} damage from {tokens.card('bloodlust')}.")
    board.settle(engine, match, result)
    for side in match.players:
        for card in list(side.play):
            if card.returns_to is not None:
                board.give_back(match, card, result)
    board.settle(engine, match, result)


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
        side.lasting = [lasting for lasting in side.lasting if lasting.get("until") != "end_of_turn"]
        for body in (*side.play, *side.heroes):
            # Temporary armor not used up goes with the turn (UMR p. 16).
            lent = sum(m.get("amount", 0) for m in body.modifiers
                       if m.get("kind") == "armor" and m.get("until") == "end_of_turn")
            body.armor = max(0, body.armor - lent)
            body.modifiers = [m for m in body.modifiers if m.get("until") != "end_of_turn"]
            # Chaos Mirror's swap lasts the turn.
            if body.printed and "atk" in body.printed:
                body.printed = {k: v for k, v in body.printed.items() if k != "atk"} or None
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

"""
Plain-text formatting over the cards, with nothing that touches Discord.
"""

from __future__ import annotations

from codex import tokens
from codex.cards import COLOR_DECK_NAMES, Card, Hero, catalog

#: How a token reads where nothing draws it.
PLAIN_WORDS = {
    "exhaust": "[exhaust]",
    "target": "[target]",
    "arrow": "->",
    "codex": "",
}


def plain_token(kind: str, arguments: tuple[str, ...]) -> str:
    if kind == "gold":
        return f"({arguments[0]})"
    if kind in ("player", "to"):
        return f"Player {arguments[0]}"
    if kind in ("card", "hero"):
        try:
            return catalog().name(arguments[0])
        except KeyError:
            return arguments[0]
    return PLAIN_WORDS[kind]


def plain_text(text: str) -> str:
    """A line of card text with its tokens as words: `{gold:2}` is
    "(2)", `{exhaust}` "[exhaust]"."""
    return tokens.render(text, plain_token)


def card_label(card: Card | Hero) -> str:
    """
    A card the way a list names it: "Trojan Duck 8/9" -- a unit's ATK/HP
    after its name; a spell "Spark"; a hero "Troq Bashar 2/3" at its
    first band. No gold cost: the author took it out of the tech
    picker's menu, the one list that names a card this way (2026-10-11).
    """
    if isinstance(card, Hero):
        band = card.bands[0]
        return f"{card.name} {band.atk}/{band.hp}"
    if card.atk is not None and card.hp is not None:
        return f"{card.name} {card.atk}/{card.hp}"
    return card.name


#: The patrol slots in words, as a line or a menu names them.
SLOT_NAMES = {
    "squad_leader": "squad leader",
    "elite": "elite",
    "scavenger": "scavenger",
    "technician": "technician",
    "lookout": "lookout",
}


def slot_name(slot: str) -> str:
    return SLOT_NAMES.get(slot, slot.replace("_", " "))


def ref_label(engine, match, seat: int, ref: str, note: str = "") -> str:
    """
    What `ref` names on `seat`'s side, in plain words for a button or a
    menu: "Iron Man 3/4", "Troq Bashar 2/3", "Tech II (5 HP)", "Tower
    (4 HP)", "Base (17 HP)". A unit's or hero's numbers are the
    engine's, with its damage after them where it has any; a building's
    is the HP it has left (`building_hp_left`, the author, 2026-10-15).
    A `note` -- why a defender is legal -- goes in brackets after it,
    in the one bracket a building's HP is already in: "Base (20 HP,
    flying)", "Iron Man 3/4 (patroller)". A name, never a rule.
    """
    label = _ref_label(engine, match, seat, ref, note)
    if note and engine.building_hp_left(match, seat, ref) is None:
        label += f" ({note})"
    return label


def _ref_label(engine, match, seat: int, ref: str, note: str) -> str:
    from codex.components import is_hero_ref
    from codex.engine import building_name, unit_ref

    player = match.player(seat)
    if ref == "workers":
        return f"Workers ({player.workers})"
    if "#" in ref:
        # Plague Lab: one kind of rune on a card.
        ref, _, kind = ref.partition("#")
        rune = {"plus": "+1/+1", "minus": "-1/-1"}.get(kind, kind)
        return f"{ref_label(engine, match, seat, ref)}: another {rune} rune"
    if ref.startswith("buried:"):
        from codex.engine import buried_entry

        found = buried_entry(match, ref)
        if found is not None:
            return f"{catalog().name(found[1]['slug'])} (buried)"
    for prefix, where in (("slot:", "slot"), ("hand:", "from the hand"), ("codex:", "from the codex"),
                          ("discard:", "from the discard pile"), ("deck:", "on top of the draw pile")):
        if ref.startswith(prefix):
            name = ref[len(prefix):]
            if prefix == "slot:":
                return f"The {slot_name(name)} slot"
            return f"{catalog().name(name)} ({where})"
    if ref.startswith("future:"):
        card = next((one for one in player.future if f"future:{one.id}" == ref), None)
        if card is not None:
            return f"{catalog().name(card.slug)} (in the future, {card.time_runes} time runes)"
    # Either spelling: a hero lent into `seat`'s patrol zone is named
    # `<owner seat>:hero:<slug>` there (`MatchState.hero_on`).
    hero = match.hero_on(seat, ref) if is_hero_ref(ref) else None
    if hero is not None:
        atk, hp = engine.hero_stats(hero)
        label = f"{catalog().name(hero.slug)} {atk}/{hp}"
        damage = hero.damage
    else:
        instance_id = unit_ref(ref)
        card = player.instance(instance_id) if instance_id is not None else None
        if card is None:
            name = (catalog().name(player.add_on.slug) if ref == "add_on" and player.add_on is not None
                    else "Base" if ref == "base" else building_name(ref))
            return _with_hp_left(engine, match, seat, ref, name, note)
        atk, hp = engine.unit_stats(card, match)
        name = catalog().name(card.slug)
        number = copy_number(player, card)
        if number:
            name += f" #{number}"
        if catalog().cards[card.slug].is_building_card:
            # A building card has HP and no ATK: what it has left.
            return _with_hp_left(engine, match, seat, ref, name, note)
        if catalog().cards[card.slug].is_permanent:
            # An upgrade has neither.
            label = name + (f" ({hp} HP)" if hp else "")
        else:
            label = f"{name} {atk}/{hp}"
        damage = card.damage
    return f"{label}, {damage} damage" if damage else label


def _with_hp_left(engine, match, seat: int, ref: str, name: str, note: str = "") -> str:
    left = engine.building_hp_left(match, seat, ref)
    if left is None:
        return name
    return f"{name} ({left} HP, {note})" if note else f"{name} ({left} HP)"


def copy_number(player, card) -> int:
    """
    Which of `player`'s copies in play `card` is, counted in the order
    they came into play from 1 -- 0 where it is the only one. Two Bone
    Collectors 3/3 read alike on two buttons, so each is labelled
    "Bone Collector #1 3/3" and carries its number on the board's
    picture (the author, 2026-10-11). A copy keeps its number while the
    ones before it stay in play. A name, never a rule.
    """
    copies = [one.id for one in player.play if one.slug == card.slug]
    return copies.index(card.id) + 1 if len(copies) > 1 and card.id in copies else 0


#: What the built-in codex views are called (`RulesEngine.codex_views`).
CODEX_VIEW_NAMES = {
    "everything": "Everything",
    "tech1": "Tech I",
    "tech2": "Tech II & III",
    "spells": "Spells",
}


def codex_view_name(view: str) -> str:
    """
    A codex view by name: "Everything", "Tech I", "Tech II & III", "Spells",
    and a spec's view by the spec -- "Anarchy" -- as `deck_name` spells
    it. The Codex menu and the tech picker's both say it.
    """
    if view.startswith("spec:"):
        return deck_name((view[len("spec:"):],))
    return CODEX_VIEW_NAMES.get(view, view)


def deck_name(specs) -> str:
    """
    A deck by its specs: "Bashing" in the basic game, where a deck is
    one spec, and "Anarchy/Blood/Fire" for the standard game's three
    (the author, 2026-10-08).
    """
    return "/".join(spec.replace("_", " ").title() for spec in specs)


def team_name(specs) -> str:
    """
    A team by its name: a colour's three heroes by the colour's deck,
    "Blood Anarchs"; any other team by its specs in the order chosen,
    "Fire/Feral/Bashing", the first the starting deck's -- never its
    heroes' names (the author, 2026-10-10) -- and the basic game's one
    hero by its spec, "Bashing".
    """
    color = catalog().color_deck_of(specs)
    if color is not None:
        return COLOR_DECK_NAMES[color]
    return deck_name(specs)


def side_names(side) -> str:
    """A side's players, as a line names them: `{player:1}`, or a
    dragon's team, "{player:1} and {player:2}" (docs/design/codex.md,
    "Multiplayer")."""
    return " and ".join(tokens.player(seat) for seat in side)


def side_verb(side, one: str, several: str) -> str:
    """The verb a side takes: "wins" for one player, "win" for a dragon's
    two."""
    return several if len(side) > 1 else one


def base_owner(match, seat: int) -> str:
    """Whose base a line names: the seat, and in a two-headed dragon both
    players of its team, "{player:1} and {player:2}" -- the base is theirs
    together (Rulebook p. 13), however the attack or the effect named it."""
    from codex import seats

    return side_names(seats.dragon_of(match, seat))


def turn_heading(match) -> str:
    """
    **The turn's heading, in the model's words**: "**Turn 7** --
    {to:1} (Bashing)" -- the turn, whose it is, addressed, and their
    team (`team_name`).
    A frontend heads each turn with it (the Discord turn message's first
    line, a mention that the post pings); it is not narration, so it is
    never said twice and a restart that lost the turn's lines still has
    it (docs/design/codex.md, "The turn message").
    """
    from codex import seats

    # A two-headed dragon's turn is both teammates' (Rulebook p. 13):
    # "**Turn 7** -- {to:1} (Blood Anarchs) and {to:2} (Moss Sentinels)".
    named = " and ".join(
        f"{tokens.addressed(seat)} ({team_name(match.player(seat).specs)})"
        for seat in seats.turn_seats(match)
    )
    return f"**Turn {match.turn}** -- {named}"

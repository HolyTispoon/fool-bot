"""
Plain-text formatting over the cards, with nothing that touches Discord.
"""

from __future__ import annotations

from codex import tokens
from codex.cards import Card, Hero, catalog

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
    if kind == "player":
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
    A card the way a list names it: "Trojan Duck (7) 8/9" -- the cost
    in brackets, a unit's ATK/HP after it; a spell "Spark (1)"; a hero
    "Troq Bashar (2) 2/3" at its first band.
    """
    if isinstance(card, Hero):
        band = card.bands[0]
        return f"{card.name} ({card.cost}) {band.atk}/{band.hp}"
    label = card.name if card.cost is None else f"{card.name} ({card.cost})"
    if card.atk is not None and card.hp is not None:
        return f"{label} {card.atk}/{card.hp}"
    return label


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


def ref_label(engine, match, seat: int, ref: str) -> str:
    """
    What `ref` names on `seat`'s side, in plain words for a button or a
    menu: "Iron Man 3/4", "Troq Bashar 2/3", "Tech II", "Tower", "base".
    A unit's or hero's numbers are the engine's, with its damage after
    them where it has any. A name, never a rule.
    """
    from codex.components import HERO
    from codex.engine import building_name, unit_ref

    player = match.player(seat)
    if ref == HERO:
        atk, hp = engine.hero_stats(player.hero)
        label = f"{catalog().name(player.hero.slug)} {atk}/{hp}"
        damage = player.hero.damage
    else:
        instance_id = unit_ref(ref)
        card = player.instance(instance_id) if instance_id is not None else None
        if card is None:
            if ref == "add_on" and player.add_on is not None:
                return catalog().name(player.add_on.slug)
            return building_name(ref)
        atk, hp = engine.unit_stats(card)
        label = f"{catalog().name(card.slug)} {atk}/{hp}"
        damage = card.damage
    return f"{label}, {damage} damage" if damage else label

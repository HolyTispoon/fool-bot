"""
Each seat's keyword sheet: every unit trait and every term the rules
use, one entry each, with what it means and the section it is from --
the player aid's glossary, a letter sheet beside the screen.

**The traits are the data's**: each trait any unit carries is listed,
with the units that carry it read from `humans.json` and its name from
`tnp.formatting.TRAIT_NAMES`, so a unit given a new trait in the sheet
appears under it when the kit is rebuilt, and a trait with no wording
here stops the build rather than printing a bare name. The wording is a
summary that cites, as the screen's is (docs/design/tnp-print-kit.md):
docs/tnp-rules.md is the rules.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from tnp.catalog import Catalog
from tnp.formatting import TRAIT_NAMES
from tnp.render import INK, MUTED, SEAT_COLOURS, SOFT_INK, _wrap, font
from tnpkit.boards import header, plural, text
from tnpkit.paper import MARGIN, px, sheet
from tnpkit.screen import winning_count

#: What each trait does, by its slug (TNP 7). `{carry}` is the Chopper
#: Carrier's capacity, read from the board's data.
TRAITS = {
    "base_defense": ("Goes only into its base's defense spot, never an attack spot, and cannot flank. Rolls like "
                     "any other unit when its base is attacked.", "TNP 7"),
    "harvest": ("In an attack its player wins, each one in the attacking pile takes a resource token off the "
                "territory. Never on defense.", "TNP 5.8"),
    "mechanical": ("A hit on it can be ignored by Repair. In the advanced game, some techs work only on "
                   "Mechanical units.", "TNP 7"),
    "repair": ("When a Mechanical unit is hit, its player may remove one of these from a force adjacent to the hit "
               "unit's force, to ignore the hit.", "TNP 6.8"),
    "scouting": ("Scouting N adds N to its player's scouting total in a battle.", "TNP 6.4"),
    "splash": ("For each roll of its force that hits, its player may also remove one infantry unit, Tough or not, "
               "a damaged one first, from a force of the side hit adjacent to the force hit.", "TNP 6.8"),
    "tough": ("Takes two hits: the first damages it (a damage token), the second removes it. A damaged one takes "
              "a hit before an undamaged one of its force; the damage lasts the rest of the battle.", "TNP 6.8"),
    "transformation": ("Only in the advanced game, with the tech Advanced Robotics, can The Transformer become "
                       "an air unit. In the basic game it is armored.", "TNP 7"),
    "transport": ("Carries one kind of ground unit: {carry}. A carried stack goes in one attack spot with its "
                  "carriers and needs no path; its ground units fight as their own forces and can take the "
                  "territory. Retreating with no path home, carriers may carry ground units out.", "TNP 6.6, 7"),
}

#: The rules' terms: the word, what it means, where; printed in
#: alphabetical order, `{goal}` the winning count read from the map.
TERMS = (
    ("Adjacent", "Two areas whose borders meet; 8 and 10, and 9 and 11, meet at a point and are adjacent. Two "
                 "forces of one side in the same column (a force and its flanker) or in neighbouring columns.",
     "TNP 2.1, 6.8"),
    ("Air unit", "Attacks any territory or base with no path. Cannot take a territory, but defends one already "
                 "held. Always able to retreat.", "TNP 5.3, 5.5, 6.6, 6.11"),
    ("Attack spot", "A and B on the deployment board: one attack each a turn, its pile on the territory card of "
                    "the territory or base it attacks. A resolves before B.", "TNP 2.5, 5.4"),
    ("Attacker", "In a battle, the player that does not hold the territory. Over a neutral one both attack: the "
                 "scouting advantage chooses, or else the lower initiative total defends.", "TNP 6.1"),
    ("Available units", "A player's units not deployed: what it may put into spots.", "TNP 5.3, 5.10"),
    ("Base", "Each player's area on the map, not a territory. A won attack on it wins the game.", "TNP 1.3, 2.1"),
    ("Base card", "One at each end of the defender's line when a base is attacked: hit with the armored rating, "
                  "never engaged; 2 hits from one force destroy one upgrade, Factory or Airport, one thing an "
                  "attack.", "TNP 6.9"),
    ("Battle", "Over a territory the other player holds or attacks too: up to six rounds.", "TNP 5.6, 6"),
    ("Column", "A force and the opposing force placed in front of it; a force alone, or a base card, is a "
               "column of its own.", "TNP 6.5, 6.9"),
    ("Control token", "Its player holds the territory it is on.", "TNP 2.1"),
    ("Conversion rates", "What a mineral or gem trades for at Production and Trade: materials or gold, never "
                         "both. Emergency rates only to defend a base.", "TNP 5.9, 6.2"),
    ("Defense spot", "Three a turn, each a territory a player holds that its held territories join to its base, "
                     "its pile on that territory's card; a territory with stranded units keeps one. The base has "
                     "a spot of its own besides. A player never attacks a territory it defends.", "TNP 2.5"),
    ("Defender", "The player that holds the territory, or the base's player.", "TNP 6.1"),
    ("Emergency base defense", "A base's defender may spend its pool, trading at the emergency rates, to "
                               "produce Base Defense units that join the battle at once.", "TNP 6.2"),
    ("Engaged", "A force with an opposing force in its column. Only unengaged forces are placed in a round.",
     "TNP 6.5"),
    ("Flanking", "A force behind one of its own in front, at most one a force; +1 in its own column, 0 one "
                 "away, −1 two away.", "TNP 6.5"),
    ("Force", "All of one player's units of one kind in a battle.", "TNP 6.1"),
    ("Gems, minerals", "Blue minerals, orange minerals and gems: the map's resource tokens, taken by harvest "
                       "into the pool and traded.", "TNP 2.2"),
    ("Ground unit", "Infantry or armored: takes a territory, and needs a path unless Chopper Carriers carry it.",
     "TNP 5.3, 5.5, 7"),
    ("Held", "A territory with a player's control token; it stays held with nobody in it until an enemy takes it.",
     "TNP 2.1"),
    ("Infrastructure", "Spending the pool on units, a facility or an upgrade, all finished at Production and "
                       "Trade.", "TNP 5.2"),
    ("Cleanup", "Every spot cleared back to available units but the stranded; then a player with {goal} tokens "
                "harvested wins.", "TNP 5.10"),
    ("Initiative", "The group a unit shoots in, 1 first; the group's losses come off once it has all rolled.",
     "TNP 6.7"),
    ("March", "Both players' attack spot A, then both players' B; within a spot by territory number, a base last.",
     "TNP 5.4"),
    ("Materials, gold", "What a player spends; only from trade.", "TNP 2.2"),
    ("Neutral", "Held by nobody. A ground unit attacking it unopposed takes it.", "TNP 5.5"),
    ("Path", "Held territories joining a player's base to the target: a ground attack needs one when it resolves.",
     "TNP 5.3"),
    ("Pile", "The units a player puts in one spot, on its territory card.", "TNP 5.3"),
    ("Pool", "A player's materials, gold, minerals and gems: open information, in front of its screen.",
     "TNP 2.2"),
    ("Position", "−1 for each column a force reaches across to its target.", "TNP 6.7"),
    ("Production and Trade", "Queues finished, then minerals and gems traded at the conversion rates.",
     "TNP 5.9"),
    ("Production cap", "The most units a facility produces in a Production and Trade phase.", "TNP 2.4"),
    ("Queue", "A facility's box on the player board: what Infrastructure placed there, finished at Production "
              "and Trade.", "TNP 5.2"),
    ("Rating", "Strong 3+, Fair 6+, Weak 12, Poor X: what a d12 needs against a type. Poor rolls one die for "
               "every two units. A 12 always hits, a 1 always misses.", "TNP 4"),
    ("Retreat", "Declared by the attacker, then the defender if not; never a base's defender. With a path home "
                "everything goes; without one only air units, and what Chopper Carriers carry. Retreating every "
                "unit loses.", "TNP 6.6"),
    ("Round", "Up to six a battle: scouting, placing, retreats, damage, victory. After the sixth the defender "
              "wins if it has units left.", "TNP 6.4, 6.10"),
    ("Scouting advantage", "The difference between the players' scouting totals: the other player places that many "
                           "forces first.", "TNP 6.4, 6.5"),
    ("Stranded", "A player's units in a held territory no longer joined to its base by its held territories: a "
                 "Stranded token goes on it, and they cannot be deployed, stay through Cleanup and keep one of the "
                 "three defense spots, until a path joins it again.", "TNP 5.7, 5.10"),
    ("Supply", "The most of one unit a player may have: its counters.", "TNP 2.3"),
    ("Territory card", "One for each territory and the enemy base, a deck a player: a pile goes on the card of "
                       "what it attacks or defends, so a territory is named by one pile a turn.", "TNP 2.5"),
    ("Unit upgrade", "Lets a facility build its upgraded unit. The Barracks builds only one of its two, Stealth "
                     "or Cyborg, until its infrastructure upgrade.", "TNP 2.4"),
)

#: The type sizes, in inches: the traits on a sheet of their own, the
#: terms flowing over as many sheets as they take. A size, never a fit:
#: a longer list takes another page rather than smaller type (the
#: author, 2026-11-06: "larger font and separate unit traits").
TRAIT_SIZE = 0.165
TERM_SIZE = 0.14

def _carry_words(catalog: Catalog) -> str:
    by_count: dict[int, list[str]] = {}
    for unit, count in catalog.board["transport"]["chopper_carrier"].items():
        name = catalog.name(unit)
        by_count.setdefault(int(count), []).append(plural(name) if count > 1 else name)
    parts = [f"{count} {' or '.join(names)}" for count, names in sorted(by_count.items(), reverse=True)]
    return ", ".join(parts[:-1]) + ", or " + parts[-1]


def trait_entries(catalog: Catalog) -> list[tuple[str, str, str]]:
    """Every trait a unit carries: its name, the units, what it does."""
    carriers: dict[str, list[str]] = {}
    for unit in catalog.units.values():
        for trait in unit.traits:
            carriers.setdefault(trait, []).append(unit.name)
    entries = []
    for slug in sorted(carriers, key=lambda s: TRAIT_NAMES.get(s, s)):
        if slug not in TRAITS:
            raise KeyError(f"no keyword wording for the trait {slug!r}: add it to tnpkit.keywords.TRAITS")
        words, cite = TRAITS[slug]
        name = TRAIT_NAMES.get(slug, slug.replace("_", " ").title()) + (" N" if slug == "scouting" else "")
        entries.append((name, ", ".join(carriers[slug]), f"{words.format(carry=_carry_words(catalog))} ({cite})"))
    return entries


def render_traits(catalog: Catalog, seat: str) -> list[Image.Image]:
    """The unit traits, each with the units that carry it."""
    entries = [(name, words, units) for name, units, words in trait_entries(catalog)]
    return _flow(seat, "Unit traits", "Every trait a unit carries, as its counter and the player board "
                 "name it.", entries, TRAIT_SIZE, columns=1)


def render_terms(catalog: Catalog, seat: str) -> list[Image.Image]:
    """The rules' terms, alphabetical."""
    goal = winning_count(catalog)
    entries = [(word, f"{words.format(goal=goal)} ({cite})", "")
               for word, words, cite in sorted(TERMS, key=lambda term: term[0].lower())]
    return _flow(seat, "Keywords", "The rules' terms, and the section each is from.", entries, TERM_SIZE,
                 columns=2)


def _flow(seat: str, title: str, note: str, entries, size: float, columns: int) -> list[Image.Image]:
    """`entries` -- (word, words, units) -- set in `columns` columns at
    `size`, on as many letter sheets as they take. An entry with units
    puts them after the word, its words on the lines under it; one
    without runs its words on after the word."""
    gap = 0.3
    width = (8.5 - 2 * MARGIN - gap * (columns - 1)) / columns
    bottom = 11 - MARGIN
    body, bold, small = font(px(size), False), font(px(size), True), font(px(size * 0.88), False)
    line = size * 1.3
    pages: list[Image.Image] = []
    state = {}

    def new_page() -> None:
        page = sheet("letter", landscape=False)
        draw = ImageDraw.Draw(page)
        words = title if not pages else f"{title} (continued)"
        state.update(page=page, draw=draw, column=0, top=header(draw, page, seat, words, note) + 0.05)
        state["y"] = state["top"]
        pages.append(page)

    def lay(word: str, words: str, units: str) -> None:
        lead_w = bold.getlength(word + "  ")
        if units:
            unit_rows = _wrap(units, small, px(width) - lead_w)[:1]
            rest = units[len(unit_rows[0]):].strip(" ,")
            unit_rows += _wrap(rest, small, px(width)) if rest else []
            first: list[str] = []
            rows = _wrap(words, body, px(width))
        else:
            unit_rows = []
            first = _wrap(words, body, px(width) - lead_w)[:1]
            rest = words[len(first[0]):].strip()
            rows = _wrap(rest, body, px(width)) if rest else []
        height = line * (max(1, len(unit_rows)) + len(rows)) + size * 0.7
        if state["y"] + height > bottom:
            if state["column"] + 1 < columns:
                state["column"] += 1
                state["y"] = state["top"]
            else:
                new_page()
        draw, y = state["draw"], state["y"]
        x = MARGIN + state["column"] * (width + gap)
        draw.text((px(x), px(y)), word, font=bold, fill=INK, anchor="lt")
        after = px(x) + lead_w
        if units:
            for index, row in enumerate(unit_rows):
                draw.text((after if index == 0 else px(x), px(y + index * line)), row, font=small, fill=MUTED,
                          anchor="lt")
            y += line * len(unit_rows)
        else:
            draw.text((after, px(y)), first[0], font=body, fill=SOFT_INK, anchor="lt")
            y += line
        for row in rows:
            draw.text((px(x), px(y)), row, font=body, fill=SOFT_INK, anchor="lt")
            y += line
        state["y"] = y + size * 0.7

    new_page()
    for word, words, units in entries:
        lay(word, words, units)
    return pages

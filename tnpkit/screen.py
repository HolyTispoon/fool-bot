"""
Each seat's screen: a tabloid sheet printed on one side and folded in
three to stand, its printed side towards its seat -- the player aid.
The deployment board and the player board stand behind it (TNP 1.2,
5.3), the available pool in front of it, where both seats see it
(TNP 2.2).

Its three panels are the turn (TNP 5), a battle (TNP 6) and the
numbers a seat looks up -- the d12, the modifiers, the conversion
rates, the Chopper Carrier's capacity, setup and winning. **It is a
summary that cites the rules, never a second copy of them**: every
paragraph names the section it condenses, so a reader with a question
goes to docs/tnp-rules.md, which the kit carries as a PDF. Every number
in it is read from the catalog.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from tnp.catalog import Catalog, Rating
from tnp.render import HIT, INK, MUTED, RATING_FILLS, SEAT_COLOURS, SOFT_INK, _icon, _shield, _wrap, font
from tnpkit.boards import DASH, box, plural, text
from tnpkit.paper import MARGIN, px, sheet

PANELS = 3
BODY = 0.128
LEADING = 1.32


class Column:
    """A panel's text, laid top to bottom."""

    def __init__(self, draw: ImageDraw.ImageDraw, x: float, y: float, w: float, accent) -> None:
        self.draw, self.x, self.y, self.w, self.accent = draw, x, y, w, accent

    def title(self, words: str) -> None:
        text(self.draw, (self.x, self.y), words, 0.28, fill=self.accent)
        self.y += 0.46

    def heading(self, words: str, cite: str = "") -> None:
        self.y += 0.06
        text(self.draw, (self.x, self.y), words, 0.165)
        if cite:
            face = font(px(0.165))
            text(self.draw, (self.x + face.getlength(words) / 300 + 0.1, self.y + 0.04), cite, 0.115, fill=MUTED,
                 bold=False)
        self.y += 0.27

    def para(self, words: str, indent: float = 0.0, bold_lead: str = "", size: float = BODY) -> None:
        face, lead_face = font(px(size), False), font(px(size), True)
        x = self.x + indent
        width = px(self.w - indent)
        lead_w = lead_face.getlength(bold_lead + " ") if bold_lead else 0
        rows = _wrap(words, face, width - lead_w) if bold_lead else _wrap(words, face, width)
        if bold_lead:
            # The lead's line is narrower; the rest re-wrap to the full width.
            first, rest = rows[0], " ".join(rows[1:])
            self.draw.text((px(x), px(self.y)), bold_lead, font=lead_face, fill=INK, anchor="lt")
            self.draw.text((px(x) + lead_w, px(self.y)), first, font=face, fill=SOFT_INK, anchor="lt")
            self.y += size * LEADING
            rows = _wrap(rest, face, width) if rest else []
        for row in rows:
            self.draw.text((px(x), px(self.y)), row, font=face, fill=SOFT_INK, anchor="lt")
            self.y += size * LEADING
        self.y += 0.05

    def item(self, mark: str, words: str, bold_lead: str = "") -> None:
        text(self.draw, (self.x + 0.02, self.y), mark, BODY, fill=self.accent)
        self.para(words, indent=0.24, bold_lead=bold_lead)

    def gap(self, inches: float = 0.08) -> None:
        self.y += inches


def render_screen(catalog: Catalog, seat: str) -> Image.Image:
    page = sheet("tabloid", landscape=True)
    draw = ImageDraw.Draw(page)
    colours = SEAT_COLOURS[seat]
    panel_w = 17 / PANELS
    for fold in range(1, PANELS):
        x = px(fold * panel_w)
        for start in range(0, page.height, px(0.16)):
            draw.line((x, start, x, start + px(0.08)), fill=DASH, width=2)
        text(draw, (fold * panel_w, 0.12), "FOLD", 0.07, fill=MUTED, anchor="mt")
    pad = 0.3
    columns = [
        Column(draw, index * panel_w + (MARGIN if index == 0 else pad), MARGIN + 0.05,
               panel_w - pad - (MARGIN if index in (0, PANELS - 1) else pad), colours["ink"])
        for index in range(PANELS)
    ]
    _shield(draw, seat, (px(17 - MARGIN - 0.32), px(MARGIN)), px(0.38))
    _turn(columns[0], catalog)
    _battle(columns[1], catalog)
    _reference(columns[2], catalog, seat)
    return page


def _turn(c: Column, catalog: Catalog) -> None:
    c.title("The turn")
    c.para("Both seats play every phase at once. Nothing either does in secret is revealed until the phase "
           "says so (TNP 1.2, 5.1).")
    c.heading("1. Infrastructure and Deployment", "TNP 5.2, 5.3")
    c.para("In secret, behind your screen, at the same time; change your plan until you say you are done. "
           "The phase ends when both seats are.")
    c.item("•", "From your pool, place units on the facility that builds them, at their cost, up to its "
                "production cap and the unit's supply; buy the Factory or the Airport, or an upgrade, putting "
                "its Built marker in that facility's queue. Nothing is finished until Production and Trade, and "
                "a facility being built takes no units.", "Build.")
    c.item("•", "Put available units into attack spots A and B, each with a target chip, and into defense "
                "spots: your base's, and any territory you hold that your held territories join to your base. "
                "Stranded units stay where they are. Base Defense units only defend your base.", "Deploy.")
    c.item("•", "Ground units need a path of held territories from your base to the target when the attack "
                "resolves. Air units, and a stack Chopper Carriers carry, need none, a base included.", "Paths.")
    c.heading("2. March", "TNP 5.4")
    c.para("Both seats' attack spot A, then both seats' B. Within a spot, attacks go in ascending territory "
           "number, an attack on a base last. Each attack is resolved whole before the next:")
    c.item("a", "Ground units with no path when it resolves go back to your base, unrevealed; the pile's air "
                "units attack alone (TNP 5.3).", "No path.")
    c.item("b", "A neutral territory nobody else is fighting for: reveal one ground unit and put your control "
                "token on it. The rest of the pile stays face down in its defense spot. Air units alone take "
                "nothing, and wait there for the rest of March.", "Neutral conquest (TNP 5.5).")
    c.item("c", "If the other seat holds it or attacks it too, fight a battle (other panel).",
           "Battle (TNP 5.6).")
    c.item("d", "If taking it cuts off a territory a seat holds from that seat's base, put that seat's "
                "Stranded token on it; it comes off once a path of held territories joins it again.",
           "Stranded (TNP 5.7).")
    c.item("e", "If the winning attacker has Workers in its pile and the territory has tokens, each Worker "
                "takes one off the map, of the kind you choose, into your pool. Move your harvest marker. "
                "Defending Workers never harvest.", "Harvest (TNP 5.8).")
    c.para("The attacker's surviving units stay in the territory's defense spot for the rest of March.")
    c.heading("3. Production and Trade", "TNP 5.9")
    c.para("Everything in a queue is finished: units join your available units, Built markers go on their "
           "squares. Units queued at a facility a base card destroyed this turn are not produced, and their cost is lost. Then trade minerals "
           "and gems from your pool at the conversion rates.")
    c.heading("4. Cleanup", "TNP 5.10")
    c.para("Every attack and defense spot is cleared back to its seat's available units, but stranded units. "
           f"Then a seat that has taken {winning_count(catalog)} tokens off the map wins (TNP 1.3).")


def _battle(c: Column, catalog: Catalog) -> None:
    c.title("A battle")
    c.heading("Before the first round", "TNP 6.1, 6.2")
    c.item("•", "The seat that does not hold the territory. Both attacking a neutral one: the seat with the "
                "scouting advantage chooses; with none, the lower total of initiative over its units there "
                "defends; equal totals, each rolls a die and the higher attacks, ties rolled again.",
           "Who attacks.")
    c.item("•", "Both reveal; all of a seat's units of one kind are one force. The attacker's units join the "
                "territory's defense spot.", "Forces.")
    c.item("•", "Attacking a base, its defender may spend its pool, trading at the emergency rates, to produce "
                "base defenses that join at once: up to the Base Defenses' cap, within supply and the limit on "
                "Smart Mines and Rocket Launchers; a Laser Cannon only with its upgrade built.",
           "Emergency base defense.")
    c.item("•", "A seat with no units in the battle has lost it (a base, once its emergency defense was "
                "offered).", "Nobody there.")
    c.heading("Each round, up to six", "TNP 6.4 to 6.10")
    c.item("1", "Each seat adds up its units' Scouting. The higher total has an advantage of the difference.",
           "Scouting.")
    c.item("2", "Only unengaged forces are placed; a seat keeps each flanking force where it is or places it "
                "again, the attacker first. With an advantage of N, the other seat places N forces first; with "
                "none, the defender first. Then the seats take turns: while the other seat has an unengaged "
                "force, each force you place goes in front of one of them; then place one new force, at an end "
                "of the line or between two columns, and your turn ends. Once the other seat's forces are all placed and engaged, place the rest "
                "flanking (behind a force of yours with nobody behind it) or as new columns.",
           "Placing.")
    c.item("3", "The attacker may declare one; only if it does not, the defender. A base's defender cannot. "
                "With a path of held territories home, everything retreats. With none, only air units, and "
                "retreating Chopper Carriers may carry ground units out up to capacity; the rest stay and "
                "fight. Retreating units do not attack this round, may be hit, and leave at its end. Retreating "
                "every unit loses the battle.", "Retreat.")
    c.item("4", "By initiative group, 1 first; in a group the attacker rolls for all its forces, then the "
                "defender. A force chooses an opposing force and rolls a die a unit at once (Poor: one for "
                "every two). The group's losses come off once the whole group has rolled.", "Damage.")
    c.item("5", "A seat with no units left has lost; both gone, nobody wins and the territory stays as it was. "
                "After round 6 the defender wins if it still has units.", "Victory.")
    c.heading("After it", "TNP 6.11")
    c.para("The attacker wins: its control token goes on the territory and its survivors into the defense spot; "
           "won with air units alone, a held territory becomes neutral. The defender wins: it keeps the "
           "territory, with air units alone too, and the attacker's survivors retreat to their base. Damage "
           "tokens come off. An attack on a base that wins the battle wins the game.")


def map_tokens(catalog: Catalog) -> int:
    return sum(int(count) for area in catalog.areas.values() for count in area.resources.values())


def winning_count(catalog: Catalog) -> int:
    """More than half the map's tokens: 49 of map 3.3's 96 (TNP 1.3)."""
    return map_tokens(catalog) // 2 + 1


def _rates_words(catalog: Catalog) -> list[tuple[str, int, object, int, object]]:
    conversion = catalog.board["conversion"]
    return [
        (words, conversion["normal"][token]["materials"], conversion["normal"][token]["gold"],
         conversion["emergency"][token]["materials"], conversion["emergency"][token]["gold"])
        for token, words in (("mineral", "A mineral, blue or orange"), ("gem", "A gem"))
    ]


def _carry_words(catalog: Catalog) -> str:
    by_count: dict[int, list[str]] = {}
    for unit, count in catalog.board["transport"]["chopper_carrier"].items():
        by_count.setdefault(int(count), []).append(plural(catalog.name(unit)) if count > 1 else catalog.name(unit))
    parts = [f"{count} {' or '.join(names)}" for count, names in sorted(by_count.items(), reverse=True)]
    return ", ".join(parts[:-1]) + ", or " + parts[-1]


def _reference(c: Column, catalog: Catalog, seat: str) -> None:
    c.title("Reference")
    draw = c.draw
    c.heading("Hits on a d12", "TNP 4")
    cell_w = (c.w - 3 * 0.08) / 4
    for index, rating in enumerate(Rating):
        x = c.x + index * (cell_w + 0.08)
        box(draw, x, c.y, cell_w, 0.62, outline=None, fill=RATING_FILLS[rating], radius=0.05)
        text(draw, (x + cell_w / 2, c.y + 0.14), rating.value.title(), 0.1, bold=False, anchor="mm")
        text(draw, (x + cell_w / 2, c.y + 0.4), rating.shown, 0.22, anchor="mm")
    c.y += 0.72
    c.para("A force rolls a d12 a unit; a die that reaches its rating's number against the target's type hits. "
           "Poor (X) rolls one die for every two units, rounded down, needing a 12. A 12 always hits and a 1 "
           "always misses. Modifiers add to the number rolled, with no cap.")
    c.heading("Modifiers", "TNP 4.2, 6.5, 6.7, 6.9")
    c.item("•", "−1 for each column a force reaches across to its target; none in its own column.", "Position.")
    c.item("•", "+1 on top of position for a force flanking behind one of its own: +1 in its own column, 0 one "
                "away, −1 two away.", "Flanking.")
    c.item("•", "Attacked with the armored rating, a column beyond each end of the defender's line, never "
                "engaged: at least −1. 2 hits from one force destroy one thing, an upgrade before its facility; "
                "never the Barracks or Base Defenses; one thing an attack.", "A base card.")

    c.heading("Conversion rates", "TNP 5.9, 6.2")
    rows = _rates_words(catalog)
    col = [c.x + 2.35, c.x + 2.95, c.x + 3.85, c.x + 4.45]
    text(draw, ((col[0] + col[1]) / 2, c.y), "NORMAL", 0.085, fill=MUTED, anchor="mt")
    text(draw, ((col[2] + col[3]) / 2, c.y), "EMERGENCY", 0.085, fill=HIT, anchor="mt")
    c.y += 0.16
    for x, kind in zip(col, ("materials", "gold", "materials", "gold")):
        _icon(draw, kind, (px(x - 0.1), px(c.y)), px(0.2))
    c.y += 0.28
    for words, *values in rows:
        text(draw, (c.x, c.y), words, BODY, fill=INK, bold=False)
        for x, value in zip(col, values):
            text(draw, (x, c.y), "—" if value is None else str(value), 0.13, anchor="mt")
        c.y += 0.22
    c.para("A token trades for materials or for gold, never both. Emergency rates only to defend your base.")

    c.heading("Chopper Carrier", "TNP 7")
    c.para(f"Carries one kind of ground unit: {_carry_words(catalog)}. A carried stack is deployed in one "
           "attack spot with its carriers and needs no path; its ground units fight as their own forces and "
           "can take the territory.")

    c.heading("Traits", "TNP 7")
    c.para("Tough takes two hits: damaged, then removed. Repair: a Worker removed from an adjacent force "
           "ignores a hit on a Mechanical unit. Splash: for each roll that hits, also remove an infantry unit "
           "from a force adjacent to the one hit. Base Defense never attacks and never flanks. Adjacent: the "
           "same column (a force and its flanker) or the next one.")

    start = catalog.board["starting"]
    units = ", ".join(f"{count} {plural(catalog.name(unit))}" for unit, count in start["units"].items())
    built = " and ".join(f.name for f in catalog.facilities.values() if f.built_at_start)
    c.heading("Setup", "TNP 3")
    c.para(f"Each seat: {units} available, {start['pool']['materials']} materials and no gold in its pool; "
           f"its {built} built. Every territory neutral, with its tokens on it.")
    c.heading("Winning", "TNP 1.3")
    total = map_tokens(catalog)
    c.para(f"An attack on the other seat's base that wins its battle, or {winning_count(catalog)} of the map's {total} "
           "tokens taken off the map, counted at Cleanup.")

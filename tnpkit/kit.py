"""
The whole kit into one folder: every sheet as a PNG and a PDF under
`sheets/`, three PDFs to print from -- the letter sheets, the tabloid
sheets, and the tabloid sheets cut into letter halves for a printer
that takes no tabloid -- the rules as a PDF, and a README saying what
each sheet is, how many of what it holds and what a table still needs.

It draws nothing of its own: it calls `pieces`, `mapsheet`, `boards`,
`screen` and `keywords`, and sets docs/tnp-rules.md through D12 Ball's rulebook
builder (`d12ball.rulebooks.book_bytes`), so the rules in the kit are
the rules the bot plays.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Iterator, Sequence

from PIL import Image

from d12ball.rulebooks import Book, book_bytes
from tnp.catalog import Catalog, load
from tnpkit import boards, keywords, mapsheet, pieces, screen, territories
from tnpkit.paper import DPI, cut_sheet, halves, save

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RULES = PROJECT_ROOT / "docs" / "tnp-rules.md"
DEFAULT_OUT = PROJECT_ROOT / "tnp" / "print"

RULES_TITLE = "The New Project: the rules"


def player_rules(text: str) -> str:
    """docs/tnp-rules.md for players: the title, then the rules from
    section 1 on. The preamble between them is for the bot's developers
    -- which documents it was transcribed from, how the code is checked
    against it -- and the kit leaves it out (the author, 2026-11-06)."""
    lines = text.splitlines(keepends=True)
    title = next(index for index, line in enumerate(lines) if line.startswith("# "))
    first = next(index for index, line in enumerate(lines) if index > title and line.startswith("## "))
    return "".join(lines[:title + 1]) + "\n" + "".join(lines[first:])


def rules_pdf() -> bytes:
    """The player rules as a PDF, set by D12 Ball's rulebook builder."""
    with tempfile.TemporaryDirectory() as scratch:
        source = Path(scratch) / "tnp-rules.md"
        source.write_text(player_rules(RULES.read_text(encoding="utf-8")), encoding="utf-8")
        return book_bytes(Book(name="tnp-rules", title=RULES_TITLE, sources=(source,)))


@dataclass(frozen=True)
class Sheet:
    """Sheets of one component: its file name, its pages, its paper, and
    the README's line about it."""

    name: str
    pages: tuple[Image.Image, ...]
    paper: str
    about: str


def build_sheets(catalog: Catalog) -> list[Sheet]:
    return list(iter_sheets(catalog))


def iter_sheets(catalog: Catalog) -> Iterator[Sheet]:
    """Every sheet, each drawn only as it is asked for, so `write_kit`
    can save one and say so before drawing the next."""
    yield Sheet("map", (mapsheet.render_map_sheet(catalog),), "tabloid",
                "Map 3.3, with each territory's setup tokens and the two point contacts.")
    yield Sheet("battle-mat", (boards.render_battle_mat(catalog),), "tabloid",
                "The battle line's four rows in columns, the round track and the initiative groups.")
    yield Sheet("track-sheet", (boards.render_track_sheet(catalog),), "letter",
                f"The harvest track, 0 to {screen.winning_count(catalog)}, and the four base cards to cut out.")
    for seat in boards.SEATS:
        word = seat.title()
        yield Sheet(f"{seat}-screen", (screen.render_screen(catalog, seat),), "tabloid",
                    f"{word}'s screen: fold in three on the dashed lines and stand it, printed side towards "
                    f"{word}. Its inside is the player aid.")
        yield Sheet(f"{seat}-player-board", tuple(boards.render_player_board(catalog, seat)), "letter",
                    f"{word}'s player board: two sheets, side by side, behind the screen.")
        yield Sheet(f"{seat}-unit-traits", tuple(keywords.render_traits(catalog, seat)), "letter",
                    f"{word}'s unit traits: every trait a unit carries, with the units that carry it.")
        yield Sheet(f"{seat}-keywords", tuple(keywords.render_terms(catalog, seat)), "letter",
                    f"{word}'s keywords: every term the rules use, with its section.")
        yield Sheet(f"{seat}-territory-cards",
                    tuple(cut_sheet(territories.territory_deck(catalog, seat), territories.CARD,
                                  title=f"{word} territory cards", turned=True)), "letter",
                    f"{word}'s territory cards: one for each territory and the enemy base. Each pile in a spot "
                    "goes on the card of what it attacks or defends.")
        yield Sheet(f"{seat}-deployment-board", (boards.render_deployment_board(catalog, seat),), "tabloid",
                    f"{word}'s deployment board, behind the screen.")
        counters = cut_sheet(pieces.unit_counters(catalog, seat), (pieces.COUNTER, pieces.COUNTER), title=f"{word} unit counters")
        yield Sheet(f"{seat}-unit-counters", tuple(counters), "letter",
                    f"{word}'s {len(pieces.unit_counters(catalog, seat))} unit counters, 1.5 inches: every unit as "
                    "many times as its supply.")
    tokens = pieces.resource_tokens(catalog) + pieces.other_tokens(catalog)
    yield Sheet("tokens", tuple(cut_sheet(tokens, (0.75, 0.75), title="Tokens")), "letter",
                f"{len(tokens)} tokens, 3/4 inch (listed below).")


def token_lines(catalog: Catalog) -> list[str]:
    counts = pieces.TOKEN_COUNTS
    resources: dict[str, int] = {}
    for area in catalog.areas.values():
        for kind, count in area.resources.items():
            resources[kind] = resources.get(kind, 0) + int(count)
    built = pieces.built_markers_per_seat(catalog)
    return [
        f"- {resources['blue_minerals']} blue minerals, {resources['orange_minerals']} orange minerals and "
        f"{resources['gems']} gems: exactly what map 3.3 holds (TNP 2.1).",
        f"- Materials: {counts['materials_1']} worth 1 and {counts['materials_5']} worth 5. Gold: "
        f"{counts['gold_1']} worth 1 and {counts['gold_5']} worth 5. The bank is not limited: run out, and "
        "use anything.",
        f"- {counts['control']} control tokens and {counts['stranded']} Stranded tokens a player.",
        f"- {counts['damage']} damage tokens, for damaged Tough units (TNP 6.8).",
        f"- {built} Built markers a player: one for each facility that does not start built and each upgrade.",
        "- A harvest marker a player, and the battle's round and group markers.",
    ]


README = """\
# The New Project: print-and-play kit

Built {built} by `scripts/render_tnp_kit.py` from the data the Discord
bot plays (`tnp/data/`) and its rules (`docs/tnp-rules.md`). **The basic
game**: Humans against Humans, Blue against Green, no technology cards.
If the rules or the units have changed since, build the kit again
rather than trusting this copy.

## Print

Everything is printed **one-sided, at actual size (100%, no fit to
page)**, {dpi} dpi.

- **With a tabloid (11 x 17 in) printer**: `print-letter.pdf` on letter
  and `print-tabloid.pdf` on tabloid.
- **Letter only**: `print-letter.pdf`, and `print-tabloid-as-letter.pdf`,
  which is each tabloid sheet cut down its middle into two letter pages.
  Butt the two halves together at their inner edges and tape them; a
  printer that cannot print to the edge leaves a thin strip out at the
  seam.

`sheets/` has every sheet on its own, as a PNG and a PDF, to reprint one.

## What is in it

{sheet_lines}

The tokens:

{token_lines}

`rules.pdf` is the rules, every section numbered as the aid and the
boards cite them ("TNP 6.7").

## Make it

- **Counters and tokens**: cut on the grey lines -- each line is shared
  by two pieces, so a paper cutter does a row at a time. Card stock, or
  paper glued to card, stacks better.
- **Screens**: fold on the two dashed lines so the printed side faces
  you, and stand it in front of your boards.
- **Player board**: the two sheets side by side.

## Not in the kit

- **d12s**: a force rolls a die a unit, so ten or more at the table, or
  roll a few at a time.
- Scissors or a paper cutter, and tape for the halves.

## Setup (TNP 3)

1. The map in the middle, each territory's tokens on it as its pill
   says. The battle mat and the track sheet beside it, both harvest
   markers on 0.
2. Each player: its screen, and behind it its player board, deployment
   board and deck of territory cards. {start_units} on the deployment board's available units, the
   rest of its counters in a supply pile; {start_materials} materials in
   front of its screen -- the pool is open information (TNP 2.2). Its
   {start_built} are built; its {start_unbuilt} are not.
3. Every territory starts neutral.
"""


def write_kit(out: Path, catalog: Catalog | None = None,
              report: Callable[[Path], None] | None = None) -> list[Path]:
    """The kit into `out`; the files written, each handed to `report` as
    soon as it is on disk, since the whole kit takes a while to draw."""
    catalog = catalog or load()
    out.mkdir(parents=True, exist_ok=True)
    sheets: list[Sheet] = []
    written: list[Path] = []

    def wrote(paths: Sequence[Path]) -> None:
        written.extend(paths)
        if report:
            for path in paths:
                report(path)

    letter: list[Image.Image] = []
    tabloid: list[Image.Image] = []
    tabloid_halves: list[Image.Image] = []
    for item in iter_sheets(catalog):
        sheets.append(item)
        wrote(save(item.pages, out / "sheets" / f"{item.name}.pdf"))
        if item.paper == "tabloid":
            tabloid.extend(item.pages)
            for page in item.pages:
                tabloid_halves.extend(halves(page))
        else:
            letter.extend(item.pages)
    for pages, name in ((letter, "print-letter.pdf"), (tabloid, "print-tabloid.pdf"),
                        (tabloid_halves, "print-tabloid-as-letter.pdf")):
        path = out / name
        pages[0].save(path, "PDF", resolution=DPI, save_all=True, append_images=pages[1:])
        wrote([path])

    rules = out / "rules.pdf"
    rules.write_bytes(rules_pdf())
    wrote([rules])

    readme = out / "README.md"
    readme.write_text(readme_text(catalog, sheets), encoding="utf-8")
    wrote([readme])
    return written


def readme_text(catalog: Catalog, sheets: Sequence[Sheet]) -> str:
    sheet_lines = []
    for item in sheets:
        count = f" ({len(item.pages)} sheets)" if len(item.pages) > 1 else ""
        sheet_lines.append(f"- **{item.name}** -- {item.paper}{count}. {item.about}")
    start = catalog.board["starting"]
    units = " and ".join(f"{count} {boards.plural(catalog.name(unit))}" for unit, count in start["units"].items())
    built = " and ".join(f.name for f in catalog.facilities.values() if f.built_at_start)
    unbuilt = " and ".join(f.name for f in catalog.facilities.values() if not f.built_at_start)
    return README.format(
        built=date.today().isoformat(), dpi=DPI, sheet_lines="\n".join(sheet_lines),
        token_lines="\n".join(token_lines(catalog)), start_units=units,
        start_materials=start["pool"]["materials"], start_built=built, start_unbuilt=unbuilt,
    )

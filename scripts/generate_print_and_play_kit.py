#!/usr/bin/env python3
"""Build the whole print-and-play kit in one command.

    python3 scripts/generate_print_and_play_kit.py
    python3 scripts/generate_print_and_play_kit.py --bleed --pdf --zip
    python3 scripts/generate_print_and_play_kit.py --paper a3

This is the thing to hand somebody before a meetup, a playtest table or
a con booth: every printable component in one folder (or one zip),
built fresh from whatever the bot itself plays. **It is the print
version of the game, as print sheets only**, never a PNG per card, and
every card is printed double-sided: a front sheet and a back sheet,
printed duplex. A team's two are its cards' standard sides and their
advanced sides, and the player cards are all four colour teams' -- the
print game has no cards for the species teams; a colour team's card
carries its player's special ability on its advanced side (the author,
2026-09-27). The maneuvers are two pairs, the six basic cards on the
standard back and the six advanced on the advanced one; the species and
role reference cards share one pair; the condition tokens have their
own (the author, 2026-09-28). **It
draws nothing on its own** -- it runs `render_maneuver_cards.py`,
`render_player_cards.py`, `render_reference_cards.py`,
`render_token_sheet.py`, `render_box_art.py` (the playtest card),
`render_boards.py` and `build_rulebooks.py`, the same scripts a
developer already reaches for to check one component at a time, and
is only their sum into a folder meant to leave the repo. So a rules
change, an import, or an art fix reaches the kit exactly the way it
reaches each of those on its own -- by re-running this -- and there is
nothing here for a future rule to drift out of step with.

The kit is print-ready output and is gitignored, like everything
else under `d12ball/print/`; run this again whenever the game underneath it changes rather
than keeping a stale copy around.

**What is not in the box.** The kit prints every card, every board and
the tokens; it does not print meeples or dice. `write_readme` below
lists what a table still needs to bring.
"""
import argparse
import shutil
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.boards import DEFAULT_PAPER, PAPERS  # noqa: E402
from d12ball.cards import AVERY_95328_CARDS, DUPLEX_COLUMNS  # noqa: E402
from d12ball.components import load_player_catalog  # noqa: E402
from d12ball.game import COLOR_TEAMS, team_display_name  # noqa: E402
from d12ball.token_sheet import TOKEN_COUNTS  # noqa: E402

# What the README calls each token, by its key in `TOKEN_COUNTS`.
TOKEN_NAMES = {
    "exhaust": "exhaustion",
    "exhausted": "Exhausted / Injured",
    "drained": "Drained / Damaged",
}


def run(script: str, script_args: list[str]) -> None:
    command = [sys.executable, str(SCRIPTS_DIR / script), *script_args]
    print(f"$ {' '.join(command)}")
    subprocess.run(command, check=True, cwd=PROJECT_ROOT)


README_TEMPLATE = """\
# D12 Ball -- Print & Play Kit

Generated {generated} by `scripts/generate_print_and_play_kit.py`.
Everything in this kit is drawn from the same data and rules the
Discord bot plays from, so it is only ever as current as the checkout
it was built from -- if the rules have moved since, rebuild the kit
rather than trusting an old copy.

## What's in the box

Every card set comes as print sheets, ready for a home or copy-shop
printer, {sheet_columns} cards to a row, and every card is double-sided:
each set is a front sheet and a back sheet. Print the pair duplex
(flip on the long edge) and each card comes out with its back behind
it -- a back sheet's rows are laid out reversed so they land back to
back.

The maneuver, reference and playtest sheets, six cards each,{player_avery_stock} are laid out for **Avery Presta 95328** (rounded-corner, pre-cut, 2.5 x 3.5in, six to a
letter page): load that stock, print each pair duplex at actual size
(100%, no fit-to-page) with the page landscape, and **flip on the
short edge**. The cards need no cutting.

- **maneuver-cards/** -- the twelve maneuver cards, as two pairs of
  sheets, six cards a sheet. `basic-front-sheet.png` is the six basic
  maneuvers and `basic-back-sheet.png` the standard back, with one
  maneuver on each point of the hexagon: the only cards a standard
  game plays. `advanced-front-sheet.png` is the six advanced maneuvers
  (the cards a gambit is played with) and `advanced-back-sheet.png`
  the advanced back, whose hexagon names both tiers on every point.
  Each sheet's top row is the offense and its bottom row the defense.
- **player-cards/** -- all {team_count} colour teams ({team_names}),
  {players_per_team} players a team, two print sheets a team. Every player
  card is double-sided, and both sides carry the player's role, skills
  and species ability. The **standard** side prints the role's ability;
  the **advanced** side, marked ADVANCED under the name, prints the
  player's special ability in its place, and for a few players higher
  skills.
  `<team>-sheet.png` is the standard sides and
  `<team>-advanced-sheet.png` the advanced sides, printed as a pair.{player_avery}
- **reference-cards/** -- the reference cards: the three double-sided
  species-ability cards (every pairing of the four species appears on
  one face), a fourth that is the first turned over, and two copies of
  the double-sided role-ability card (the six basic roles). `front-sheet.png` is each card's front and `back-sheet.png`
  its back, printed as a pair.
- **tokens/** -- the condition tokens, double-sided, on one piece of
  letter paper: {token_counts}. They come two ways -- pick one:
  `light-*` is drawn for paper, pale with a coloured ring, and easy on
  ink; `dark-*` is the bot's own black art, as it looks on screen.
  `<style>-front-sheet.png` is every token's front and
  `<style>-back-sheet.png` its back. Print the two duplex (flip on the
  long edge) and cut the tokens out -- a light token along the grey
  line on the front, a dark one through its black margin: each lands
  with its back behind it -- the back sheet is laid out mirrored so
  they line up, and either way the cut runs a little outside the art so
  a printer a little out of line still cuts clean. The exhaustion token has its Cyborg drain on
  the back, and each marker is a condition on one side and what it
  turns into on a failed check on the other. Need more? Print the
  pair of pages again.
- **playtest-cards/** -- the playtest card, six to a page on the same
  Avery stock: the box cover on its front, and on its back the board,
  the feedback survey (a QR code and its address) and where to play
  online. `playtest-cards-front-sheet.png` and
  `playtest-cards-back-sheet.png` print as a pair, like the reference
  cards; the cards are landscape, turned on the page.
- **boards/** -- the field board at every size the ruleset defines
  (7 and 9 spaces), each also cut up two ways for a letter printer --
  a `-top` and `-bottom` half, or a `-field` sheet and a `-rows`
  sheet (see below); the jumbotron board (clock, score, token
  supplies);
  and the team board (the bench, the back bench, the maneuvers, the
  formation strip -- one sheet holds both coaches' panels, cut in
  half), as the standard board and in each colour team's colour.

## Paper and cutting

Cards are poker size (2.5 x 3.5in) at 300dpi, and every board is
300dpi too.

**Only the field board wants a big sheet.** It is {paper}
({paper_size}) -- see `PAPERS` / `DEFAULT_PAPER` in
`d12ball/boards.py` -- because its spaces have to be wide enough to
stand two sides' meeples on, and shrinking it to letter would take
that away. If you have no printer that size, print it on two letter
sheets instead, either of two ways. Both tape up into that same board,
at exactly the size the big sheet prints, and both print **at 100%
(actual size), landscape** -- never "fit to page", which shrinks the
spaces.

- **The field and the rows** -- the field in one piece:
  1. Print `field-board-<n>-field.png` and `field-board-<n>-rows.png`.
     The first is the whole field -- the goals, the spaces and the
     shooting ranges -- along the sheet's long side. The second is
     the two zone-assignment rows, one above the other.
  2. Cut the rows sheet in half on its dashed line.
  3. Lay the field sheet down, the title at the top left. Tape the
     rows sheet's top half (its writing upside down) along the field
     sheet's **top** edge -- it faces the visiting coach across the
     table -- and its bottom half along the field sheet's **bottom**
     edge, facing the home coach. Each row's zones line up
     over the field's own: home on the left, visitors on the right.
- **The two halves** -- `field-board-<n>-top.png` and
  `field-board-<n>-bottom.png`, taped along the cut. Simpler, but the
  seam runs across the middle of the field.

**Everything else is letter** ({letter_size}), the size a printer in
the house has in it: the jumbotron on one sheet, landscape, and the
team board two coaches to a page.

Cut cards on the rounded outline printed on each one; a print-sheet's
cells are sized so dividing the sheet into an even grid cuts every
card dead centre (see "The printed boards" in
`docs/design/printed-boards.md`). Pass `--bleed` when building the kit
if a print shop wants the extra 1/8in margin to trim into.

## What to bring besides this kit

Printed here: every card, every board and the tokens. Not printed:

- **A d12 a side** (a twelve-sided die) -- it is also the ball, and the
  face it shows is the ball's speed.
- **Nine meeples or pawns a team**, in each team's own colour --
  `d12ball/render.py`'s `TEAM_COLORS` names the hex if you want to
  match a set to the board's own palette.

## Rules

The two rulebooks, as PDFs on letter paper, are in **rulebooks/**:

- **learn-to-play.pdf** -- *D12 Ball: Learn to Play*, the illustrated
  guide to the training mode. Start here.
- **charter.pdf** -- *The D12Ball Charter: Laws of the Game*, the whole
  ruleset, numbered: the one thing to check a mechanic against. It is
  built from the same text the bot's own `/d12ball rules_*` commands
  serve.

## Rebuilding

    python3 scripts/generate_print_and_play_kit.py

Add `--bleed` for a print shop, `--pdf` for a PDF of each board
alongside its PNG, and `--zip` to also bundle the whole kit into
`<out>.zip` for handing to somebody who does not want a folder. See `--help` for the rest.
"""


# What the README says of the player cards' Avery pages, where the kit
# has them: `--no-avery-players` leaves the pages out, and these with
# them.
PLAYER_AVERY = """
  The same cards come a second way, for Avery Presta 95328 stock (see
  above), every page full, so a page may hold two teams:
  `avery-1.png` to `avery-{avery_pages}.png` are the standard sides,
  team after team in roster order, and `advanced-avery-1.png` to
  `advanced-avery-{avery_pages}.png` their advanced sides -- print each
  page with its advanced page of the same number."""
PLAYER_AVERY_STOCK = """ and the player
cards' `avery-` pages,"""


def write_readme(
    out_dir: Path, paper: str, players_per_team: int, player_avery: bool,
) -> None:
    width, height = PAPERS[paper]
    readme = README_TEMPLATE.format(
        player_avery=(
            PLAYER_AVERY.format(
                avery_pages=-(-(len(COLOR_TEAMS) * players_per_team) // AVERY_95328_CARDS)
            )
            if player_avery else ""
        ),
        player_avery_stock=PLAYER_AVERY_STOCK if player_avery else "",
        generated=date.today().isoformat(),
        sheet_columns=DUPLEX_COLUMNS,
        team_count=len(COLOR_TEAMS),
        team_names=", ".join(team_display_name(team) for team in COLOR_TEAMS),
        token_counts=", ".join(
            f"{count} {TOKEN_NAMES[name]}" for name, count in TOKEN_COUNTS.items()
        ),
        players_per_team=players_per_team,
        paper=paper,
        paper_size=f"{width:.2f} x {height:.2f}in",
        letter_size="{:.2f} x {:.2f}in".format(*PAPERS["letter"]),
    )
    (out_dir / "README.md").write_text(readme)
    print(f"wrote {out_dir / 'README.md'}")


def zip_kit(out_dir: Path) -> Path:
    zip_path = out_dir.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(out_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(out_dir.parent))
    print(f"wrote {zip_path}")
    return zip_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build the whole print-and-play kit -- the maneuver, player "
            "and reference card sheets, the tokens and every board -- in "
            "one folder."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "d12ball" / "print" / "print-and-play",
        help="Directory to write the kit into (default: ./d12ball/print/print-and-play)",
    )
    parser.add_argument(
        "--paper",
        default=DEFAULT_PAPER,
        choices=sorted(PAPERS),
        help=(
            f"The field board's sheet size (default: {DEFAULT_PAPER}). "
            "The jumbotron and the team board have papers of their own."
        ),
    )
    parser.add_argument(
        "--bleed",
        action="store_true",
        help="Add the print-shop 1/8in bleed to every component.",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="Also write a PDF of each board.",
    )
    parser.add_argument(
        "--no-avery-players",
        action="store_true",
        help=(
            "Leave out the player cards' Avery Presta 95328 pages, which "
            "are the sheets' cards a second way (the landing page's kit)."
        ),
    )
    parser.add_argument(
        "--zip",
        action="store_true",
        help="Also bundle the finished kit into <out>.zip.",
    )
    args = parser.parse_args()

    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True)

    bleed_flag = ["--bleed"] if args.bleed else []

    run(
        "render_maneuver_cards.py",
        ["--out", str(args.out / "maneuver-cards"), "--sheets-only", *bleed_flag],
    )

    player_args = ["--out", str(args.out / "player-cards"), "--sheets-only", *bleed_flag]
    for team in COLOR_TEAMS:
        player_args += ["--team", team.value]
    if args.no_avery_players:
        player_args.append("--no-avery")
    run("render_player_cards.py", player_args)

    run(
        "render_reference_cards.py",
        ["--out", str(args.out / "reference-cards"), *bleed_flag],
    )

    run("render_token_sheet.py", ["--out", str(args.out / "tokens")])

    # The card a playtest table is handed: the box cover on its front,
    # the board and the survey on its back (the author, 2026-09-29).
    run(
        "render_box_art.py",
        [
            "--out", str(args.out / "playtest-cards"),
            "--only", "playtest-card", "--sheets-only", *bleed_flag,
        ],
    )

    board_args = [
        "--out", str(args.out / "boards"),
        "--paper", args.paper,
        *bleed_flag,
    ]
    if args.pdf:
        board_args.append("--pdf")
    run("render_boards.py", board_args)

    # The two rulebooks as the PDFs a table reads, on letter paper
    # whatever sheet the field board is on.
    run("build_rulebooks.py", ["--out", str(args.out / "rulebooks")])

    catalog = load_player_catalog()
    players_per_team = len(catalog.teams[COLOR_TEAMS[0]].players)
    write_readme(
        args.out, args.paper, players_per_team, not args.no_avery_players
    )

    if args.zip:
        zip_kit(args.out)

    print(f"\nprint-and-play kit written to {args.out}")


if __name__ == "__main__":
    main()

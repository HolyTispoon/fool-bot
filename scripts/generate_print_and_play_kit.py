#!/usr/bin/env python3
"""Build the whole print-and-play kit in one command.

    python3 scripts/generate_print_and_play_kit.py
    python3 scripts/generate_print_and_play_kit.py --bleed --pdf --zip
    python3 scripts/generate_print_and_play_kit.py --teams --paper a3

This is the thing to hand somebody before a meetup, a playtest table or
a con booth: every printable component in one folder (or one zip),
built fresh from whatever the bot itself plays. **It is the print
version of the game, as print sheets only**: each card set is one
sheet (two for a team: its cards' standard sides and their advanced
sides, printed duplex), never a PNG per card, and the player cards are
all four colour teams' -- the print game has no cards for the species
teams; a colour team's card carries its player's special ability on
its advanced side (the author, 2026-09-27). The species and role reference cards share
one sheet, and the condition tokens have two sheets of their own, printed duplex. **It
draws nothing on its own** -- it runs `render_maneuver_cards.py`,
`render_player_cards.py`, `render_reference_cards.py`,
`render_token_sheet.py`, `render_boards.py` and `build_rulebooks.py`, the same scripts a
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
printer, {sheet_columns} cards to a row.

- **maneuver-cards/print-sheet.png** -- the twelve maneuver cards (six
  basic, six gambits) and their shared back.
- **player-cards/** -- all {team_count} colour teams ({team_names}),
  {players_per_team} players a team, two print sheets a team. Every player
  card is double-sided, and both sides carry the player's role, skills
  and species ability. The **standard** side prints the role's ability;
  the **advanced** side, marked ADVANCED under the name, prints the
  player's special ability in its place, and for a few players higher
  skills.
  `<team>-sheet.png` is the standard sides and
  `<team>-advanced-sheet.png` the advanced sides. Print a team's two
  sheets duplex (flip on the long edge) and every card comes out with
  its standard side on one face and its advanced side on the other --
  the advanced sheet's rows are laid out reversed so they land back to
  back (`duplex_order` in `d12ball/player_cards.py`).
- **reference-cards/print-sheet.png** -- the reference cards: the
  three double-sided species-ability cards (every pairing of the four
  species appears on one face) and the double-sided role-ability card
  (the six basic roles). Each card's front is printed beside its back:
  cut the two out together and glue them back to back.
- **tokens/** -- the condition tokens, double-sided, on one piece of
  letter paper: {token_counts}. `front-sheet.png` is every token's
  front and `back-sheet.png` its back. Print the two duplex (flip on
  the long edge) and cut the tokens out: each lands with its back
  behind it -- the back sheet is laid out mirrored so they line up,
  and each face has a thin black margin so a printer a little out of
  line still cuts clean. The exhaustion token has its Cyborg drain on
  the back, and each marker is a condition on one side and what it
  turns into on a failed check on the other. Need more? Print the
  pair of pages again.
- **boards/** -- the field board at every size the ruleset defines
  (7 and 9 spaces), each also as a `-top` and `-bottom` half for a
  letter printer; the jumbotron board (clock, score, token supplies);
  and the team board (a coach's die and maneuvers, the bench, the
  formation strip -- one sheet holds both coaches' panels, cut in
  half).

## Paper and cutting

Cards are poker size (2.5 x 3.5in) at 300dpi, and every board is
300dpi too.

**Only the field board wants a big sheet.** It is {paper}
({paper_size}) -- see `PAPERS` / `DEFAULT_PAPER` in
`d12ball/boards.py` -- because its spaces have to be wide enough to
stand two sides' meeples on, and shrinking it to letter would take
that away. If you have no printer that size, print
`field-board-<n>-top.png` and `field-board-<n>-bottom.png` instead:
they are that same board cut in half, two letter sheets, taped along
the cut, at exactly the size the big sheet prints.

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
alongside its PNG, `--teams` for a team board per team colour rather
than one uncoloured one, and `--zip` to also bundle the whole kit into
`<out>.zip` for handing to somebody who does not want a folder. See `--help` for the rest.
"""


def write_readme(out_dir: Path, paper: str, players_per_team: int) -> None:
    width, height = PAPERS[paper]
    readme = README_TEMPLATE.format(
        generated=date.today().isoformat(),
        sheet_columns=4,
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
        "--teams",
        action="store_true",
        help=(
            "Render a team board per team colour instead of one "
            "uncoloured board."
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
    run("render_player_cards.py", player_args)

    run(
        "render_reference_cards.py",
        ["--out", str(args.out / "reference-cards"), *bleed_flag],
    )

    run("render_token_sheet.py", ["--out", str(args.out / "tokens")])

    board_args = [
        "--out", str(args.out / "boards"),
        "--paper", args.paper,
        *bleed_flag,
    ]
    if args.pdf:
        board_args.append("--pdf")
    if args.teams:
        board_args.append("--teams")
    run("render_boards.py", board_args)

    # The two rulebooks as the PDFs a table reads, on letter paper
    # whatever sheet the field board is on.
    run("build_rulebooks.py", ["--out", str(args.out / "rulebooks")])

    catalog = load_player_catalog()
    players_per_team = len(catalog.teams[COLOR_TEAMS[0]].players)
    write_readme(args.out, args.paper, players_per_team)

    if args.zip:
        zip_kit(args.out)

    print(f"\nprint-and-play kit written to {args.out}")


if __name__ == "__main__":
    main()

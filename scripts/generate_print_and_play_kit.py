#!/usr/bin/env python3
"""Build the whole print-and-play kit in one command.

    python3 scripts/generate_print_and_play_kit.py
    python3 scripts/generate_print_and_play_kit.py --bleed --pdf --zip
    python3 scripts/generate_print_and_play_kit.py --teams --paper a3

This is the thing to hand somebody before a meetup, a playtest table or
a con booth: every printable component in one folder (or one zip),
built fresh from whatever the bot itself plays. **It draws nothing on
its own** -- it runs `render_maneuver_cards.py`, `render_player_cards.py`,
`render_species_cards.py` and `render_boards.py`, the same four scripts
a developer already reaches for to check one component at a time, and
is only their sum into a folder meant to leave the repo. So a rules
change, an import, or an art fix reaches the kit exactly the way it
reaches each of those on its own -- by re-running this -- and there is
nothing here for a future rule to drift out of step with.

The kit is print-ready output and is gitignored, like `cards/` and
`print/`; run this again whenever the game underneath it changes rather
than keeping a stale copy around.

**What is not in the box.** The kit prints every card and every board;
it does not print meeples, dice or exhaustion tokens, none of which the
bot draws as cut-out components (a player's own tokens sit on their
card, not on a punch sheet -- see "The printed boards" in
docs/design/printed-boards.md). `write_readme` below lists what a table
still needs to bring, read straight off "The ball, the dice, and the
tokens" in docs/living-rules.md so the list cannot drift from what that
section says either.
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

- **maneuver-cards/** -- the twelve maneuver cards (six basic, six
  gambits) and their one shared back, plus `print-sheet.png`
  ({sheet_columns} to a row) for a home or copy-shop printer.
- **player-cards/** -- all {team_count} teams' rosters, front (the
  basic role) and back (the advanced version, species keyword and
  all), {players_per_team} players a team, plus a `<team>-sheet.png`
  and `<team>-advanced-sheet.png` for each. Print the front sheet and
  the advanced sheet duplex and they land back to back correctly --
  see `duplex_order` in `d12ball/player_cards.py`.
- **species-cards/** -- the three double-sided species-ability
  reference cards (every pairing of the four species appears on one
  face), plus `print-sheet.png`.
- **boards/** -- the field board at every size the ruleset defines
  (7 and 9 spaces), the jumbotron board (clock, score, token
  supplies), and the team board (a coach's die and maneuvers, the
  bench, the formation strip -- one sheet holds both coaches' panels,
  cut in half).

## Paper and cutting

Cards are poker size (2.5 x 3.5in) at 300dpi. Boards are {paper}
({paper_size}) at 300dpi, which is what a home or copy-shop printer
actually stocks -- see `PAPERS` / `DEFAULT_PAPER` in
`d12ball/boards.py`. Cut cards on the rounded outline printed on each
one; a print-sheet's cells are sized so dividing the sheet into an
even grid cuts every card dead centre (see "The printed boards" in
`docs/design/printed-boards.md`). Pass `--bleed` when building the kit
if a print shop wants the extra 1/8in margin to trim into.

## What to bring besides this kit

Printed here: every card and every board. Not printed, because the
rules never turn them into cut-out components:

- **A d12 a side** (a twelve-sided die) -- it is also the ball, and the
  face it shows is the ball's speed.
- **Nine meeples or pawns a team**, in each team's own colour --
  `d12ball/render.py`'s `TEAM_COLORS` names the hex if you want to
  match a set to the board's own palette.
- **A handful of small tokens** for exhaustion, per player -- these sit
  on a player's own card, not on a punch sheet, so bring poker chips,
  glass beads or coins rather than looking for them in this kit.

## Rules

`living-rules.md` alongside this README is the whole ruleset, copied
straight from `docs/living-rules.md` -- the same text the bot's own
`/d12ball rules_*` commands serve, and the one thing to check a
mechanic against.

## Rebuilding

    python3 scripts/generate_print_and_play_kit.py

Add `--bleed` for a print shop, `--pdf` for a PDF of each board
alongside its PNG, `--teams` for a team-coloured board and set of
player-card sheets per team colour (on top of the generic ones above),
and `--zip` to also bundle the whole kit into `<out>.zip` for handing
to somebody who does not want a folder. See `--help` for the rest.
"""


def write_readme(out_dir: Path, paper: str, team_count: int, players_per_team: int) -> None:
    width, height = PAPERS[paper]
    readme = README_TEMPLATE.format(
        generated=date.today().isoformat(),
        sheet_columns=4,
        team_count=team_count,
        players_per_team=players_per_team,
        paper=paper,
        paper_size=f"{width:.2f} x {height:.2f}in",
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
            "Build the whole print-and-play kit -- every maneuver, "
            "player and species card, and every board -- in one folder."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "print-and-play",
        help="Directory to write the kit into (default: ./print-and-play)",
    )
    parser.add_argument(
        "--paper",
        default=DEFAULT_PAPER,
        choices=sorted(PAPERS),
        help=f"Board sheet size (default: {DEFAULT_PAPER}).",
    )
    parser.add_argument(
        "--teams",
        action="store_true",
        help=(
            "Also render a team-coloured board and a per-team-coloured "
            "player-card set, not just the generic ones."
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
        ["--out", str(args.out / "maneuver-cards"), "--sheet", *bleed_flag],
    )

    player_args = ["--out", str(args.out / "player-cards"), "--sheet", *bleed_flag]
    run("render_player_cards.py", player_args)

    run(
        "render_species_cards.py",
        ["--out", str(args.out / "species-cards"), "--sheet", *bleed_flag],
    )

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

    shutil.copyfile(
        PROJECT_ROOT / "docs" / "living-rules.md",
        args.out / "living-rules.md",
    )
    print(f"wrote {args.out / 'living-rules.md'}")

    catalog = load_player_catalog()
    team_count = len(catalog.teams)
    players_per_team = len(next(iter(catalog.teams.values())).players)
    write_readme(args.out, args.paper, team_count, players_per_team)

    if args.zip:
        zip_kit(args.out)

    print(f"\nprint-and-play kit written to {args.out}")


if __name__ == "__main__":
    main()

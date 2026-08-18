#!/usr/bin/env python3
"""Render the roster as cards for the physical game.

One card a player, print-ready at 2.5 x 3.5 inches (poker size), with
the player's ability printed under the portrait:

    python3 scripts/render_player_cards.py --out cards/players
    python3 scripts/render_player_cards.py --sheet --bleed
    python3 scripts/render_player_cards.py --team orange

The layout lives in `d12ball/player_cards.py` and everything on a card
comes from `players.json`, so a re-import reaches the cards by
re-running this.

Faces only: the back of a player's card is that player's advanced
version, and advanced mode is unspecified -- the sheet's `Advanced`
ability column is empty for all thirty-six. Print these one-sided
until it is filled.
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.cards import print_sheet  # noqa: E402
from d12ball.components import Team, load_player_catalog  # noqa: E402
from d12ball.player_cards import (  # noqa: E402
    TEAM_SHEET_COLUMNS,
    render_player_card,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render every player's card for the tabletop game.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "cards" / "players",
        help="Directory to write the PNGs into (default: ./cards/players)",
    )
    parser.add_argument(
        "--team",
        choices=[team.value for team in Team],
        action="append",
        help=(
            "Render only this team; repeatable. Every team by default."
        ),
    )
    parser.add_argument(
        "--bleed",
        action="store_true",
        help="Add a 1/8in bleed margin for a print shop to trim into.",
    )
    parser.add_argument(
        "--sheet",
        action="store_true",
        help=(
            "Also write <team>-sheet.png: that team's nine in an even "
            f"grid {TEAM_SHEET_COLUMNS} across, each centred in its "
            "own cell."
        ),
    )
    args = parser.parse_args()

    catalog = load_player_catalog()
    teams = (
        [Team(value) for value in args.team]
        if args.team
        else list(catalog.teams)
    )
    args.out.mkdir(parents=True, exist_ok=True)

    for team in teams:
        cards = []
        for index, player in enumerate(catalog.teams[team].players, start=1):
            card = render_player_card(catalog, player, team, args.bleed)
            slug = player.name.lower().replace(" ", "-")
            # Numbered by where the roster lists them, which is the
            # order the standard deal reads, so a printed team comes
            # off the sheet in the order it is dealt.
            path = args.out / f"{team.value}-{index}-{slug}.png"
            card.save(path, dpi=(300, 300))
            cards.append(card)
            print(f"wrote {path}")

        if args.sheet:
            sheet_path = args.out / f"{team.value}-sheet.png"
            print_sheet(cards, columns=TEAM_SHEET_COLUMNS).save(
                sheet_path, dpi=(300, 300)
            )
            print(f"wrote {sheet_path}")


if __name__ == "__main__":
    main()

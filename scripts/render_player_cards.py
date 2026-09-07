#!/usr/bin/env python3
"""Render the roster as cards for the physical game.

One card a player, print-ready at 2.5 x 3.5 inches (poker size), with
the player's ability printed under the portrait:

    python3 scripts/render_player_cards.py --out cards/players
    python3 scripts/render_player_cards.py --sheet --bleed
    python3 scripts/render_player_cards.py --team orange

The layout lives in `d12ball/player_cards.py` and everything on a card
comes from `players.json` and `species.json`, so a re-import reaches
the cards by re-running this.

**Both sides are written.** The back of a player's card is that
player's advanced version -- the same card with the keyword of their
species ability beside their role ability. `--sheet` writes the backs
as a sheet of their own, with every row reversed so a duplex print
lands each back behind its own front; see `duplex_order`. Pass
`--fronts-only` for the one-sided run these used to be.

What the back is still waiting on is an advanced *role* ability: the
sheet's `Advanced` column is empty for all thirty-six, so the band
repeats the basic sentence.
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
    duplex_order,
    render_player_card,
    render_player_card_back,
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
            "Also write <team>-sheet.png and <team>-advanced-sheet.png: "
            f"that team's nine in an even grid {TEAM_SHEET_COLUMNS} "
            "across, each centred in its own cell, the backs in duplex "
            "order."
        ),
    )
    parser.add_argument(
        "--fronts-only",
        action="store_true",
        help="Skip the advanced backs and print one-sided.",
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
        fronts = []
        backs = []
        for index, player in enumerate(catalog.teams[team].players, start=1):
            slug = player.name.lower().replace(" ", "-")
            # Numbered by where the roster lists them, which is the
            # order the standard deal reads, so a printed team comes
            # off the sheet in the order it is dealt.
            stem = f"{team.value}-{index}-{slug}"

            card = render_player_card(catalog, player, team, args.bleed)
            path = args.out / f"{stem}.png"
            card.save(path, dpi=(300, 300))
            fronts.append(card)
            print(f"wrote {path}")

            if args.fronts_only:
                continue
            back = render_player_card_back(
                catalog, player, team, args.bleed
            )
            back_path = args.out / f"{stem}-advanced.png"
            back.save(back_path, dpi=(300, 300))
            backs.append(back)
            print(f"wrote {back_path}")

        if args.sheet:
            sheet_path = args.out / f"{team.value}-sheet.png"
            print_sheet(fronts, columns=TEAM_SHEET_COLUMNS).save(
                sheet_path, dpi=(300, 300)
            )
            print(f"wrote {sheet_path}")

            if backs:
                back_sheet = args.out / f"{team.value}-advanced-sheet.png"
                print_sheet(
                    duplex_order(backs, TEAM_SHEET_COLUMNS),
                    columns=TEAM_SHEET_COLUMNS,
                ).save(back_sheet, dpi=(300, 300))
                print(f"wrote {back_sheet}")


if __name__ == "__main__":
    main()

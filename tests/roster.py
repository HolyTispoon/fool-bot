"""
Naming a player in a test without naming a player.

The roster is data the author revises. Five orange players were renamed
on 2026-08-17, and every test that had picked one by id broke -- on
main, independently of the branch the rename landed on. Almost none of
those tests were about *who* the player was: they wanted a fielded
card, or a fullback, or three of a side to drain the bench with. They
ask for that here instead, so the next rename reaches them for free.

Ask for a player by whatever the test actually depends on:

- `fielded(match, role)` -- the card a standard deal fields in that
  role, which is the only one of that role on the field.
- `benched(match, role)` -- the same for the bench, which holds a
  second defender, playmaker and striker.
- `field_players(match)` -- the six on the field in deal order, for a
  test that just needs *some* players ("three of a side, to drain the
  bench"). A side's bench is `team_board.bench` and needs no wrapper.

Every team is dealt the same six roles in the same order and benches
the same three -- see `default_formation_deal` in
`d12ball/components.py` -- so these answer for any team, and a side is
named by its `TeamSide` rather than by which colour is playing it. The
side defaults to the home one, since that is the side most of these
tests act on; a test working the other end passes `TeamSide.VISITING`.

**`fielded` and `benched` read the catalog, not the board**: they name
the player a *standard deal* puts in that role, which is what a fixture
wants and stays answerable after the test has substituted them off.
`field_players` reads the match itself, so it follows a substitution.

A test genuinely about a particular player -- the roster listing, the
import, a portrait's art -- should still name them. This is for the
ones that only ever needed somebody.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from d12ball.components import (
    duplicate_card_id,
    MatchState,
    PlayerDefinition,
    PlayerRole,
    TeamSide,
    load_player_catalog,
)
from d12ball.game import Team


@lru_cache(maxsize=1)
def catalog():
    """The player catalog, read once for the whole suite."""
    return load_player_catalog()


def team_of(match: MatchState, side: TeamSide) -> Team:
    return match.setup_for_side(side).team


def _by_role(team: Team, role: PlayerRole) -> list[PlayerDefinition]:
    return [
        player
        for player in catalog().teams[team].players
        if player.role == role
    ]


def _card_id(match: MatchState, side: TeamSide, player_id: str) -> str:
    """
    The id this match holds that player under on that side.

    Their own, unless the two sides overlap and this is the visiting
    copy -- see "One player, both sides" in CLAUDE.md. These helpers
    read the catalog rather than the board on purpose (so they stay
    answerable after a substitution), which is exactly why they have
    to make this translation themselves.
    """
    setup = match.setup_for_side(side)
    on_this_side = (
        setup.field_players
        + setup.team_board.bench
        + setup.team_board.back_bench
    )
    if player_id in on_this_side:
        return player_id
    duplicate = duplicate_card_id(player_id)
    if duplicate in on_this_side:
        return duplicate
    raise LookupError(f"{player_id} is not on this match's {side.value} side.")


def fielded(
    match: MatchState,
    role: PlayerRole,
    side: TeamSide = TeamSide.HOME,
) -> str:
    """
    The player a standard deal puts on the field in `role`.

    The deal takes one of each role in roster order, so this is the
    first of them -- and for the three roles that appear twice, the
    other one is `benched`.
    """
    return _card_id(
        match, side, _by_role(team_of(match, side), role)[0].player_id,
    )


def benched(
    match: MatchState,
    role: PlayerRole,
    side: TeamSide = TeamSide.HOME,
) -> str:
    """
    The player a standard deal benches in `role`.

    Only the defender, playmaker and striker have one; asking for any
    other role is a test asking for somebody who does not exist.
    """
    players = _by_role(team_of(match, side), role)
    if len(players) < 2:
        raise LookupError(
            f"{team_of(match, side).value.title()} benches no {role.value}."
        )
    return _card_id(match, side, players[1].player_id)


def field_players(
    match: MatchState, side: TeamSide = TeamSide.HOME,
) -> list[str]:
    """The six cards this side has on the field, in deal order."""
    return [
        player_id
        for players in match.setup_for_side(side).zones.values()
        for player_id in players
    ]


def fielded_of_species(
    match: MatchState,
    species: str,
    side: TeamSide = TeamSide.HOME,
) -> str:
    """
    A card this side has **on the field** of that species, for a test
    about a species ability rather than about a role.

    It reads the board rather than the catalog, unlike `fielded` and
    `benched`: which species a colour team fields is the roster's
    business (three of its own plus two of each other), so "somebody of
    this species on this side" is a question about the deal that
    actually happened. A species team fields nine of one, so any of the
    six answers there.

    Raises rather than returning None -- a test that asks for a Fire
    Demon on a side holding none is a fixture that has gone wrong, and
    the ability under test would silently never fire.
    """
    for player_id in field_players(match, side):
        if catalog().player_by_id(player_id).species == species:
            return player_id
    raise LookupError(
        f"No {species} on this match's {side.value} side."
    )


def roles(player_ids: Iterable[str]) -> tuple[PlayerRole, ...]:
    """
    The roles of `player_ids`, in the order given.

    For a test asserting *what* a deal fielded rather than who. It
    comes back as a tuple because `BasicRuleset.standard_setup` holds
    tuples, and comparing against that list itself is the point.
    """
    return tuple(
        catalog().player_by_id(player_id).role for player_id in player_ids
    )


def display_name(player_id: str) -> str:
    """
    The name a coach is shown, for a test asserting a label the bot
    builds out of one -- a High Pass distance button, say. The wording
    around it is the thing under test; the name inside it is not.
    """
    return catalog().player_by_id(player_id).name

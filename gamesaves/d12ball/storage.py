import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional
from d12ball.game import TEAM_PAIRS, D12BallGame, Team


LOGGER = logging.getLogger(__name__)

# The color a species was fielded under exclusively, before the
# 2026-08-17 reshuffle split each species across all four colors --
# the mirror image of SPECIES_TEAM in
# scripts/import_d12ball_players.py. A saved game from before that
# change names its players `{legacy color}_{slug(name)}` and its two
# sides' Team by this same color; kept here rather than imported from
# the importer, since scripts/ is tools rather than a package and this
# needs to run at load time.
LEGACY_COLOR_FOR_SPECIES = {
    "fire_demon": "orange",
    "cyborg": "teal",
    "telekinetic": "purple",
    "ooze": "slime",
}
_LEGACY_COLOR_VALUES = frozenset(LEGACY_COLOR_FOR_SPECIES.values())

# `{name a legacy id was built from: that player's name now}`, for the
# players who have been renamed since. A legacy id carries the name the
# player had when the game was saved, and that is the one thing the
# current catalog cannot tell you -- everything else about the old id
# (the color, from the species) is still derivable, which is why this
# is three entries rather than the table of 36 the rest of this
# deliberately avoids. Written down because it has to be, not because
# it was easier.
#
# These three landed in 36250a9 on 2026-08-17, a day before the
# reshuffle and separately from it, so a game saved before that commit
# has been failing `TeamSetup.validate` ever since -- first on the
# rename, then on the reshuffle. That is the second live traceback:
# `/d12ball resume` on a game older than both.
#
# Add to this whenever a player is renamed, or a save older than the
# rename stops loading. `_unmapped_legacy_ids` is what says so out
# loud if anybody forgets.
LEGACY_RENAMED_NAMES = {
    "blazekick": "brightburn",
    "kindlefoot": "kindlefinger",
    "sizzik": "sizzifizik",
}

# Built once and cached: load_player_catalog() reads and parses
# players.json, and load_games() is called once at startup for every
# saved game, so there is no reason to repeat that per game.
_legacy_id_map: Optional[dict[str, str]] = None


def _build_legacy_id_map() -> dict[str, str]:
    """
    `{old id: new id}` for every player who has one, reconstructed from
    the *current* catalog rather than a hardcoded table of 36 pairs --
    a player's old id was `{legacy color}_{slug(name)}`
    (LEGACY_COLOR_FOR_SPECIES keyed off their species) and their new
    one is already `player_id` on the catalog entry. See the
    legacy-migration gotcha in docs/design/gotchas.md.
    """
    global _legacy_id_map
    if _legacy_id_map is not None:
        return _legacy_id_map

    # Imported here, not at module scope: d12ball.components is a much
    # heavier import (Pillow-adjacent data model code) than anything
    # else this module needs, and every other caller of load_games
    # already pays for it elsewhere by the time this runs.
    from d12ball.components import load_player_catalog

    catalog = load_player_catalog()
    legacy_ids: dict[str, str] = {}
    by_current_name: dict[str, tuple[str, str]] = {}
    for roster in catalog.teams.values():
        for player in roster.players:
            legacy_color = LEGACY_COLOR_FOR_SPECIES.get(player.species)
            if legacy_color is None:
                continue
            current_name = player.name.lower()
            legacy_ids[f"{legacy_color}_{current_name}"] = player.player_id
            by_current_name[current_name] = (legacy_color, player.player_id)

    # A renamed player answers to their old id as well. The color is
    # still read off their species rather than written down, so a
    # rename recorded here cannot disagree with the reshuffle about
    # which team the save is from.
    for old_name, current_name in LEGACY_RENAMED_NAMES.items():
        renamed = by_current_name.get(current_name)
        if renamed is None:
            continue
        legacy_color, player_id = renamed
        legacy_ids[f"{legacy_color}_{old_name}"] = player_id

    _legacy_id_map = legacy_ids
    return legacy_ids


def _unmapped_legacy_ids(value) -> set[str]:
    """
    Every string still shaped like a legacy id after a migration has
    run -- `{legacy color}_{something}`, which no id in the reshuffled
    catalog looks like.

    A migration that fires but cannot map everything leaves a side
    half-remapped, which is worse than not firing at all: the save
    still fails `TeamSetup.validate`, and the traceback says only that
    the setup does not match, naming nobody. Almost always a rename
    missing from `LEGACY_RENAMED_NAMES`, so the leftovers *are* the
    diagnosis and this is what puts them in the log.
    """
    if isinstance(value, str):
        color, separator, rest = value.partition("_")
        if separator and rest and color in _LEGACY_COLOR_VALUES:
            return {value}
        return set()
    found: set[str] = set()
    if isinstance(value, list):
        for item in value:
            found |= _unmapped_legacy_ids(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            found |= _unmapped_legacy_ids(key)
            found |= _unmapped_legacy_ids(item)
    return found


def _remap_legacy_ids(value, mapping: dict[str, str]):
    """
    Walk a JSON-shaped value -- dicts, lists, and everything else --
    replacing any string that is a key in `mapping`, **including dict
    keys themselves** (exhaustion and assigned_positions are both
    keyed by player id). Returns `(remapped_value, anything_replaced)`;
    the flag is how the caller tells an old-shape save from a fresh
    one apart without trusting a team value's name -- "orange" is a
    legal Team both before and after the reshuffle, just for different
    rosters, so the id strings actually present are the only reliable
    signal.

    One generic pass this way is what covers every field a legacy
    save could hold a player id in -- board spaces, zones, both
    benches, ball_carrier_id/challenger_id, exhaustion/injured sets,
    pending_run_back_*, assigned_positions keys, shootout order/used/
    shooters, goal-log player_ids -- without special-casing any of
    them by name.
    """
    if isinstance(value, str):
        if value in mapping:
            return mapping[value], True
        return value, False

    if isinstance(value, list):
        replaced = False
        remapped = []
        for item in value:
            new_item, item_replaced = _remap_legacy_ids(item, mapping)
            remapped.append(new_item)
            replaced = replaced or item_replaced
        return remapped, replaced

    if isinstance(value, dict):
        replaced = False
        remapped = {}
        for key, item in value.items():
            new_key = key
            if isinstance(key, str) and key in mapping:
                new_key = mapping[key]
                replaced = True
            new_item, item_replaced = _remap_legacy_ids(item, mapping)
            remapped[new_key] = new_item
            replaced = replaced or item_replaced
        return remapped, replaced

    return value, False


def migrate_legacy_game_data(game_data: dict) -> dict:
    """
    Tolerant, on-load remap of a game saved before the 2026-08-17
    eight-team reshuffle, in the style already established for
    `team_board`/`player_board` and `LEGACY_HALFTIME_STAGES` -- not a
    one-time destructive rewrite of the save file, since both
    developers run the bot from their own trees against their own
    saves and a half-finished game outlives the change that broke it.

    This is the concrete fix for a stuck game reported live: a saved
    match's roster no longer matches the reshuffled catalog, so
    `TeamSetup.validate` raises `ValueError('The setup does not match
    the team roster.')` the moment `/d12ball resume` (or anything else)
    tries to validate it. Every id the save names is reconstructed and
    rewritten to its new form, and each side's Team is remapped from
    the legacy color to its *paired species team* -- not left as the
    color -- because that species roster is the one whose membership
    the legacy save actually matches; the reshuffled color of the same
    name now holds different players.

    A game already in the new shape is returned untouched: nothing
    here fires unless `_remap_legacy_ids` actually found a legacy id
    somewhere in it.
    """
    legacy_ids = _build_legacy_id_map()
    remapped, replaced = _remap_legacy_ids(game_data, legacy_ids)
    if not replaced:
        return game_data

    for key in ("player_1_team", "player_2_team"):
        value = remapped.get(key)
        if value in _LEGACY_COLOR_VALUES:
            remapped[key] = TEAM_PAIRS[Team(value)].value

    match_state = remapped.get("match_state")
    if match_state:
        for side_key in ("home", "visiting"):
            side = match_state.get(side_key)
            if side and side.get("team") in _LEGACY_COLOR_VALUES:
                side["team"] = TEAM_PAIRS[Team(side["team"])].value

        # Scoped to the match state, which is the only part of a save
        # that holds player ids and the only part `validate` reads.
        # A game's own name could carry anything.
        leftovers = _unmapped_legacy_ids(match_state)
        if leftovers:
            LOGGER.error(
                "D12 Ball game %s is a legacy save this build cannot fully "
                "migrate: %s could not be matched to a current player, so "
                "the game will not load. Almost certainly a rename missing "
                "from LEGACY_RENAMED_NAMES in gamesaves/d12ball/storage.py.",
                remapped.get("game_id", "?"),
                ", ".join(sorted(leftovers)),
            )

    return remapped

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_FOLDER = PROJECT_ROOT / "data"
GAMES_FILE = DATA_FOLDER / "d12ball_games.json"

# Whether the last save failed to reach the disk, refused or rejected.
# A run of failures is one thing wrong repeated once or twice a click,
# so only the first of them is worth waking anyone for; see
# `save_games`.
_save_failing = False

# Whether the file was there but could not be read. The games in
# memory are then not the games on disk, and `save_games` refuses to
# write over it -- see "A file we could not read is never written
# over" in that function.
_load_unreadable = False

def load_games() -> dict[str, D12BallGame]:
    global _load_unreadable

    _load_unreadable = False

    try:
        DATA_FOLDER.mkdir(parents=True, exist_ok=True)
        file_exists = GAMES_FILE.exists()
    except OSError as error:
        # The folder is not reachable at all -- an unmounted drive, the
        # case in `save_games`. Whether there is a file behind it is
        # unknown, so assume there is: coming up empty and then saving
        # over it when the mount returns is the one outcome that loses
        # games for good.
        LOGGER.error("Could not reach the D12 Ball save folder: %s", error)
        _load_unreadable = True

        return {}

    if not file_exists:
        return {}

    try:
        with GAMES_FILE.open("r", encoding="utf-8") as file:
            raw_data = json.load(file)
    except (json.JSONDecodeError, OSError) as error:
        # Errors, not warnings: every game the bot knows about has just
        # vanished from its view, and the players will see that as the
        # bot forgetting their match.
        LOGGER.error("Could not load D12 Ball games: %s", error)
        _load_unreadable = True

        return {}

    games: dict[str, D12BallGame] = {}
    known_fields = {field.name for field in fields(D12BallGame)}

    for game_id, game_data in raw_data.items():
        # A game saved before the 2026-08-17 eight-team reshuffle names
        # its players by their old id and its two sides by a legacy
        # color -- migrate_legacy_game_data is a no-op the moment
        # neither is true any more. See the legacy-migration gotcha in
        # docs/design/gotchas.md.
        migrated = migrate_legacy_game_data(game_data)
        if migrated is not game_data:
            LOGGER.info(
                "Migrated saved game %s off its pre-reshuffle team ids.",
                game_id,
            )
            game_data = migrated

        # A key the record no longer has is a field that was removed
        # while games saved under it were still half-played --
        # `tie_mode`, when league mode went. Dropping it keeps those
        # games loading; passing it through would raise TypeError and
        # take the whole game out of the bot's view. Console-only,
        # because nobody can act on it and every restart would repeat
        # it.
        retired = sorted(set(game_data) - known_fields)
        if retired:
            LOGGER.info(
                "Ignoring retired field(s) %s on saved game %s.",
                ", ".join(retired),
                game_id,
            )
            game_data = {
                key: value
                for key, value in game_data.items()
                if key in known_fields
            }

        # TypeError is a field the record no longer takes; ValueError
        # is a value it no longer accepts -- a board size of 6, since
        # the six-space board was withdrawn (2026-09-22 in
        # docs/rules-log.md). Either way it is this game that is
        # unreadable, and letting it out of here would take every other
        # game in the file down with it.
        try:
            games[game_id] = D12BallGame(**game_data)
        except (TypeError, ValueError) as error:
            LOGGER.error("Skipping invalid saved game %s: %s", game_id, error)

    return games


def save_games(games: dict[str, D12BallGame]) -> None:
    """
    Write the games out, and **never raise doing it.**

    This is called from about a hundred and fifty places, most of them
    part-way through resolving a turn, and a raise there takes the turn
    down with it: the click's callback dies wherever the save happened
    to sit, so a coach whose maneuver has already been announced and
    whose board has already been redrawn is told "something went wrong,
    please try again" -- and trying again applies the turn twice. The
    live game is the one in memory; this file is what a restart reads.
    Losing it is worth an entry in #logs, not a broken turn.

    Real cause seen in the wild: the checkout lives on a mounted
    network drive (a Windows Google Drive letter) and the mount went
    away mid-game, so `mkdir` walked the whole path up to a drive root
    that no longer existed. Nothing in the bot can fix that, which is
    exactly why it must not be the bot that breaks.

    The write itself is already all-or-nothing -- a temporary file
    renamed over the real one -- so a failure part-way through leaves
    the last good save intact rather than a truncated one.

    **A file we could not read is never written over.** The other half
    of the same mount going away is the bot starting up while it is
    gone: `load_games` comes back empty, and the first save after the
    mount returns would replace every saved game with the one or two
    played since. So a load that failed on anything but "there is no
    file yet" blocks writing until the process is restarted, which is
    the thing to do anyway -- the games it needs are in the file.
    """
    global _save_failing

    if _load_unreadable and GAMES_FILE.exists():
        if not _save_failing:
            LOGGER.error(
                "Not saving D12 Ball games over %s, which this run could "
                "not read: restart the bot now that it is readable, or "
                "these games are lost.",
                GAMES_FILE,
            )

        _save_failing = True

        return

    serialized_games = {
        game_id: asdict(game)
        for game_id, game in games.items()
    }

    temporary_file = GAMES_FILE.with_suffix(".tmp")

    try:
        DATA_FOLDER.mkdir(parents=True, exist_ok=True)

        with temporary_file.open("w", encoding="utf-8") as file:
            json.dump(serialized_games, file, indent=2)

        temporary_file.replace(GAMES_FILE)
    except OSError as error:
        # The first failure of a run reaches the server, because
        # somebody has to go and remount the drive (or free the disk).
        # The ones behind it are the same fact repeated once or twice a
        # click, so they stay on the console -- see "The level you log
        # at decides who sees it" in docs/design/logging.md.
        if _save_failing:
            LOGGER.info("Still could not save D12 Ball games: %s", error)
        else:
            LOGGER.error(
                "Could not save D12 Ball games, so a restart would lose "
                "everything played since the last successful save: %s",
                error,
                exc_info=error,
            )

        _save_failing = True

        return

    if _save_failing:
        LOGGER.info("Saving D12 Ball games again.")

    _save_failing = False
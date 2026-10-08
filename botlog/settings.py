"""
Which bot this process is, as far as logging is concerned: the prefix
its environment variables carry, the name its notices say, and the state
file its deploy notice remembers the last build in.

Two bots run from this repository -- fool-bot and the Codex bot -- each
its own process with its own state file (docs/design/codex.md, "Its own
process, its own token"). fool-bot is the default, so a process that
never calls `configure` reads `FOOLBOT_*`, says nothing about its name
and keeps `data/bot_state.json`, exactly as before. The Codex bot calls
it with the prefix `CODEX`, and each `CODEX_*` variable it reads falls
back to its `FOOLBOT_*` value when unset, so one `.env` serves both and
one #logs channel carries both, each notice naming its bot.
"""

import os
from pathlib import Path
from typing import Optional

import botstate

DEFAULT_PREFIX = "FOOLBOT"

_prefix = DEFAULT_PREFIX
_bot_name = ""
_state_file: Path = botstate.STATE_FILE


def configure(
    prefix: str = DEFAULT_PREFIX,
    bot_name: str = "",
    state_file: Optional[Path] = None,
) -> None:
    """Name this process's variables, its notices and its state file."""
    global _prefix, _bot_name, _state_file

    _prefix = prefix
    _bot_name = bot_name
    _state_file = state_file if state_file is not None else botstate.STATE_FILE


def prefix() -> str:
    return _prefix


def bot_name() -> str:
    """The name a notice says, or "" for the unnamed default."""
    return _bot_name


def state_file() -> Path:
    return _state_file


def variable(name: str) -> str:
    """The full name of one of this bot's variables: `LOG_MIRROR` is
    `FOOLBOT_LOG_MIRROR` or `CODEX_LOG_MIRROR`."""
    return f"{_prefix}_{name}"


def env(name: str, default: str = "") -> str:
    """
    `<prefix>_<name>` from the environment, falling back to
    `FOOLBOT_<name>` when this bot's own is not set at all, then to
    `default`. A value that is set is this bot's whatever it says, as
    each reader has always taken it -- a blank `CODEX_LOG_CHANNEL_ID=`
    is a choice, not an absence.
    """
    for key in (variable(name), f"{DEFAULT_PREFIX}_{name}"):
        value = os.environ.get(key)
        if value is not None:
            return value
    return default

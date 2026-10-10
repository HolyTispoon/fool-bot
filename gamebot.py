"""
The bot class both bots run on, and the command-tree sync gate.

fool-bot (`foolbot.py`) and the Codex bot (`codexbot.py`) are two
processes with two tokens (docs/design/codex.md, "Its own process, its
own token"), but the same bot underneath: a `commands.Bot` that loads
its extensions, then registers its slash commands with Discord only when
they differ from the ones last registered from this checkout. What
differs between them is a parameter here -- the extensions, the state
file the fingerprint is kept in, the variable that forces a sync, and
whether the message-content intent is wanted.
"""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Iterable, Optional

import discord
from discord import app_commands
from discord.ext import commands

import botstate

LOGGER = logging.getLogger(__name__)

# The key in the bot's state file holding a digest of the command tree
# last successfully registered with Discord, beside the deploy notice's
# sha and local for the same reason.
COMMAND_FINGERPRINT_KEY = "command_tree_fingerprint"

# What a sync variable has to say to force a sync.
FORCING_VALUES = ("always", "force", "on", "1", "yes")


def command_tree_fingerprint(
    tree: app_commands.CommandTree,
) -> Optional[str]:
    """
    A digest of exactly what `tree.sync()` would upload, or None when
    that cannot be worked out -- in which case the caller should sync,
    which is what it did unconditionally before this existed.

    It hashes the payload rather than a list of command names because
    the payload is what Discord actually stores: renaming a parameter
    or editing a description changes it, and those are exactly the
    changes that look like nothing has happened until someone notices
    the old description still in the client.

    `_get_all_commands` is private, and reproducing sync()'s payload is
    the only way to be sure the digest covers everything it sends --
    so anything at all going wrong here returns None and syncs, rather
    than risking a fingerprint that matches while the commands differ.
    A translator would rewrite the payload after this point, so its
    presence is the same kind of "cannot tell": neither bot sets one.
    """
    if tree.translator is not None:
        return None

    try:
        payload = [
            command.to_dict(tree)
            for command in tree._get_all_commands(guild=None)
        ]
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    except Exception as error:
        LOGGER.info(
            "Could not fingerprint the command tree (%r); syncing it.",
            error,
        )
        return None

    return hashlib.sha256(encoded).hexdigest()


def command_sync_forced(variable: str) -> bool:
    """
    True when `variable` (FOOLBOT_COMMAND_SYNC, CODEX_COMMAND_SYNC) asks
    for a sync regardless of the fingerprint -- the way back in when
    Discord's copy and this checkout's have drifted apart some other
    way, such as commands edited from a second checkout or a sync that
    was recorded as done and was not.
    """
    raw = os.environ.get(variable, "").strip().lower()

    return raw in FORCING_VALUES


async def sync_command_tree(
    tree: app_commands.CommandTree,
    *,
    fingerprint: Optional[str],
    forced: bool,
    state_file: Optional[Path],
    sync_variable: str,
) -> None:
    """
    Register the global command tree with Discord, but only when it
    differs from the one last registered from this checkout.

    Registering global commands is among the more heavily rate
    limited things a bot can do, and setup_hook runs on every
    process start -- which across a day of testing is dozens of
    starts, every one of them uploading a command list identical to
    the last. Nothing about the commands had changed; the requests
    were the whole cost.

    The fingerprint is only written once the sync has actually
    landed, the same way the deploy notice only records a sha once
    the post has gone out: a sync that raised has not happened, and
    the next start should try it again. `state_file` None is
    botstate's default, read at call time.
    """
    if (
        fingerprint is not None
        and not forced
        and fingerprint == botstate.read_key(COMMAND_FINGERPRINT_KEY, state_file)
    ):
        LOGGER.info(
            "The command tree is unchanged since the last sync; not "
            "syncing. Set %s=always to sync anyway.",
            sync_variable,
        )
        return

    synced = await tree.sync()
    LOGGER.info("Synced %d commands.", len(synced))

    if fingerprint is not None:
        botstate.write_key(COMMAND_FINGERPRINT_KEY, fingerprint, state_file)

    return synced


def read_command_ids(path: Path) -> dict[str, int]:
    """
    Another bot's top-level command ids, by name, as it wrote them after
    its last sync -- `{}` where there is no file or it cannot be read.
    fool-bot reads the Codex bot's, the one file read across the line,
    to mention `</codex create_game:ID>` in its hub (docs/design/codex.md,
    "fool-bot's hub points at the lobby").
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(name): int(value) for name, value in data.items()
            if isinstance(value, (int, str)) and str(value).isdigit()}


def write_command_ids(commands, path: Path) -> None:
    """Write `commands`' ids by name to `path`; a failure is logged, never
    raised -- the hub falls back to the command's name in plain text."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({command.name: command.id for command in commands}, indent=2),
            encoding="utf-8",
        )
    except OSError as error:
        LOGGER.warning("Could not write the command ids to %s: %s", path, error)


class GameBot(commands.Bot):
    def __init__(
        self,
        extensions: Iterable[str],
        state_file: Optional[Path],
        sync_variable: str,
        message_content: bool,
        command_ids_file: Optional[Path] = None,
    ):
        intents = discord.Intents.default()
        # Privileged, off by default. Without it, message.content on a
        # message the bot did not author is stripped to "" unless the
        # message is a DM or mentions the bot -- so a game channel's
        # export shows every bot post's text but every player chat line
        # as blank. A bot that wants it must also have it toggled on for
        # its application in the Discord Developer Portal (Bot ->
        # Privileged Gateway Intents -> Message Content Intent), or the
        # gateway rejects the connection; a bot of slash commands and
        # buttons alone does not ask.
        intents.message_content = message_content

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
        )
        self.extensions_to_load = tuple(extensions)
        self.state_file = state_file
        self.sync_variable = sync_variable
        #: Where this bot writes its top-level command ids after a sync,
        #: for another bot to mention them; None writes nothing.
        self.command_ids_file = command_ids_file

    async def setup_hook(self):
        for extension in self.extensions_to_load:
            LOGGER.info("Loading extension %s...", extension)
            await self.load_extension(extension)
            LOGGER.info("Extension %s loaded.", extension)

        await self.sync_commands_if_changed()

    async def sync_commands_if_changed(self) -> None:
        synced = await sync_command_tree(
            self.tree,
            fingerprint=command_tree_fingerprint(self.tree),
            forced=command_sync_forced(self.sync_variable),
            state_file=self.state_file,
            sync_variable=self.sync_variable,
        )
        await self.record_command_ids(synced)

    async def record_command_ids(self, synced) -> None:
        """
        Write the command ids after a sync. A start that skipped the sync
        writes them only when the file is missing, from one fetch of the
        registered commands -- the ids do not change between syncs.
        """
        if self.command_ids_file is None:
            return
        if synced is None:
            if self.command_ids_file.exists():
                return
            try:
                synced = await self.tree.fetch_commands()
            except discord.HTTPException as error:
                LOGGER.warning("Could not fetch the command ids: %s", error)
                return
        write_command_ids(synced, self.command_ids_file)

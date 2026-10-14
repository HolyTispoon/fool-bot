"""
The web app as a local background process, for the Godot spike.

    python3 sidecar.py <repo> <folder>

Runs `webapp.server.serve` from <repo> over files in <folder> -- never
the checkout's data/ -- bound to 127.0.0.1 on a port it picks, which it
announces as one JSON line on stdout. It leaves when stdin reaches end
of file, which is what happens when the process that started it goes
away, however that process went.

This is what `python3 -m webapp --local <folder>` is to become (step 1
of docs/godot/README.md); until then it is the same few lines
landing/capture.py starts its own server with, plus the three things a
child process needs that a hosted one does not.
"""

import asyncio
import json
import logging
import os
import socket
import sys
import threading
from pathlib import Path

repo, folder = sys.argv[1], Path(sys.argv[2])
sys.path.insert(0, repo)
folder.mkdir(parents=True, exist_ok=True)

# Nobody reads the pipe this process's stderr is: a full one would stop
# the server in the middle of a write. Everything it says goes to a file.
sys.stderr = open(folder / "sidecar.log", "w", buffering=1)
logging.basicConfig(stream=sys.stderr, level=logging.INFO)


def leave_with_the_parent() -> None:
    sys.stdin.read()
    os._exit(0)


threading.Thread(target=leave_with_the_parent, daemon=True).start()

with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
os.environ["FOOLBOT_WEB_PORT"] = str(port)
os.environ["FOOLBOT_WEB_HOST"] = "127.0.0.1"

# Announced before the server is listening, which is why wire.gd asks
# until somebody answers. The real flag announces once it is bound.
print(json.dumps({"port": port}), flush=True)

from webapp.server import serve  # noqa: E402  (the import is the slow part)

asyncio.run(serve(
    games_file=folder / "games.json",
    rooms_file=folder / "rooms.json",
    chat_file=folder / "chat.json",
    journal_file=folder / "journal.json",
    names_file=folder / "names.json",
    secret_file=folder / "secret",
))

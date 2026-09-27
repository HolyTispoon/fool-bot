"""
The board as the web app draws it, captured for d12ball.com.

    python3 scripts/build_landing.py --capture-board

The landing page shows the board a player sees at play.d12ball.com, not
the printed board and not the bot's PNG (the author, on the canvas,
2026-09-27) -- so the picture is taken of the web app itself:

1. a web game is staged in a temporary directory through `GameService`,
   as a room would set one up: two coaches seated, Purple picked by the
   first and the Cyborgs by the second, the coin flipped, Purple at
   home, the match dealt and begun -- the kickoff, before anybody moves;
2. the web app is started over that directory alone (`webapp.server.serve`
   with every file it keeps pointed there), on a spare local port;
3. a headless Chrome opens the room as an observer -- both seats are
   held, so a visitor is seated nowhere -- waits for the board's SVG,
   and captures the `.board-panel` rectangle at twice the pixel density,
   over the DevTools protocol;
4. the app and the browser are stopped and the directory removed.

The capture is written to `landing/d12ball/board.png`, which is
committed: the build copies that file and never starts a browser, so the
page is the same bytes wherever it is built -- on a machine with no
Chrome, in the test suite, on Cloudflare's build image. Take it again by
hand after a web app redesign step changes the board
(docs/design/landing-pages.md, "The board").
"""
from __future__ import annotations

import asyncio
import base64
import io
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

from d12ball.game import Team

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BOARD_CAPTURE = Path(__file__).resolve().parent / "d12ball" / "board.png"

HOME_TEAM = Team.PURPLE
VISITING_TEAM = Team.CYBORGS
# A desktop window, since the board panel reflows at narrow widths, and
# twice the density so the picture stays sharp on a phone's screen.
WINDOW = (1440, 1000)
DENSITY = 2
BOARD_DRAWN = ".board-panel #board svg"
STARTUP_SECONDS = 30

CHROME_CANDIDATES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)

# The web app, run over nothing but the capture's own directory: every
# file it would keep under data/ is named here instead.
SERVER = """
import asyncio, sys
from pathlib import Path
from webapp.server import serve
folder = Path(sys.argv[1])
asyncio.run(serve(
    games_file=folder / "games.json",
    rooms_file=folder / "rooms.json",
    chat_file=folder / "chat.json",
    journal_file=folder / "journal.json",
    names_file=folder / "names.json",
))
"""


class CaptureError(RuntimeError):
    pass


def find_chrome() -> str | None:
    """A Chrome or Chromium on this machine, or None."""
    configured = os.environ.get("LANDING_CHROME")
    for candidate in ((configured,) if configured else ()) + CHROME_CANDIDATES:
        found = shutil.which(candidate) or (
            candidate if Path(candidate).is_file() else None
        )
        if found:
            return found
    return None


def stage_game(folder: Path) -> str:
    """Save one web game at kickoff into `folder/games.json`, and return
    its id. Two coaches hold the seats, so the page's visitor watches."""
    from webapp.server import build_service

    service = build_service(folder / "games.json")
    game = service.create_game(
        player_1_id=1, player_1_name="Home",
        player_2_id=2, player_2_name="Visitors",
    )
    service.pick_team(game.game_id, 1, HOME_TEAM)
    service.pick_team(game.game_id, 2, VISITING_TEAM)
    service.flip_coin(game.game_id, 1)
    winner = game.coin_winner_player_number
    # Whoever won the coin, the first coach -- Purple -- is at home.
    service.choose_home_or_visiting(
        game.game_id, winner, "home" if winner == 1 else "visiting",
    )
    service.begin(game.game_id)
    return game.game_id


def spare_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


async def wait_for_port(port: int, process: subprocess.Popen) -> None:
    for _ in range(STARTUP_SECONDS * 10):
        if process.poll() is not None:
            raise CaptureError(f"the web app exited with {process.returncode}")
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            return
        except OSError:
            await asyncio.sleep(0.1)
    raise CaptureError(f"nothing answered on port {port}")


async def devtools_port(profile: Path, process: subprocess.Popen) -> int:
    marker = profile / "DevToolsActivePort"
    for _ in range(STARTUP_SECONDS * 10):
        if process.poll() is not None:
            raise CaptureError(f"Chrome exited with {process.returncode}")
        if marker.exists() and marker.read_text().strip():
            return int(marker.read_text().splitlines()[0])
        await asyncio.sleep(0.1)
    raise CaptureError("Chrome never opened its DevTools port")


class DevTools:
    """Just enough of the DevTools protocol to load a page and take a
    picture of part of it."""

    def __init__(self, socket_):
        self.socket = socket_
        self.next_id = 0

    async def call(self, method: str, **params):
        self.next_id += 1
        await self.socket.send_json({"id": self.next_id, "method": method, "params": params})
        while True:
            message = await self.socket.receive_json()
            if message.get("id") == self.next_id:
                if "error" in message:
                    raise CaptureError(f"{method}: {message['error']}")
                return message.get("result", {})

    async def evaluate(self, expression: str):
        result = await self.call(
            "Runtime.evaluate", expression=expression,
            returnByValue=True, awaitPromise=True,
        )
        return result.get("result", {}).get("value")


PANEL_RECT = f"""
(async () => {{
  if (!document.querySelector({BOARD_DRAWN!r})) return null;
  await document.fonts.ready;
  const r = document.querySelector('.board-panel').getBoundingClientRect();
  return [r.left + scrollX, r.top + scrollY, r.width, r.height,
          document.documentElement.scrollHeight];
}})()
"""


async def shoot(chrome_port: int, url: str) -> bytes:
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://127.0.0.1:{chrome_port}/json/list") as listing:
            targets = await listing.json()
        page = next(target for target in targets if target.get("type") == "page")
        async with session.ws_connect(page["webSocketDebuggerUrl"], max_msg_size=0) as ws:
            tools = DevTools(ws)
            width, height = WINDOW
            await tools.call(
                "Emulation.setDeviceMetricsOverride",
                width=width, height=height, deviceScaleFactor=DENSITY, mobile=False,
            )
            await tools.call("Page.navigate", url=url)
            rect = None
            for _ in range(STARTUP_SECONDS * 4):
                rect = await tools.evaluate(PANEL_RECT)
                if rect:
                    break
                await asyncio.sleep(0.25)
            if not rect:
                raise CaptureError(f"the board never drew at {url}")
            # Let the board fit itself to its box, then measure again.
            await asyncio.sleep(1.0)
            left, top, panel_width, panel_height, page_height = await tools.evaluate(PANEL_RECT)
            shot = await tools.call(
                "Page.captureScreenshot",
                format="png",
                captureBeyondViewport=True,
                clip={
                    "x": left, "y": top,
                    "width": panel_width, "height": panel_height,
                    "scale": 1,
                },
            )
            return base64.b64decode(shot["data"])


async def capture(out: Path, chrome: str) -> Path:
    with tempfile.TemporaryDirectory(prefix="landing-capture-") as scratch:
        folder = Path(scratch)
        game_id = stage_game(folder)
        port = spare_port()
        environment = {
            **os.environ,
            "FOOLBOT_WEB_PORT": str(port),
            "FOOLBOT_WEB_HOST": "127.0.0.1",
            "FOOLBOT_LOG_LEVEL": "WARNING",
        }
        server = subprocess.Popen(
            [sys.executable, "-c", SERVER, str(folder)],
            cwd=PROJECT_ROOT, env=environment,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        profile = folder / "chrome"
        browser = None
        try:
            await wait_for_port(port, server)
            browser = subprocess.Popen(
                [
                    chrome, "--headless=new", "--disable-gpu", "--no-first-run",
                    "--no-default-browser-check", "--hide-scrollbars",
                    f"--user-data-dir={profile}", "--remote-debugging-port=0",
                    f"--window-size={WINDOW[0]},{WINDOW[1]}", "about:blank",
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            png = await shoot(
                await devtools_port(profile, browser),
                f"http://127.0.0.1:{port}/room/{game_id}",
            )
        finally:
            for process in (browser, server):
                if process is not None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
    out.parent.mkdir(parents=True, exist_ok=True)
    # Re-saved through Pillow, whose optimiser takes a Chrome PNG down
    # by about half.
    Image.open(io.BytesIO(png)).save(out, "PNG", optimize=True)
    return out


def capture_board(out: Path = BOARD_CAPTURE, chrome: str | None = None) -> Path:
    """Take the board again into `out` (the committed capture by
    default). Raises `CaptureError` with no Chrome on the machine."""
    chrome = chrome or find_chrome()
    if chrome is None:
        raise CaptureError(
            "no Chrome or Chromium found; set LANDING_CHROME to one"
        )
    return asyncio.run(capture(Path(out), chrome))

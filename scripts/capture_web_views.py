#!/usr/bin/env python3
"""
The web app on the three screens it is looked at on: desktop, iPad and
phone, one PNG each.

    python3 scripts/capture_web_views.py --out shots/
    python3 scripts/capture_web_views.py --out shots/ --selector '#jumbotron'
    python3 scripts/capture_web_views.py --out shots/ \\
        --games-file data/d12ball_web_games.json --game <id>

The page has three layouts (docs/design/web-app.md, "Three ways to look
at the game"), and a change to it is shown on all three. Each view is
the query app.css keys its layout on:

- desktop -- 1440x900, a mouse: the stacked page;
- iPad -- 1180x820 on its side, touch: the tablet's two columns
  (961px to 1400px across with a coarse pointer);
- phone -- 390x844 upright, touch: the one-screen phone with the
  bottom sheet (960px and under).

By default a web game is staged at kickoff exactly as the landing
page's board capture stages one (`landing/capture.py`); `--games-file`
and `--game` show a saved web game instead, copied into the temporary
directory so the file itself is never written. Either way the room is
opened as an observer -- both seats are held by somebody else -- so
nothing on the field is lit for the reader. The web app and the browser
run over a temporary directory and are stopped when the pictures are
taken; nothing is written under data/.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import glob
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from landing import capture  # noqa: E402


@dataclass(frozen=True)
class View:
    name: str
    width: int
    height: int
    density: int
    touch: bool


VIEWS = (
    View("desktop", 1440, 900, 1, touch=False),
    View("ipad", 1180, 820, 2, touch=True),
    View("phone", 390, 844, 3, touch=True),
)

# Which layout app.css actually chose, read back so a view that fell
# into the wrong one fails rather than passing for the right one.
LAYOUT = """
(() => {
  const m = (q) => window.matchMedia(q).matches;
  if (m("(max-width: 960px)")) return "phone";
  if (m("(min-width: 961px) and (max-width: 1400px) and (orientation: landscape) and (any-pointer: coarse)")) return "ipad";
  return "desktop";
})()
"""


def element_rect(selector: str) -> str:
    return f"""
(async () => {{
  if (!document.querySelector({capture.BOARD_DRAWN!r})) return null;
  await document.fonts.ready;
  const found = document.querySelector({selector!r});
  if (!found) return null;
  const r = found.getBoundingClientRect();
  return r.width && r.height ? [r.left + scrollX, r.top + scrollY, r.width, r.height] : null;
}})()
"""


VIEWPORT = f"""
(async () => {{
  if (!document.querySelector({capture.BOARD_DRAWN!r})) return null;
  await document.fonts.ready;
  return [scrollX, scrollY, innerWidth, innerHeight];
}})()
"""


def find_chrome(given: str | None) -> str | None:
    if given:
        return given
    found = capture.find_chrome()
    if found:
        return found
    # Playwright's own Chromium, where a machine has one and no Chrome.
    browsers = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if browsers:
        for candidate in sorted(glob.glob(f"{browsers}/chromium-*/chrome-linux/chrome")):
            return candidate
    return None


async def shoot(port: int, url: str, view: View, selector: str | None) -> bytes:
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.put(f"http://127.0.0.1:{port}/json/new?about:blank") as made:
            page = await made.json()
        async with session.ws_connect(page["webSocketDebuggerUrl"], max_msg_size=0) as ws:
            tools = capture.DevTools(ws)
            await tools.call(
                "Emulation.setDeviceMetricsOverride",
                width=view.width, height=view.height,
                deviceScaleFactor=view.density, mobile=view.touch,
            )
            await tools.call(
                "Emulation.setTouchEmulationEnabled",
                enabled=view.touch, maxTouchPoints=5 if view.touch else 1,
            )
            await tools.call("Page.navigate", url=url)
            probe = element_rect(selector) if selector else VIEWPORT
            rect = None
            for _ in range(capture.STARTUP_SECONDS * 4):
                rect = await tools.evaluate(probe)
                if rect:
                    break
                await asyncio.sleep(0.25)
            if not rect:
                raise capture.CaptureError(
                    f"{view.name}: {selector or 'the board'} never drew at {url}"
                )
            layout = await tools.evaluate(LAYOUT)
            if layout != view.name:
                raise capture.CaptureError(
                    f"{view.name}: the page chose the {layout} layout"
                )
            # Let the board fit itself to its box, then measure again.
            await asyncio.sleep(1.0)
            left, top, width, height = await tools.evaluate(probe)
            shot = await tools.call(
                "Page.captureScreenshot",
                format="png",
                captureBeyondViewport=bool(selector),
                clip={"x": left, "y": top, "width": width, "height": height, "scale": 1},
            )
            return base64.b64decode(shot["data"])


async def capture_views(
    out: Path, chrome: str, selector: str | None,
    games_file: Path | None, game_id: str | None,
) -> list[Path]:
    with tempfile.TemporaryDirectory(prefix="web-views-") as scratch:
        folder = Path(scratch)
        if games_file is not None:
            shutil.copyfile(games_file, folder / "games.json")
        else:
            game_id = capture.stage_game(folder)
        port = capture.spare_port()
        environment = {
            **os.environ,
            "FOOLBOT_WEB_PORT": str(port),
            "FOOLBOT_WEB_HOST": "127.0.0.1",
            "FOOLBOT_LOG_LEVEL": "WARNING",
        }
        server = subprocess.Popen(
            [sys.executable, "-c", capture.SERVER, str(folder)],
            cwd=PROJECT_ROOT, env=environment,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        profile = folder / "chrome"
        browser = None
        written = []
        try:
            await capture.wait_for_port(port, server)
            flags = [
                chrome, "--headless=new", "--disable-gpu", "--no-first-run",
                "--no-default-browser-check", "--hide-scrollbars",
                f"--user-data-dir={profile}", "--remote-debugging-port=0",
            ]
            # Chrome refuses to sandbox itself as root, as in a container.
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                flags.append("--no-sandbox")
            browser = subprocess.Popen(
                flags + ["about:blank"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            chrome_port = await capture.devtools_port(profile, browser)
            url = f"http://127.0.0.1:{port}/room/{game_id}"
            out.mkdir(parents=True, exist_ok=True)
            for view in VIEWS:
                path = out / f"{view.name}.png"
                path.write_bytes(await shoot(chrome_port, url, view, selector))
                written.append(path)
        finally:
            for process in (browser, server):
                if process is not None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
        return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument("--out", type=Path, required=True,
                        help="directory for desktop.png, ipad.png and phone.png")
    parser.add_argument("--selector",
                        help="capture this element rather than the whole screen, e.g. '#jumbotron'")
    parser.add_argument("--games-file", type=Path,
                        help="a web games file to show a saved game from (read, never written)")
    parser.add_argument("--game", help="the game's id in --games-file")
    parser.add_argument("--chrome", help="the Chrome or Chromium to run")
    args = parser.parse_args()
    if (args.games_file is None) != (args.game is None):
        parser.error("--games-file and --game go together")
    chrome = find_chrome(args.chrome)
    if chrome is None:
        parser.error("no Chrome found; pass --chrome")
    for path in asyncio.run(capture_views(
        args.out, chrome, args.selector, args.games_file, args.game,
    )):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

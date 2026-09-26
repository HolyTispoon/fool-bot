"""
The web frontend -- ARCHITECTURE.md, part 4.

A frontend of its own over the same model the Discord cog plays, run
as its own process (`python3 -m webapp`) over its own games file: it
shares the rules with the bot and nothing at runtime. It
authenticates a person, turns a request into an `Action`, calls
`apply_action`, and renders the `GameResult` as JSON for a page. It
decides nothing about the game. The reasoning, and what it may not
do, is in docs/design/web-app.md.

**It imports neither `discord` nor `cogs`** -- principle 10 in
CLAUDE.md, "the web app may not reach past the flow", ratcheted by
`tests/test_web_purity.py`. What it needs of the game it asks the
model or the service for; if something is missing, the flow grows a
method and the bot gets it too.
"""

from webapp.server import WebApp, start_web_app

__all__ = ["WebApp", "start_web_app"]

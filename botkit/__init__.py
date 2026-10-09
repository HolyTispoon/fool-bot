"""
What the two bots' Discord frontends share, one home for each piece
(docs/codex-bot.md, step 9; docs/design/codex.md, "What the two games
share"): fool-bot's D12 Ball cog (`cogs/d12ball/`, `cogs/d12ball_views/`)
and the Codex bot's (`cogs/codex/`, `cogs/codex_views/`).

The leaves moved earlier stay where they went -- `gamebot.py`, `botlog/`,
`cogs/game_auth.py`, `cogs/d12ball_boards.py` -- and this package holds
what step 9 found identical in the two frontends. It imports neither
game (`tests/test_shared_kits.py`).
"""

"""
What the two games' models share, one home for each piece (docs/codex-bot.md,
step 9; docs/design/codex.md, "What the two games share").

D12 Ball's model (`d12ball/`, `gamesaves/d12ball/`) and the Codex bot's
(`codex/`, `gamesaves/codex/`) were built to the same shapes, the second
copied from the first. What turned out identical, or different only by
the game's name, lives here and both import it; what differs in
substance stays in each game. Held to the model's rules: it imports no
`discord`, defines no `async def` and imports no Pillow
(`tests/test_shared_kits.py`), and it imports neither game.
"""

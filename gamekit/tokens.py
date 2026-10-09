"""
What a token is to a frontend, for both games (`d12ball.tokens`,
`codex.tokens`, which re-export `Resolver`): a kind and its arguments,
rendered by whatever the frontend resolves them to.

Only the resolver's signature is shared. Each game's token grammar is
its own -- every D12 Ball token carries an argument (`{team:purple}`),
and Codex's glyphs are bare (`{exhaust}`) -- so each game keeps its own
`KINDS`, `TOKEN_PATTERN`, builders and the `render`/`find` that read its
pattern (docs/design/codex.md, "What the two games share").
"""

from typing import Callable, Optional

#: What a frontend renders a token with: the kind and its arguments in,
#: the text out -- or `None` to leave the token as it stands.
Resolver = Callable[[str, tuple[str, ...]], Optional[str]]

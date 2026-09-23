"""
The marks narration leaves for a frontend to draw.

A sentence the model says names things a coach *sees* rather than
reads: a team's ring, a role's badge after a name, an exhaustion
token, a species' ability mark, and the coach a question is put to.
On Discord each of those is an application emoji or a user mention;
on a web page each is an image or a link; in a test transcript each
is whatever the test says. The model knows only *which* thing it is
naming, so that is what it writes down -- a token, `{team:purple}`,
`{role:fullback:orange}`, `{condition:exhaust}`, `{species:cyborg}`,
`{coach:1}` -- and the frontend renders every one of them once, at
its door (`D12Ball.render_text`), the way a `PromptKind` is rendered
into a view rather than in each view. Step 9 of
docs/architecture-migration.md; the reasoning is in
docs/design/model-discord-split.md, "Tokens".

**A token is the model's, and its rendering is not.** The five
builders below are the only way a token is written, so its spelling
lives in one place; `render` is the only way one is read, and it
takes the frontend's resolver rather than knowing any. A resolver
that answers `None` for a token leaves it in the text, which is what
lets a test see a token a frontend forgot -- nothing here falls back
to a Discord string or a Unicode circle, because those are what
Discord shows and belong beside the emoji it fetches.

**A coach is a player number, not a side.** The coin decides which
side is whose, and a coach is named in the setup messages before it
has been flipped, so the number is the one key that names a coach
at every point of a game. The record maps it to an account, a name,
or the AI (`formatting.coach_name`); which of those a frontend shows
is its own -- Discord mentions an account and names the AI.
"""

import re
from typing import Callable, Optional

from d12ball.components import PlayerRole
from d12ball.game import Team


#: The condition marks a sentence may carry, by the name the token
#: spells. The exhaustion token, the two conditions it leads to, and
#: a Cyborg's own three words for them (see "Lithium Powered" in
#: docs/living-rules.md).
#:
#: **A Cyborg's token is its own mark.** Drain is exhaustion under
#: another name, so the pair reads the same way the human one does --
#: `drain` is the token and `drained` the condition it leads to,
#: exactly as `exhaust` is to `exhausted`. It is a separate mark
#: rather than the exhaust one because the board already draws a
#: Cyborg's tally in the Cyborgs' own teal (`exhaust_cyborg.png`,
#: `render.draw_exhaustion_badge`), and a sentence counting out amber
#: triangles beside a card showing teal ones is the same tally in two
#: colours.
CONDITION_EXHAUST = "exhaust"
CONDITION_EXHAUSTED = "exhausted"
CONDITION_INJURED = "injured"
CONDITION_DRAIN = "drain"
CONDITION_DRAINED = "drained"
CONDITION_DAMAGED = "damaged"
CONDITIONS = (
    CONDITION_EXHAUST,
    CONDITION_EXHAUSTED,
    CONDITION_INJURED,
    CONDITION_DRAIN,
    CONDITION_DRAINED,
    CONDITION_DAMAGED,
)

#: The kinds a token may be, in the order a reader meets them.
KINDS = ("team", "role", "condition", "species", "coach")

TOKEN_PATTERN = re.compile(
    r"\{(" + "|".join(KINDS) + r"):([a-z0-9_]+(?::[a-z0-9_]+)*)\}"
)

#: What a frontend renders a token with: the kind and its arguments
#: in, the text out -- or `None` to leave the token as it stands.
Resolver = Callable[[str, tuple[str, ...]], Optional[str]]


def team(value: Team) -> str:
    """The mark of a team -- its ring on Discord, "🟣" before the
    upload lands."""
    return f"{{team:{Team(value).value}}}"


def role(player_role: PlayerRole, value: Optional[Team] = None) -> str:
    """
    The badge after a player's name, in the colour of the team the
    card is being fielded as where one is given -- the plain cut
    otherwise, for the one line that must not take a side (an own
    goal under the side it counted for; see
    `formatting.format_goal_scorer`). Discord shows `[FB]` for a
    badge it has no upload of.
    """
    role_value = PlayerRole(player_role).value
    if value is None:
        return f"{{role:{role_value}}}"
    return f"{{role:{role_value}:{Team(value).value}}}"


def condition(name: str) -> str:
    """An exhaustion or drain token, or one of the four condition
    marks."""
    if name not in CONDITIONS:
        raise ValueError(f"not a condition mark: {name!r}")
    return f"{{condition:{name}}}"


def species(value: str) -> str:
    """The mark of a species ability, at the head of its banner."""
    return f"{{species:{value}}}"


def coach(player_number: int) -> str:
    """
    The coach a sentence addresses -- a mention on Discord, where
    the account is a person's, and the AI's name where it is the
    AI's. A sentence that *names* a coach rather than addressing
    them uses `formatting.coach_name`, which is plain text.
    """
    if player_number not in (1, 2):
        raise ValueError(f"not a player number: {player_number!r}")
    return f"{{coach:{player_number}}}"


def render(text: str, resolve: Resolver) -> str:
    """
    Every token in `text`, replaced by what `resolve` says it shows
    as. A token the resolver answers `None` for is left in place.
    """
    def substitute(found: re.Match) -> str:
        kind = found.group(1)
        arguments = tuple(found.group(2).split(":"))
        rendered = resolve(kind, arguments)
        return found.group(0) if rendered is None else rendered

    return TOKEN_PATTERN.sub(substitute, text)


def find(text: str) -> list[tuple[str, tuple[str, ...]]]:
    """The tokens in `text`, in order -- for a test that asks what a
    sentence names, or that none were left unrendered."""
    return [
        (found.group(1), tuple(found.group(2).split(":")))
        for found in TOKEN_PATTERN.finditer(text)
    ]

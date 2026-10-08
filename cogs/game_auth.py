"""
Who may act on a game, and posting a game's next prompt: shared by both
bots (docs/codex-bot.md, decision 2).

Moved out of `cogs/d12ball_helpers.py`, which re-exports every name, so
nothing under cogs/d12ball* changed for it. The predicates read only the
record's seat fields -- `player_1_id`, `player_2_id` -- which
`d12ball.game.D12BallGame` and `codex.game.CodexGame` spell alike, so
one gate serves both (docs/design/permissions.md;
docs/design/codex.md, "Who may act, shared").
"""

from typing import Optional, Protocol

import discord


class GameRecord(Protocol):
    """What the gates read off a game record, D12 Ball's or Codex's."""

    player_1_id: Optional[int]
    player_2_id: Optional[int]


# --- Who may act on a game -------------------------------------------
#
# Every gate in the flow -- a lobby setting, a roll button, a maneuver
# pick, a coaching menu -- comes through one of the three predicates
# below, so "who may press this" is answered in one place rather than at
# the eighty-odd sites that ask it.
#
# The rule is: **the coach it belongs to, or a game helper.** A game
# helper is anyone the server trusts with `manage_channels` -- the same
# permission `/d12ball resume`, `/d12ball abandon_game` and the
# full-time Archive button were already gated on, and the same one
# `/debug reset_channels` uses. It is the permission a playtest
# organiser has and an ordinary coach does not, which is exactly the
# line wanted here: somebody helping a new player into a game can flip
# Tutorial on in their lobby, press the buttons they are stuck on, and
# start the game for them, without being a player in it.
#
# There is deliberately no second gate anywhere. A check written at a
# call site is a check that drifts from this one, which is how the
# lobby came to refuse a helper the tutorial toggle while letting them
# abandon the whole game with a slash command.


def game_participant_ids(game: GameRecord) -> set[int]:
    """
    The Discord ids of the game's coaches -- never the AI, which has no
    user id to be. A test game has both sides set to the same person, so
    this is a one-element set for it.
    """
    return {
        coach_id
        for coach_id in (game.player_1_id, game.player_2_id)
        if coach_id is not None
    }


def is_game_helper(user) -> bool:
    """
    Whether this person may act on a game they are not playing in:
    anyone the server trusts with `manage_channels`.

    Read off `guild_permissions`, so a `discord.User` (a DM, or a member
    Discord handed us uncached) answers False rather than raising -- the
    same tolerant shape every other optional lookup in this file has.
    Deliberately a permission and not a role: a role would have to be
    created per server and found by name, where every server already
    has somebody holding this.

    **`is True`, not a truthiness test**, and that is about the suite
    rather than about Discord: a permission is a bool, and nearly every
    person in `tests/` is a `MagicMock(spec=discord.Member)`, whose
    `guild_permissions.manage_channels` is a Mock and therefore truthy.
    Under a plain `bool(...)` every mocked click in the game would read
    as a helper's, which turns every gate in this file into a no-op and
    does it silently -- the tests still pass, because a gate that lets
    everyone through refuses nobody. A test that means to grant this
    says so, with `SimpleNamespace(manage_channels=True)`.
    """
    permissions = getattr(user, "guild_permissions", None)
    return getattr(permissions, "manage_channels", False) is True


def may_act_for_coach(user, coach_id: Optional[int]) -> bool:
    """
    Whether this person may press a button that belongs to the coach
    `coach_id` -- that coach, or a game helper.

    `coach_id` is None for a side the AI is playing, and a helper may
    act there too: nothing ever puts a prompt to Dinky, so the only way
    to reach one is a game that has gone wrong, which is precisely when
    somebody has to be able to answer it. A coach who is not a helper
    still matches on their own id alone, so this is exactly the old
    check for everybody it was already about.
    """
    return user.id == coach_id or is_game_helper(user)


def may_act_in_game(user, game: GameRecord) -> bool:
    """
    Whether this person may press a button either coach may press -- a
    roll, the maneuver reference -- which is either coach, or a game
    helper. See "Every roll is a coach's" in docs/design/maneuvers.md.
    """
    return user.id in game_participant_ids(game) or is_game_helper(user)


# The key on `Interaction.extras` that says a helper's click has been
# confirmed. Set by `HelperConfirmationView.confirm` on the click that
# answers the confirmation, before it re-runs the button that asked
# for it -- so the gate that raised the first time reads it and lets
# the same click through. It is on the interaction rather than on the
# match or the view because it is a fact about *this click* and
# nothing else: the next click the helper makes for somebody else is
# asked again.
HELPER_CONFIRMED_EXTRA = "d12ball_helper_confirmed"


def helper_click_confirmed(interaction) -> bool:
    """Whether this click already carries a helper's confirmation."""
    extras = getattr(interaction, "extras", None)
    return bool(extras) and extras.get(HELPER_CONFIRMED_EXTRA) is True


class HelperConfirmationRequired(Exception):
    """
    Raised by `SafeView.may_act_for` and `SafeView.may_act_in_game`
    when the click is a game helper's, is for somebody other than
    themselves, and has not been confirmed -- see "Who may act on a
    game" in docs/design/permissions.md.

    It is an exception rather than a third return value because the
    gates are called from fifty-odd callbacks as `if not
    self.may_act_for(...)`, every one of which has yet to respond or
    change anything when it asks. Raising lets the click leave the
    callback untouched and reach `SafeView.on_error`, which is the one
    place that knows the button it came from and can put the
    confirmation up in its place. `coach_ids` is who the click would
    act for -- one coach, or both for a button either may press -- and
    is only ever used to word the confirmation.
    """

    def __init__(self, coach_ids: tuple[Optional[int], ...]):
        super().__init__(
            "A game helper's click for somebody else needs confirming."
        )
        self.coach_ids = coach_ids


async def send_new_prompt(
    interaction: discord.Interaction,
    content: Optional[str] = None,
    *,
    file: Optional[discord.File] = None,
    view: Optional[discord.ui.View] = None,
    allowed_mentions: Optional[discord.AllowedMentions] = None,
) -> discord.Message:
    """
    Post a new, public message for this game -- a fresh prompt or
    announcement that is not itself the answer to a coach's ephemeral
    click (see `send_error_fallback` for that).

    `interaction.followup.send` ties whatever it posts into the same
    interaction as the response that came before it, and Discord's
    client shows that by quoting the earlier one in a "replying to"
    strip above the new message. That is right for the message that
    genuinely *is* this click's own answer -- the one response Discord
    lets an interaction give -- and wrong for everything a cascade goes
    on to post afterwards, which has nothing to do with the click that
    started it and reads as clutter wearing a reply it doesn't need.
    So this answers the interaction itself only while it still has an
    answer to give, and posts a plain, unreferenced channel message
    once it doesn't -- the same `is_done()` read `send_error_fallback`
    already makes, for the opposite reason: that one always answers
    ephemerally and only picks the route; this one changes the message
    itself, because a plain channel post can't be ephemeral.
    """
    args = () if content is None else (content,)
    kwargs: dict = {}
    if file is not None:
        kwargs["file"] = file
    if view is not None:
        kwargs["view"] = view
    if allowed_mentions is not None:
        kwargs["allowed_mentions"] = allowed_mentions

    if interaction.response.is_done():
        return await interaction.channel.send(*args, **kwargs)

    await interaction.response.send_message(*args, **kwargs)
    return await interaction.original_response()

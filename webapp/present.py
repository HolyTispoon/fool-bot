"""
What a web page is handed: the position in words and controls.

This is the web frontend's half of what `D12Ball.present` is on
Discord -- ARCHITECTURE.md, part 4. It renders; it decides nothing.
Every control it builds comes off `PendingPrompt.options` and nothing
else, which is the rule a Discord view is held to as well (CLAUDE.md,
"A view builds its buttons from `PendingPrompt.options` and nothing
else"): a candidate list, a distance or a hand worked out here would
be a second reading the driver cannot see, and the moment the web app
has a rule of its own the whole exercise has failed (principle 10).

Three things it does that Discord does differently, and each is a
frontend's to decide (principle 8):

- **The tokens are rendered here**, at this frontend's door, the way
  the cog renders them at its own (`D12Ball.rendered`). A team is a
  coloured dot, a role a badge, a coach their name --
  `d12ball/tokens.py` says which thing is named and nothing about how
  it is drawn.
- **A control is a button or a chooser**, not a `discord.ui.Item`: the
  page collects what a chooser's fields say and posts one `Action`,
  where Discord walks a coach through a menu at a time. The hub is the
  one prompt where that shows.
- **What a coach may not see is not sent.** A maneuver pick and a
  shootout order are secret (the model says so in the ask itself), so
  the rows for a side this viewer does not coach are left out of the
  payload rather than greyed in the page. A frontend that sends a
  secret and hides it in CSS has published it.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from d12ball import tokens
from d12ball.components import MatchState, PlayerRole, TeamSide
from d12ball.engine import RulesEngine
from d12ball.formatting import (
    coach_name,
    role_brackets,
    space_label,
    travel_space_label,
)
from d12ball.game import D12BallGame, Formation, Team, team_display_name
from d12ball.prompts import PendingPrompt, PromptKind, asked_sides
from d12ball.render import TEAM_COLORS


#: What the page calls each of a turn's three actions, and each of the
#: answers a decision prompt offers. The model's own wording is in the
#: ask above the buttons; these are the buttons.
CHOICE_LABELS: Mapping[str, str] = {
    "shoot": "Take a shot",
    "maneuver": "Maneuver",
    "time_out": "Call a time out",
    "take": "Take it",
    "decline": "Pass",
    "declare": "Coach",

    "roll": "Roll",
    "back": "Back",
    "done": "Done",
}

#: How this frontend draws the six condition marks. Discord fetches
#: an application emoji for each and falls back to one of these when
#: the upload has not landed (`CONDITION_EMOJI_FALLBACKS`); a page has
#: no upload to wait for, so the fallback is what it draws. They are
#: the same characters on purpose -- a coach reading both should be
#: reading the same game -- and they are a frontend's choice, not a
#: constant the model shares.
CONDITION_MARKS: Mapping[str, str] = {
    tokens.CONDITION_EXHAUST: "😮‍💨",
    tokens.CONDITION_EXHAUSTED: "🥵",
    tokens.CONDITION_INJURED: "🤕",
    tokens.CONDITION_DRAIN: "⚡",
    tokens.CONDITION_DRAINED: "🪫",
    tokens.CONDITION_DAMAGED: "💥",
}

#: What a tutorial beat says about the buttons it has railed off. The
#: refusal itself is the driver's (`_rail`); this is the page greying
#: the rest, which is what the Discord views do with the same reading.
RAILED_NOTE = "The tutorial is on one step of a single game."


@dataclass(frozen=True)
class Viewer:
    """
    Who is reading the page: one of the two coaches, or nobody.

    A spectator sees the board, the score and what has been said; they
    answer nothing and are sent no side's secrets.
    """

    player_number: Optional[int] = None

    @property
    def is_coach(self) -> bool:
        return self.player_number in (1, 2)


def render_text(game: D12BallGame, text: str) -> str:
    """
    One of the model's sentences, as HTML for the page.

    Three passes, and the order is the whole of what makes it safe:
    **escape**, so nothing a name or a game's title carries can be
    markup; **the model's markdown**, which only ever adds tags around
    text that has already been escaped; then **the tokens**, whose
    spelling (`{team:purple}`) survives both untouched and whose
    rendering is the only other HTML on the page. Rendering tokens
    first would put markup in front of the escape, and running the
    markdown after them would read an emitted attribute as emphasis.
    """
    return tokens.render(_markdown(html.escape(text)), _resolver(game))


#: The model's sentences are written in the markdown a coach reads in
#: a Discord message -- a headline at `##`, a card or a name in bold,
#: an aside in italics. That is the model's voice rather than a
#: medium (principle 5), so **both** frontends render it: Discord's
#: client does it for the bot, and this does it here. The subset is
#: what the narration actually uses; anything else is left as the
#: characters it is.
BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
ITALIC = re.compile(r"(?<![*\w])\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\*)")
HEADLINE = re.compile(r"^(#{2,3})\s+(.*)$", re.M)


def _markdown(escaped: str) -> str:
    """The narration's own markup, over text that is already escaped."""
    text = HEADLINE.sub(r'<span class="headline">\2</span>', escaped)
    text = BOLD.sub(r"<strong>\1</strong>", text)
    return ITALIC.sub(r"<em>\1</em>", text)


def _resolver(game: D12BallGame) -> tokens.Resolver:
    """How this frontend draws what a sentence names."""

    def resolve(kind: str, arguments: tuple[str, ...]) -> Optional[str]:
        if kind == "team":
            return _team_mark(arguments[0])
        if kind == "role":
            role = PlayerRole(arguments[0])
            team = arguments[1] if len(arguments) > 1 else None
            return (
                f'<span class="badge{_team_class(team)}">'
                f"{html.escape(role_brackets(role))}</span>"
            )
        if kind == "condition":
            mark = CONDITION_MARKS.get(arguments[0])
            if mark is None:
                return None
            return (
                f'<span class="mark" title="{arguments[0]}">{mark}</span>'
            )
        if kind == "species":
            return (
                '<span class="mark species">'
                f"{html.escape(arguments[0].replace('_', ' ').title())}</span>"
            )
        if kind == "coach":
            return (
                '<span class="coach">'
                f"{html.escape(coach_name(game, int(arguments[0])))}</span>"
            )
        return None

    return resolve


def _team_mark(value: str) -> str:
    """A team's ring, in the one colour `render.py` draws it in."""
    colour = TEAM_COLORS[Team(value)]
    return (
        f'<span class="ring" style="background:{colour}" '
        f'title="{html.escape(team_display_name(Team(value)))}"></span>'
    )


def _team_class(team: Optional[str]) -> str:
    return f" {team}" if team else ""


# -- Controls --------------------------------------------------------
#
# A button answers a prompt on its own; a chooser is a button whose
# arguments the page collects first, for the one prompt whose answer
# takes two of them at once. Both carry the whole `Action`, so the
# page sends back exactly what it was offered and nothing it made up
# -- see `webapp/server.py`, which refuses anything else.


def button(
    label: str,
    kind: PromptKind,
    choice: str = "",
    *,
    disabled: bool = False,
    note: str = "",
    **arguments: Any,
) -> dict:
    return {
        "type": "button",
        "label": label,
        "disabled": disabled,
        "note": note,
        "action": {
            "kind": kind.value,
            "choice": choice,
            "arguments": _arguments(arguments),
        },
    }


def chooser(
    label: str,
    submit: str,
    fields: Sequence[dict],
    kind: PromptKind,
    choice: str = "",
    **arguments: Any,
) -> dict:
    """
    `label` is the sentence in front of the fields and `submit` is
    what the button says -- two, because the sentence is usually a
    half one ("Hellguard [FB] changes zone with") and a button is a
    verb.
    """
    return {
        "type": "chooser",
        "label": label,
        "submit": submit,
        "fields": list(fields),
        "action": {
            "kind": kind.value,
            "choice": choice,
            "arguments": _arguments(arguments),
        },
    }


def field(name: str, label: str, choices: Sequence[tuple[str, str]]) -> dict:
    """
    One thing a chooser collects. `label` is empty where the
    chooser's own sentence already names it ("Hellguard [FB] changes
    zone with"), which is most of them -- a word in front of the menu
    there would be the sentence said twice.
    """
    return {
        "name": name,
        "label": label,
        "choices": [{"value": value, "label": text} for value, text in choices],
    }


def _arguments(arguments: Mapping[str, Any]) -> dict:
    return {
        name: value.value if isinstance(value, (TeamSide, Formation)) else value
        for name, value in arguments.items()
        if value is not None
    }


def section(label: Optional[str], controls: Sequence[dict]) -> Optional[dict]:
    """A group of controls under a heading, or nothing where the group
    is empty -- an empty menu is not a menu."""
    controls = [control for control in controls if control is not None]
    if not controls:
        return None
    return {"label": label, "controls": controls}


@dataclass(frozen=True)
class Asked:
    """One prompt, for the one viewer the controls are being built
    for."""

    engine: RulesEngine
    game: D12BallGame
    match: MatchState
    prompt: PendingPrompt
    viewer: Viewer

    @property
    def options(self):
        return self.prompt.options

    @property
    def kind(self) -> PromptKind:
        return self.prompt.kind

    def sides(self) -> tuple[TeamSide, ...]:
        """The sides this viewer coaches."""
        if not self.viewer.is_coach:
            return ()
        return tuple(
            side
            for side in (TeamSide.HOME, TeamSide.VISITING)
            if self.engine.side_player_number(self.game, side)
            == self.viewer.player_number
        )

    def label(self, player_id: str) -> str:
        """
        A player named the way every player in this game is named --
        the engine's one spelling, so a control reads exactly as the
        Discord button beside it does ("Hellguard [FB]"). See "Naming
        a player" in docs/design/naming-and-wording.md.
        """
        return self.engine.format_roster_player(player_id)

    def players(
        self, player_ids: Sequence[str], kind: PromptKind, **arguments: Any
    ) -> list[dict]:
        return [
            button(self.label(player_id), kind, player_id=player_id, **arguments)
            for player_id in player_ids
        ]


def may_answer(asked: Asked) -> bool:
    """
    Whether this viewer is one the prompt is put to -- the web app's
    half of `SafeView.may_act_for`, off the same reading the service
    answers an AI side by (`d12ball.prompts.asked_sides`).

    A prompt nobody in particular is asked -- every roll, the
    tutorial's Continue -- is either coach's to press, which is what
    "nothing rolls dice on its own" means from this side: the button
    is there for both of them and neither is being asked a question.
    A spectator answers nothing.
    """
    if not asked.viewer.is_coach:
        return False
    sides = asked_sides(asked.match, asked.prompt)
    if not sides:
        return True
    return bool(set(sides) & set(asked.sides()))


def controls_for(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: Optional[PendingPrompt],
    viewer: Viewer,
) -> list[dict]:
    """
    What this viewer may press, as sections of controls -- empty where
    the question is somebody else's, or where there is no question.
    """
    if prompt is None:
        return []
    asked = Asked(engine, game, match, prompt, viewer)
    if not may_answer(asked):
        return []
    build = CONTROLS.get(prompt.kind)
    if build is None:
        return []
    return [group for group in build(asked) if group is not None]


def _continue(asked: Asked) -> list:
    return [section(None, [button("Continue", asked.kind)])]


def _turn(asked: Asked) -> list:
    options = asked.options
    return [
        section(
            None,
            [
                button(
                    CHOICE_LABELS[action],
                    asked.kind,
                    action,
                    disabled=action not in options.live,
                    note=RAILED_NOTE if action not in options.live else "",
                )
                for action in options.actions
            ],
        )
    ]


def _roll(asked: Asked) -> list:
    options = asked.options
    controls = [button(CHOICE_LABELS["roll"], asked.kind, "roll")]
    if options.back:

        controls.append(
            button(
                CHOICE_LABELS["back"],
                asked.kind,
                "back",
                disabled=options.back_railed,
                note=RAILED_NOTE if options.back_railed else "",
            )
        )
    overdrive = [
        button(
            f"Overdrive: {asked.label(player_id)} "
            f"(drain {options.overdrive_cost(player_id)})",
            asked.kind,
            "overdrive",
            player_id=player_id,
        )
        for player_id in options.overdrive_player_ids
    ] + [
        # Gearclaw's Boost (Law 21), on the same terms.
        button(
            f"Boost: {asked.label(player_id)}",
            asked.kind,
            "boost",
            player_id=player_id,
        )
        for player_id in options.boost_player_ids
    ]
    return [section(None, controls), section("Before the die", overdrive)]


def _decision(
    asked: Asked, labels: Optional[Mapping[str, str]] = None,
) -> list:
    """
    A prompt's yes and no. `labels` is what a kind calls its two
    answers where the generic `CHOICE_LABELS` are not enough -- a
    Smooth names both players, since which of the two ends up with
    the ball is the whole question.
    """
    options = asked.options
    labels = labels or {}
    return [
        section(
            None,
            [
                button(
                    labels.get(choice)
                    or CHOICE_LABELS.get(
                        choice, choice.replace("_", " ").title()
                    ),
                    asked.kind,
                    choice,
                    disabled=(
                        options.railed is not None and choice != options.railed
                    ),
                    note=(
                        RAILED_NOTE
                        if options.railed is not None
                        and choice != options.railed
                        else ""
                    ),
                    **_decision_arguments(asked, choice),
                )
                for choice in options.choices
            ],
        )
    ]


def _smooth(asked: Asked) -> list:
    """
    The Smooth's two buttons, each naming its player: the Telekinetic
    who takes the ball over, and -- where declining leaves somebody
    holding it -- the player it stays with
    (`SmoothOptions.keeper_id`). The page says what the Discord
    buttons say, off the same one list.
    """
    keeper_id = asked.options.keeper_id
    return _decision(asked, {
        "take": f"{asked.label(asked.prompt.player_id)} takes it over",
        "decline": (
            f"{asked.label(keeper_id)} keeps the ball" if keeper_id else ""
        ),
    })


def _decision_arguments(asked: Asked, choice: str) -> dict:
    """The two decisions whose answer names who is answering."""
    if asked.kind is PromptKind.COACHING_OFFER:
        return {"side": asked.prompt.side}

    if asked.kind in (PromptKind.MIND_PULL, PromptKind.SMOOTH):
        return {"player_id": asked.prompt.player_id}
    return {}


def _players(asked: Asked) -> list:
    return [section(None, asked.players(asked.options.player_ids, asked.kind))]


def _shooter(asked: Asked) -> list:
    return [
        section(
            None,
            [
                button(asked.label(player_id), asked.kind, shooter_id=player_id)
                for player_id in asked.options.player_ids
            ],
        )
    ]


def _halftime_token(asked: Asked) -> list:
    return [
        section(
            None,
            asked.players(
                asked.options.player_ids, asked.kind, side=asked.prompt.side,
            ),
        )
    ]


def _send(asked: Asked) -> list:
    """The challenger and the loose ball: somebody, or nobody."""
    options = asked.options
    extra = (
        {"skill_type": asked.prompt.skill_type}
        if asked.kind is PromptKind.LOOSE_BALL_PICK
        else {}
    )
    decline = (
        button(
            "Send nobody",
            asked.kind,
            "decline",
            disabled=options.decline_railed,
            note=RAILED_NOTE if options.decline_railed else "",
            **extra,
        )
        if options.may_decline
        else None
    )
    return [
        section(
            None,
            [
                button(
                    asked.label(player_id),
                    asked.kind,
                    "send",
                    player_id=player_id,
                    **extra,
                )
                for player_id in options.player_ids
            ],
        ),
        section(None, [decline] if decline else []),
    ]


def _run_back_space(asked: Asked) -> list:
    """
    Where the player the prompt named runs back to. The distance is on
    the label because it is the price -- a token a space, the same
    reading the Discord button puts there (`travel_space_label`).
    """
    options = asked.options
    return [
        section(
            None,
            [
                button(
                    travel_space_label(
                        options.zone,
                        space_index,
                        distance,
                        asked.match.board,
                    ),
                    asked.kind,
                    space_index=space_index,
                )
                for space_index, distance in zip(
                    options.space_indices, options.distances,
                )
            ],
        )
    ]



def _distance(asked: Asked) -> list:
    """Every prompt that asks how far, and the push back a beaten
    Setup Pass owes."""
    options = asked.options
    distances = [
        button(
            _spaces(distance),
            asked.kind,
            distance=distance,
            disabled=options.railed is not None and distance != options.railed,
            note=(
                RAILED_NOTE
                if options.railed is not None and distance != options.railed
                else ""
            ),
        )
        for distance in options.distances
    ]
    if options.may_pass_out:
        # A Setup Pass with nowhere to go is the card's one way out of
        # play, and it is the absence of a distance rather than a
        # choice -- the driver reads it the same way.
        distances = [button("Put it out of play", asked.kind)]

    # Quantor running onto the pass (Law 21): the same distances, with
    # the run declared beside them.
    runs = [
        button(
            f"{_spaces(distance)}, {asked.label(options.runner_id)} "
            "runs onto it (drain 3)",
            asked.kind,
            distance=distance,
            runner=True,
        )
        for distance in options.runner_distances
    ]
    return [section(None, distances), section("Run onto the pass", runs)]


def _spaces(distance: int) -> str:
    return "Same space" if distance == 0 else (
        f"{distance} space" if distance == 1 else f"{distance} spaces"
    )


def _low_pass(asked: Asked) -> list:
    """
    One control per distance, and a chooser where several teammates
    share the landing space -- which is the second question the
    adapter takes beside the distance.
    """
    controls = []
    for option in asked.options.passes:
        if len(option.receiver_ids) > 1:
            controls.append(
                chooser(
                    f"{_spaces(option.distance)} -- who receives it?",
                    "Pass",
                    [
                        field(
                            "receiver_id",
                            "",
                            [
                                (player_id, asked.label(player_id))
                                for player_id in option.receiver_ids
                            ],
                        )
                    ],
                    asked.kind,
                    distance=option.distance,
                )
            )
            continue
        receiver = (
            f" - {asked.label(option.receiver_ids[0])}"
            if option.receiver_ids
            else ""
        )
        controls.append(
            button(
                f"{_spaces(option.distance)}{receiver}",
                asked.kind,
                distance=option.distance,
            )
        )
    return [section(None, controls)]


def _speed(asked: Asked) -> list:
    options = asked.options
    return [
        section(
            None,
            [
                button(
                    f"Ball speed {target}",
                    asked.kind,
                    target_speed=target,
                    disabled=(
                        options.railed is not None and target != options.railed
                    ),
                    note=(
                        RAILED_NOTE
                        if options.railed is not None
                        and target != options.railed
                        else ""
                    ),
                )
                for target in options.targets
            ],
        )
    ]


def _maneuver(asked: Asked) -> list:
    """
    **One row, and it is this coach's own.** The pick is secret until
    both are in, so the other side's hand is not in what this viewer
    is sent -- see the module docstring.
    """
    mine = set(asked.sides())
    controls = []
    for hand in asked.options.hands:
        if hand.team_side not in mine or hand.picked:
            continue

        controls.extend(
            button(
                asked.engine.maneuver_name(key),
                asked.kind,
                side=hand.side,
                maneuver_key=key,
                disabled=hand.railed is not None and key != hand.railed,
                note=(
                    RAILED_NOTE
                    if hand.railed is not None and key != hand.railed
                    else ""
                ),
            )
            for key in hand.maneuver_keys
        )
    return [section("Your hand", controls)]


def _shootout_order(asked: Asked) -> list:
    mine = set(asked.sides())
    controls: list[dict] = []
    for entry in asked.options.sides:
        if TeamSide(entry.side) not in mine:
            continue
        controls.extend(
            button(
                asked.label(player_id),
                asked.kind,
                "send",
                side=entry.side,
                player_id=player_id,
            )
            for player_id in entry.player_ids
        )
        controls.append(
            button("Start again", asked.kind, "restart", side=entry.side)
        )
    return [section("Your order", controls)]


def _shootout_pick(asked: Asked) -> list:
    mine = set(asked.sides())
    controls: list[dict] = []
    for entry in asked.options.sides:
        if TeamSide(entry.side) not in mine:
            continue
        controls.extend(
            button(
                asked.label(player_id),
                asked.kind,
                side=entry.side,
                player_id=player_id,
            )
            for player_id in entry.player_ids
        )
    return [section("Your shooter", controls)]


def _coaching_hub(asked: Asked) -> list:
    """
    The Coaching Choice's four menus and its Done, on one page.

    Discord walks a coach through a menu at a time because a message
    holds twenty-five buttons; a page has room for all four, so the
    two that take a pair of names are choosers rather than two steps.
    Everything offered is the options', including why Done may be
    refused (`finish_refusal`, the kickoff space a side must cover).
    """
    options = asked.options
    side = asked.prompt.side
    return [

        section(
            "Formation",
            [
                button(
                    formation.value,
                    asked.kind,
                    "formation",
                    side=side,
                    formation=formation,
                    disabled=formation == options.current_formation,
                    note=(
                        "Where they stand now"
                        if formation == options.current_formation
                        else ""
                    ),
                )
                for formation in options.formations
            ],
        ),
        section(
            "Substitution",
            [
                chooser(
                    "",
                    "Substitute",
                    [
                        field(
                            "outgoing_player_id",
                            "Off",
                            [
                                (player_id, asked.label(player_id))
                                for player_id in options.outgoing_ids
                            ],
                        ),
                        field(
                            "incoming_player_id",
                            "On",
                            [
                                (player_id, asked.label(player_id))
                                for player_id in options.incoming_ids
                            ],
                        ),
                    ],
                    asked.kind,
                    "substitute",
                    side=side,
                )
            ]
            if options.may_substitute
            and options.outgoing_ids
            and options.incoming_ids
            else [],
        ),
        section(
            "Change zones",
            [
                chooser(
                    f"{asked.label(swap.player_id)} changes zone with",
                    "Swap",
                    [
                        field(
                            "other_player_id",
                            "",
                            [
                                (player_id, asked.label(player_id))
                                for player_id in swap.partner_ids
                            ],
                        )
                    ],
                    asked.kind,
                    "swap",
                    side=side,
                    player_id=swap.player_id,
                )
                for swap in options.swaps
            ],
        ),
        section("Move within a zone", _repositions(asked)),

        section(
            None,
            [
                button(
                    CHOICE_LABELS["done"],
                    asked.kind,
                    "done",
                    side=side,
                    disabled=options.finish_refusal is not None,
                    note=options.finish_refusal or "",
                )
            ],
        ),
    ]


def _repositions(asked: Asked) -> list[dict]:

    """
    A meeple moved inside its own zone -- and, where more than one
    teammate is standing on the space it is moving to, which of them
    comes back to keep the zone covered. One is no choice and the
    driver takes it; several is the second question, as a chooser.
    """
    side = asked.prompt.side
    controls: list[dict] = []
    for entry in asked.options.repositions:
        for space in entry.spaces:
            label = (
                f"{asked.label(entry.player_id)} to "
                f"{space_label(entry.zone, space.space_index, asked.match.board)}"
            )

            if len(space.trade_with) > 1:
                controls.append(
                    chooser(
                        f"{label} -- who comes back?",
                        "Move",
                        [
                            field(
                                "swap_with",
                                "",
                                [
                                    (player_id, asked.label(player_id))
                                    for player_id in space.trade_with
                                ],
                            )
                        ],
                        asked.kind,
                        "reposition",
                        side=side,
                        player_id=entry.player_id,
                        space_index=space.space_index,
                    )
                )
                continue
            controls.append(
                button(
                    label,
                    asked.kind,
                    "reposition",
                    side=side,
                    player_id=entry.player_id,
                    space_index=space.space_index,
                    note=(
                        f"{asked.label(space.trade_with[0])} comes back"
                        if space.trade_with
                        else ""
                    ),
                )
            )
    return controls


#: One builder per `PromptKind`, the way `PLAIN_PROMPT_VIEWS` and
#: `view_for_prompt` are the cog's one mapping from a kind to what it
#: puts up. A kind with no row here is a prompt this frontend cannot
#: offer, and `tests/test_web_app.py` asserts there is none --
#: `GAME_OVER` aside, which asks nothing (the rematch under it opens a
#: new game, which is not an action on this one).
CONTROLS: Mapping[PromptKind, Callable[[Asked], list]] = {
    PromptKind.TUTORIAL_CONTINUE: _continue,
    PromptKind.PLAYER_ACTION: _turn,
    PromptKind.SKILL_TEST: _roll,
    PromptKind.LOOSE_BALL_SKILL_TEST: _roll,
    PromptKind.SCORE_ATTEMPT: _roll,
    PromptKind.SHOOTOUT_TEST: _roll,
    PromptKind.INJURY_TEST: _roll,
    PromptKind.OWN_GOAL_ROLL: _roll,
    PromptKind.MIND_PULL: _decision,
    PromptKind.SMOOTH: _smooth,
    PromptKind.SET_UP_ATTEMPT: _decision,
    PromptKind.COACHING_OFFER: _decision,
    PromptKind.BALL_HANDLER_SELECTION: _players,
    PromptKind.RUN_BACK_PLAYER: _players,
    PromptKind.BALL_RECOVERY: _players,
    PromptKind.SHOOTER_CHOICE: _shooter,
    PromptKind.HALFTIME_EXTRA_TOKEN: _halftime_token,
    PromptKind.MANEUVER_CHALLENGE: _send,
    PromptKind.LOOSE_BALL_PICK: _send,
    PromptKind.RUN_BACK_SPACE: _run_back_space,
    PromptKind.HIGH_PASS_CHOICE: _distance,
    PromptKind.SETUP_PASS_CHOICE: _distance,
    PromptKind.SETUP_PASS_PUSH_BACK: _distance,
    PromptKind.DRIBBLE_ADVANCE_CHOICE: _distance,
    PromptKind.DRIBBLE_BURST_CHOICE: _distance,
    PromptKind.LOW_PASS_CHOICE: _low_pass,
    PromptKind.SPEED_DELTA_CHOICE: _speed,
    PromptKind.MANEUVER_ACTION: _maneuver,
    PromptKind.SHOOTOUT_ORDER: _shootout_order,
    PromptKind.SHOOTOUT_PICK: _shootout_pick,
    PromptKind.COACHING_HUB: _coaching_hub,
}

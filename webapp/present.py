"""
What a web page is handed: the position in words and controls.

This is the web frontend's half of what `D12Ball.present` is on
Discord -- ARCHITECTURE.md, part 4. It renders; it decides nothing.
Every control it builds comes off `PendingPrompt.options` and nothing
else -- **read as the wire writes it**, `prompt.to_dict()`, so the one
format a frontend is handed has a consumer and `tests/test_wire_shapes.py`
is testing something read (decision 3 of docs/web-app-next.md) --
which is the rule a Discord view is held to as well (CLAUDE.md,
"A view builds its buttons from `PendingPrompt.options` and nothing
else"): a candidate list, a distance or a hand worked out here would
be a second reading the driver cannot see, and the moment the web app
has a rule of its own the whole exercise has failed (principle 10).

Three things it does that Discord does differently, and each is a
frontend's to decide (principle 8):

- **The tokens are rendered here**, at this frontend's door, the way
  the cog renders them at its own (`D12Ball.rendered`), and with the
  same pictures: a team is its team emoji, a role the badge edged in
  the team's colour, a condition its mark, a coach their name --
  `d12ball/tokens.py` says which thing is named and nothing about how
  it is drawn.
- **The answer is the thing on the board.** A control names the
  object it lights -- a meeple, a space, the ball, a goal, the die,
  the whistle, a time-out tile, a card -- as its `place`, with a chip
  saying what clicking it means, and carries no colour; where nothing
  on the board can be the answer it is the one neutral outlined
  control (`NEUTRAL`). Discord colours its buttons; a page lights the
  object in gold.
- **A control is a button or a chooser**, not a `discord.ui.Item`: the
  page collects what a chooser's fields say and posts one `Action`,
  where Discord walks a coach through a menu at a time. The Coaching
  Choice is where that shows most: each move is one control made of
  two things on the board, the one picked up (`first`) and the one it
  is put on (`place`), so the pair is the page's way of choosing a
  control the options listed, never a move of its own.
- **A prompt carries its situation** where the cog posts a matchup
  with the same question (`SITUATIONS`) -- the shot and the challenge
  -- as the brief's words and the players' portraits for the page to
  lay out, where the cog posts a PNG. The kind is the key.
- **What a coach may not see is not sent.** A maneuver pick and a
  shootout order are secret (the model says so in the ask itself), so
  the rows for a side this viewer does not coach are left out of the
  payload rather than greyed in the page. A frontend that sends a
  secret and hides it in CSS has published it.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping, Optional, Sequence

from d12ball import stats, tokens
from d12ball.components import (
    MANEUVER_TIER_GAMBIT,
    SPECIES_CYBORG,
    SPECIES_FIRE_DEMON,
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
)
from d12ball.engine import RulesEngine
from d12ball.formatting import (
    capitalized,
    coach_name,
    player_with_role,
    role_brackets,
    space_label,
    travel_space_label,
)
from d12ball.game import (
    COLOR_TEAMS,
    D12BallGame,
    Formation,
    Team,
    paired_team,
    team_display_name,
)
from d12ball.prompts import PendingPrompt, PromptKind, asked_sides
from d12ball.dice_brief import (
    challenge_side,
    maneuver_challenge_brief,
    score_attempt_brief,
)
from d12ball.flow.effects import OWN_GOAL_SAFE_TOTAL
from d12ball.personal_abilities import PersonalAbility
from d12ball.player_cards import species_ability
from d12ball.render import (
    CHALLENGE_BAND_FULL,
    CHALLENGE_BAND_HALF,
    CHALLENGE_TITLE,
    SCORE_ATTEMPT_TITLE,
    SCORE_ATTEMPT_UNDEFENDED,
    TEAM_COLORS,
    ChallengeSide,
    zone_labels,
)


#: What the page calls each of a turn's three actions, and each of the
#: answers a decision prompt offers. The model's own wording is in the
#: ask above the buttons; these are the buttons.
CHOICE_LABELS: Mapping[str, str] = {
    "shoot": "Shoot to score",
    "maneuver": "Maneuver",
    "time_out": "Time out",
    "take": "Take it",
    "decline": "Pass",
    "declare": "Coach",

    "roll": "Roll",
    "back": "Back",
    "done": "Done",
}

#: How this frontend draws the six condition marks: the PNGs the bot
#: uploads as its application emoji, by the name each is uploaded
#: under (`CONDITION_EMOJI_NAMES` in the cog). A coach reading both
#: should be reading the same game, so the page shows the pictures a
#: Discord message does rather than the characters it falls back to.
#: The one name that differs from its token is `drain`, whose upload
#: is named for the art it was made from.
CONDITION_EMOJI: Mapping[str, str] = {
    tokens.CONDITION_EXHAUST: "exhaust",
    tokens.CONDITION_EXHAUSTED: "exhausted",
    tokens.CONDITION_INJURED: "injured",
    tokens.CONDITION_DRAIN: "exhaust_cyborg",
    tokens.CONDITION_DRAINED: "drained",
    tokens.CONDITION_DAMAGED: "damaged",
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
#: A headline is a block of its own, so the line break that ends it is
#: part of it -- left behind, it would be an empty line under every
#: headline on a page that keeps the sentences' line breaks.
HEADLINE = re.compile(r"^(#{1,3})[ \t]+(.*)$\n?", re.M)


def _markdown(escaped: str) -> str:
    """The narration's own markup, over text that is already escaped.
    A headline keeps its level (`h1` to `h3`), as Discord draws `#`
    larger than `##`."""
    text = HEADLINE.sub(
        lambda found: (
            f'<span class="headline h{len(found.group(1))}">'
            f"{found.group(2)}</span>"
        ),
        escaped,
    )
    text = BOLD.sub(r"<strong>\1</strong>", text)
    return ITALIC.sub(r"<em>\1</em>", text)


def _resolver(game: D12BallGame) -> tokens.Resolver:
    """How this frontend draws what a sentence names: with the bot's
    own emoji, as a Discord message draws it."""

    def resolve(kind: str, arguments: tuple[str, ...]) -> Optional[str]:
        if kind == "team":
            team = Team(arguments[0])
            return emoji(f"team_{team.value}", team_display_name(team))
        if kind == "role":
            role = PlayerRole(arguments[0])
            team = Team(arguments[1]) if len(arguments) > 1 else None
            return emoji(
                role_emoji_name(role, team), role_brackets(role), "badge",
            )
        if kind == "condition":
            name = CONDITION_EMOJI.get(arguments[0])
            if name is None:
                return None
            return emoji(name, arguments[0].replace("_", " "))
        if kind == "species":
            name = arguments[0]
            return (
                f'<img class="emoji species" src="/species/{name}_color.png" '
                f'alt="" title="{html.escape(name.replace("_", " ").title())}">'
            )
        if kind == "coach":
            return (
                '<span class="coach">'
                f"{html.escape(coach_name(game, int(arguments[0])))}</span>"
            )
        return None

    return resolve


def emoji(name: str, said: str, css: str = "") -> str:
    """
    One of the bot's emoji, inline in a sentence. `said` is its alt
    text, which is what a copy of the sentence reads -- the role badge's
    is its brackets, the fallback a Discord message shows too.
    """
    said = html.escape(said)
    return (
        f'<img class="emoji{" " + css if css else ""}" '
        f'src="/emoji/{name}.png" alt="{said}" title="{said}">'
    )


def role_emoji_name(role: PlayerRole, team: Optional[Team]) -> str:
    """
    A role badge's upload: edged in the colour of the team the card is
    fielded as, where a sentence names one. A species team shares its
    colour team's hex, so it shares its badge too -- resolved here the
    way the cog's `ROLE_TEAM_EMOJI_NAMES` resolves it.
    """
    if team is None:
        return f"role_{role.value}"
    colour = team if team in COLOR_TEAMS else paired_team(team)
    return f"role_{role.value}_{colour.value}"


# -- Controls --------------------------------------------------------
#
# **The answer is the thing on the board** (step 4 of
# docs/web-app-redesign.md): a control names the object it lights -- a
# meeple, a space, the ball, a goal, the die, the whistle, a time-out
# tile, a card -- as its `place`, with the chip that says what clicking
# it means, and the page lights that object and attaches the click.
# Where nothing on the board can be the answer the control is the one
# neutral outlined style. **No control carries a colour**: the colour a
# Discord button has is Discord's, and the page's one colour for "this
# is yours to press" is the gold the object is lit in.
#
# A place says where on the page and never what is answered: the answer
# is `action`, and only `action` is checked against what was offered --
# see `webapp/server.py`, which refuses anything else. A chooser is a
# control whose arguments the page collects first (a pair of names on
# the hub, the receiver on a shared space), and carries the whole
# `Action` the same way.


#: The one style a control that names no object has: outlined, no
#: fill, no colour. Every other control has a `place` instead.
NEUTRAL = "neutral"


def button(
    label: str,
    kind: PromptKind,
    choice: str = "",
    *,
    place: Optional[dict] = None,
    also: Sequence[dict] = (),
    chip: str = "",
    cost: Optional[dict] = None,
    disabled: bool = False,
    note: str = "",
    player: Optional[str] = None,
    card: Optional[dict] = None,
    post: Optional[str] = None,
    first: Optional[dict] = None,
    first_chip: str = "",
    **arguments: Any,
) -> dict:
    """
    One answer. `place` is the object on the page it lights (the
    `ON_*` names and `on_*` builders below), or `None` for the neutral
    control; `also` is any further object the same answer lights -- a
    Set Up's shot is the goal *and* the shooter -- so clicking either
    sends it; `chip` is what clicking the lit object means, and `cost`
    what it charges, drawn as the token image and a count
    (`{"emoji", "count"}`), never the word "token". `label` is the
    control said in full, for the keyboard list and anywhere the
    object cannot be drawn. `player` is the card id a control names,
    so the page can show that player's card; `card` is the maneuver
    card a control plays (`{"key", "side"}`). None of them is part of
    the answer: what is sent back is `action`.

    `post` is a press that is not an answer to this game at all -- the
    rematch, which opens another -- and names the room route it goes
    to instead; `webapp/server.py` never takes one as an action.

    `first` makes it an answer given with two objects: the one picked
    up first -- a bench meeple coming on, a player changing zones or
    moving -- and then `place`, the one it is put on. The page lights
    every `first` -- with its `first_chip`, where it has one -- and
    once one is
    picked, the `place` of each control that starts from it; dragging
    the first onto the second is the same answer. It is still one
    control and one `Action`: the pair is the page's way of choosing
    it, never a move of its own.
    """
    return {
        "type": "button",
        "label": label,
        "disabled": disabled,
        "note": note,
        "place": place,
        "also": list(also) if place else [],
        "chip": chip or None,
        "cost": cost,
        "style": None if place else NEUTRAL,
        "player": player,
        "card": card,
        "post": post,
        "first": first if place else None,
        "first_chip": (first_chip or None) if place and first else None,
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
    *,
    place: Optional[dict] = None,
    chip: str = "",
    first: Optional[dict] = None,
    first_chip: str = "",
    **arguments: Any,
) -> dict:
    """
    `label` is the sentence in front of the fields and `submit` is
    what the button says -- two, because the sentence is usually a
    half one ("Hellguard [FB] changes zone with") and a button is a
    verb. A chooser with a `place` is opened by clicking that object,
    and asks its one field in the question box.
    """
    return {
        "type": "chooser",
        "label": label,
        "submit": submit,
        "fields": list(fields),
        "place": place,
        "chip": chip or None,
        "style": None if place else NEUTRAL,
        "first": first if place else None,
        "first_chip": (first_chip or None) if place and first else None,
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


def section(
    label: Optional[str], controls: Sequence[dict], how: str = "",
) -> Optional[dict]:
    """A group of controls under a heading, or nothing where the group
    is empty -- an empty menu is not a menu. `how` is how the page
    answers it, where that is not plain from the lit things (a drag, or
    two clicks) -- this frontend's words about its own controls."""
    controls = [control for control in controls if control is not None]
    if not controls:
        return None
    group = {"label": label, "controls": controls}
    if how:
        group["how"] = how
    return group


# -- The objects a control may light ---------------------------------
#
# Each names a thing the page already draws: the board's meeples and
# spaces (by the zone and index `webapp/board.py` hands every space),
# the ball, the goals (by the side that defends it, as the board draws
# them), the out-of-play mark on a goal zone, the time-out tiles on the
# jumbotron bar, and in the question box the die, the faces of a speed
# choice, the whistle, the note, the hand's cards and the rematch mark.

#: The ball, wherever it is drawn.
ON_BALL = {"at": "ball"}
#: The large die in the question box: clicking it rolls.
ON_DIE = {"at": "die"}
#: The whistle: Done, Start the game, Pick it up.
ON_WHISTLE = {"at": "whistle"}
#: The tutorial's note: clicking anywhere on it goes on.
ON_NOTE = {"at": "note"}
#: The REMATCH mark in the box.
ON_REMATCH = {"at": "rematch"}


def on_player(player_id: str) -> dict:
    return {"at": "player", "id": player_id}


def on_space(zone: Any, space_index: int) -> dict:
    return {"at": "space", "zone": Zone(zone).value, "space_index": space_index}


def on_goal(side: TeamSide) -> dict:
    """The goal `side` defends."""
    return {"at": "goal", "side": TeamSide(side).value}


def off_the_end(side: TeamSide) -> dict:
    """The ✕ on the goal zone `side` defends: out of play."""
    return {"at": "out_of_play", "side": TeamSide(side).value}


def on_tile(side: TeamSide) -> dict:
    return {"at": "time_out_tile", "side": TeamSide(side).value}


def on_face(value: int) -> dict:
    return {"at": "face", "value": value}


def on_card(key: str, side: str) -> dict:
    return {"at": "card", "key": key, "side": side}


def on_formation(formation: Any) -> dict:
    """A formation's tile in the question box: the Coaching Choice's
    shapes, drawn as dots per zone."""
    return {"at": "formation", "name": Formation(formation).value}


def on_bench(side: Any) -> dict:
    """A side's bench, under the board: the Coaching Offer's yes."""
    return {"at": "bench", "side": TeamSide(side).value}


@dataclass(frozen=True)
class Asked:
    """
    One prompt, for the one viewer the controls are being built for.

    `prompt` is the question **as the wire writes it**
    (`PendingPrompt.to_dict`), and every builder reads that and nothing
    else of it: a value is the wire's -- a side is `"home"`, a
    formation its name, a zone its value -- and becomes the model's
    own type only where a model function is asked about it (a space's
    label). What may be chosen is still the prompt's; this is only the
    one format both ends are written against.
    """

    engine: RulesEngine
    game: D12BallGame
    match: MatchState
    prompt: Mapping[str, Any]
    viewer: Viewer
    #: The sides the prompt is put to (`asked_sides`), for an object
    #: that belongs to one side -- the time-out tile, the goal a side
    #: shoots at.
    asked: tuple[TeamSide, ...] = ()

    @property
    def options(self) -> Mapping[str, Any]:
        return self.prompt["options"]

    @property
    def kind(self) -> PromptKind:
        return PromptKind(self.prompt["kind"])

    def sides(self) -> tuple[TeamSide, ...]:
        """The sides this viewer coaches."""
        return coached_sides(self.engine, self.game, self.viewer)

    def label(self, player_id: str) -> str:
        """
        A player named the way every player in this game is named --
        the engine's one spelling, so a control reads exactly as the
        Discord button beside it does ("Hellguard [FB]"). See "Naming
        a player" in docs/design/naming-and-wording.md.
        """
        return self.engine.format_roster_player(player_id)

    def cost(self, player_id: Optional[str], count: int) -> Optional[dict]:
        """
        A price in this player's own tokens, as the page draws it: the
        token image the bot draws on their card -- a Cyborg's drain
        under its own (`drain_wording`) -- and the count.
        """
        if not count or player_id is None:
            return None
        drain = self.engine.drain_wording(self.game, player_id)
        return {"emoji": "exhaust_cyborg" if drain else "exhaust", "count": count}

    def attacking_goal(self) -> TeamSide:
        """The goal the side on the ball shoots at: the other side's."""
        side = self.asked[0] if self.asked else TeamSide(
            self.match.ball.possession,
        )
        return TeamSide.VISITING if side is TeamSide.HOME else TeamSide.HOME


def coached_sides(
    engine: RulesEngine, game: D12BallGame, viewer: Viewer,
) -> tuple[TeamSide, ...]:
    """The sides this viewer coaches: none for somebody watching."""
    if not viewer.is_coach:
        return ()
    return tuple(
        side
        for side in (TeamSide.HOME, TeamSide.VISITING)
        if engine.side_player_number(game, side) == viewer.player_number
    )


def may_answer(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    viewer: Viewer,
) -> bool:
    """
    Whether this viewer is one the prompt is put to -- the web app's
    half of `SafeView.may_act_for`, off the same reading the service
    answers an AI side by (`d12ball.prompts.asked_sides`).

    A prompt nobody in particular is asked -- every roll, the
    tutorial's Continue -- is either coach's to press, which is what
    "nothing rolls dice on its own" means from this side: the die is
    there for both of them and neither is being asked a question.
    A spectator answers nothing.
    """
    if not viewer.is_coach:
        return False
    sides = asked_sides(match, prompt)
    if not sides:
        return True
    return bool(set(sides) & set(coached_sides(engine, game, viewer)))


def controls_for(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: Optional[PendingPrompt],
    viewer: Viewer,
    wire: Optional[Mapping[str, Any]] = None,
) -> list[dict]:
    """
    What this viewer may press, as sections of controls -- empty where
    the question is somebody else's, or where there is no question.

    Whose question it is, is the model's reading of the prompt itself
    (`asked_sides`); what is offered is built from the prompt as the
    wire writes it (`Asked`), so `wire` may be handed in where the
    caller has already written it.
    """
    asked = _asked(engine, game, match, prompt, viewer, wire)
    if asked is None:
        return []
    return [group for group in CONTROLS[asked.kind](asked) if group is not None]


def _asked(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: Optional[PendingPrompt],
    viewer: Viewer,
    wire: Optional[Mapping[str, Any]] = None,
) -> Optional[Asked]:
    if prompt is None or prompt.kind not in CONTROLS:
        return None
    if not may_answer(engine, game, match, prompt, viewer):
        return None
    return Asked(
        engine,
        game,
        match,
        prompt.to_dict() if wire is None else wire,
        viewer,
        asked_sides(match, prompt),
    )


#: The objects the question box draws itself -- the die, a speed's
#: faces, the whistle, the note, the REMATCH mark, the hand's cards,
#: the formation tiles --
#: which the lit line does not repeat: it says what is lit elsewhere.
IN_THE_BOX = frozenset({
    "die", "face", "whistle", "note", "rematch", "card", "formation",
})


def split_footnote(
    engine: RulesEngine,
    game: D12BallGame,
    match: Optional[MatchState],
    prompt: PendingPrompt,
    ask: str,
) -> tuple[str, str]:
    """
    A Coaching Choice's ask with its Spreadable reminder taken off the
    end, and the reminder: the question box says the reminder under the
    whistle rather than under the title (the author, 2026-09-26). The
    words are the model's either way (`RulesEngine.spreadable_note`,
    which `prompts._window` appends); only where they stand is the
    page's. Any other ask comes back whole, with no footnote.
    """
    if match is None or prompt.side is None:
        return ask, ""
    note = engine.spreadable_note(game, match, TeamSide(prompt.side))
    if not note or not ask.endswith(note):
        return ask, ""
    return ask[: -len(note)].rstrip("\n"), note


def lit_line(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: Optional[PendingPrompt],
    viewer: Viewer,
    controls: Sequence[dict],
    wire: Optional[Mapping[str, Any]] = None,
) -> list[dict]:
    """
    What the question box says is lit on the board (and on the
    jumbotron's tile), and -- muted -- what is dark and why: a line per
    object, `{"text", "dark"}`. The box's own objects are not repeated.

    It is built from the controls this viewer was handed and nothing
    else, so it cannot name a thing that is not lit. The turn is the
    one prompt that also says what is *not* offered, because its three
    objects are always on the board and a coach looks for the one that
    is dark: a shot out of range is not offered at all (`TurnOptions`),
    which the range bar under the field shows, and a time out not
    offered is dark on its tile.
    """
    asked = _asked(engine, game, match, prompt, viewer, wire)
    if asked is None or not controls:
        return []
    lines = []
    for group in controls:
        for control in group["controls"]:
            place = control.get("place")
            if not place or place["at"] in IN_THE_BOX:
                # The box draws its own objects, which say themselves.
                continue
            if control.get("first"):
                # An answer given with two objects (the Coaching
                # Choice's) is said by its group's how-line, and the
                # board lights every player it may start from: a list
                # of them here only repeats the board (the author,
                # 2026-09-26).
                continue
            name = " and ".join(
                _object_name(asked, one)
                for one in (place, *control.get("also", ()))
            )
            said = control.get("chip") or control["label"]
            if said == name:
                said = control["label"]
            text = name if said == name else f"{name} · {said}"
            cost = control.get("cost")
            if cost:
                verb = "drain" if cost["emoji"] == "exhaust_cyborg" else "exhaust"
                text = f"{text} ({verb} {cost['count']})"
            if control.get("disabled"):
                lines.append({"text": f"{text} -- {control['note']}", "dark": True})
            else:
                lines.append({"text": text, "dark": False})
    if asked.kind is PromptKind.COACHING_HUB:
        # What the window has left to substitute with is the options'
        # (`allowance`); the bench is dark once it is spent.
        options = asked.options
        if options.get("allowance"):
            lines.append({
                "text": f"{options['allowance']}.",
                "dark": not (
                    options["may_substitute"] and options["incoming_ids"]
                ),
            })
    if asked.kind is PromptKind.PLAYER_ACTION:
        offered = set(asked.options["actions"])
        if "shoot" not in offered:
            lines.append({
                "text": "The goal is dark: no shot from where the ball stands "
                "(the range is under the field).",
                "dark": True,
            })
        if "time_out" not in offered:
            lines.append({
                "text": "The time-out tile is dark: no time out to call now.",
                "dark": True,
            })
    return lines


def _object_name(asked: Asked, place: Mapping[str, Any]) -> str:
    """What a lit object is called in the question box's lit line."""
    at = place["at"]
    if at == "player":
        return asked.label(place["id"])
    if at == "space":
        return capitalized(space_label(
            Zone(place["zone"]), place["space_index"], asked.match.board,
        ))
    if at == "goal":
        return "The goal"
    if at == "bench":
        team = asked.match.setup_for_side(TeamSide(place["side"])).team
        return f"The {team_display_name(team)} bench"
    if at == "time_out_tile":
        return "The time-out tile"
    if at == "out_of_play":
        return "The goal zone"
    if at == "face":
        return f"Speed {place['value']}"
    if at == "card":
        return asked.engine.maneuver_name(place["key"])
    if at == "formation":
        return place["name"]
    return {
        "ball": "The ball",
        "die": "The die",
        "whistle": "The whistle",
        "note": "The note",
        "rematch": "Rematch",
    }.get(at, at)


def _continue(asked: Asked) -> list:
    return [section(None, [
        button("Continue", asked.kind, place=ON_NOTE, chip="continue"),
    ])]


#: What clicking each of the turn's three objects does, on its chip.
TURN_CHIPS = {"maneuver": "maneuver", "shoot": "shoot", "time_out": "call it"}


def _turn(asked: Asked) -> list:
    """
    The turn's three answers, each on its own object: the ball on the
    handler for a maneuver, the goal the side attacks for a shot, the
    side's time-out tile for the time out -- each only where
    `TurnOptions.actions` offers it, and dark where the tutorial has
    railed it off.
    """
    options = asked.options
    side = asked.asked[0] if asked.asked else TeamSide(asked.match.ball.possession)
    places = {
        "maneuver": ON_BALL,
        "shoot": on_goal(asked.attacking_goal()),
        "time_out": on_tile(side),
    }
    controls = [
        button(
            CHOICE_LABELS[action],
            asked.kind,
            action,
            place=places[action],
            chip=TURN_CHIPS[action],
            disabled=action not in options["live"],
            note=RAILED_NOTE if action not in options["live"] else "",
        )
        for action in options["actions"]
    ]
    return [section(None, controls)]


def _roll(asked: Asked) -> list:
    """
    The die, lit in the question box; the walk-back of a score attempt
    as the neutral control; and before the die, a ⚡ on each meeple
    that may declare Overdrive or Boost, with what the Overdrive drains.
    """
    options = asked.options
    controls = [
        button(CHOICE_LABELS["roll"], asked.kind, "roll", place=ON_DIE, chip="roll"),
    ]
    if options["back"]:
        controls.append(
            button(
                CHOICE_LABELS["back"],
                asked.kind,
                "back",
                disabled=options["back_railed"],
                note=RAILED_NOTE if options["back_railed"] else "",
            )
        )
    before = [
        button(
            f"⚡ Overdrive: {asked.label(player_id)} "
            f"(drain {options['overdrive_costs'][player_id]})",
            asked.kind,
            "overdrive",
            place=on_player(player_id),
            chip="⚡ Overdrive",
            cost={
                "emoji": "exhaust_cyborg",
                "count": options["overdrive_costs"][player_id],
            },
            player=player_id,
            player_id=player_id,
        )
        for player_id in options["overdrive_player_ids"]
    ] + [
        # Gearclaw's Boost (Law 21), on the same terms.
        button(
            f"Boost: {asked.label(player_id)}",
            asked.kind,
            "boost",
            place=on_player(player_id),
            chip="⚡ Boost",
            player=player_id,
            player_id=player_id,
        )
        for player_id in options["boost_player_ids"]
    ]
    return [section(None, controls), section("Before the die", before)]


#: What the yes of each decision is about on the board, and its chip.
#: The no is the neutral control, worded from the option. A Set Up's
#: shot lights the goal and the player who may take it; a Coaching
#: Offer lights the side's bench (the author, 2026-09-26).
DECISION_YES: Mapping[PromptKind, tuple[str, str]] = {
    PromptKind.MIND_PULL: ("player", "pull"),
    PromptKind.SMOOTH: ("player", "take it over"),
    PromptKind.JOIN_THE_BALL: ("player", "join the ball"),
    PromptKind.FORCE_TEST: ("player", "force a skill test"),
    PromptKind.SET_UP_ATTEMPT: ("goal+player", "shoot"),
    PromptKind.COACHING_OFFER: ("bench", "coach"),
}


def _decision(
    asked: Asked, labels: Optional[Mapping[str, str]] = None,
) -> list:
    """
    A prompt's yes and no. The yes lights the thing the decision is
    about -- the meeple it names; for a Set Up's shot the goal and the
    shooter; for a Coaching Offer the side's bench -- and the no is the
    neutral control. `labels` is what a kind calls its two answers
    where the generic `CHOICE_LABELS` are not enough -- a Smooth names
    both players, since which of the two ends up with the ball is the
    whole question.
    """
    options = asked.options
    labels = labels or {}
    yes = DECISION_YES.get(asked.kind)
    controls = []
    for choice in options["choices"]:
        railed = options["railed"] is not None and choice != options["railed"]
        label = labels.get(choice) or CHOICE_LABELS.get(
            choice, choice.replace("_", " ").title()
        )
        place, also, chip = None, (), ""
        if yes is not None and choice != "decline":
            what, chip = yes
            if what == "goal+player":
                place = on_goal(asked.attacking_goal())
                also = (on_player(asked.prompt["player_id"]),)
            elif what == "bench":
                place = on_bench(asked.prompt["side"])
            else:
                place = on_player(asked.prompt["player_id"])
        controls.append(
            button(
                label,
                asked.kind,
                choice,
                place=place,
                also=also,
                chip=chip,
                disabled=railed,
                note=RAILED_NOTE if railed else "",
                **_decision_arguments(asked, choice),
            )
        )
    return [section(None, controls)]


def _smooth(asked: Asked) -> list:
    """
    The Smooth's two answers, each naming its player: the Telekinetic
    who takes the ball over (their meeple, lit), and -- where declining
    leaves somebody holding it -- the player it stays with
    (`SmoothOptions.keeper_id`). The page says what the Discord
    buttons say, off the same one list.
    """
    keeper_id = asked.options["keeper_id"]
    return _decision(asked, {
        "take": f"{asked.label(asked.prompt['player_id'])} takes it over",
        "decline": (
            f"{asked.label(keeper_id)} keeps the ball" if keeper_id else ""
        ),
    })


def _decision_arguments(asked: Asked, choice: str) -> dict:
    """The two decisions whose answer names who is answering."""
    if asked.kind is PromptKind.COACHING_OFFER:
        return {"side": asked.prompt["side"]}

    if asked.kind in (
        PromptKind.MIND_PULL,
        PromptKind.SMOOTH,
        PromptKind.JOIN_THE_BALL,
        PromptKind.FORCE_TEST,
        PromptKind.FLY,
    ):
        return {"player_id": asked.prompt["player_id"]}
    return {}


#: What clicking a lit meeple means, per pick among players.
PLAYER_CHIPS: Mapping[PromptKind, str] = {
    PromptKind.BALL_HANDLER_SELECTION: "handles",
    PromptKind.RUN_BACK_PLAYER: "runs back",
    PromptKind.BALL_RECOVERY: "picks it up",
    PromptKind.HALFTIME_EXTRA_TOKEN: "clears one more",
    PromptKind.SHOOTER_CHOICE: "shoots",
    PromptKind.SHOOTOUT_PICK: "shoots",
}


def _players(asked: Asked) -> list:
    """
    A pick among players: each lit where it stands. The ball's
    recovery says how far each is from the ball and what the pickup
    would charge them -- `PlayerOptions.costs`, a token a space for
    every pickup, a time out's included (the author, 2026-09-26).
    """
    options = asked.options
    distances = dict(zip(options["player_ids"], options["distances"]))
    costs = dict(zip(options["player_ids"], options.get("costs") or []))
    controls = []
    for player_id in options["player_ids"]:
        chip = PLAYER_CHIPS[asked.kind]
        if player_id in distances:
            chip = f"{chip} · {_away(distances[player_id])}"
        controls.append(
            button(
                asked.label(player_id),
                asked.kind,
                place=on_player(player_id),
                chip=chip,
                cost=asked.cost(player_id, costs.get(player_id, 0)),
                player=player_id,
                player_id=player_id,
            )
        )
    return [section(None, controls)]


def _away(distance: int) -> str:
    return "on the ball" if distance == 0 else (
        f"{_spaces(distance).lower()} away"
    )


def _shooter(asked: Asked) -> list:
    return [
        section(
            None,
            [
                button(
                    asked.label(player_id),
                    asked.kind,
                    place=on_player(player_id),
                    chip=PLAYER_CHIPS[asked.kind],
                    player=player_id,
                    shooter_id=player_id,
                )
                for player_id in asked.options["player_ids"]
            ],
        )
    ]


def _halftime_token(asked: Asked) -> list:
    return [
        section(
            None,
            [
                button(
                    asked.label(player_id),
                    asked.kind,
                    place=on_player(player_id),
                    chip=PLAYER_CHIPS[asked.kind],
                    player=player_id,
                    player_id=player_id,
                    side=asked.prompt["side"],
                )
                for player_id in asked.options["player_ids"]
            ],
        )
    ]


#: Sending nobody is clicking the ball: what its chip says, by kind.
DECLINE_CHIPS: Mapping[PromptKind, str] = {
    PromptKind.MANEUVER_CHALLENGE: "let it through",
    PromptKind.LOOSE_BALL_PICK: "send nobody",
}


def _send(asked: Asked) -> list:
    """
    The challenger and the loose ball: somebody, or nobody. Each
    candidate is lit with the walk-in it pays -- a token a space
    (`SendOptions.distances`, the Charter's "Gaining tokens") -- and
    sending nobody is clicking the ball itself, only where the rule
    lets this side decline.
    """
    options = asked.options
    extra = (
        {"skill_type": asked.prompt["skill_type"]}
        if asked.kind is PromptKind.LOOSE_BALL_PICK
        else {}
    )
    decline = (
        button(
            "Send nobody",
            asked.kind,
            "decline",
            place=ON_BALL,
            chip=DECLINE_CHIPS[asked.kind],
            disabled=options["decline_railed"],
            note=RAILED_NOTE if options["decline_railed"] else "",
            **extra,
        )
        if options["may_decline"]
        else None
    )
    distances = dict(zip(options["player_ids"], options["distances"]))
    return [
        section(
            None,
            [
                button(
                    asked.label(player_id),
                    asked.kind,
                    "send",
                    place=on_player(player_id),
                    chip=(
                        "on the ball" if not distances.get(player_id)
                        else _spaces(distances[player_id])
                    ),
                    cost=asked.cost(player_id, distances.get(player_id, 0)),
                    player=player_id,
                    player_id=player_id,
                    **extra,
                )
                for player_id in options["player_ids"]
            ],
        ),
        section(None, [decline] if decline else []),
    ]


def _join_the_ball(asked: Asked) -> list:
    """Glompex's yes and no (Law 21), in the Discord view's words."""
    return _decision(asked, {"join": "Join the ball", "decline": "Stay"})


def _force_test(asked: Asked) -> list:
    """Scorchit's yes and no (Law 21), in the Discord view's words."""
    return _decision(
        asked, {"force": "Force a skill test", "decline": "Let it stand"},
    )


def _fly(asked: Asked) -> list:
    """
    Zenith's Fly (Law 21): each space the prompt offers lit, with its
    price (`FlyOptions.spaces`, a token a space), and Stay.
    """
    options = asked.options
    player_id = asked.prompt["player_id"]
    return [
        section(
            None,
            [
                button(
                    travel_space_label(
                        Zone(space["zone"]),
                        space["space_index"],
                        space["distance"],
                        asked.match.board,
                    ),
                    asked.kind,
                    "fly",
                    place=on_space(space["zone"], space["space_index"]),
                    chip=f"fly · {_spaces(space['distance']).lower()}",
                    cost=asked.cost(player_id, space["distance"]),
                    player_id=player_id,
                    zone=space["zone"],
                    space_index=space["space_index"],
                )
                for space in options["spaces"]
            ]
            + [
                button(
                    "Stay",
                    asked.kind,
                    "decline",
                    player_id=player_id,
                ),
            ],
        )
    ]


def _run_back_space(asked: Asked) -> list:
    """
    Where the player the prompt named runs back to: each space of
    their zone lit with its price -- a token a space, the same reading
    the Discord button puts there (`travel_space_label`).
    """
    options = asked.options
    player_id = asked.prompt.get("player_id")
    return [
        section(
            None,
            [
                button(
                    travel_space_label(
                        _zone(options["zone"]),
                        space_index,
                        distance,
                        asked.match.board,
                    ),
                    asked.kind,
                    place=on_space(options["zone"], space_index),
                    chip=(
                        "stays here" if distance == 0
                        else f"runs back · {_spaces(distance).lower()}"
                    ),
                    cost=asked.cost(player_id, distance),
                    space_index=space_index,
                )
                for space_index, distance in zip(
                    options["space_indices"], options["distances"],
                )
            ],
        )
    ]


def _distance(asked: Asked) -> list:
    """
    Every prompt that asks how far, and the push back a failed Setup
    Pass gambit owes: each distance lights the space it lands on
    (`DistanceOptions.landings`), with a chip saying what landing there
    means -- the push back into the goal zone lights the ✕ on that goal
    zone instead. A Setup Pass with nowhere to go is put out of play at
    the ✕ on the far goal zone; Quantor's run onto the pass is a second chip
    on the same spaces.
    """
    options = asked.options
    landings = options.get("landings") or []
    if len(landings) != len(options["distances"]):
        landings = [None] * len(options["distances"])
    controls = []
    for distance, landing in zip(options["distances"], landings):
        railed = options["railed"] is not None and distance != options["railed"]
        chip, cost = _landing_chip(asked, distance)
        place = (
            on_space(landing["zone"], landing["space_index"])
            if landing else None
        )
        if distance == options.get("goal_zone"):
            # The push back into the goal zone comes to rest on the same
            # last space as the longest that does not, so it lights the
            # ✕ on that goal zone instead: the side asked is the defense,
            # and the end is the one the offense defends.
            place = off_the_end(asked.attacking_goal())
            chip = f"{distance} back · goal zone"
        controls.append(
            button(
                _spaces(distance),
                asked.kind,
                place=place,
                chip=chip,
                cost=cost,
                disabled=railed,
                note=RAILED_NOTE if railed else "",
                distance=distance,
            )
        )
    if options["may_pass_out"]:
        # A Setup Pass with nowhere to go is the card's one way out of
        # play, and it is the absence of a distance rather than a
        # choice -- the driver reads it the same way.
        controls = [
            button(
                "Put it out of play",
                asked.kind,
                place=off_the_end(asked.attacking_goal()),
                chip="out of play",
            )
        ]

    # Quantor running onto the pass (Law 21): the same distances, with
    # the run declared beside them.
    by_distance = {
        distance: landing
        for distance, landing in zip(options["distances"], landings)
    }
    runner_id = options["runner_id"]
    runs = [
        button(
            f"{_spaces(distance)}, {asked.label(runner_id)} "
            "runs onto it (drain 3)",
            asked.kind,
            place=(
                on_space(
                    by_distance[distance]["zone"],
                    by_distance[distance]["space_index"],
                )
                if by_distance.get(distance) else None
            ),
            chip=f"{asked.label(runner_id)} runs onto it",
            cost={"emoji": "exhaust_cyborg", "count": 3},
            distance=distance,
            runner=True,
        )
        for distance in options["runner_distances"]
    ]
    return [section(None, controls), section("Run onto the pass", runs)]


def _landing_chip(asked: Asked, distance: int) -> tuple[str, Optional[dict]]:
    """
    What landing a distance means, as the Discord button beside it
    says it: a pass names who is standing there to take it
    (`high_pass_destination_note`), a burst what it costs
    (`dribble_burst_cost`), the rest only how far.
    """
    kind, match = asked.kind, asked.match
    if kind in (PromptKind.HIGH_PASS_CHOICE, PromptKind.SETUP_PASS_CHOICE):
        note = asked.engine.high_pass_destination_note(match, distance)
        return f"{_spaces(distance)} · {note.split(', ', 1)[-1]}", None
    if kind is PromptKind.DRIBBLE_BURST_CHOICE:
        cost = asked.engine.dribble_burst_cost(match, distance, asked.game)
        return (
            f"burst {_spaces(distance).lower()}",
            asked.cost(match.active_player_id, cost),
        )
    if kind is PromptKind.DRIBBLE_ADVANCE_CHOICE:
        return f"advance {_spaces(distance).lower()}", None
    if kind is PromptKind.SETUP_PASS_PUSH_BACK:
        return f"{distance} back", None
    return _spaces(distance), None


def _spaces(distance: int) -> str:
    return "Same space" if distance == 0 else (
        f"{distance} space" if distance == 1 else f"{distance} spaces"
    )


def _low_pass(asked: Asked) -> list:
    """
    One control per landing: the teammate standing there lit, named
    the way `LowPassChoiceView` names it -- the teammate and the space
    (`match.ball_destination`, the label the Discord button reads) --
    and where several teammates share the landing space, the space
    itself lit, asking in the box which of them receives it: the
    second question the adapter takes beside the distance.
    """
    match = asked.match
    controls = []
    for option in asked.options["passes"]:
        distance = option["distance"]
        receiver_ids = option["receiver_ids"]
        zone, space_index = match.ball_destination(
            match.ball.possession, distance,
        )
        where = space_label(zone, space_index, match.board)
        if len(receiver_ids) > 1:
            controls.append(
                chooser(
                    f"{len(receiver_ids)} players -- {where}: "
                    "who receives it?",
                    "Pass",
                    [
                        field(
                            "receiver_id",
                            "",
                            [
                                (player_id, asked.label(player_id))
                                for player_id in receiver_ids
                            ],
                        )
                    ],
                    asked.kind,
                    place=on_space(zone, space_index),
                    chip=f"{len(receiver_ids)} may receive",
                    distance=distance,
                )
            )
            continue
        receiver = receiver_ids[0] if receiver_ids else None
        controls.append(
            button(
                f"{asked.label(receiver)} -- {where}" if receiver else where,
                asked.kind,
                place=on_player(receiver) if receiver else on_space(zone, space_index),
                chip="receives" if receiver else "lands here",
                player=receiver,
                distance=distance,
            )
        )
    return [section(None, controls)]


def _speed(asked: Asked) -> list:
    """The speeds within reach, as a row of d12 faces in the box --
    nothing on the board is a speed to be chosen."""
    options = asked.options
    return [
        section(
            None,
            [
                button(
                    f"Ball speed {target}",
                    asked.kind,
                    place=on_face(target),
                    target_speed=target,
                    disabled=(
                        options["railed"] is not None
                        and target != options["railed"]
                    ),
                    note=(
                        RAILED_NOTE
                        if options["railed"] is not None
                        and target != options["railed"]
                        else ""
                    ),
                )
                for target in options["targets"]
            ],
        )
    ]


def _maneuver(asked: Asked) -> list:
    """
    **The hand, and it is this coach's own.** The pick is secret until
    both are in, so the other side's hand is not in what this viewer
    is sent -- see the module docstring; the page draws it face down
    (`hand_table`). Each card is the answer, the printed card itself.

    **A side that has picked keeps its hand** (the author, 2026-09-26):
    it may change its card until the other side has picked too, which
    `asked_sides` says by still asking it and `maneuver_pick_refusal`
    takes. The card laid down is ringed and dead -- the same card
    twice is refused -- and the rest read "play this instead". Which
    card was laid is the position (`offense_maneuver` /
    `defense_maneuver`), read for this viewer's own side only.

    **The gambits the side does not hold are shown dimmed** --
    `ManeuverHand.withheld`, the model's answer, never worked out here
    -- as dead controls with the note, so a coach reads what being
    behind would put in their hand (step 5 of
    docs/web-app-redesign.md). A side that holds its gambits has them
    in `maneuver_keys` like any card; either way the page lays the
    gambits out as a second row (`card.gambit`), since a card's tier is
    printed on it.
    """
    mine = set(asked.sides())
    groups = []
    for hand in asked.options["hands"]:
        if _side(hand["team_side"]) not in mine:
            continue
        side, railed = hand["side"], hand["railed"]
        laid = _laid_down(asked.match, side) if hand["picked"] else None
        controls = []
        for key in hand["maneuver_keys"]:
            railed_off = railed is not None and key != railed
            controls.append(button(
                asked.engine.maneuver_name(key),
                asked.kind,
                place=on_card(key, side),
                chip=(
                    "your card, face down" if key == laid
                    else "play this instead" if laid else "play"
                ),
                card=_card(asked.engine, key, side, picked=key == laid),
                side=side,
                maneuver_key=key,
                disabled=railed_off or key == laid,
                note=RAILED_NOTE if railed_off else "",
            ))
        controls.extend(
            button(
                asked.engine.maneuver_name(key),
                asked.kind,
                place=on_card(key, side),
                card=_card(asked.engine, key, side, withheld=True),
                side=side,
                maneuver_key=key,
                disabled=True,
                note=WITHHELD_NOTE,
            )
            for key in hand["withheld"]
        )
        groups.append(controls)
    # One viewer holds both hands only in a test game; each is named.
    labelled = len(groups) > 1
    return [
        section(
            f"Your hand · {controls[0]['card']['side']}" if labelled
            else "Your hand",
            controls,
        )
        for controls in groups
    ]


def _laid_down(match: MatchState, side: str) -> Optional[str]:
    """The card this side has laid face down, for its own coach."""
    return (
        match.offense_maneuver if side == "offense"
        else match.defense_maneuver
    )


def still_to_answer(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: Optional[PendingPrompt],
    viewer: Viewer,
    wire: Optional[Mapping[str, Any]] = None,
) -> bool:
    """
    Whether this viewer still owes the prompt an answer, beside being
    offered controls: on the maneuver pick a coach whose card is down
    may change it, but the question is waiting on the other side, so
    the box says so and the tab carries no mark. Read off the hands'
    own `picked`; every other prompt is owed wherever it is offered.
    """
    asked = _asked(engine, game, match, prompt, viewer, wire)
    if asked is None:
        return False
    if asked.kind is not PromptKind.MANEUVER_ACTION:
        return True
    mine = set(asked.sides())
    return any(
        not hand["picked"]
        for hand in asked.options["hands"]
        if _side(hand["team_side"]) in mine
    )


def waiting_on(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: Optional[PendingPrompt],
    viewer: Viewer,
) -> list[str]:
    """
    Who the question is waiting on, by name -- the coach of each side
    `asked_sides` names that this viewer does not coach, as the record
    calls them (`coach_name`, which names the AI), once each and in the
    order asked. Empty for a question nobody in particular is asked,
    and for one that is only this viewer's.

    What the question box's WAITING tag says after "Waiting on", so an
    observer reads whose move it is rather than "the other side", which
    is only somebody's from a seat.

    **It never reads a pick.** On the maneuver pick both hands are
    asked until the second card is down, and whether the other side's
    is down already is theirs (`hand_table` keeps the same back either
    way), so an observer is told both names and a coach whose card is
    down the other's -- the same whatever the other side has done. The
    shootout's sides are narrowed to those still to answer by
    `asked_sides` itself, which `shootout_sides` tells everybody.
    """
    if prompt is None:
        return []
    mine = set(coached_sides(engine, game, viewer))
    names: list[str] = []
    for side in asked_sides(match, prompt):
        if side in mine:
            continue
        name = coach_name(game, engine.side_player_number(game, side))
        if name not in names:
            names.append(name)
    return names


#: What a dimmed gambit says: the reason it is not in the hand, which
#: is the rule `may_play_gambits` answers.
WITHHELD_NOTE = "Held only by the side behind."


def _card(
    engine: RulesEngine, key: str, side: str, **more: Any,
) -> dict:
    """A maneuver card as a control or the table shows it: its key, the
    side holding it (which colours it) and whether it is a gambit --
    printed on the card, so laid out as the second row."""
    maneuver = engine.maneuver_catalog.get(key)
    return {
        "key": key,
        "side": side,
        "gambit": maneuver is not None
        and maneuver.tier == MANEUVER_TIER_GAMBIT,
        **more,
    }


def hand_table(
    engine: RulesEngine,
    game: D12BallGame,
    match: Optional[MatchState],
    prompt: Optional[PendingPrompt],
    viewer: Viewer,
    wire: Optional[Mapping[str, Any]] = None,
) -> Optional[dict]:
    """
    The hands on the maneuver pick this viewer does not hold, face
    down -- every hand for an observer -- with the line that says they
    are turned over together (step 5 of docs/web-app-redesign.md).
    `None` for any other prompt, or where every hand is this viewer's.

    **A back is drawn whether or not that side has picked.** Whether
    the other coach has chosen is not said on Discord either (the
    refusal that would say it is answered after authorization,
    `maneuver_pick_refusal`), so a back that turned up with a pick
    would publish it. The card this viewer's own side laid down is in
    its hand, ringed (`_maneuver`).
    """
    if (
        prompt is None or match is None
        or prompt.kind is not PromptKind.MANEUVER_ACTION
    ):
        return None
    wire = prompt.to_dict() if wire is None else wire
    mine = set(coached_sides(engine, game, viewer))
    backs = []
    for hand in wire["options"]["hands"]:
        team_side = _side(hand["team_side"])
        if team_side is None or team_side in mine:
            continue
        backs.append({
            "side": hand["side"],
            "team": team_display_name(match.setup_for_side(team_side).team),
            "team_side": team_side.value,
        })
    if not backs:
        return None
    return {
        "backs": backs,
        "note": (
            "Both cards are turned over together."
            if mine else "The hands are turned over together."
        ),
    }


#: What the question box says of each side on the shootout's two
#: secret questions, by whether that side has answered: the model's
#: public line says the same once it has ("<team> has set their
#: shooting order."), and nothing is said of an answer half made.
SHOOTOUT_SAID: Mapping[PromptKind, tuple[str, str]] = {
    PromptKind.SHOOTOUT_ORDER: ("is setting its order", "has set its order"),
    PromptKind.SHOOTOUT_PICK: (
        "is choosing its shooter", "has chosen its shooter",
    ),
}


def shootout_sides(
    engine: RulesEngine,
    game: D12BallGame,
    match: Optional[MatchState],
    prompt: Optional[PendingPrompt],
    wire: Optional[Mapping[str, Any]] = None,
) -> Optional[dict]:
    """
    Whether each side has answered the shootout's secret question --
    the order, or sudden death's pick -- and nothing else about it
    (step 7 of docs/web-app-redesign.md): what an observer and the
    other coach are shown, and the coach setting theirs too, since it
    says whether the other side is waiting on them. `None` for any
    other prompt.

    **Read off the options' own rows** (`ShootoutOptions.owed`, which
    is a side with nobody left to place): a side is set or it is not,
    and a count of who has been placed so far is not sent, since how
    far a coach has got is theirs as much as the order is.
    """
    if (
        prompt is None or match is None
        or prompt.kind not in SHOOTOUT_SAID
    ):
        return None
    wire = prompt.to_dict() if wire is None else wire
    waiting, done = SHOOTOUT_SAID[prompt.kind]
    sides = []
    for entry in wire["options"]["sides"]:
        team_side = _side(entry["side"])
        answered = not entry["player_ids"]
        sides.append({
            "team_side": team_side.value,
            "team": team_display_name(match.setup_for_side(team_side).team),
            "done": answered,
            "said": done if answered else waiting,
        })
    return {
        "sides": sides,
        "note": (
            "Each order is shown a shooter at a time, as they shoot."
            if prompt.kind is PromptKind.SHOOTOUT_ORDER
            else "Both shooters are shown together."
        ),
    }


#: The prompts whose answer opens with a block for the answering coach
#: alone: the order as it stands (`periods.shootout_order_step`) and
#: "You send out ..." (`periods.shootout_pick_step`), both secret until
#: the reveal. The cog puts that block on the coach's own ephemeral
#: menu and posts the rest (`D12Ball.post_ai_answer`, and the two
#: `Shootout*SelectView`s); a page's log is read by everybody in the
#: room, so the block is not kept there at all (`own_block_dropped`).
OWN_FIRST_BLOCK = frozenset({
    PromptKind.SHOOTOUT_ORDER,
    PromptKind.SHOOTOUT_PICK,
})


def own_block_dropped(
    kind: Optional[PromptKind], lines: Sequence[str],
) -> list[str]:
    """An answer's lines as everybody may read them: without the first
    block where that is the answering coach's own (`OWN_FIRST_BLOCK`)."""
    lines = list(lines)
    return lines[1:] if kind in OWN_FIRST_BLOCK else lines


def reveal(
    engine: RulesEngine,
    game: D12BallGame,
    match: Optional[MatchState],
) -> Optional[dict]:
    """
    Both cards face up, with what the cards said between them, from
    the moment both are in until the maneuver is over
    (`reset_maneuver`): once turned over they are public, as the reveal
    line says them. Between them is `cards_outcome` -- the engine's
    reading of the two cards, before any die: `TIE`, or which way the
    one that beats the other points. What the maneuver came to (an
    injury's forfeit, a forced test, the roll) is the outcome banner's,
    which is the model's own headline. An unchallenged card is shown
    alone. `None` while there is nothing turned over.
    """
    if match is None or not match.maneuver_selections_complete:
        return None
    cards = [{"key": match.offense_maneuver, "side": "offense"}]
    if not match.maneuver_uncontested:
        cards.append({"key": match.defense_maneuver, "side": "defense"})
    for one, team_side in zip(
        cards, (TeamSide(match.ball.possession), match.defending_side()),
    ):
        one["name"] = engine.maneuver_name(one["key"])
        one["team_side"] = TeamSide(team_side).value
    outcome = engine.cards_outcome(match)
    between = {
        None: "unchallenged",
        "tie": "TIE",
        "offense": "BEATS",
        "defense": "BEATS",
    }[outcome]
    return {"cards": cards, "between": between, "winner": outcome}


def _shootout_order(asked: Asked) -> list:
    """
    The secret order, as six slots in the question box (step 7 of
    docs/web-app-redesign.md): a section per side this viewer coaches
    and still owes an order, holding a control per player still to be
    placed and Start again, and under `order` the slots.

    **The slots are the order this side has already sent** --
    `MatchState.shootout_order`, the record, read for the viewer's own
    seat only, the way `restore_shootout_menus` puts it back on a
    Discord menu (`shootout_order_text`) -- and as many empty ones as
    the options still list, so the count is the squad's and not a
    number here. Who may still be placed is the options' and nothing
    else. The page fills the empty slots in its own draft and sends
    each name in slot order when the whistle locks it: the same
    `send` a Discord menu sends one click at a time, each checked
    against what was offered as it goes. The other side's order is
    never in this section: its rows are skipped, not greyed.
    """
    mine = set(asked.sides())
    groups: list[Optional[dict]] = []
    for entry in asked.options["sides"]:
        side = _side(entry["side"])
        if side not in mine or not entry["player_ids"]:
            continue
        placed = asked.match.shootout_order(side)
        controls = [
            button(
                asked.label(player_id),
                asked.kind,
                "send",
                player=player_id,
                side=entry["side"],
                player_id=player_id,
            )
            for player_id in entry["player_ids"]
        ]
        controls.append(
            button(
                "Start again",
                asked.kind,
                "restart",
                side=entry["side"],
            )
        )
        group = section("Your order", controls)
        group["order"] = {
            "side": entry["side"],
            "placed": [
                {"id": player_id, "label": asked.label(player_id)}
                for player_id in placed
            ],
            "slots": len(placed) + len(entry["player_ids"]),
        }
        groups.append(group)
    return groups


def _shootout_pick(asked: Asked) -> list:
    mine = set(asked.sides())
    controls: list[dict] = []
    for entry in asked.options["sides"]:
        if _side(entry["side"]) not in mine:
            continue
        controls.extend(
            button(
                asked.label(player_id),
                asked.kind,
                place=on_player(player_id),
                chip=PLAYER_CHIPS[asked.kind],
                player=player_id,
                side=entry["side"],
                player_id=player_id,
            )
            for player_id in entry["player_ids"]
        )
    return [section("Your shooter", controls)]


def _coaching_hub(asked: Asked) -> list:
    """
    The Coaching Choice, played on the board (step 6 of
    docs/web-app-redesign.md): the formations as tiles in the box, and
    every other move as the two things it is made of -- a bench meeple
    onto the player it replaces, a player onto the teammate they change
    zones with, a player onto the space they move to -- each pair one
    control (`button`'s `first`), so the page lights only what the
    options allow and sends the `Action` the Discord menus send.
    Everything offered is the options', including why Done may be
    refused (`finish_refusal`, the kickoff space a side must cover),
    which is said under the whistle.
    """
    options = asked.options
    side = asked.prompt["side"]
    current = options["current_formation"]
    return [
        section(
            "Formation",
            [
                _formation(asked, formation, current)
                for formation in options["formations"]
            ],
            how="click a shape",
        ),
        section(
            "Substitute",
            [
                button(
                    f"{asked.label(incoming)} on for {asked.label(outgoing)}",
                    asked.kind,
                    "substitute",
                    # No chip on a player to pick up, here or below:
                    # lit, it says itself, and one pick lights every
                    # answer that starts from it (the author,
                    # 2026-09-26).
                    first=on_player(incoming),
                    place=on_player(outgoing),
                    chip=f"\u21d0 {asked.label(incoming)}",
                    side=side,
                    outgoing_player_id=outgoing,
                    incoming_player_id=incoming,
                )
                for incoming in options["incoming_ids"]
                for outgoing in options["outgoing_ids"]
            ]
            if options["may_substitute"]
            else [],
            how=(
                "drag a bench meeple onto the player it replaces, or "
                "click the two in turn"
            ),
        ),
        section(
            "Change zones",
            [
                button(
                    f"{asked.label(swap['player_id'])} changes zone with "
                    f"{asked.label(other)}",
                    asked.kind,
                    "swap",
                    first=on_player(swap["player_id"]),
                    place=on_player(other),
                    chip="swap \u21c4",
                    side=side,
                    player_id=swap["player_id"],
                    other_player_id=other,
                )
                for swap in options["swaps"]
                for other in swap["partner_ids"]
            ],
            how=(
                "pick up a player and drop it on a teammate in another "
                "zone"
            ),
        ),
        section(
            "Move within a zone",
            _repositions(asked),
            how=(
                "pick up a player and drop it on a lit space in its own "
                "zone"
            ),
        ),
        section(
            None,
            [
                button(
                    CHOICE_LABELS["done"],
                    asked.kind,
                    "done",
                    place=ON_WHISTLE,
                    chip="done",
                    side=side,
                    disabled=options["finish_refusal"] is not None,
                    note=options["finish_refusal"] or "",
                )
            ],
        ),
    ]


def _formation(asked: Asked, formation: str, current: Optional[str]) -> dict:
    """
    A formation's tile: its name, and its shape as the dots the tile
    draws per zone, left to right as the field is -- a side's own goal
    zone is at its own end. The counts are the ruleset's
    (`RulesEngine.formation_shape`), never read off the name. The shape
    a side stands in is dead, as the Discord menu greys it.
    """
    shape = asked.engine.formation_shape(asked.match, Formation(formation))
    counts = [shape.own_goal, shape.midfield, shape.opponent_goal]
    if TeamSide(asked.prompt["side"]) is TeamSide.VISITING:
        counts.reverse()
    control = button(
        formation,
        asked.kind,
        "formation",
        place=on_formation(formation),
        chip="now" if formation == current else "",
        side=asked.prompt["side"],
        formation=formation,
        disabled=formation == current,
        note="Where they stand now" if formation == current else "",
    )
    control["shape"] = counts
    return control


def _repositions(asked: Asked) -> list[dict]:
    """
    A meeple moved inside its own zone: the player, then the space --
    and, where more than one teammate is standing on the space it is
    moving to, which of them comes back to keep the zone covered. One
    is no choice and the driver takes it; several is the second
    question, a chooser the space opens in the box.
    """
    side = asked.prompt["side"]
    controls: list[dict] = []
    for entry in asked.options["repositions"]:
        player_id, zone = entry["player_id"], _zone(entry["zone"])
        for space in entry["spaces"]:
            space_index, trade_with = space["space_index"], space["trade_with"]
            label = (
                f"{asked.label(player_id)} to "
                f"{space_label(zone, space_index, asked.match.board)}"
            )
            pair = {
                "first": on_player(player_id),
                "place": on_space(zone, space_index),
            }
            if len(trade_with) > 1:
                controls.append(
                    chooser(
                        f"{label} -- who comes back?",
                        "Move",
                        [
                            field(
                                "swap_with",
                                "",
                                [
                                    (one, asked.label(one))
                                    for one in trade_with
                                ],
                            )
                        ],
                        asked.kind,
                        "reposition",
                        chip="move here",
                        **pair,
                        side=side,
                        player_id=player_id,
                        space_index=space_index,
                    )
                )
                continue
            comes_back = (
                f"{asked.label(trade_with[0])} comes back" if trade_with else ""
            )
            controls.append(
                button(
                    label,
                    asked.kind,
                    "reposition",
                    chip="move here" + (
                        f" \u00b7 {comes_back}" if comes_back else ""
                    ),
                    **pair,
                    side=side,
                    player_id=player_id,
                    space_index=space_index,
                    note=comes_back,
                )
            )
    return controls


def _side(value: Optional[str]) -> Optional[TeamSide]:
    """A side off the wire, as the model's own, to compare with the
    sides this viewer coaches."""
    return None if value is None else TeamSide(value)


def _zone(value: Optional[str]) -> Optional[Zone]:
    """A zone off the wire, as the model's own, for the space's label
    -- the formatter's question, asked of its own type."""
    return None if value is None else Zone(value)


def _game_over(asked: Asked) -> list:
    """
    A finished game asks nothing of the match; what is under it is the
    rematch, as `RematchView` puts it under the bot's full-time
    message -- a new room with this one's settings and seats, which is
    not an action on this game, so it goes to the room's own route
    (`GameService.rematch`) rather than to `apply_action`. Either
    coach may press it: a finished game is nobody's question. On the
    page it is the REMATCH mark in the box.
    """
    return [
        section(
            None,
            [button("Rematch", asked.kind, place=ON_REMATCH, post="/rematch")],
        )
    ]


#: The rows of the full-time block, in the canvas's order: what each
#: is called, and how it is read off a side's `stats.SideReport`.
FULL_TIME_ROWS: tuple[tuple[str, Callable[[Any], str]], ...] = (
    ("goals", lambda one: str(one.goals)),
    ("shots", lambda one: str(one.shots)),
    ("maneuvers won", lambda one: str(one.maneuvers_won)),
    (
        "skill tests",
        lambda one: f"{one.skill_tests} / {one.skill_tests_taken}",
    ),
    ("exhaustion taken", lambda one: str(one.exhaustion)),
    ("time outs", lambda one: str(one.time_outs)),
)


def full_time(game: D12BallGame, match: Optional[MatchState]) -> Optional[dict]:
    """
    The numbers beside the result once the game is over (step 5 of
    docs/web-app-redesign.md, the "Full time" artboard): a row per
    statistic, home against visitors, each read by
    `stats.collect_sides` over the match's events -- the fold the bot's
    `/d12ball stats` tables are made of, split by side. The page draws
    each side's number in its team's colour; it counts nothing.
    `None` before the game is over.
    """
    if match is None or not game.is_finished:
        return None
    sides = stats.collect_sides(match)
    home, visiting = sides[TeamSide.HOME], sides[TeamSide.VISITING]
    return {
        "rows": [
            {"label": label, "home": read(home), "visiting": read(visiting)}
            for label, read in FULL_TIME_ROWS
        ],
        "home": team_display_name(match.home.team),
        "visiting": team_display_name(match.visiting.team),
    }


def plain_text(game: D12BallGame, text: str) -> str:
    """
    One of the model's sentences as plain text, for the log as a file:
    the markdown as the model wrote it, and each token as the words a
    copy of the page reads -- a team its name, a role its brackets, a
    condition its word, a coach their name. The alt text `render_text`
    gives each picture, so the two say the same sentence.
    """

    def resolve(kind: str, arguments: tuple[str, ...]) -> Optional[str]:
        if kind == "team":
            return team_display_name(Team(arguments[0]))
        if kind == "role":
            return role_brackets(PlayerRole(arguments[0]))
        if kind == "condition":
            return arguments[0].replace("_", " ")
        if kind == "species":
            return arguments[0].replace("_", " ").title()
        if kind == "coach":
            return coach_name(game, int(arguments[0]))
        return None

    return tokens.render(text, resolve)


#: One builder per `PromptKind`, the way `PLAIN_PROMPT_VIEWS` and
#: `view_for_prompt` are the cog's one mapping from a kind to what it
#: puts up. A kind with no row here is a prompt this frontend cannot
#: offer, and `tests/test_web_app.py` asserts there is none.
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
    PromptKind.JOIN_THE_BALL: _join_the_ball,
    PromptKind.FORCE_TEST: _force_test,
    PromptKind.FLY: _fly,
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
    PromptKind.GAME_OVER: _game_over,
}


# -- The situation ----------------------------------------------------------
#
# The matchup a question is asked over, where the cog posts one with it:
# the shot's composition over its roll (`D12Ball.begin_score_attempt`),
# and the challenge over the maneuver pick (`announce_maneuver_challenge`).
# On Discord each is a PNG. **The page draws it itself** (the author,
# 2026-09-28): the same brief the PNG is drawn from --
# `dice_brief.maneuver_challenge_brief` and `score_attempt_brief` -- as
# words and portraits on the page's own background, in a window of its
# own above the question box. The numbers are the brief's and so the
# game's; how they are laid out, like the PNG's, is the frontend's.
#
# **Deliberately not the field strip or the coach's half-field**
# (the author, 2026-09-26): the page's board is beside the prompt, so
# a coach can see the field. And nothing here goes in the log.
#
# Each is the position's and holds nobody's hand, so it is the same for
# a coach and an observer.


@dataclass(frozen=True)
class Bearing:
    """
    What bears on one part of a roll -- the player rolling a skill test's
    attack, a shot's wall, the one rolling an injury check: the species
    whose ability reaches it, the personal abilities that act on it, and
    the skill it adds, if any. **Which reminder goes with which roll,
    never whether an ability fires**: whether a player holds one is
    `has_species_ability` / `has_personal_ability`, asked below.
    """

    species: tuple[str, ...] = ()
    personal: frozenset = frozenset()
    skill: Optional[str] = None


def _situation_player(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    player_id: str,
    side: Optional[ChallengeSide],
    bearing: Bearing = Bearing(),
) -> dict:
    """One portrait in the situation: who, what they add, whether it is
    half of their skill (a shot's defender off the ball) -- the last
    three `None` for a roll nobody contests -- and the abilities that
    bear on it (`_abilities`)."""
    return {
        "id": player_id,
        "label": render_text(
            game,
            engine.format_player_label(
                match, engine.get_player_definition(player_id),
            ),
        ),
        # Plain, for the line that says whose an ability is in a wall.
        "short": player_with_role(engine.get_player_definition(player_id)),
        "portrait": f"/api/game/{game.game_id}/portrait/{player_id}.png",
        "value": None if side is None else side.value,
        "skill": None if side is None else side.skill,
        "halved": False if side is None else side.halved,
        "abilities": _abilities(engine, game, player_id, bearing),
    }


#: The personal abilities any roll a Cyborg makes can carry: Voltus's
#: cheap Overdrive and Gearclaw's Boost, spent on the die (Law 21).
_ON_THE_DIE = frozenset({
    PersonalAbility.CHEAP_OVERDRIVE, PersonalAbility.BOOST,
})
#: The ignites a Fire Demon's own die can carry in a skill test and on
#: a shot -- Blazebulk's, Sizzifizik's, Brightburn's burn (Law 21).
_IGNITES = frozenset({
    PersonalAbility.ALWAYS_BLAZES, PersonalAbility.WIDE_IGNITION,
    PersonalAbility.BRIGHT_BURN,
})

#: What bears on each part of each roll the situation is asked over
#: (the author, 2026-09-28: only what applies to the roll). Volatile
#: reaches a skill test and the shooter's die, never an injury check or
#: an own-goal roll (Law 20.2.3); Overdrive any d12 a Cyborg rolls (Law
#: 20.3.5). A personal ability is here where it changes the roll's
#: number, whether it is rolled, or what winning it means -- and on the
#: maneuver challenge also what a maneuver does once it has won, since
#: the coach is choosing one there (the author, 2026-09-28): Emberdash's
#: dribble, Vorix's set-up and Acidel's pressure, each on the attack
#: alone. Quantor's run on is never here: it is for a teammate's pass,
#: so it does not apply to a roll Quantor is in (the author,
#: 2026-09-28). Bulwark's drain threshold applies to every roll he is
#: in (`ALWAYS_BEARS`). Zorch
#: adds the speed modifier to every roll but the shot, which adds it
#: already (`speed_roll_bonus`). Merge is not here: it is a number
#: another player adds, the model's own line in the side's modifiers
#: (`merge_bonus`); and a Mind Pull is the Telekinetics' ability
#: already, which the window says.
#: The personal abilities named on every roll the player is in: Bulwark
#: is only Drained at 10, which is what his tokens mean on any of them
#: (the author, 2026-09-28).
ALWAYS_BEARS = frozenset({PersonalAbility.HIGH_DRAIN_THRESHOLD})

BEARINGS: Mapping[str, Bearing] = {
    "skill_test_attack": Bearing(
        (SPECIES_FIRE_DEMON, SPECIES_CYBORG),
        _ON_THE_DIE | _IGNITES | {
            PersonalAbility.OVERDRIVE_UPGRADE,
            PersonalAbility.OFFENSIVE_GAMBITS,
            PersonalAbility.FORCES_THE_TEST,
            PersonalAbility.DEFENSIVE_THROW,
            PersonalAbility.SPEED_ROLLS,
            # What an attacking card does once won -- the dribble, the
            # High Pass, the Pressure into the goal zone -- since the
            # coach is choosing it (the author, 2026-09-28).
            PersonalAbility.FREE_BURST,
            PersonalAbility.LONG_SET_UP,
            PersonalAbility.PRESSURE_SHOT,
        },
        "offense",
    ),
    "skill_test_defence": Bearing(
        (SPECIES_FIRE_DEMON, SPECIES_CYBORG),
        _ON_THE_DIE | _IGNITES | {
            PersonalAbility.OVERDRIVE_UPGRADE,
            PersonalAbility.DEFENSIVE_GAMBITS,
            PersonalAbility.FORCES_THE_TEST,
            PersonalAbility.SPEED_ROLLS,
        },
        "defense",
    ),
    # A contest for the ball -- a loose ball's, or a long High Pass's:
    # the same dice as a skill test's, and Slitheron's win without one
    # is the reason there was no roll when a contest is skipped.
    "contest_attack": Bearing(
        (SPECIES_FIRE_DEMON, SPECIES_CYBORG),
        _ON_THE_DIE | _IGNITES | {
            PersonalAbility.SPEED_ROLLS, PersonalAbility.WINS_CONTESTS,
        },
        "offense",
    ),
    "contest_defence": Bearing(
        (SPECIES_FIRE_DEMON, SPECIES_CYBORG),
        _ON_THE_DIE | _IGNITES | {
            PersonalAbility.SPEED_ROLLS, PersonalAbility.WINS_CONTESTS,
        },
        "defense",
    ),
    # A scoring opportunity offered off a pass: whatever bears on the
    # shot, and the ability that offered it (Zytheris).
    "set_up": Bearing(
        (SPECIES_FIRE_DEMON, SPECIES_CYBORG),
        _ON_THE_DIE | _IGNITES | {
            PersonalAbility.CLEAR_SHOT, PersonalAbility.SHOOTS_OFF_ANY_PASS,
        },
        "offense",
    ),
    "shot_attack": Bearing(
        (SPECIES_FIRE_DEMON, SPECIES_CYBORG),
        _ON_THE_DIE | _IGNITES | {PersonalAbility.CLEAR_SHOT},
        "offense",
    ),
    "shot_defence": Bearing(
        (), frozenset({PersonalAbility.FULL_BLOCK}), "defense",
    ),
    "injury": Bearing(
        (SPECIES_CYBORG,),
        _ON_THE_DIE | {
            PersonalAbility.INJURY_IGNITION, PersonalAbility.SPEED_ROLLS,
        },
    ),
    "own_goal": Bearing(
        (SPECIES_CYBORG,),
        _ON_THE_DIE | {
            PersonalAbility.DEFENSIVE_THROW, PersonalAbility.SPEED_ROLLS,
        },
        "offense",
    ),
    "mind_pull": Bearing(
        (),
        frozenset({
            PersonalAbility.STRONG_PULL, PersonalAbility.FREE_PULL,
            PersonalAbility.ADJACENT_PULL,
        }),
    ),
}


def _abilities(
    engine: RulesEngine,
    game: D12BallGame,
    player_id: str,
    bearing: Bearing,
) -> list[dict]:
    """
    What a player brings to this roll beyond their skill (the author,
    2026-09-28): their species' ability where it reaches the roll and
    the game plays it, in the sheet's own short words (`species.json`,
    never shortened here), and in an advanced game their personal
    ability where it applies to the roll (`_personal_bears`), as the
    advanced face of their card prints it (`personal_ability_text`).
    """
    notes = []
    for kind in bearing.species:
        if not engine.has_species_ability(game, player_id, kind):
            continue
        entry = species_ability(kind)
        if entry.get("ability_short"):
            notes.append({
                "kind": "species",
                "species": kind,
                "name": entry.get("name", ""),
                "text": entry["ability_short"],
            })
    personal = engine.personal_ability_text(game, player_id)
    if personal and _personal_bears(engine, game, player_id, bearing):
        # "Special ability", the author's word for it on the page
        # (2026-09-28); the Law calls it a personal ability.
        notes.append({
            "kind": "personal", "name": "Special ability", "text": personal,
        })
    return notes


def _personal_bears(
    engine: RulesEngine,
    game: D12BallGame,
    player_id: str,
    bearing: Bearing,
) -> bool:
    """Whether a player's personal line applies to this roll: an ability
    the bearing names, or -- for the players whose line is an advanced
    skill score ("High defensive skill.") -- a raised score in the skill
    this roll adds, read as the game plays it against the role's."""
    if any(
        engine.has_personal_ability(game, player_id, ability)
        for ability in bearing.personal | ALWAYS_BEARS
    ):
        return True
    if bearing.skill is None:
        return False
    return (
        engine.skills(game, player_id).of(bearing.skill)
        != engine.skills(None, player_id).of(bearing.skill)
    )


def _merged(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    side: dict,
    team_side: TeamSide,
    rolling: Sequence[str],
    skill: str,
) -> dict:
    """A side with what its Oozes on the ball add by Merge (Law 20.5),
    in `merge_bonus`'s own lines -- the ones the dice list it under."""
    _, lines, _ = engine.merge_bonus(game, match, team_side, rolling, skill)
    side["modifiers"] = [*side["modifiers"], *lines]
    return side


def _situation_side(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    team: Team,
    players: Sequence[tuple[str, ChallengeSide]],
    with_ability: bool,
    empty: str = "",
    bearing: Bearing = Bearing(),
) -> dict:
    """
    One side of the matchup, worded as the PNG words it
    (`render.group_text_lines`): one player reads as themselves -- the
    skill they roll on, any modifier this attempt earns, their ability
    -- and several as a wall, their contributions added up, because
    that sum is the only number the roll uses.
    """
    sides = [side for _, side in players]
    if not sides:
        skill = ""
    elif len(sides) == 1:
        only = sides[0]
        halved_from = f" (half of {only.skill})" if only.halved else ""
        skill = f"{only.skill_name} skill +{only.value}{halved_from}"
    else:
        terms = " + ".join(str(side.value) for side in sides)
        skill = (
            f"{sides[0].skill_name} skill: {terms}"
            f" = {sum(side.value for side in sides)}"
        )
    return {
        "team": team_display_name(team),
        "colour": TEAM_COLORS[team],
        "players": [
            _situation_player(engine, game, match, player_id, side, bearing)
            for player_id, side in players
        ],
        "skill": skill,
        "modifiers": list(sides[0].modifiers) if len(sides) == 1 else [],
        "ability": (
            sides[0].ability
            if with_ability and len(sides) == 1 and sides[0].ability
            else None
        ),
        # What a wall's two badges mean, in the PNG's own band labels
        # (`render.CHALLENGE_BAND_FULL`, `CHALLENGE_BAND_HALF`): those
        # the wall has, whole skills first.
        "bands": [
            {"halved": halved, "text": text}
            for halved, text in (
                (False, CHALLENGE_BAND_FULL[0]), (True, CHALLENGE_BAND_HALF[0]),
            )
            if len(sides) > 1 and any(side.halved == halved for side in sides)
        ],
        "empty": empty if not sides else None,
    }


def _where(match: MatchState, zone: Zone, space_index: int) -> str:
    """A space as the matchup images caption it: "Space 4 — Midfield"
    (`dice_brief.maneuver_challenge_brief`)."""
    return capitalized(
        f"{space_label(zone, space_index, match.board)}"
        f" — {zone_labels(match.board.layout.board_size)[zone].title()}"
    )


def _player_where(match: MatchState, player_id: str) -> str:
    zone, space_index = match.board.meeple_position(player_id)
    return _where(match, Zone(zone), space_index)


def _roller(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    player_id: str,
    line: str,
    modifiers: Sequence[str] = (),
    bearing: Bearing = Bearing(),
) -> dict:
    """
    The one side of a roll nobody rolls against -- an injury check, an
    own-goal roll, a Mind Pull: who rolls, the line that says what they
    bring to it, and anything declared on it (an Overdrive, a Boost,
    Zorch's speed), in the shape `_situation_side` hands a matchup's.
    """
    team = match.team_for_player(player_id)
    return {
        "team": team_display_name(team),
        "colour": TEAM_COLORS[team],
        "players": [
            _situation_player(
                engine, game, match, player_id, None, bearing,
            ),
        ],
        "skill": line,
        "modifiers": list(modifiers),
        "ability": None,
        "bands": [],
        "empty": None,
    }


def _declared(
    engine: RulesEngine, game: D12BallGame, match: MatchState, player_id: str,
) -> tuple[int, list[str]]:
    """What is already added to this player's next roll, and the lines
    the dice list it under -- `overdrive_details` and Zorch's
    `speed_roll_bonus`, the two every one of these rolls adds."""
    speed, speed_line = engine.speed_roll_bonus(game, match, player_id)
    return (
        match.overdrive_modifier(player_id) + speed,
        [*engine.overdrive_details(match, player_id), *filter(None, [speed_line])],
    )


def _roll(
    dice: int, target: int, added: int, rule: str, otherwise: str,
) -> dict:
    """
    What a roll needs, for the die the page draws beside the roller:
    how many d12 (the higher kept of two), the lowest total that does
    it, the face that total asks of the die once everything declared
    is added -- `face`, clamped to a die's faces -- and what each way
    it goes means.
    """
    face = target - added
    return {
        "dice": dice,
        "target": target,
        "face": min(max(face, 1), 12),
        "certain": face <= 1,
        "impossible": face > 12,
        "rule": rule,
        "otherwise": otherwise,
    }


def _injury_situation(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> Optional[dict]:
    """
    An injury check (Law 15.3): the player, the tokens they carry, and
    the total that beats them -- `injury_test_target`, the number the
    check compares against. A Cyborg's is a damage test, over drain
    tokens, and what it risks is Damaged.
    """
    player_id = prompt.player_id
    if player_id is None:
        return None
    carried = match.exhaustion.get(player_id, 0)
    token_noun, _ = engine.token_word_and_mark(game, player_id)
    injured_word, _ = engine.injured_word_and_mark(game, player_id)
    added, modifiers = _declared(engine, game, match, player_id)
    target = engine.injury_test_target(match, player_id)
    tokens_word = "token" if carried == 1 else "tokens"
    return {
        "title": engine.injury_test_name(game, player_id).upper(),
        "where": _player_where(match, player_id),
        "sides": [
            _roller(
                engine, game, match, player_id,
                f"Carries {carried} {token_noun} {tokens_word}",
                modifiers, BEARINGS["injury"],
            ),
        ],
        "roll": _roll(
            1, target, added,
            f"One d12. Safe on a total of {target} or more: higher than"
            f" their {carried} {tokens_word}.",
            f"Anything lower and they are {injured_word}.",
        ),
    }


def _own_goal_situation(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> Optional[dict]:
    """
    The own-goal roll (Law 11.2): the handler with nowhere left to be
    pushed, what they add -- `attacking_skill`'s own-goal reading and
    its name, Umbrik's defensive skill included -- and
    `OWN_GOAL_SAFE_TOTAL`.
    """
    player_id = match.active_player_id
    if player_id is None:
        return None
    skill = engine.attacking_skill(game, match, player_id, "own_goal")
    # Umbrik's is his defensive skill (Law 21), named as the one added.
    skill_name = engine.attacking_skill_name(
        game, match, player_id, "own_goal",
    )
    added, modifiers = _declared(engine, game, match, player_id)
    against = Team(match.setup_for_side(match.defending_side()).team)
    return {
        "title": "Own goal risk",
        "where": _where(match, match.ball.zone, match.ball.space_index),
        "sides": [
            _roller(
                engine, game, match, player_id,
                f"{skill_name} skill {skill:+d}", modifiers,
                # Umbrik adds his defensive skill here (Law 21).
                replace(BEARINGS["own_goal"], skill=(
                    "defense" if skill_name == "Defensive" else "offense"
                )),
            ),
        ],
        "roll": _roll(
            2, OWN_GOAL_SAFE_TOTAL, skill + added,
            f"Two d12, the higher kept, plus their skill. A total of"
            f" {OWN_GOAL_SAFE_TOTAL} or more avoids it.",
            f"Under {OWN_GOAL_SAFE_TOTAL} and the goal counts for"
            f" {team_display_name(against)}.",
        ),
    }


def _mind_pull_situation(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> Optional[dict]:
    """
    A Mind Pull on offer (Law 20.4): the Telekinetic, what it costs --
    `mind_pull_cost`, paid pull or miss -- and `mind_pull_minimum`.
    Nothing declared reaches it, so the face is the total.
    """
    player_id = prompt.player_id
    if player_id is None:
        return None
    cost = engine.mind_pull_cost(game, player_id)
    token_noun, _ = engine.token_word_and_mark(game, player_id)
    minimum = engine.mind_pull_minimum(game, player_id)
    return {
        "title": "Mind Pull",
        "where": _player_where(match, player_id),
        "sides": [
            _roller(
                engine, game, match, player_id,
                (
                    f"Costs {cost} {token_noun} "
                    f"{'token' if cost == 1 else 'tokens'}, pull or miss"
                    if cost else "Costs no token"
                ),
                bearing=BEARINGS["mind_pull"],
            ),
        ],
        "roll": _roll(
            1, minimum, 0,
            f"One d12. {minimum} or more pulls the ball in: it stops on"
            " their space and their side has it.",
            "Anything lower and the ball goes on past them.",
        ),
    }


def _notes(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    player_ids: Sequence[Optional[str]],
) -> list[dict]:
    """
    A special ability that bears on the situation from somebody who is
    not rolling -- Quantor waiting on a teammate's pass, Glompex offered
    the step onto the ball -- said under the row with whose it is, as
    the advanced face of their card prints it (`personal_ability_text`).
    """
    notes = []
    for player_id in player_ids:
        if player_id is None:
            continue
        text = engine.personal_ability_text(game, player_id)
        if not text:
            continue
        notes.append({
            "id": player_id,
            "short": player_with_role(engine.get_player_definition(player_id)),
            "colour": TEAM_COLORS[match.team_for_player(player_id)],
            "name": "Special ability",
            "text": text,
        })
    return notes


def _join_situation(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> Optional[dict]:
    """
    Glompex's offer (Law 21), made before the cards are chosen: the
    challenge he would step into, and his ability said under it. Once
    he has stepped on, the challenge names what he adds by Merge, so
    the maneuver pick does not repeat him (the author, 2026-09-28).
    """
    challenge = _challenge_situation(engine, game, match, prompt)
    if challenge is None:
        return None
    challenge["notes"] = [
        *_notes(engine, game, match, [prompt.player_id]),
        *challenge["notes"],
    ]
    return challenge


def _challenge_situation(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> Optional[dict]:
    """The player on the ball against the challenger the position
    holds -- `match.challenger_id`, set when a challenger is sent and
    cleared by `reset_maneuver`, so an uncontested maneuver has none."""
    challenger = match.challenger_id
    if challenger is None:
        return None
    attacker = match.active_player_id
    offense, defense, where = maneuver_challenge_brief(
        engine, match, challenger, game,
    )
    # Both roll if the cards tie, and an Ooze on the ball who is
    # neither adds by Merge -- as `skill_test_step` asks it.
    rolling = (attacker, challenger)
    return {
        "title": CHALLENGE_TITLE,
        "where": where,
        "sides": [
            _merged(
                engine, game, match,
                _situation_side(
                    engine, game, match, match.team_for_player(attacker),
                    [(attacker, offense)], with_ability=True,
                    bearing=BEARINGS["skill_test_attack"],
                ),
                match.ball.possession, rolling, "offense",
            ),
            _merged(
                engine, game, match,
                _situation_side(
                    engine, game, match, match.team_for_player(challenger),
                    [(challenger, defense)], with_ability=True,
                    bearing=BEARINGS["skill_test_defence"],
                ),
                match.defending_side(), rolling, "defense",
            ),
        ],
        "roll": None,
        # Quantor may run onto any teammate's High Pass or Set-up Pass,
        # so while a teammate is on the ball and he is on the field the
        # coach choosing the card is told (the author, 2026-09-28).
        "notes": _notes(
            engine, game, match,
            [engine.pass_runner_on_field(game, match)],
        ),
    }


def _shot_situation(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> dict:
    """The shooter with the modifiers this attempt earns, and every
    defender between them and the goal as one wall -- or nobody. No
    ability on either side, as the PNG leaves them off
    (`render.render_score_attempt`)."""
    shooter, defenders, where = score_attempt_brief(engine, match, game)
    defender_ids = [
        defender.player.player_id
        for defender in engine.intervening_defenders(match, game)
    ]
    return {
        "title": SCORE_ATTEMPT_TITLE,
        "where": where,
        "sides": [
            # Merge in a shot is the attack alone (Law 20.5.2), as
            # `score_attempt_step` asks it.
            _merged(
                engine, game, match,
                _situation_side(
                    engine, game, match,
                    match.team_for_player(match.active_player_id),
                    [(match.active_player_id, shooter)], with_ability=False,
                    bearing=BEARINGS["shot_attack"],
                ),
                match.ball.possession, (match.active_player_id,), "offense",
            ),
            _situation_side(
                engine, game, match,
                Team(match.setup_for_side(match.defending_side()).team),
                list(zip(defender_ids, defenders)), with_ability=False,
                empty=SCORE_ATTEMPT_UNDEFENDED,
                bearing=BEARINGS["shot_defence"],
            ),
        ],
        "roll": None,
    }


def _contest_situation(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> Optional[dict]:
    """
    A contest for the ball about to be rolled (Law 10) -- a loose
    ball's, or a long High Pass's (Law 10.4): the two sent, each with
    what the roll adds for them, as `score_loose_ball` adds it. The
    side on the ball adds offensive skill and the other defensive,
    nothing for an injured contestant; the thrower's side of a High
    Pass contest adds the ball speed modifier, signed; Zorch his own
    elsewhere; Merge on both sides; and whatever Overdrive or Boost is
    already declared.
    """
    offense_id = match.loose_ball_offense_player
    defense_id = match.loose_ball_defense_player
    if offense_id is None or defense_id is None:
        return None
    high_pass = match.pending_loose_ball_is_high_pass
    rolling = (offense_id, defense_id)

    def contestant(player_id, attacking, bearing, team_side, skill_kind):
        side = _situation_side(
            engine, game, match, match.team_for_player(player_id),
            [(player_id, challenge_side(
                engine, player_id, match.team_for_player(player_id),
                attacking=attacking, game=game,
            ))],
            with_ability=False, bearing=bearing,
        )
        if player_id in match.injured:
            # An injured contestant adds no skill of their own (Law
            # 15.4); the die and everything else still count.
            side["skill"] = (
                f"{'Offensive' if attacking else 'Defensive'} skill +0 "
                "(injured)"
            )
        extra = list(engine.overdrive_details(match, player_id))
        if attacking and high_pass:
            extra.append(
                f"{match.ball_speed_modifier():+d} ball speed modifier",
            )
        else:
            _, speed_line = engine.speed_roll_bonus(game, match, player_id)
            extra.extend(filter(None, [speed_line]))
        side["modifiers"] = [*side["modifiers"], *extra]
        return _merged(
            engine, game, match, side, team_side, rolling, skill_kind,
        )

    return {
        "title": "High Pass contest" if high_pass else "Contest for the ball",
        "where": _where(match, match.ball.zone, match.ball.space_index),
        "sides": [
            contestant(
                offense_id, True, BEARINGS["contest_attack"],
                match.ball.possession, "offense",
            ),
            contestant(
                defense_id, False, BEARINGS["contest_defence"],
                match.defending_side(), "defense",
            ),
        ],
        "roll": None,
    }


def _set_up_situation(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> Optional[dict]:
    """
    A scoring opportunity offered off a pass, where it is Zytheris's
    special ability that offered it (Law 21; the author, 2026-09-28):
    the shooter, with the ability named. Any other set-up -- a Winger's,
    a High Pass reaching the goal -- is the ask's to say and has none.
    """
    shooter = prompt.player_id
    if shooter is None or not engine.has_personal_ability(
        game, shooter, PersonalAbility.SHOOTS_OFF_ANY_PASS,
    ):
        return None
    skill = engine.skills(game, shooter).offense
    return {
        "title": "Scoring opportunity",
        "where": _player_where(match, shooter),
        "sides": [
            _roller(
                engine, game, match, shooter,
                f"Offensive skill {skill:+d}", (), BEARINGS["set_up"],
            ),
        ],
        "roll": None,
    }


#: The situation a prompt is asked over, by its kind: the two matchups,
#: and the three rolls a player makes alone -- the injury check, the
#: own-goal roll and the Mind Pull on offer (the author, 2026-09-28). A
#: kind not here has none.
SITUATIONS: Mapping[
    PromptKind,
    Callable[
        [RulesEngine, D12BallGame, MatchState, PendingPrompt],
        Optional[dict],
    ],
] = {
    PromptKind.SCORE_ATTEMPT: _shot_situation,
    PromptKind.MANEUVER_ACTION: _challenge_situation,
    PromptKind.JOIN_THE_BALL: _join_situation,
    PromptKind.LOOSE_BALL_SKILL_TEST: _contest_situation,
    PromptKind.SET_UP_ATTEMPT: _set_up_situation,
    PromptKind.INJURY_TEST: _injury_situation,
    PromptKind.OWN_GOAL_ROLL: _own_goal_situation,
    PromptKind.MIND_PULL: _mind_pull_situation,
}


def situation(
    engine: RulesEngine,
    game: D12BallGame,
    match: Optional[MatchState],
    prompt: Optional[PendingPrompt],
) -> Optional[dict]:
    """The matchup `prompt` is asked over, as the page draws it, or
    `None` where it has none."""
    if prompt is None or match is None or prompt.kind not in SITUATIONS:
        return None
    found = SITUATIONS[prompt.kind](engine, game, match, prompt)
    if found is not None:
        found.setdefault("notes", [])
    return found

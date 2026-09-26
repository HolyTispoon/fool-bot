"""
What a match is waiting on, answered with no Discord in the room.

`pending(engine, game, match)` is the single reading of "what is this
match waiting on?" -- the branch chain that used to be
`D12Ball.pending_turn_view`, moved whole. It answers one of two ways.
A `PendingPrompt` is a question for somebody: a `PromptKind` naming
it, the line to put above it, and the handful of parameters the
question carries. A `FollowOn` is a step the bot itself owes, where
nobody is asked anything -- a run back with only forced placements
left, the tail of a time out, the next stage of halftime with no
window open. **`pending_prompt` and `owed_step` are the two readers
over it**, one for each shape, and exactly one of them answers for
any position: a frontend puts up what the first hands back and never
sees a step, and `GameService.resume` runs what the second hands
back. Turning a prompt into a `discord.ui.View` is the cog's job and
the cog's alone (`D12Ball.view_for_prompt`), which is what lets a
second frontend ask the same question without reimplementing the
chain.

**A step is refused while one is owed.** `driver.answer` reads
`owed_step` before it reads the question, so an action arriving
mid-cascade -- a click on a stale prompt, a web request between two
of the bot's own steps -- is refused rather than applied on top of a
position the model has not finished with. Until step 5 of
docs/architecture-migration.md the chain answered `PLAYER_ACTION` for
those states, and a turn action was accepted with `pending_run_back`
still set underneath it (finding 1 of docs/web-app.md).

**A second copy of this chain is the failure mode.** It is how a resume
comes to offer a different prompt from the one a restart restores, and
with two frontends it is how a web app and the bot come to disagree
about whose turn it is. See "Recovering a stuck game" in
docs/design/recovery.md.

Nothing here mutates: the whole chain is a read, and the three builders
folded into it (the run back's, the loose ball's, the effect choice's)
were already pure decisions over match state that happened to end in a
`View` constructor.

**One kind per view class.** A prompt built with different arguments
for different situations is one kind carrying the difference in its
parameters, not several -- `SPEED_DELTA_CHOICE` is Setup Pass's, the
dribbles' and Steal/Intercept's, told apart by `maneuver_key`, and
`LOW_PASS_CHOICE` is the plain one and the free one, told apart by
`free`. That is the rule the cog's mapping table is a table under.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping, Optional, Union

from d12ball.components import (
    OVERDRIVE_DRAIN_COST,
    SPECIES_TELEKINETIC,
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
)

from d12ball.flow.result import FollowOn, FollowOnStep
from d12ball.formatting import (
    address_coach,
    ball_space_label,
    contest_noun,
    format_player_with_team,
    space_label,
)
from d12ball.game import D12BallGame, Formation
from d12ball.wire import jsonable
from d12ball import tokens, tutorial

if TYPE_CHECKING:  # pragma: no cover - typing only
    from d12ball.engine import RulesEngine


class PromptKind(Enum):
    """
    Every distinct prompt the chain can come back with.

    The members are grouped the way the chain reads them, which is not
    the order they matter in -- the ordering decisions live in
    `pending_prompt` itself, in the comments on the branches.
    """

    # The two that outrank everything, because nothing is played
    # while either is up: a tutorial note the coach has not pressed
    # Continue on, and a game that is over. Both Phase 6's, and both
    # for the same reason -- each used to be a message the cog put up
    # on its own, so a restart could not say the match was waiting on
    # it, and a second frontend could not know it was.
    TUTORIAL_CONTINUE = "tutorial_continue"
    GAME_OVER = "game_over"

    # Windows and periods
    COACHING_HUB = "coaching_hub"
    COACHING_OFFER = "coaching_offer"
    HALFTIME_EXTRA_TOKEN = "halftime_extra_token"

    # Interrupts, which outrank the turn they interrupt
    MIND_PULL = "mind_pull"
    SMOOTH = "smooth"
    INJURY_TEST = "injury_test"
    OWN_GOAL_ROLL = "own_goal_roll"

    # The shootout
    SHOOTOUT_ORDER = "shootout_order"
    SHOOTOUT_PICK = "shootout_pick"
    SHOOTOUT_TEST = "shootout_test"

    # The turn
    PLAYER_ACTION = "player_action"
    BALL_HANDLER_SELECTION = "ball_handler_selection"
    RUN_BACK_SPACE = "run_back_space"
    RUN_BACK_PLAYER = "run_back_player"
    BALL_RECOVERY = "ball_recovery"
    LOOSE_BALL_PICK = "loose_ball_pick"
    LOOSE_BALL_SKILL_TEST = "loose_ball_skill_test"
    SCORE_ATTEMPT = "score_attempt"
    # The two halves of a scoring opportunity, closed in Phase 6 of
    # docs/design/model-discord-split.md -- until then each was a
    # `FollowOnStep` whose view carried what match state did not hold.
    SET_UP_ATTEMPT = "set_up_attempt"
    SHOOTER_CHOICE = "shooter_choice"
    MANEUVER_CHALLENGE = "maneuver_challenge"
    MANEUVER_ACTION = "maneuver_action"
    SKILL_TEST = "skill_test"

    # The effect a settled maneuver owes
    LOW_PASS_CHOICE = "low_pass_choice"
    HIGH_PASS_CHOICE = "high_pass_choice"
    SETUP_PASS_CHOICE = "setup_pass_choice"
    SPEED_DELTA_CHOICE = "speed_delta_choice"
    DRIBBLE_ADVANCE_CHOICE = "dribble_advance_choice"
    DRIBBLE_BURST_CHOICE = "dribble_burst_choice"
    # Setup Pass's cost, once a deflection has beaten it: how much
    # further back the coach who won drives the ball. A kind since
    # Phase 6; until then the view had no kind at all, so a restart
    # in that window fell through to the turn prompt.
    SETUP_PASS_PUSH_BACK = "setup_pass_push_back"


@dataclass(frozen=True)
class PendingPrompt:
    """
    The question, the line asking it, and what the question is about.

    Only the parameters the branches actually carry are here. Anything
    else a frontend needs it can ask the engine for, with the match it
    already holds -- a prompt is what to ask, not a rendering brief.
    """

    kind: PromptKind
    ask: str
    #: RUN_BACK_PLAYER: which of a stack may be the one to run back.
    player_ids: list[str] = field(default_factory=list)
    #: MIND_PULL, INJURY_TEST, RUN_BACK_SPACE, SPEED_DELTA_CHOICE.
    player_id: Optional[str] = None
    #: HALFTIME_EXTRA_TOKEN, LOOSE_BALL_PICK: the board side asked.
    side: Optional[TeamSide] = None
    #: LOW_PASS_CHOICE and SPEED_DELTA_CHOICE: the card resolving.
    maneuver_key: Optional[str] = None
    #: LOOSE_BALL_PICK and SPEED_DELTA_CHOICE: "offense" or "defense".
    skill_type: Optional[str] = None
    #: LOW_PASS_CHOICE: a pass that costs the passer nothing.
    free: bool = False
    #: SET_UP_ATTEMPT: the clock cost of the maneuver that offered it,
    #: which the shot adds its own extra minute to rather than
    #: replacing. Not derivable from the position by the time the offer
    #: is put, which is why it is on the match -- see
    #: `MatchState.pending_scoring_opportunity`.
    distance_moved: int = 1
    #: SET_UP_ATTEMPT: an overshoot is a shot or a contest, both at the
    #: same disadvantage, so declining lands in the long-pass contest
    #: rather than settling the ball (2026-08-10).
    contest_on_decline: bool = False
    #: **What may be chosen**, as the dataclass this kind's options
    #: take (`OPTIONS`, below): the candidates, the distances, the
    #: hand, the hub's four lists -- and which of them the tutorial
    #: rails off. Built once, in `pending`, off the same engine
    #: calls the adapter refuses against, so a view, the web app and
    #: `driver.answer` read one list. `None` for the two kinds with
    #: nothing to choose (the tutorial's Continue, the finished game).
    options: Optional[PromptOptions] = None

    def to_dict(self) -> dict:
        """
        The question as JSON, for a frontend that renders it over a
        wire -- `d12ball.wire`. It is written and never read back: what
        comes the other way is an `Action`, checked against the
        position rather than against this.

        Every field is here, the options included, because a web page
        builds its controls from the same list a view builds its
        buttons from and nothing else (CLAUDE.md, "State and saves").
        `ask` carries the model's tokens as it stands; rendering them
        is the frontend's, at its own door.
        """
        return {
            "kind": self.kind.value,
            "ask": self.ask,
            "player_ids": list(self.player_ids),
            "player_id": self.player_id,
            "side": None if self.side is None else TeamSide(self.side).value,
            "maneuver_key": self.maneuver_key,
            "skill_type": self.skill_type,
            "free": self.free,
            "distance_moved": self.distance_moved,
            "contest_on_decline": self.contest_on_decline,
            "options": (
                None if self.options is None else self.options.to_dict()
            ),
        }


@dataclass(frozen=True)
class Action:
    """
    What somebody did, named by the question it answers.

    **It names a prompt rather than a step**, which is the whole
    difference between this and `FollowOn`. A step is what the bot does
    next and the model names it; an action is what a *person* did, and
    the only thing that makes it legal is that the match was waiting on
    exactly that question. So an action carries the `PromptKind` it
    answers and `apply` checks it against `pending_prompt` before
    anything is applied -- which is a rule about whose turn it is, and
    therefore the model's.

    `choice` is which of the prompt's answers it is, where a prompt
    offers more than one: "send" or "decline" on a loose ball, "take"
    or "decline" on a scoring opportunity. A string rather than a
    second enum, because the answers belong to the prompt and not to
    the game -- a kind with one answer leaves it empty, and an
    unrecognised one is refused the way a wrong kind is.

    `arguments` is what the person chose and nothing else: a space, a
    player, a distance. **Anything the position already says is read
    off the prompt instead**, which is why `apply` hands the
    `PendingPrompt` to the answer rather than only the action. The
    loose ball's `skill_type` and the set-up's two numbers are the
    model's own answers to its own question, and a frontend that had to
    send them back could send back different ones.

    Defined here rather than in `d12ball.flow.driver`, which is where
    it is read from, because the AI builds one (`AIStrategy.choose`)
    and the engine holds the AI: a prompt and its answer are one
    module's, and the driver re-exports it.
    """

    kind: PromptKind
    choice: str = ""
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """What was chosen, as JSON."""
        return {
            "kind": self.kind.value,
            "choice": self.choice,
            "arguments": jsonable(dict(self.arguments)),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Action":
        """
        An action off the wire -- **the one thing a frontend sends
        back**, and the only `from_dict` in `d12ball.wire`'s half of
        the world.

        The kind is built rather than taken as it arrives: `Action.kind`
        is compared to the prompt's by identity, so a kind left as the
        string a request carried is not the member it names and every
        such action would be refused as a stale click, which is a
        sentence about the game for what is a malformed request
        (finding 10 of docs/web-app.md). `PromptKind(...)` raises
        `ValueError` for a name the game does not have, which is the
        frontend's to answer at its door: nothing here has touched a
        game yet.

        The arguments are left as they arrive. They are what a person
        chose -- a space, a player, a distance -- and what each means is
        the adapter's (`d12ball.flow.driver.ANSWERS`), which is also
        where a `side` or a `formation` becomes the model's own type.
        """
        return cls(
            kind=PromptKind(data["kind"]),
            choice=data.get("choice") or "",
            arguments=dict(data.get("arguments") or {}),
        )


# -- What each kind offers ------------------------------------------
#
# **A dataclass per shape, not a flat list** (decision 2 of
# docs/web-app.md): the hub has four lists and a formation menu, and
# a flat list of strings would hand the model's structure back to the
# frontend to parse. Every list is a tuple so a prompt stays hashable
# and two readings of one position compare equal.
#
# **The rail is part of the offer.** Where the tutorial fixes a choice
# the options say which one, so a Discord view greys the rest and a
# web page does the same without asking `tutorial.resolve_choice`
# itself. The driver refuses off the same reading (`_rail`).


@dataclass(frozen=True)
class PlayerOptions:
    """
    A pick among players, nothing else to it: the ball handler, who of
    a stack runs back, who picks the ball up, who takes the shot, who
    loses the halftime token.
    """

    player_ids: tuple[str, ...]
    #: BALL_RECOVERY: how far each candidate is from the ball, in the
    #: order of `player_ids` -- the price on the button. Empty for the
    #: kinds where nothing is charged.
    distances: tuple[int, ...] = ()

    def to_dict(self) -> dict:
        return {
            "shape": "player",
            "player_ids": list(self.player_ids),
            "distances": list(self.distances),
        }



@dataclass(frozen=True)
class SendOptions:
    """
    A pick among players that may also be nobody -- the challenger,
    the loose-ball contestant. `may_decline` is the rule (a defender
    already on the ball pays no walk-in, so cannot decline to); a
    tutorial beat that rails the decline off says so in
    `decline_railed`, and the frontend builds the button dead rather
    than absent.
    """

    player_ids: tuple[str, ...]
    may_decline: bool
    decline_railed: bool = False
    #: How far each candidate is from the ball, in the order of
    #: `player_ids`: the walk-in a challenger pays, the reach a
    #: contestant needs. On the prompt so that a button's label and a
    #: web page's read one measure and neither asks the board itself.
    distances: tuple[int, ...] = ()

    def to_dict(self) -> dict:
        return {
            "shape": "send",
            "player_ids": list(self.player_ids),
            "may_decline": self.may_decline,
            "decline_railed": self.decline_railed,
            "distances": list(self.distances),
        }



@dataclass(frozen=True)
class SpaceOptions:
    """
    RUN_BACK_SPACE: where the prompt's player may run back to -- the
    spaces of their own zone, and what each costs. A run back is
    charged a token a space (`MatchState.run_back_distance`), so the
    distance is the price on the button, and it is on the prompt so
    that no frontend measures it itself.
    """

    space_indices: tuple[int, ...]
    zone: Optional[Zone] = None
    distances: tuple[int, ...] = ()

    def to_dict(self) -> dict:
        return {
            "shape": "space",
            "space_indices": list(self.space_indices),
            "zone": None if self.zone is None else Zone(self.zone).value,
            "distances": list(self.distances),
        }



@dataclass(frozen=True)
class DistanceOptions:
    """
    How far: a High Pass, a Setup Pass, a Dribble Advance, a Dribble
    Burst, the push back a beaten Setup Pass owes. `railed` is the one
    distance the tutorial allows, or `None`.
    """

    distances: tuple[int, ...]
    railed: Optional[int] = None
    #: SETUP_PASS_CHOICE with nowhere to go: the card's one way out of
    #: play, answered with no distance at all. Said outright rather
    #: than left for a frontend to infer from an empty list.
    may_pass_out: bool = False
    #: Quantor (Law 21): the teammate who may drain 3 to run onto this
    #: pass, and the distances they may run onto -- answered with the
    #: distance and `runner=True`. See `RulesEngine.pass_runner`.
    runner_id: Optional[str] = None
    runner_distances: tuple[int, ...] = ()

    def to_dict(self) -> dict:
        return {
            "shape": "distance",
            "distances": list(self.distances),
            "railed": self.railed,
            "may_pass_out": self.may_pass_out,
            "runner_id": self.runner_id,
            "runner_distances": list(self.runner_distances),
        }



@dataclass(frozen=True)
class PassOption:
    """One Low Pass on offer: the distance, and who is standing there
    to receive it (several where teammates share the space)."""

    distance: int
    receiver_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "distance": self.distance,
            "receiver_ids": list(self.receiver_ids),
        }


@dataclass(frozen=True)
class LowPassOptions:
    """LOW_PASS_CHOICE, plain, Skilled or free."""

    passes: tuple[PassOption, ...]

    def to_dict(self) -> dict:
        return {
            "shape": "low_pass",
            "passes": [option.to_dict() for option in self.passes],
        }


@dataclass(frozen=True)
class SpeedOptions:
    """SPEED_DELTA_CHOICE: the speeds within the player's reach."""

    targets: tuple[int, ...]
    railed: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "shape": "speed",
            "targets": list(self.targets),
            "railed": self.railed,
        }


@dataclass(frozen=True)
class TurnOptions:
    """
    PLAYER_ACTION: which of the three actions the position offers,
    in the order a frontend lays them out, and which of those the
    tutorial leaves live. A shot out of range is not offered at all;
    a railed one is offered and dead, so a coach reads in the lesson
    why it is not theirs yet.
    """

    actions: tuple[str, ...]
    live: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "shape": "turn",
            "actions": list(self.actions),
            "live": list(self.live),
        }


@dataclass(frozen=True)
class ManeuverHand:
    """
    One side's row on the maneuver prompt: the cards it may play
    (`RulesEngine.maneuver_tiers`, per side), the one the tutorial
    allows, and whether the side has picked already -- kept on the
    prompt rather than dropped, because the message is never edited
    and a restored view has to carry the same buttons.
    """

    side: str
    maneuver_keys: tuple[str, ...]
    picked: bool
    railed: Optional[str] = None
    #: Which side of the board holds this hand -- "offense" is whoever
    #: has the ball, and that is read once, here, rather than by each
    #: frontend and `asked_sides` separately.
    team_side: Optional[TeamSide] = None

    def to_dict(self) -> dict:
        return {
            "side": self.side,
            "maneuver_keys": list(self.maneuver_keys),
            "picked": self.picked,
            "railed": self.railed,
            "team_side": (
                None if self.team_side is None
                else TeamSide(self.team_side).value
            ),
        }



@dataclass(frozen=True)
class ManeuverOptions:
    """MANEUVER_ACTION: a hand per side on the prompt."""

    hands: tuple[ManeuverHand, ...]

    def owed(self) -> tuple[str, ...]:
        """The sides still to pick."""
        return tuple(hand.side for hand in self.hands if not hand.picked)

    def to_dict(self) -> dict:
        return {
            "shape": "maneuver",
            "hands": [hand.to_dict() for hand in self.hands],
        }


@dataclass(frozen=True)
class RollOptions:
    """
    The six roll prompts. The roll is the button either coach may
    press; what varies is who may declare Overdrive before it, and --
    on a score attempt alone -- whether the shot may still be walked
    back (`back`), and whether the tutorial has railed that walk-back
    off (`back_railed`).
    """

    overdrive_player_ids: tuple[str, ...]
    back: bool = False
    back_railed: bool = False
    # Gearclaw's Boost (Law 21): who may declare one on this roll.
    boost_player_ids: tuple[str, ...] = ()
    # What each offered Overdrive drains, `(player_id, drain)` -- 3,
    # or Voltus's 2 -- so a button's label is the prompt's number and
    # not a second reading of the rule.
    overdrive_costs: tuple[tuple[str, int], ...] = ()

    def overdrive_cost(self, player_id: str) -> int:
        return dict(self.overdrive_costs).get(
            player_id, OVERDRIVE_DRAIN_COST,
        )

    def to_dict(self) -> dict:
        return {
            "shape": "roll",
            "overdrive_player_ids": list(self.overdrive_player_ids),
            "boost_player_ids": list(self.boost_player_ids),
            "overdrive_costs": {
                player_id: cost for player_id, cost in self.overdrive_costs
            },
            "back": self.back,
            "back_railed": self.back_railed,
        }


@dataclass(frozen=True)
class DecisionOptions:
    """
    A yes or a no: take the set-up shot or decline it, take the ball
    over or leave it, reach for it or let it go, coach or pass.
    `choices` are this kind's two answers as `CHOICES` spells them; `railed` is the one the tutorial fixes, or `None`.
    """

    choices: tuple[str, ...]
    railed: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "shape": "decision",
            "choices": list(self.choices),
            "railed": self.railed,
        }


@dataclass(frozen=True)
class SmoothOptions:
    """
    A Smooth's yes and no, and **who keeps the ball on the no**.

    The decision is `DecisionOptions`' shape with one field added
    rather than that shape with a nullable field on it, because the
    field is a Smooth's alone: a Mind Pull declined leaves the ball
    with the other side, which the pull's own wording already says,
    and a coaching offer has no ball in it at all.

    `keeper_id` is `RulesEngine.smooth_keeper`'s answer -- the player
    the arrival this offer is holding back is about to leave holding
    it, or `None` where that arrival leaves nobody holding it (a loose
    ball, a new play). A frontend names them on the decline so the
    button says what declining *does* rather than only what it does
    not; where there is no keeper it has nothing to name and says the
    plain thing instead.
    """

    choices: tuple[str, ...]
    keeper_id: Optional[str] = None
    railed: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "shape": "smooth",
            "choices": list(self.choices),
            "keeper_id": self.keeper_id,
            "railed": self.railed,
        }


@dataclass(frozen=True)
class SwapOptions:
    """One fielded player and who they may change zones with."""

    player_id: str
    partner_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "partner_ids": list(self.partner_ids),
        }


@dataclass(frozen=True)
class RepositionSpace:
    """One space a meeple may move to within its zone, and which
    teammate has to come back to make room where several stand there
    (empty where the move is plain, or trades with the only one)."""

    space_index: int
    trade_with: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "space_index": self.space_index,
            "trade_with": list(self.trade_with),
        }


@dataclass(frozen=True)
class RepositionOptions:
    """One fielded player and the spaces of their zone they may move
    to -- every one but where they stand, the trade rule keeping
    coverage whichever is picked."""

    player_id: str
    spaces: tuple[RepositionSpace, ...]
    #: The zone the spaces are in -- the player's own -- so a label
    #: names the space without asking the setup where they stand.
    zone: Optional[Zone] = None

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "spaces": [space.to_dict() for space in self.spaces],
            "zone": None if self.zone is None else Zone(self.zone).value,
        }



@dataclass(frozen=True)
class CoachingHubOptions:
    """
    COACHING_HUB: the window's four sub-menus, for the side whose
    window is open. `formations` is empty where the occasion offers
    no positioning (the window before the shootout), as are `swaps`
    and `repositions`. `may_substitute` is the allowance *and* the
    pool: with either spent there is nobody to offer for anybody.
    """

    formations: tuple[Formation, ...]
    current_formation: Optional[Formation]
    may_substitute: bool
    outgoing_ids: tuple[str, ...]
    incoming_ids: tuple[str, ...]
    swaps: tuple[SwapOptions, ...]
    repositions: tuple[RepositionOptions, ...]
    #: Why the window may not be closed yet, or `None` -- the one
    #: thing that can hold a coach in it is their own kickoff space
    #: standing empty (`RulesEngine.coaching_finish_refusal`). The
    #: AI reads it to cover the space before it says it is done; a
    #: frontend may grey the button with it.
    finish_refusal: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "shape": "coaching_hub",
            "formations": [
                Formation(formation).value for formation in self.formations
            ],
            "current_formation": (
                None
                if self.current_formation is None
                else Formation(self.current_formation).value
            ),
            "may_substitute": self.may_substitute,
            "outgoing_ids": list(self.outgoing_ids),
            "incoming_ids": list(self.incoming_ids),
            "swaps": [swap.to_dict() for swap in self.swaps],
            "repositions": [
                reposition.to_dict() for reposition in self.repositions
            ],
            "finish_refusal": self.finish_refusal,
        }


@dataclass(frozen=True)
class SidePlayers:
    """One side's players on a shootout prompt: who may still be put
    in the order, or who may still shoot. Empty once that side has
    answered."""

    side: TeamSide
    player_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "side": TeamSide(self.side).value,
            "player_ids": list(self.player_ids),
        }


@dataclass(frozen=True)
class ShootoutOptions:
    """SHOOTOUT_ORDER and SHOOTOUT_PICK: both sides at once, each
    answering on its own menu."""

    sides: tuple[SidePlayers, ...]

    def owed(self) -> tuple[TeamSide, ...]:
        """The sides still to answer."""
        return tuple(entry.side for entry in self.sides if entry.player_ids)

    def for_side(self, side: TeamSide) -> tuple[str, ...]:
        """One side's players, or nothing once it has answered."""
        for entry in self.sides:
            if entry.side == side:
                return entry.player_ids
        return ()

    def to_dict(self) -> dict:
        return {
            "shape": "shootout",
            "sides": [entry.to_dict() for entry in self.sides],
        }


PromptOptions = Union[
    PlayerOptions,
    SendOptions,
    SpaceOptions,
    DistanceOptions,
    LowPassOptions,
    SpeedOptions,
    TurnOptions,
    ManeuverOptions,
    RollOptions,
    DecisionOptions,
    SmoothOptions,
    CoachingHubOptions,
    ShootoutOptions,
]


def shootout_order_prompt(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
) -> PendingPrompt:
    """
    The secret ordering, put to whichever sides still owe theirs.

    **One ask for the live question and the restored one**, the way
    `maneuver_action_ask` is: `periods.ask_shootout_orders` puts this
    up and the chain re-reads it, and it names only the sides still
    to answer -- so once the AI has set its order through the
    service, the coach reads a question addressed to them alone.
    """
    owing = [
        side
        for side in (TeamSide.HOME, TeamSide.VISITING)
        if not match.shootout_order_complete(side)
    ]
    return PendingPrompt(
        PromptKind.SHOOTOUT_ORDER,
        # Nobody has shot, so the usual "skill test 1 of 6, 0 — 0"
        # is a scoreline with nothing in it yet.
        "### Extreme shootout\n"
        f"{engine.shootout_mentions(game, match, owing)}: set the "
        "order your six players shoot in. Nobody else sees it.",
    )


def shootout_pick_prompt(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
) -> PendingPrompt:
    """Sudden death's pick, put to whichever sides still owe one --
    `shootout_order_prompt`'s reason."""
    owing = [
        side
        for side in (TeamSide.HOME, TeamSide.VISITING)
        if match.shootout_shooter(side) is None
    ]
    return PendingPrompt(
        PromptKind.SHOOTOUT_PICK,
        f"{engine.shootout_heading(match)}\n"
        f"{engine.shootout_mentions(game, match, owing)}: choose who "
        "goes out next, from the players who have not shot yet "
        "this round. Nobody else sees it until the reveal.",
    )


def run_back_prompt(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
) -> Optional[PendingPrompt]:
    """
    The run-back prompt for whichever player still needs a real choice.

    Any forced placements are always applied immediately in
    `continue_run_back`, before a message is ever posted, so anything
    still outstanding by the time this is called is an actual choice.

    Which of the two prompts it is is read back off the position,
    exactly as the cascade reads it: a stack with more than one player
    to spare comes back as the question of who runs, and everything
    else as the question of where.

    **A pick already made narrows the first question into the
    second.** `MatchState.run_back_pick` is the coach's answer to
    "who", recorded by `run_back_player_step`, and while it names one
    of the players the position still asks about the question is
    "where" for that player -- which is what the click that answers
    it is checked against. It used to live on the Discord message and
    nowhere else, so a restart asked "who" again and the driver
    refused "where" as a question the match had moved on from; see
    the field.
    """
    step = engine.next_run_back_step(game, match)
    if step is None:
        return None
    _, candidates = step
    picked = match.run_back_pick
    if len(candidates) == 1 or picked in candidates:
        return PendingPrompt(
            PromptKind.RUN_BACK_SPACE,
            "Choose where the next player runs back to:",
            player_id=picked if picked in candidates else candidates[0],
        )
    return PendingPrompt(
        PromptKind.RUN_BACK_PLAYER,
        "Choose which of your doubled-up players runs back:",
        player_ids=candidates,
    )


def loose_ball_pick_prompt(
    engine: "RulesEngine",
    match: MatchState,
) -> Optional[PendingPrompt]:
    """
    The loose-ball pick for the one side currently on the clock --
    purely from match state, so a bot restart mid-pick reconstructs
    correctly, same as `run_back_prompt`.

    `skill_type` is which side owes the pick and `side` is the board
    side that is, which is what names the candidates. They are two
    answers to one question and both are carried because the two views
    built from this need one each.
    """
    skill_type = engine.loose_ball_side_on_the_clock(match)
    if skill_type is None:
        return None
    return PendingPrompt(
        PromptKind.LOOSE_BALL_PICK,
        f"Choose who goes after the {contest_noun(match)}:",
        side=engine.loose_ball_prompt_side(match),
        skill_type=skill_type,
    )


def scoring_opportunity_prompt(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
) -> Optional[PendingPrompt]:
    """
    The scoring opportunity a coach has been asked about and has not
    answered: the attempt-or-decline offer, or the pick of who takes
    the shot.

    **Both were `FollowOnStep`s until Phase 6**, and for one reason:
    the view carried arguments match state did not hold, so a prompt
    carrying them would be a shape this chain could never produce --
    which is the second reading principle 3 is against. What closed
    them is `MatchState.pending_scoring_opportunity`, and what it
    holds is the *question*: the attempt's two numbers, which nothing
    in the position remembers, and for the shooter's pick nothing at
    all beyond the fact that it is being asked. The candidates are read
    back off the board here, where a restart reads everything else.

    The wording is the bare question. The live offer opens with the
    lines of the pass that set it up (see
    `d12ball.flow.arrivals.offer_scoring_attempt_choice`), which a
    restart has not got and does not invent -- the same difference the
    run back's prompt has carried since Phase 4.
    """
    outstanding = match.pending_scoring_opportunity or {}
    kind = outstanding.get("kind")

    if kind == "attempt":
        shooter = engine.get_player_definition(outstanding["shooter_id"])
        return PendingPrompt(
            PromptKind.SET_UP_ATTEMPT,
            f"{engine.format_player_label(match, shooter)} can "
            "attempt the scoring opportunity, or let it go:",
            player_id=shooter.player_id,
            distance_moved=outstanding.get("distance_moved", 1),
            contest_on_decline=outstanding.get(
                "contest_on_decline", False,
            ),
        )

    if kind == "shooter":
        candidates = engine.scoring_opportunity_candidates(
            match, match.ball.possession,
        )
        if not candidates:
            # The position no longer offers anybody the shot, which is
            # not a state the game can reach between the offer and the
            # answer -- nothing moves while a coach is being asked. A
            # save that says otherwise has been edited or has come
            # through a migration, and falling through to the turn
            # prompt is what every other unreadable corner of this
            # chain does.
            return None
        return PendingPrompt(
            PromptKind.SHOOTER_CHOICE,
            f"{shooter_mention(engine, game, match)}, choose who "
            "takes the shot:",
            player_ids=candidates,
        )

    return None


def shooter_mention(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
) -> str:
    """
    The coach who is being asked to send somebody after a scoring
    opportunity, as a mention.

    Shared by the live offer and the restored one so the two cannot
    word the same question differently -- which is the whole of
    principle 5 in one sentence.
    """
    return format_player_with_team(
        game,
        engine.possession_player_number(game, match),
        mention=True,
    )


def maneuver_prompt_wording(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    sides: list[str],
) -> tuple[list[str], str]:
    """
    Who is addressed above the maneuver prompt, and what they are told
    to do.

    Both come off the same `sides` list the buttons are built from,
    which is the point: a coach named here and given no row to press
    would stall a game, and nothing else would catch it.

    The instruction says what the position asks -- a pick, and a
    secret one -- and nothing about where the buttons are. Until step
    9 of docs/architecture-migration.md it named the row's colour
    ("from the red row", "red for the offense, green for the
    defense"), which is Discord's layout and not the game's; the
    Discord prompt words that for itself
    (`cogs.d12ball_helpers.build_maneuver_action_caption`), and a web
    page has its own buttons to point at.
    """
    waiting_on = [
        format_player_with_team(
            game,
            engine.possession_player_number(game, match)
            if side == "offense"
            else engine.defending_player_number(game, match),
            mention=True,
        )
        for side in sides
    ]

    instruction = (
        "choose a maneuver -- only you can see what you picked."
        if len(sides) == 1
        else "both sides pick privately -- only you can see what you picked."
    )
    return waiting_on, instruction


def maneuver_gambit_paragraph(ask: str, gambit_access: str) -> str:
    """
    Who holds their gambits, under the ask and above the cards --
    `""` for a basic game, which adds nothing. One join, so the
    Discord caption and the model's ask put the paragraph in the same
    place.
    """
    if gambit_access:
        return f"{ask}\n\n{gambit_access}"
    return ask


def maneuver_action_ask(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
) -> str:
    """
    The whole of what the maneuver prompt says: who is being asked,
    which row is theirs, and who holds their gambits.

    **One wording for the live prompt and the restored one.** The
    tutorial holds this prompt behind a note, and what goes up after
    the click is whatever `pending_prompt` says the match is waiting
    on -- so the restore's ask has to be the live one, or the coach
    would read a different question after the note from the one it
    was put in front of. See `d12ball.flow.gates`.

    Who holds their gambits goes under the instruction and above the
    cards. It is public knowledge either coach could work out from the
    scoreboard and the board (see `RulesEngine.may_play_gambits`), and
    `""` in the games and positions where the question does not arise
    -- so this adds a paragraph to an advanced prompt and nothing at
    all to a basic one.
    """
    sides = list(engine.maneuver_pick_sides(game, match))
    waiting_on, instruction = maneuver_prompt_wording(
        engine, game, match, sides,
    )
    return maneuver_gambit_paragraph(
        f"{' and '.join(waiting_on)}, {instruction}",
        engine.describe_gambit_access(game, match),
    )


def speed_choice_ask(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    player_id: str,
    skill_type: str,
) -> str:
    """
    The speed choice, worded for the coach whose player made the move:
    up to that player's skill, either way.

    One wording for the live prompt and the restored one, for
    `maneuver_action_ask`'s reason: the tutorial holds this one behind
    a note too.
    """
    skill_value = engine.skills(game, player_id).of(skill_type)
    mention = address_coach(
        engine.controlling_player_number(game, match, player_id),
    )
    return f"{mention}, manipulate the ball's speed (up to {skill_value}):"


#: Every effect choice is put up under the same line; what differs is
#: which choice is under it.
EFFECT_ASK = "Resolve the maneuver:"

#: What the score-attempt prompt says the first time it is put up.
#: The one thing the composition image does not show is how the two
#: rolls are read against each other, so it rides on the prompt --
#: which becomes the dice image the moment it is answered, taking the
#: explanation with it once it is no longer needed. A restart asks the
#: bare question instead (see `pending_prompt`).
SCORE_ATTEMPT_ASK = (
    "Either player can roll. Both sides roll one d12; the attacker "
    "scores on a total equal to or higher than the defence."
)


def effect_choice_prompt(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
) -> Optional[PendingPrompt]:
    """
    Whichever initial effect choice is pending for a decisively-won
    maneuver, purely from match state -- used both to restore it on a
    bot restart and (implicitly, by the same logic) to post it the
    first time. Returns None for a maneuver that needs no choice
    (Deflect, Pressure) or an unrecognized winner -- those resolve
    synchronously and should never actually leave this state persisted
    except in a narrow crash window, which falls back to
    `PromptKind.PLAYER_ACTION`.

    A Playmaker's Dribble Advance has two possible pending prompts
    (distance, then speed) with nothing in match state to tell them
    apart, so a restart in that narrow window guesses the first one --
    the same class of crash-window gap as the unrecognized-winner case
    above. A won Low Pass or High Pass that has moved on to its
    scoring-opportunity attempt/decline choice
    (`SetUpAttemptChoiceView`) has the same gap, as does a Low Pass
    waiting on which of several teammates on the destination space
    receives it (`LowPassReceiverView`): this always reconstructs the
    first-stage distance choice instead. Nothing has been applied by
    then, so the coach re-picks.
    """
    # **An effect continuation is read first**, because it says the
    # effect is already past the prompt its winner would restore.
    # Setup Pass's speed choice has been answered by the time one
    # is set, and a beaten Skilled Pass's Low Pass belongs to the
    # *defense* -- reading the winner there would put the steal's
    # speed choice back up and let a coach answer it twice. See
    # `continue_effect` for why the field outlives its dispatch.
    continuation = match.pending_effect_continuation or {}
    if continuation.get("kind") == "setup_pass_shot":
        return PendingPrompt(
            PromptKind.SETUP_PASS_CHOICE, EFFECT_ASK,
        )
    if continuation.get("kind") == "free_low_pass":
        return PendingPrompt(
            PromptKind.LOW_PASS_CHOICE,
            EFFECT_ASK,
            maneuver_key="low_pass",
            free=True,
        )

    winner_key = engine.settled_maneuver_winner(match)
    if winner_key is None:
        # Still owed a skill test, so no effect is pending yet.
        return None
    # A tie a skill test settled resolves as the basic card, so the
    # prompt restored has to be that card's -- see
    # `RulesEngine.resolving_maneuver`.
    winner_key = engine.resolving_maneuver(match, winner_key)
    if winner_key in ("low_pass", "skilled_pass"):
        return PendingPrompt(
            PromptKind.LOW_PASS_CHOICE, EFFECT_ASK, maneuver_key=winner_key,
        )
    if winner_key == "high_pass":
        return PendingPrompt(PromptKind.HIGH_PASS_CHOICE, EFFECT_ASK)
    if winner_key == "setup_pass":
        return _speed_delta(
            engine, game, match, match.active_player_id, "offense", winner_key,
        )
    if winner_key in ("dribble_advance", "dribble_burst"):
        handler = engine.get_player_definition(match.active_player_id)
        # **A Playmaker's advance has two prompts, and the carrier
        # tells them apart.** `select_ball_handler` clears
        # `ball_carrier_id` at the top of every turn and
        # `dribble_advance_step` is what sets it again, so a handler
        # recorded as carrying has already run and is owed the speed
        # choice; one who is not has not yet been asked how far. This
        # used to be the crash-window guess the docstring above
        # describes, and Phase 6 needed it exact: every click is
        # checked against this reading now, and a speed choice read
        # as a distance choice is a refused click.
        if (
            winner_key == "dribble_advance"
            and handler.role == PlayerRole.PLAYMAKER
            and match.ball_carrier_id != match.active_player_id
        ):
            return PendingPrompt(
                PromptKind.DRIBBLE_ADVANCE_CHOICE, EFFECT_ASK,
            )
        # A Dribble Burst asks a distance of everybody, not only a
        # Playmaker, and asks nothing else: the ball is left at 12
        # rather than offered to the handler (the author, 2026-09-20).
        # So a handler already on the last space of the field has
        # nothing to be asked at all, and the burst resolves like a
        # Deflect -- a crash window there falls back to the turn
        # prompt, the same as every other choiceless effect.
        if winner_key == "dribble_burst":
            if engine.dribble_burst_distances(match):
                return PendingPrompt(
                    PromptKind.DRIBBLE_BURST_CHOICE, EFFECT_ASK,
                )
            return None
        return _speed_delta(
            engine, game, match, match.active_player_id, "offense", winner_key,
        )
    if winner_key in ("steal", "intercept") or (
        winner_key in ("pressure", "double_team")
        and engine.gambit_cost(match, winner_key) == "dribble_burst"
    ):
        # The defense's speed step after a steal -- the card's own,
        # or **Dribble Burst's cost**: beaten by a pressure, the
        # defense takes the ball at the speed the burst put into it
        # and gets the same step once everyone is back in position
        # (`apply_pressure_turnover`). The run back answers ahead of
        # this while it lasts; after it the winner alone says a speed
        # choice is owed. Both read since step 6 of
        # docs/architecture-migration.md, when the full-game policy
        # first walked the burst's window and found the chain naming
        # the pressure's own resolution again.
        #
        # **Whose step it is, is whoever holds the ball after the run
        # back**, which `finish_run_back` hands on as
        # `pending_run_back_stays_player_id` -- the stealer as a rule,
        # but a substitution in the window before the run back moves
        # the exemption to whoever came on (`MatchState.substitute`).
        # Read off the same field, so a restart asks the same player
        # the step did; the challenger is the fallback for a save
        # from before the field was written.
        return _speed_delta(
            engine,
            game,
            match,
            match.pending_run_back_stays_player_id or match.challenger_id,
            "defense",
            winner_key,
        )
    if (
        winner_key in ("deflect", "clear")
        and engine.gambit_cost(match, winner_key) == "setup_pass"
        and not match.pending_loose_ball
        and match.pending_scoring_opportunity is None
    ):
        # **Setup Pass's cost**, still owed: the deflection has been
        # played and the ball is not yet loose, so the coach who beat
        # it is being asked how much further back it goes. Once the
        # loose ball begins the `pending_loose_ball` branch above
        # answers instead, and an overshoot into a shot is the
        # scoring opportunity's.
        return PendingPrompt(PromptKind.SETUP_PASS_PUSH_BACK, EFFECT_ASK)
    return None


def _speed_delta(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    player_id: Optional[str],
    skill_type: str,
    maneuver_key: str,
) -> PendingPrompt:
    return PendingPrompt(
        PromptKind.SPEED_DELTA_CHOICE,
        speed_choice_ask(engine, game, match, player_id, skill_type)
        if player_id is not None
        else EFFECT_ASK,
        player_id=player_id,
        skill_type=skill_type,
        maneuver_key=maneuver_key,
    )


def pending_prompt(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
) -> Optional[PendingPrompt]:
    """
    The prompt a saved match still owes: the question to put in front
    of whoever it is waiting on, and a line asking for it -- or `None`
    where nobody is asked, because the bot owes a step of its own
    (see `owed_step`).

    **This and `owed_step` are the two readers over `pending`, the
    only reading of "what is this match waiting on?"**, and the cog
    has two callers of this one that must not drift apart. Startup
    re-attaches the view to the message the prompt was already posted
    on (`turn_message_id`); `/d12ball resume` posts a fresh message
    carrying the same one, for the games where that message is gone,
    was never recorded, or was left with nothing live on it. A second
    copy of the chain is how a resume ends up offering a different
    prompt from the one a restart restores.
    """
    waiting = pending(engine, game, match)
    return waiting if isinstance(waiting, PendingPrompt) else None


def owed_step(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
) -> Optional[FollowOn]:
    """
    The step the bot itself owes on this position, or `None` where
    somebody is asked something instead (see `pending_prompt`).

    **"Asked" and "owed" are two functions over one chain** (decision
    1 of docs/web-app.md). A step inside a `PendingPrompt` would be a
    prompt every frontend had to know not to render; a step of its
    own is what `GameService.resume` runs and what `driver.answer`
    refuses against. The states that come back here are the ones a
    restart used to strand hardest -- the cascade's next step was the
    bot's, so there was no button anywhere -- and the ones a web
    request could otherwise land on mid-cascade.
    """
    waiting = pending(engine, game, match)
    return waiting if isinstance(waiting, FollowOn) else None


def asked_sides(
    match: MatchState,
    prompt: PendingPrompt,
) -> tuple[TeamSide, ...]:
    """
    Which side of the board a prompt is asked of -- the third reader
    over the chain, beside `pending_prompt` and `owed_step`.

    **One reading of "whose question is this"**, so the service can
    answer for an AI side (`GameService.run`) and, once step 9 of
    docs/architecture-migration.md lands, so a frontend can render
    the coach a line names. Empty for a question nobody in particular
    owns: the six rolls, which either coach may press (CLAUDE.md,
    "Nothing rolls dice on its own"), the tutorial's Continue and the
    finished game. Two sides for the questions put to both at once --
    the maneuver pick and the shootout's two menus -- narrowed to the
    sides still to answer, which the options already say.

    Read off the prompt's own parameters and the position, in that
    order: the side or the player the prompt names where it names
    one, the window's side, the defending side for the two questions
    put to the defense, and possession for everything else. It is a
    table by kind rather than a field on the prompt because every
    branch of the chain would otherwise have to set it, and one that
    forgot would read as nobody's.
    """
    kind = prompt.kind
    if kind in NOBODYS_QUESTIONS:
        return ()
    if kind is PromptKind.MANEUVER_ACTION:
        return tuple(
            hand.team_side
            for hand in prompt.options.hands
            if not hand.picked
        )
    if kind in (PromptKind.SHOOTOUT_ORDER, PromptKind.SHOOTOUT_PICK):
        return tuple(prompt.options.owed())
    if kind in (
        PromptKind.COACHING_HUB,
        PromptKind.COACHING_OFFER,
        PromptKind.HALFTIME_EXTRA_TOKEN,
        PromptKind.LOOSE_BALL_PICK,
    ):
        return (TeamSide(prompt.side),) if prompt.side is not None else ()

    if kind in PLAYERS_OWN_QUESTIONS:
        player_id = prompt.player_id or (
            prompt.player_ids[0] if prompt.player_ids else None
        )
        return (
            (match.side_for_player(player_id),)
            if player_id is not None else ()
        )
    if kind in DEFENSES_QUESTIONS:
        return (match.defending_side(),)
    return (match.ball.possession,)


#: The prompts nobody in particular is asked: either coach may press
#: the roll, and the other two have no side at all.
NOBODYS_QUESTIONS = frozenset({
    PromptKind.TUTORIAL_CONTINUE,
    PromptKind.GAME_OVER,
    PromptKind.INJURY_TEST,
    PromptKind.OWN_GOAL_ROLL,
    PromptKind.SHOOTOUT_TEST,
    PromptKind.LOOSE_BALL_SKILL_TEST,
    PromptKind.SCORE_ATTEMPT,
    PromptKind.SKILL_TEST,
})

#: The prompts put to whichever side the player they name is on --
#: a Telekinetic's two offers, the stealer's speed, the run back's
#: who and where.
PLAYERS_OWN_QUESTIONS = frozenset({
    PromptKind.MIND_PULL,
    PromptKind.SMOOTH,
    PromptKind.SPEED_DELTA_CHOICE,
    PromptKind.RUN_BACK_PLAYER,
    PromptKind.RUN_BACK_SPACE,
})

#: The two questions put to the defense: who challenges, and how far
#: back a beaten Setup Pass goes.
DEFENSES_QUESTIONS = frozenset({
    PromptKind.MANEUVER_CHALLENGE,
    PromptKind.SETUP_PASS_PUSH_BACK,
})


def pending(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
) -> Union[PendingPrompt, FollowOn]:
    """
    What this match is waiting on: a question for somebody, or the
    step the bot owes. Read through `pending_prompt` and `owed_step`;
    called directly only where either answer will do, which is a
    `StepResult.next` -- the tutorial's Continue, holding nothing,
    hands on to whichever it is.

    The chain is `_pending`; what this adds is the prompt's `options`
    (`OPTIONS`, by kind), built here once so every reader -- a view,
    `driver.answer`, a web page -- holds the same list.
    """
    waiting = _pending(engine, game, match)
    if isinstance(waiting, FollowOn):
        return waiting
    return with_options(engine, game, match, waiting)


def with_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> PendingPrompt:
    """
    The prompt with its options built off the position -- `OPTIONS`
    by kind, or the prompt as it was for a kind with nothing to
    choose.

    Two callers: `pending`, for the chain's own reading, and
    `driver.advance`, for the prompt a step hands back as its `next`
    -- the same question, worded by the step that reached it, and it
    has to carry the same list. Built off the prompt's own parameters
    (the player asked, the side, the card) so the two agree.
    """
    build = OPTIONS.get(prompt.kind)
    if build is None:
        return prompt
    return replace(prompt, options=build(engine, game, match, prompt))


def _pending(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
) -> Union[PendingPrompt, FollowOn]:
    """
    The chain itself -- see `pending`, which is this plus the options.

    Ordering matters more than it looks:

    - Setup and halftime come first because both leave
      `active_player_id` None, and the "no ball handler yet" branch
      would otherwise misread either as the kickoff.
    - `challenger_id` (or `maneuver_uncontested`) is what says a
      maneuver is under way, not `pending_action`, which
      `choose_challenger` clears the moment a challenger is picked.
    - An owed injury test and an owed own-goal roll come next, ahead of
      everything else, because both are interruptions of a turn whose
      own state is still set underneath them and would otherwise answer
      first.

    **A branch answers a `FollowOn` where its next step is the bot's,
    not a coach's** -- a run back with only forced placements left, a
    loose ball both sides have answered, an effect with no choice in
    it, the tail of a time out. Each names the step that drives that
    state on, which is the same step the flow reaches inline when it
    gets there in one run; the name is the door a resume comes back in
    through. There is no button to restore for any of them, and
    startup does not try: it skips the game and says so, and
    `/d12ball resume` runs the step.
    """
    if getattr(game, "tutorial_gate", None):
        # Ahead of everything: a note held behind Continue is a
        # click the game is waiting on before whatever the note
        # explains goes up, and nothing about the position says so
        # -- the position underneath is exactly what it was before
        # the note. See `d12ball.flow.gates`.
        return PendingPrompt(
            PromptKind.TUTORIAL_CONTINUE, tutorial.gate_text(game),
        )

    if getattr(game, "is_finished", False):
        # Nothing is asked of a finished game; what it waits on is
        # the rematch, which is the frontend's to offer. Ahead of the
        # branches below because the match under a finished game is
        # whatever full time or the shootout left there, and every
        # one of them would misread it.
        return PendingPrompt(PromptKind.GAME_OVER, "")

    if match.pending_setup_stage is not None:
        # Before kickoff, so active_player_id is None and the "no
        # ball handler yet" branch below would otherwise misread
        # this as the kickoff prompt -- the same reason halftime is
        # checked ahead of it.
        return _stage_window(
            engine,
            game,
            match,
            FollowOnStep.ADVANCE_SETUP_STAGE,
            "Coaching Choice, before kickoff:",
        )

    if match.pending_full_time_stage is not None:
        # Between the whistle and the shootout, so the turn is
        # already reset and every branch below would misread it.
        # Always the hub: the window is given rather than declared,
        # so there is no offer to come back to.
        return _stage_window(
            engine,
            game,
            match,
            FollowOnStep.ADVANCE_FULL_TIME_STAGE,
            "Coaching Choice, before the shootout:",
        )

    if match.pending_halftime_stage is not None:
        # Halftime resets active_player_id before its own stages
        # run, so it has to be checked ahead of the "no ball
        # handler yet" branch below, which would otherwise misread
        # halftime as kickoff.
        stage = engine.halftime_stage(match)
        if stage in ("extra_token_home", "extra_token_visiting"):
            side = (
                TeamSide.HOME
                if stage == "extra_token_home"
                else TeamSide.VISITING
            )
            # The same question `begin_halftime_extra_token` asks
            # before it puts the menu up: a side with nobody eligible
            # is passed over in silence, which is the stage's own
            # step. An AI side is asked like a coach and answers
            # through the service (`AIStrategy.choose`).
            eligible = [
                player_id
                for player_id in match.setup_for_side(side).field_players
                if player_id not in match.injured
            ]
            if not eligible:
                return FollowOn(FollowOnStep.ADVANCE_HALFTIME_STAGE)
            return PendingPrompt(
                PromptKind.HALFTIME_EXTRA_TOKEN,
                "Halftime: choose a player to clear an extra "
                "exhaustion token.",
                side=side,
            )
        # coaching_home / coaching_visiting. Always the hub:
        # halftime never asks whether to declare, so there is no
        # offer to come back to, unlike an ordinary turnover's
        # window below. A part-made pick inside the flow is not
        # persisted and restarts here, the same simplification a
        # run-back choice makes.
        return _stage_window(
            engine,
            game,
            match,
            FollowOnStep.ADVANCE_HALFTIME_STAGE,
            "Halftime Coaching Choice:",
        )

    if match.pending_smooth:
        # The two queues are never both full: `check_for_ball_arrival`
        # queues every pull on the path first and the Smooth where the
        # ball lands only once they have drained -- so this branch and
        # the pull's below could come in either order. The stage a
        # restart comes back to is read off the queue that is full and
        # the path (`continue_mind_pull`), not off this order.
        player = engine.get_player_definition(match.pending_smooth[0])
        smooth_emoji = tokens.species(SPECIES_TELEKINETIC)
        return PendingPrompt(
            PromptKind.SMOOTH,
            # **It names the ability**, the way the live offer
            # `continue_smooth` puts up does: a coach coming back to a
            # restored question has not got the line that opened it,
            # and "can still take the ball over" read as a rule
            # nobody could place (the author, 2026-09-22). "Still" is
            # this branch's own word, and the only thing left that
            # tells the two apart.
            f"{smooth_emoji} **Smooth** — "
            f"{engine.format_player_label(match, player)} can still take "
            "the ball to become the ball handler:",
            player_id=player.player_id,
        )

    if match.pending_mind_pull:
        # Ahead of the injury tests and of everything a maneuver
        # leaves set, for a stronger version of their reason: a
        # pull interrupts an arrival that has *not happened yet*,
        # so the maneuver's own state is still exactly as it was
        # and every branch below would resolve the arrival this is
        # holding back. It is also the one interrupt that can
        # change who has the ball, so answering it first is what
        # keeps the rest of the chain reading a settled position.
        player = engine.get_player_definition(match.pending_mind_pull[0])
        return PendingPrompt(
            PromptKind.MIND_PULL,
            f"{engine.format_player_label(match, player)} can still reach "
            "for the ball:",
            player_id=player.player_id,
        )

    if match.pending_injury_tests:
        # Ahead of everything a contest leaves set, because that is
        # all still set: a maneuver's skill test comes back here
        # with its challenger and both picks in place, and a loose
        # ball with no active player at all, which the kickoff
        # branch below would misread.
        player = engine.get_player_definition(match.pending_injury_tests[0])
        test_name = engine.injury_test_name(game, player.player_id)
        return PendingPrompt(
            PromptKind.INJURY_TEST,
            f"{engine.format_player_label(match, player)} still "
            f"owes {'a' if test_name[0] not in 'aeiou' else 'an'} "
            f"{test_name}:",
            player_id=player.player_id,
        )

    if match.pending_own_goal:
        # Same reason: the Pressure that risked it is still the
        # live maneuver, so the effect branch would otherwise offer
        # to resolve it a second time.
        return PendingPrompt(
            PromptKind.OWN_GOAL_ROLL,
            "Either player can roll for the own goal.",
        )

    scoring_opportunity = scoring_opportunity_prompt(engine, game, match)
    if scoring_opportunity is not None:
        # After the interrupts and ahead of everything a maneuver
        # leaves set, which is the same reason the own-goal roll is:
        # the pass that opened the scoring opportunity is still the
        # live maneuver, so the effect branch below would offer to
        # resolve it a second time. Behind the interrupts because a
        # scoring opportunity is an arrival like any other and both
        # gates run in front of it -- `offer_scoring_attempt_choice`
        # calls `check_for_ball_arrival` before it asks anybody, so a
        # match in this state has already drained them.
        return scoring_opportunity

    if match.pending_shootout:
        # The three shootout states, read off the same three
        # questions `advance_shootout` asks and in the same order.
        # It comes after the injury queue because a shootout skill
        # test owes its checks before the next one is set up, and
        # ahead of everything below because the match underneath a
        # shootout is still whatever full time left there. An AI
        # side's order or shooter is asked of it like a coach's
        # (`ShootoutOptions.owed`), and the service answers for it.
        if not match.shootout_orders_complete:
            return shootout_order_prompt(engine, game, match)
        if not match.shootout_shooters_complete:
            return shootout_pick_prompt(engine, game, match)
        return PendingPrompt(
            PromptKind.SHOOTOUT_TEST,
            "Either player can roll the shootout skill test:",
        )

    if match.pending_time_out:
        # A time out resets the turn before either window opens,
        # so active_player_id is None and the kickoff branch below
        # would misread it -- the same reason setup and halftime
        # are checked ahead of that one. Always the hub: ceding is
        # what bought the window, so neither coach is ever asked
        # whether to take it. With no window open the cascade died
        # between the second one closing and the tail behind it,
        # and the tail is the bot's.
        if match.pending_coaching_side is not None:
            return _window(
                engine,
                game,
                match,
                PromptKind.COACHING_HUB,
                "Coaching Choice, on the time out:",
            )
        return FollowOn(FollowOnStep.FINISH_TIME_OUT)

    if match.pending_coaching_side is not None:
        # A window mid-flight comes back as either the offer or the
        # menu. A part-made choice (picked who goes off, not yet
        # who comes on) is not persisted and restarts at the menu,
        # the same way a run-back choice does.
        #
        # **Ahead of the kickoff branch below**, because a new play's
        # window opens after the reset has cleared the turn: a window
        # offered after a missed shot has no ball handler yet, and
        # read the other way round it was the kickoff prompt -- which
        # a restart put up over an open window, and which Phase 6
        # then refused the window's own answers against.
        if match.pending_coaching_declared:
            return _window(
                engine, game, match, PromptKind.COACHING_HUB,
                "Coaching Choice:",
            )
        return _window(
            engine, game, match, PromptKind.COACHING_OFFER,
            "Coaching Choice — coach, or pass?",
        )

    if match.pending_run_back:
        # A choice a coach still has to make, or the cascade's own
        # next pass: the forced placements, an AI side's picks and
        # the drop back into an empty kickoff are all
        # `continue_run_back`'s, and a position with nothing left to
        # ask is that step's to finish.
        return run_back_prompt(engine, game, match) or FollowOn(
            FollowOnStep.CONTINUE_RUN_BACK,
        )

    if match.pending_ball_recovery:
        # An out-of-bounds ball whose run back has already
        # finished, waiting on the winning side to send someone to
        # pick it up -- unless the step has nobody to ask: a side
        # with somebody already on the ball, or nobody fielded at
        # all, places no one. The question is `begin_ball_recovery`'s
        # own.
        side = match.ball.possession
        candidates = (
            [] if match.eligible_ball_handlers()
            else match.contest_candidates(side)
        )
        if not candidates:
            return FollowOn(FollowOnStep.BEGIN_BALL_RECOVERY)
        return PendingPrompt(
            PromptKind.BALL_RECOVERY,
            "Send the nearest player either side of the ball to "
            "pick it up at "
            f"{ball_space_label(match)}:",
        )

    if match.pending_loose_ball:
        # Named off the position like every other message on this
        # path: only a ball lying where nobody stands is loose, and
        # a resume that calls a contest -- or a High Pass -- a
        # loose ball misreads it in front of the coach about to
        # act on it. See contest_noun.
        noun = contest_noun(match)
        if (
            match.loose_ball_offense_player is not None
            and match.loose_ball_defense_player is not None
        ):
            return PendingPrompt(
                PromptKind.LOOSE_BALL_SKILL_TEST,
                f"Either player can roll for the {noun}:",
            )
        # Both sides answered and fewer than two players sent: out of
        # bounds or an unopposed take, and settling it is the step's.
        return loose_ball_pick_prompt(engine, match) or FollowOn(
            FollowOnStep.RESOLVE_LOOSE_BALL,
        )

    if match.active_player_id is None:
        # No ball handler yet: the kickoff. **Behind every flag a
        # position can carry** -- a run back, a pickup, a loose ball
        # -- because each of those is a position with no handler in
        # it that is not a kickoff: a new play's reset clears the turn
        # before its run back, and a contest can be lying on the
        # board with nobody having taken the ball. Read ahead of them,
        # as it used to be, this branch answered "choose who takes the
        # ball" over a run back's own question -- which a restart put
        # up, and which Phase 6 refused the run back's answers against.
        return PendingPrompt(
            PromptKind.BALL_HANDLER_SELECTION, "Choose who takes the ball:",
        )

    if match.pending_action == "shoot":
        return PendingPrompt(
            PromptKind.SCORE_ATTEMPT,
            "Either player can roll for the score attempt.",
        )

    if match.pending_action == "maneuver" and match.challenger_id is None:
        return PendingPrompt(
            PromptKind.MANEUVER_CHALLENGE,
            "Choose who challenges the maneuver:",
        )

    if match.challenger_id is not None or match.maneuver_uncontested:
        # challenger_id is only ever set while a maneuver is in
        # progress and cleared by reset_maneuver(), so it alone
        # disambiguates this from any other phase -- pending_action
        # itself is cleared to None by choose_challenger() right
        # when the challenger is picked, so it can't be relied on
        # from here on. maneuver_uncontested says the same thing
        # for a maneuver that never had a challenger, and is
        # cleared by the same reset.
        if not match.maneuver_selections_complete:
            return PendingPrompt(
                PromptKind.MANEUVER_ACTION,
                maneuver_action_ask(engine, game, match),
            )
        winner_key = engine.settled_maneuver_winner(match)
        if winner_key is None:
            # No winner yet means a skill test is owed -- a tie, or
            # a decisive maneuver an injured player still has to
            # roll for. Asking the ranking directly here would get
            # both wrong.
            return PendingPrompt(
                PromptKind.SKILL_TEST, "Either player can roll:",
            )
        # A won card with nothing to ask -- a Deflect, a Pressure, a
        # burst from the last space -- resolves by running its
        # effect, which is the step the reveal names.
        return effect_choice_prompt(engine, game, match) or FollowOn(
            FollowOnStep.BEGIN_EFFECT_RESOLUTION, {"winner_key": winner_key},
        )

    return PendingPrompt(PromptKind.PLAYER_ACTION, "Choose an action:")


def _window(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    kind: PromptKind,
    ask: str,
) -> Union[PendingPrompt, FollowOn]:
    """
    An open Coaching Choice: the menu or the offer, for the side whose
    window it is. An AI side's is the same prompt -- it answers it
    through the service, one hub action at a time, the way a coach
    does (step 7 of docs/architecture-migration.md).

    The Spreadable reminder is part of the window's ask wherever the
    window is read, not only where it opened -- see
    `RulesEngine.spreadable_note`.
    """
    side = TeamSide(match.pending_coaching_side)
    ask = "\n".join(
        part for part in (ask, engine.spreadable_note(game, match, side))
        if part
    )
    return PendingPrompt(kind, ask, side=side)


def _stage_window(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    advance: FollowOnStep,
    ask: str,
) -> Union[PendingPrompt, FollowOn]:
    """
    One stage of setup, halftime or full time: the hub where its
    window is open, and the stage's own advance where it is not --
    the process died between setting the stage and opening the
    window, and re-driving the sequence is what puts it up.

    The open window is read first for the reason `GameService.resume`
    used to spell out: the advancers would re-open it, which resets
    the allowance a coach had already spent.
    """
    if match.pending_coaching_side is None:
        return FollowOn(advance)
    return _window(engine, game, match, PromptKind.COACHING_HUB, ask)


# -- Building the options --------------------------------------------


#: Which players a given roll prompt puts an Overdrive offer to.
#:
#: **The same six lists the views build their buttons from**, which is
#: what makes this one reading rather than two: `RollOptions` carries
#: whichever of them `RulesEngine.overdrive_candidates` still allows,
#: and an action naming anybody else is refused by
#: `d12ball.flow.rolls.declare_overdrive_step` against this same list.
#:
#: It is keyed on the prompt because that is what a declaration is
#: attached to -- Overdrive is declared *before* a roll and spent by
#: it, so "which roll are we in" is the whole of what decides who may
#: take one. The six are the rules' own list. It lived in `rolls.py`
#: until the options were built here.
OVERDRIVE_ROLLERS = {
    PromptKind.SKILL_TEST: lambda match, prompt: [
        match.active_player_id, match.challenger_id,
    ],
    PromptKind.LOOSE_BALL_SKILL_TEST: lambda match, prompt: [
        match.loose_ball_offense_player, match.loose_ball_defense_player,
    ],
    PromptKind.SCORE_ATTEMPT: lambda match, prompt: [
        match.active_player_id,
    ],
    PromptKind.OWN_GOAL_ROLL: lambda match, prompt: [
        match.active_player_id,
    ],
    PromptKind.INJURY_TEST: lambda match, prompt: [prompt.player_id],
    PromptKind.SHOOTOUT_TEST: lambda match, prompt: [
        match.shootout_shooter(side)
        for side in (TeamSide.HOME, TeamSide.VISITING)
    ],
}


#: The six prompts a roll is asked on, and therefore the six an
#: Overdrive can be declared on. The rules' own list.
ROLL_KINDS = frozenset(OVERDRIVE_ROLLERS)


#: Which of a prompt's answers each kind offers, where it offers more
#: than one.
#:
#: One table, beside `OPTIONS`: `DecisionOptions.choices` is built
#: from it and `driver.answer` refuses against it, so a button and the
#: refusal cannot spell an answer differently. An unlisted kind takes
#: the empty choice and nothing else, which is what a prompt with one
#: answer means.
CHOICES: Mapping[PromptKind, tuple[str, ...]] = {
    # **Every roll prompt offers two answers**, and the second one
    # does not settle it: Overdrive is declared before the dice and
    # the roll is still owed afterwards. `SCORE_ATTEMPT` has its
    # own third, below, because a declared shot can also be walked
    # back.
    **{
        kind: ("roll", "overdrive", "boost")
        for kind in ROLL_KINDS
    },
    PromptKind.LOOSE_BALL_PICK: ("send", "decline"),
    PromptKind.SET_UP_ATTEMPT: ("take", "decline"),
    PromptKind.SMOOTH: ("take", "decline"),
    PromptKind.MIND_PULL: ("take", "decline"),
    PromptKind.MANEUVER_CHALLENGE: ("send", "decline"),
    PromptKind.PLAYER_ACTION: ("shoot", "maneuver", "time_out"),
    PromptKind.SHOOTOUT_ORDER: ("send", "restart"),
    PromptKind.COACHING_OFFER: ("declare", "decline"),
    PromptKind.COACHING_HUB: (
        "formation", "substitute", "swap", "reposition", "done",
    ),
    PromptKind.SCORE_ATTEMPT: ("roll", "back", "overdrive", "boost"),
}


def overdrive_rollers(
    match: MatchState,
    prompt: PendingPrompt,
) -> list[str]:
    """Who is rolling, for the roll this prompt is asking for."""
    rollers = OVERDRIVE_ROLLERS.get(prompt.kind)
    if rollers is None:
        return []
    return [player_id for player_id in rollers(match, prompt) if player_id]


def _railed(game: D12BallGame, key: str, options) -> Optional[object]:
    """The one option the tutorial allows out of `options`, or None."""
    return tutorial.resolve_choice(tutorial.beat_for_game(game), key, options)


def _decline_railed(game: D12BallGame, key: str) -> bool:
    """Whether the tutorial has railed this prompt's decline off."""
    return _railed(game, key, ("never",)) == "never"


def _roll_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> RollOptions:
    return RollOptions(**_declarations(engine, game, match, prompt))


def _declarations(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> dict:
    """
    The declarations a roll prompt offers before its die: Overdrive,
    with what each drains, and Gearclaw's Boost.
    """
    rollers = overdrive_rollers(match, prompt)
    overdrives = tuple(engine.overdrive_candidates(game, match, rollers))
    return {
        "overdrive_player_ids": overdrives,
        "boost_player_ids": tuple(
            engine.boost_candidates(game, match, rollers),
        ),
        "overdrive_costs": tuple(
            (player_id, engine.overdrive_cost(game, player_id))
            for player_id in overdrives
        ),
    }


def _score_attempt_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> RollOptions:
    # A shot not yet rolled always has somewhere to walk back to, and
    # only a coach's own shot is walked back: an AI side's stands
    # (`rolls.retract_shot_step`). A tutorial beat that rails a
    # set-up shot to "attempt" is railing this same choice, since Back
    # leads straight to that offer's decline.
    return replace(
        _roll_options(engine, game, match, prompt),
        back=(
            match.may_cancel_pending_shot()
            and not engine.side_is_ai(game, match.ball.possession)
        ),
        back_railed=(
            match.pending_shot_is_set_up
            and _railed(game, "setup_attempt", ("attempt", "decline"))
            == "attempt"
        ),
    )


def _turn_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> TurnOptions:
    actions = ["maneuver"]
    if match.can_attempt_score():
        actions.append("shoot")
    if match.may_call_time_out():
        actions.append("time_out")
    allowed = tutorial.allowed_actions(tutorial.beat_for_game(game))
    live = [
        action for action in actions
        if allowed is None or action in allowed
    ]
    return TurnOptions(tuple(actions), tuple(live))


def _maneuver_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> ManeuverOptions:
    beat = tutorial.beat_for_game(game)
    hands = []
    for side in engine.maneuver_pick_sides(game, match):
        allowed = tutorial.allowed_maneuvers(beat, side)
        picked = (
            match.offense_maneuver if side == "offense"
            else match.defense_maneuver
        )
        hands.append(ManeuverHand(
            side=side,
            maneuver_keys=tuple(
                card.key for card in engine.maneuver_hand(game, match, side)
            ),
            picked=picked is not None,
            railed=allowed[0] if allowed else None,
            team_side=(
                match.ball.possession if side == "offense"
                else match.defending_side()
            ),
        ))

    return ManeuverOptions(tuple(hands))


def _challenge_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> SendOptions:
    candidates = tuple(match.challenge_candidates())
    return SendOptions(
        player_ids=candidates,
        may_decline=match.may_decline_challenge(),
        decline_railed=_decline_railed(game, "challenge_decline"),
        distances=_distances_to_ball(match, candidates),
    )



def _loose_ball_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> SendOptions:
    candidates = tuple(engine.loose_ball_candidates(match, prompt.side))
    return SendOptions(
        player_ids=candidates,
        may_decline=match.may_decline_loose_ball(prompt.side),
        decline_railed=_decline_railed(game, "loose_ball_decline"),
        distances=_distances_to_ball(match, candidates),
    )


def _distances_to_ball(
    match: MatchState, player_ids: tuple[str, ...],
) -> tuple[int, ...]:
    """Each candidate's distance to the ball, in their order."""
    return tuple(match.distance_to_ball(player_id) for player_id in player_ids)



def _handler_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> PlayerOptions:
    # Not `eligible_ball_handlers`: a ball carrier narrows this to one.
    return PlayerOptions(tuple(engine.turn_handler_candidates(game, match)))


def _named_players(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> PlayerOptions:
    """RUN_BACK_PLAYER and SHOOTER_CHOICE: the branch already named
    them."""
    return PlayerOptions(tuple(prompt.player_ids))


def _run_back_space_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> SpaceOptions:
    side = match.side_for_player(prompt.player_id)
    zone = match.setup_for_side(side).assigned_zone(prompt.player_id)
    spaces = tuple(
        engine.placement_spaces_in_zone(
            game, match, side, zone, prompt.player_id,
        ),
    )
    return SpaceOptions(
        spaces,
        zone=zone,
        distances=tuple(
            match.run_back_distance(prompt.player_id, zone, space_index)
            for space_index in spaces
        ),
    )



def _ball_recovery_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> PlayerOptions:
    candidates = tuple(match.contest_candidates(match.ball.possession))
    return PlayerOptions(candidates, _distances_to_ball(match, candidates))



def _halftime_token_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> PlayerOptions:
    return PlayerOptions(tuple(
        player_id
        for player_id in match.setup_for_side(prompt.side).field_players
        if player_id not in match.injured
    ))


def _set_up_attempt_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> DecisionOptions:
    # The script names the rail as the button did ("attempt"); the
    # answer is `CHOICES`' word for it.
    railed = _railed(game, "setup_attempt", ("attempt", "decline"))
    return DecisionOptions(
        CHOICES[PromptKind.SET_UP_ATTEMPT],
        railed={"attempt": "take", "decline": "decline"}.get(railed),
    )


def _decision_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> DecisionOptions:
    """A yes or a no, spelled as `CHOICES` spells this kind's."""
    return DecisionOptions(CHOICES[prompt.kind])


def _smooth_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> SmoothOptions:
    """The same yes and no, and the player the no leaves the ball
    with (`RulesEngine.smooth_keeper`)."""
    return SmoothOptions(
        CHOICES[prompt.kind],
        keeper_id=engine.smooth_keeper(match),
    )


def _low_pass_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> LowPassOptions:
    key = prompt.maneuver_key or "low_pass"
    return LowPassOptions(tuple(
        PassOption(
            distance,
            tuple(engine.low_pass_receivers(match, distance)),
        )
        for distance, _ in engine.pass_candidates(match, key)
    ))


def _high_pass_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> DistanceOptions:
    distances = tuple(engine.high_pass_distance_options(match))
    runner_id, runner_distances = engine.pass_runner(game, match, distances)
    return DistanceOptions(
        distances,
        _railed(game, "high_pass", distances),
        runner_id=runner_id,
        runner_distances=runner_distances,
    )


def _setup_pass_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> DistanceOptions:
    # Empty is the card's one way out of play: a pass with nowhere to
    # go, which the answer sends with no distance at all.
    distances = tuple(engine.setup_pass_distances(match))
    runner_id, runner_distances = engine.pass_runner(game, match, distances)
    return DistanceOptions(
        distances,
        may_pass_out=not distances,
        runner_id=runner_id,
        runner_distances=runner_distances,
    )



def _speed_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> SpeedOptions:
    targets = tuple(
        engine.speed_targets(
            match, prompt.player_id, prompt.skill_type, game,
        ),
    )
    # The tutorial's speed rail is "take the highest offered" -- the
    # cap is the stealer's own defensive skill, so the script cannot
    # name a number.
    return SpeedOptions(targets, _railed(game, "speed", targets))


def _dribble_advance_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> DistanceOptions:
    distances = engine.dribble_advance_distances(game, match)
    return DistanceOptions(
        distances, _railed(game, "dribble_advance", distances),
    )


def _dribble_burst_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> DistanceOptions:
    return DistanceOptions(tuple(engine.dribble_burst_distances(match)))


def _push_back_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> DistanceOptions:
    return DistanceOptions(tuple(engine.setup_pass_push_back_distances(match)))


def _shootout_order_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> ShootoutOptions:
    return ShootoutOptions(tuple(
        SidePlayers(side, tuple(match.shootout_order_remaining(side)))
        for side in (TeamSide.HOME, TeamSide.VISITING)
    ))


def _shootout_pick_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> ShootoutOptions:
    return ShootoutOptions(tuple(
        SidePlayers(
            side,
            () if match.shootout_shooter(side) is not None
            else tuple(match.shootout_eligible(side)),
        )
        for side in (TeamSide.HOME, TeamSide.VISITING)
    ))


def _coaching_hub_options(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
) -> CoachingHubOptions:
    side = TeamSide(match.pending_coaching_side)
    setup = match.setup_for_side(side)
    occasion = match.coaching_occasion
    positioning = occasion is None or occasion.offers_positioning
    pool = tuple(match.substitution_pool(side))
    fielded = tuple(setup.field_players)
    team = set(fielded)

    swaps: list[SwapOptions] = []
    repositions: list[RepositionOptions] = []
    if positioning:
        for player_id in fielded:
            zone = setup.assigned_zone(player_id)
            swaps.append(SwapOptions(
                player_id,
                tuple(
                    other for other in fielded
                    if other != player_id
                    and setup.assigned_zone(other) != zone
                ),
            ))
            standing = match.board.meeple_position(player_id)
            spaces = []
            for space_index in range(len(match.board.spaces[zone])):
                if standing == (zone, space_index):
                    continue
                spaces.append(RepositionSpace(
                    space_index,
                    tuple(
                        other
                        for other in match.board.spaces[zone][space_index]
                        if other in team
                    ),
                ))
            repositions.append(
                RepositionOptions(player_id, tuple(spaces), zone=zone),
            )


    return CoachingHubOptions(
        formations=(
            tuple(engine.available_formations(match)) if positioning else ()
        ),
        current_formation=(
            engine.current_formation(match, side) if positioning else None
        ),
        may_substitute=match.may_substitute() and bool(pool),
        outgoing_ids=fielded if pool else (),
        incoming_ids=pool,
        swaps=tuple(swaps),
        repositions=tuple(repositions),
        finish_refusal=engine.coaching_finish_refusal(match, side),
    )


#: What each kind offers, built off the position -- the second table
#: over `PromptKind` beside the chain, and the one a frontend builds
#: its buttons from. A kind with no row (the tutorial's Continue, the
#: finished game) has nothing to choose.
OPTIONS = {
    PromptKind.COACHING_HUB: _coaching_hub_options,
    PromptKind.COACHING_OFFER: _decision_options,
    PromptKind.HALFTIME_EXTRA_TOKEN: _halftime_token_options,
    PromptKind.MIND_PULL: _decision_options,
    PromptKind.SMOOTH: _smooth_options,
    PromptKind.INJURY_TEST: _roll_options,
    PromptKind.OWN_GOAL_ROLL: _roll_options,
    PromptKind.SHOOTOUT_ORDER: _shootout_order_options,
    PromptKind.SHOOTOUT_PICK: _shootout_pick_options,
    PromptKind.SHOOTOUT_TEST: _roll_options,
    PromptKind.PLAYER_ACTION: _turn_options,
    PromptKind.BALL_HANDLER_SELECTION: _handler_options,
    PromptKind.RUN_BACK_SPACE: _run_back_space_options,
    PromptKind.RUN_BACK_PLAYER: _named_players,
    PromptKind.BALL_RECOVERY: _ball_recovery_options,
    PromptKind.LOOSE_BALL_PICK: _loose_ball_options,
    PromptKind.LOOSE_BALL_SKILL_TEST: _roll_options,
    PromptKind.SCORE_ATTEMPT: _score_attempt_options,
    PromptKind.SET_UP_ATTEMPT: _set_up_attempt_options,
    PromptKind.SHOOTER_CHOICE: _named_players,
    PromptKind.MANEUVER_CHALLENGE: _challenge_options,
    PromptKind.MANEUVER_ACTION: _maneuver_options,
    PromptKind.SKILL_TEST: _roll_options,
    PromptKind.LOW_PASS_CHOICE: _low_pass_options,
    PromptKind.HIGH_PASS_CHOICE: _high_pass_options,
    PromptKind.SETUP_PASS_CHOICE: _setup_pass_options,
    PromptKind.SPEED_DELTA_CHOICE: _speed_options,
    PromptKind.DRIBBLE_ADVANCE_CHOICE: _dribble_advance_options,
    PromptKind.DRIBBLE_BURST_CHOICE: _dribble_burst_options,
    PromptKind.SETUP_PASS_PUSH_BACK: _push_back_options,
}

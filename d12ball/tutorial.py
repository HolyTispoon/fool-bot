"""
The scripted opening a `/d12ball create_game tutorial:true` game plays
before it becomes an ordinary game against Dinky.

**Every lesson is a real turn.** The tutorial does not simulate the
game or draw pictures of it: it sets a position, says what to press and
why, and then the coach presses it on the same buttons, the same board
and the same maneuver cards they will use for the rest of the match.
That is the whole design, and two things follow from it.

- **`/d12ball resume` and restart recovery work unchanged.** A lesson
  leaves the match in states the game already knows how to resume, so
  nothing here adds a branch to `pending_turn_view` and nothing here is
  a step only a live interaction can carry forward. What a restart can
  lose is a lesson's *text*, which is already in the channel above the
  prompt it explained.
- **A beat sets its own position** (`apply_beat`), through
  `MatchState.deploy_side` -- the same atomic, exhaustion-free
  placement a formation change is made of. So a beat cannot inherit a
  mess from the one before it, and the five specs below can be read as
  what the coach will actually be looking at.

**The rails.** A beat names the turn action and the maneuver the coach
must pick, and the views build every other button *disabled* rather
than omitting it (`allowed_actions`, `allowed_maneuvers`) -- the point
is to learn what the hand holds while only one card is live. The rails
come off after the last beat.

Sub-choices are deliberately **not** railed: a Low Pass's destination,
a Dribble Advance's distance, a ball-speed delta and a run-back space
are all legal moves with no wrong answer, and they are where a coach
learns by doing. Which maneuver outranks which is what decides a beat's
outcome, so leaving those free cannot stop a lesson landing. The one
exception is beat 5's High Pass distance (`forced_high_pass_distance`),
because a pass of 2 is what puts the ball on the striker in range and
turns the beat into the set-up shot it exists for.

**Positions are written from the coach's own goal forward**, as
`board_size` matters and which side the coach ended up on does not:
`absolute_index` mirrors a spec for a coach playing the visiting side,
exactly the way a formation is read (see "Formations and occupancy" in
CLAUDE.md). Nothing here forces the coin toss, so the tutorial plays
the same either way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .components import MatchState, PlayerRole, TeamSide


# Maneuver names, spelled once. They are the catalog's own, out of
# `d12ball/data/maneuvers.json` -- a beat naming one that has been
# renamed upstream should fail loudly rather than silently pick
# nothing, which is what `validate_script` is for.
LOW_PASS = "Low Pass"
DRIBBLE_ADVANCE = "Dribble Advance"
HIGH_PASS = "High Pass"
BLOCK_DEFLECT = "Block Deflect"
STEAL_INTERCEPT = "Steal Intercept"
PRESSURE = "Pressure"


# A side's six, by role, at a forward index counted from that side's
# own goal end. Written out per beat rather than derived, because the
# whole point of a scripted position is that it can be read.
StandardShape = dict[PlayerRole, int]


def standard_shape() -> StandardShape:
    """
    The 2-2-2 a side is dealt, in forward indices on the seven-space
    board. Beats that want the ordinary kickoff position start here.
    """
    return {
        PlayerRole.FULLBACK: 0,
        PlayerRole.DEFENDER: 1,
        PlayerRole.MIDFIELDER: 2,
        PlayerRole.PLAYMAKER: 3,
        PlayerRole.WINGER: 5,
        PlayerRole.STRIKER: 6,
    }


def absolute_index(board_size: int, side: TeamSide, forward: int) -> int:
    """
    A forward index -- counted from `side`'s own goal end -- as a flat
    index across the board.

    Home attacks from low indices to high, so its forward index *is*
    the flat one; the visitors attack the other way and read mirrored.
    Same convention a formation is dealt in.
    """
    if TeamSide(side) is TeamSide.HOME:
        return forward
    return board_size - 1 - forward


@dataclass(frozen=True)
class TutorialBeat:
    """
    One scripted turn: the position it is played from, what the coach
    is told, and what each side must pick.

    `player_maneuver` is the card the coach is railed onto and
    `dinky_maneuver` is what Dinky plays against it. Those two decide
    the outcome on rank alone, which is why a beat can promise what it
    teaches without the tutorial touching a die.
    """

    step: int
    title: str
    # Posted before the turn prompt: where everyone is standing and
    # what the coach is about to press.
    lesson: str
    # Posted before the maneuver menu: what the three cards do and
    # which one this beat wants.
    maneuver_note: str
    # Which side holds the ball -- True when it is the coach's.
    player_has_ball: bool
    ball_forward: int
    player_shape: StandardShape
    dinky_shape: StandardShape
    player_maneuver: str
    dinky_maneuver: str
    # The turn actions the coach may press. Everything else is built
    # disabled -- see `allowed_actions`.
    actions: tuple[str, ...] = ("maneuver",)
    # Beat 5 only: the pass has to be 2 spaces or it is not a set-up.
    high_pass_distance: Optional[int] = None

    def possession(self, player_side: TeamSide) -> TeamSide:
        player_side = TeamSide(player_side)
        if self.player_has_ball:
            return player_side
        return (
            TeamSide.VISITING
            if player_side is TeamSide.HOME
            else TeamSide.HOME
        )

    def maneuver_for(
        self,
        player_side: TeamSide,
        side: str,
    ) -> Optional[str]:
        """
        The card this beat wants from the *coach*, when `side` (the
        "offense"/"defense" the maneuver menu is keyed by) is theirs.
        None when the menu belongs to Dinky, who is written straight
        into the match rather than asked.
        """
        player_is_offense = self.player_has_ball
        if (side == "offense") == player_is_offense:
            return self.player_maneuver
        return None

    def dinky_maneuver_for(self, side: str) -> Optional[str]:
        """The mirror of `maneuver_for`, for the side Dinky picks."""
        player_is_offense = self.player_has_ball
        if (side == "offense") == player_is_offense:
            return None
        return self.dinky_maneuver


def card_for_role(
    match: MatchState,
    catalog,
    side: TeamSide,
    role: PlayerRole,
) -> str:
    """
    The card this side has on the field in `role`.

    Reads the **field**, not the catalog, so a spec keeps working over
    a side that has substituted -- which the coach's own side has, by
    the time the new play after beat 5 has been and gone. A shape names
    each role once, so the first match is the only one.
    """
    for player_id in match.setup_for_side(side).field_players:
        if catalog.player_by_id(player_id).role == role:
            return player_id
    raise LookupError(
        f"The {TeamSide(side).value} side has no {role.value} on the field."
    )


def apply_beat(
    match: MatchState,
    catalog,
    beat: TutorialBeat,
    player_side: TeamSide,
) -> None:
    """
    Put the board in the position `beat` is played from.

    Both sides are laid down whole through `deploy_side`, which sets
    each card's zone assignment and its meeple's space together and
    charges nothing -- so the arrangement is one a coach could have
    made, and `set_assigned_positions` records it as the one they did.
    That second call matters: a new play restores to it, so without it
    the goal at the end of beat 5 would reset both sides onto whatever
    the *deal* had been rather than onto the position the tutorial has
    been playing from.

    Exhaustion is cleared with the position. A beat is a fresh lesson
    rather than a continuation, and tokens carried in from a walk-in
    two beats ago would put an Exhausted badge on a card for reasons
    nothing on screen explains.
    """
    player_side = TeamSide(player_side)
    dinky_side = (
        TeamSide.VISITING
        if player_side is TeamSide.HOME
        else TeamSide.HOME
    )
    board_size = match.board.layout.board_size

    for side, shape in (
        (player_side, beat.player_shape),
        (dinky_side, beat.dinky_shape),
    ):
        placement = []
        for role, forward in shape.items():
            flat = absolute_index(board_size, side, forward)
            zone, space_index = match.board.position_at_flat_index(flat)
            placement.append(
                (card_for_role(match, catalog, side, role), zone, space_index)
            )
        match.deploy_side(side, placement)
        match.set_assigned_positions(side)

    possession = beat.possession(player_side)
    ball_flat = absolute_index(board_size, possession, beat.ball_forward)
    zone, space_index = match.board.position_at_flat_index(ball_flat)
    match.ball.zone = zone
    match.ball.space_index = space_index
    match.ball.possession = possession
    match.ball.speed = 1

    match.exhaustion.clear()
    match.exhausted.clear()
    match.ball_carrier_id = None
    match.active_player_id = None


# The five scripted turns, in order. Step numbering starts at 1 because
# 0 is the welcome, which is posted with the kickoff board rather than
# being a turn of its own, and the step after the last is the handover.
BEATS: tuple[TutorialBeat, ...] = (
    TutorialBeat(
        step=1,
        title="Your first turn",
        lesson=(
            "## 1. Your first turn\n"
            "This is the kickoff position, and the ball is yours.\n\n"
            "The field is **seven spaces** across, in three zones: your "
            "own goal, midfield, and the goal you are attacking. Your "
            "six cards are on the board as meeples, three more are on "
            "your bench, and the numbers on each card are that "
            "player's **offensive** and **defensive skill**.\n\n"
            "A turn starts with the player standing on the ball -- the "
            "**handler**. You have only one there, so they are picked "
            "for you. Then you choose what to do with them.\n\n"
            "There are three things a handler can do: shoot, maneuver, "
            "or cede the ball to buy a coaching window. **You are not "
            "offered the shot at all** -- the ball is not in your "
            "shooting range, which is the far third of the field, and "
            "you have to work it up there first. Ceding is greyed out "
            "because the tutorial wants this turn played.\n\n"
            "**Press Maneuver.**"
        ),
        maneuver_note=(
            "### Choosing a maneuver\n"
            "A maneuver is a fight for the ball between two players, "
            "and both sides pick a card **secretly and at the same "
            "time**. Your hand holds three:\n\n"
            "- **Low Pass** -- ball to the nearest teammate ahead or "
            "behind, up to 2 spaces. Ball speed +1.\n"
            "- **Dribble Advance** -- your player *and* the ball move "
            "forward a space, and you may change the ball's speed.\n"
            "- **High Pass** -- the ball flies 2 to 4 spaces forward.\n\n"
            "Which one wins is not a roll. The six maneuvers form a "
            "**cycle**, like rock-paper-scissors with six hands: each "
            "one beats exactly one of the other side's, ties with one, "
            "and loses to one. The Maneuver Reference button draws it.\n\n"
            "Dinky's defender is standing on the ball already, so they "
            "challenge for free -- nobody had to be sent.\n\n"
            "**Pick Dribble Advance.** It beats Block Deflect, and it "
            "is the card that carries the ball forward.\n\n"
            "It will then ask you two things: how far to go -- your "
            "playmaker is one of the roles that may make it 2 -- and "
            "whether to change the ball's speed. Both are yours to "
            "answer however you like; neither is wrong."
        ),
        player_has_ball=True,
        ball_forward=3,
        player_shape=standard_shape(),
        dinky_shape=standard_shape(),
        player_maneuver=DRIBBLE_ADVANCE,
        dinky_maneuver=BLOCK_DEFLECT,
    ),
    TutorialBeat(
        step=2,
        title="A tie, and the skill test",
        lesson=(
            "## 2. When nobody outranks anybody\n"
            "Dribble Advance beat Block Deflect outright last turn -- "
            "no dice, because the cycle had already settled it.\n\n"
            "The ball is back in midfield, and this time **Dinky has "
            "nobody standing on it**. So before any card is chosen, "
            "the defense has to *send* somebody: the nearest player "
            "either side of the ball, at a cost of **one exhaustion "
            "token per space walked**. Watch the token appear on their "
            "card. A defense that does not fancy the cost may send "
            "nobody at all -- and then the maneuver simply succeeds.\n\n"
            "**Press Maneuver.**"
        ),
        maneuver_note=(
            "### A tie is a skill test\n"
            "Every maneuver has a **rank**, and two cards of the same "
            "rank tie. A tie is not a draw -- it goes to a **skill "
            "test**: each player rolls a d12 and adds their skill (the "
            "attacker their offensive, the defender their defensive), "
            "plus anything their role's ability is worth. Highest "
            "total takes it, and both of them pick up an exhaustion "
            "token for the effort.\n\n"
            "**Pick Low Pass.** It is rank 1, and so is the Block "
            "Deflect Dinky is about to play -- so this one goes to the "
            "dice, and you will see how a contest is actually rolled."
        ),
        player_has_ball=True,
        ball_forward=3,
        player_shape=standard_shape(),
        dinky_shape={
            PlayerRole.FULLBACK: 0,
            PlayerRole.DEFENDER: 1,
            PlayerRole.MIDFIELDER: 2,
            PlayerRole.PLAYMAKER: 2,
            PlayerRole.WINGER: 5,
            PlayerRole.STRIKER: 6,
        },
        player_maneuver=LOW_PASS,
        dinky_maneuver=BLOCK_DEFLECT,
    ),
    TutorialBeat(
        step=3,
        title="Losing the ball",
        lesson=(
            "## 3. Losing the ball\n"
            "Same position, same card -- and this time it goes wrong, "
            "which is the point.\n\n"
            "**Press Maneuver.**"
        ),
        maneuver_note=(
            "### Turnovers, and the run back\n"
            "**Pick Low Pass again.** Dinky is playing **Steal "
            "Intercept**, which beats it, so you are about to lose the "
            "ball.\n\n"
            "Watch what a turnover does. The ball changes hands and "
            "moves back a space with the player who took it. Anyone "
            "left standing outside their own zone then has to **run "
            "back** into it, at a token a space -- the same rate a "
            "walk-in costs. If that catches one of yours you will be "
            "asked which space they return to, and each button shows "
            "what that space costs.\n\n"
            "Not every turnover works like this. A goal or a missed "
            "shot is a **new play** instead: both sides reset to the "
            "arrangement their coach set, free of charge and free of "
            "exhaustion. A steal is the one you pay for."
        ),
        player_has_ball=True,
        ball_forward=3,
        player_shape=standard_shape(),
        dinky_shape={
            PlayerRole.FULLBACK: 0,
            PlayerRole.DEFENDER: 1,
            PlayerRole.MIDFIELDER: 2,
            PlayerRole.PLAYMAKER: 2,
            PlayerRole.WINGER: 5,
            PlayerRole.STRIKER: 6,
        },
        player_maneuver=LOW_PASS,
        dinky_maneuver=STEAL_INTERCEPT,
    ),
    TutorialBeat(
        step=4,
        title="Your turn to defend",
        lesson=(
            "## 4. Your turn to defend\n"
            "Dinky has the ball in midfield and is coming at your "
            "goal. You have a player standing on the ball already, so "
            "they challenge without being sent and without paying a "
            "token.\n\n"
            "You do not press anything to start a turn you are "
            "defending -- Dinky moves, and then you are asked for a "
            "card. Sit tight."
        ),
        maneuver_note=(
            "### The other three cards\n"
            "Defending, your hand is the other half of the cycle:\n\n"
            "- **Block Deflect** -- knocks the ball back a space and "
            "loose, for either side to fight over. Ball speed -1.\n"
            "- **Steal Intercept** -- the turnover you were on the "
            "wrong end of last turn.\n"
            "- **Pressure** -- pushes the handler and the ball back a "
            "space and moves your defender forward onto them. If it "
            "pushes them past their own goal line it is an **own "
            "goal** risk, and they have to roll for it.\n\n"
            "**Pick Pressure.** Dinky is dribbling, and Pressure beats "
            "Dribble Advance -- so you will drive them backwards and "
            "take a space off them."
        ),
        player_has_ball=False,
        ball_forward=3,
        player_shape=standard_shape(),
        dinky_shape=standard_shape(),
        player_maneuver=PRESSURE,
        dinky_maneuver=DRIBBLE_ADVANCE,
    ),
    TutorialBeat(
        step=5,
        title="A shot at goal",
        lesson=(
            "## 5. A shot at goal\n"
            "Last lesson, and this one is worth a goal.\n\n"
            "You have the ball back in midfield with your "
            "**midfielder**, and your **striker** is standing deep in "
            "Dinky's half -- inside your **shooting range**, the far "
            "third of the field. There is one defender left between "
            "that space and the goal.\n\n"
            "A High Pass of exactly 2 spaces lands on your striker, "
            "and a pass that lands on a teammate already in shooting "
            "range is a **scoring opportunity**: they get an immediate "
            "shot, out of turn. Your striker's ability is worth **+3** "
            "on exactly that shot.\n\n"
            "**Press Maneuver.**"
        ),
        maneuver_note=(
            "### High Pass, and what a shot is up against\n"
            "**Pick High Pass.** Dinky is playing Steal Intercept, and "
            "High Pass beats it -- so the pass gets through.\n\n"
            "You will then be asked how far to throw it. **Take 2 "
            "spaces**; the longer throws are greyed out this once, "
            "because only a pass of 2 is caught cleanly. A 3- or "
            "4-space pass has to be *won* by whoever it lands near, "
            "with the ball's speed counting against them.\n\n"
            "When the shot comes, take it. A score attempt is your d12 "
            "plus the shooter's offensive skill against Dinky's d12 "
            "plus every defender in the way -- a defender standing on "
            "the ball adds all of their defensive skill, one further "
            "back adds half, rounded up. Ties go to the shooter."
        ),
        player_has_ball=True,
        ball_forward=3,
        player_shape={
            PlayerRole.FULLBACK: 0,
            PlayerRole.DEFENDER: 1,
            PlayerRole.PLAYMAKER: 2,
            PlayerRole.MIDFIELDER: 3,
            PlayerRole.WINGER: 4,
            PlayerRole.STRIKER: 5,
        },
        dinky_shape={
            PlayerRole.FULLBACK: 0,
            PlayerRole.DEFENDER: 2,
            PlayerRole.MIDFIELDER: 3,
            PlayerRole.PLAYMAKER: 4,
            PlayerRole.WINGER: 5,
            PlayerRole.STRIKER: 5,
        },
        player_maneuver=HIGH_PASS,
        dinky_maneuver=STEAL_INTERCEPT,
        high_pass_distance=2,
    ),
)


FIRST_STEP = BEATS[0].step
# One past the last beat: the step the tutorial ends on. Reaching it
# posts the handover and clears the flag, so the turn it stages is an
# ordinary one.
HANDOVER_STEP = BEATS[-1].step + 1


WELCOME = (
    "# Welcome to D12 Ball\n"
    "You are playing **Dinky**, and the first five turns are a guided "
    "warm-up: I will tell you where everybody is, what each button "
    "does, and which card to pick. Everything else is greyed out while "
    "we go, so you cannot get lost.\n\n"
    "The board above is the whole game state -- the field with both "
    "sides' meeples on it, each side's cards with their skills, the "
    "benches, and the clock. It is re-posted as it changes, and the "
    "**View full image** link under it opens it big.\n\n"
    "The score and the clock from these five turns carry into the real "
    "game, so the warm-up counts. Play well and you will start it "
    "ahead.\n\n"
    "*You can leave the tutorial at any time with "
    "`/d12ball skip_tutorial`.*"
)


COACHING_NOTE = (
    "### 6. The Coaching Choice\n"
    "A goal is a **new play**: both sides go back to the arrangement "
    "their coach set, free of exhaustion, and the side that was scored "
    "against restarts. And a new play is one of the moments a coach "
    "may call a **Coaching Choice** -- the window you are being "
    "offered now.\n\n"
    "Inside it you can do four things, in any order and as often as "
    "you like before you press Done:\n\n"
    "- **Formation** -- re-deal your six into a different shape.\n"
    "- **Substitution** -- swap someone on the field for someone on "
    "your bench.\n"
    "- **Zone assignment** -- move a card between zones.\n"
    "- **Space positioning** -- move a meeple within its zone.\n\n"
    "Two things to know. You may only *declare* one of these per half, "
    "so spending it here means going without until halftime -- and "
    "you get two substitutions out of it. And Done is refused until "
    "somebody of yours is standing on your own kickoff space.\n\n"
    "This is the last thing the tutorial explains. Take the window or "
    "decline it; either way, the game is yours from here."
)


HANDOVER = (
    "# That's the tutorial\n"
    "The rails are off -- every button is live from here, and Dinky is "
    "playing for real.\n\n"
    "What the warm-up did not cover, the game will: halftime, "
    "injuries and recovery, loose balls, ceding the ball for a "
    "coaching window, and the extreme shootout that settles a level "
    "score at full time.\n\n"
    "Three commands worth knowing:\n"
    "- `/d12ball rules_search` -- one section of the rules, in the "
    "channel.\n"
    "- `/d12ball maneuver_reference` -- the defeat cycle.\n"
    "- `/d12ball resume` -- puts the current question back up if a "
    "prompt ever goes missing.\n\n"
    "Good luck."
)


SKIPPED = (
    "**Tutorial ended.** Every button is live from here and Dinky is "
    "playing for real -- the board, the score and the clock stay "
    "exactly as they are."
)


def beat_for_step(step: Optional[int]) -> Optional[TutorialBeat]:
    """The beat a step names, or None once the beats have run out."""
    if step is None:
        return None
    for beat in BEATS:
        if beat.step == step:
            return beat
    return None


def allowed_actions(beat: Optional[TutorialBeat]) -> Optional[tuple[str, ...]]:
    """
    The turn actions a coach may press this beat, or None for no rail.

    `PlayerActionView` builds everything else disabled rather than
    leaving it out: a coach should see that Shoot and Cede exist, and
    read in the lesson why neither is theirs to press yet.
    """
    return None if beat is None else beat.actions


def allowed_maneuvers(
    beat: Optional[TutorialBeat],
    player_side: TeamSide,
    side: str,
) -> Optional[tuple[str, ...]]:
    """
    The maneuver a coach may pick this beat, or None for no rail.

    Only ever one, and only ever on the coach's own half of the menu --
    Dinky's card is written straight into the match and never goes
    through a view at all.
    """
    if beat is None:
        return None
    wanted = beat.maneuver_for(player_side, side)
    return None if wanted is None else (wanted,)


def forced_high_pass_distance(beat: Optional[TutorialBeat]) -> Optional[int]:
    """
    The one distance beat 5 may throw. See the module docstring for why
    this is the only sub-choice on rails.
    """
    return None if beat is None else beat.high_pass_distance


def validate_script(maneuver_catalog) -> None:
    """
    Every card a beat names is one the catalog actually holds.

    The maneuvers are imported from a spreadsheet, so a rename upstream
    would otherwise leave a beat quietly railing a coach onto a button
    that no longer exists. Called once at cog load, where it fails
    loudly.
    """
    known = {
        maneuver.name
        for maneuver in (
            list(maneuver_catalog.offense) + list(maneuver_catalog.defense)
        )
    }
    for beat in BEATS:
        for name in (beat.player_maneuver, beat.dinky_maneuver):
            if name not in known:
                raise ValueError(
                    f"Tutorial beat {beat.step} names an unknown maneuver: "
                    f"{name!r}. Known: {sorted(known)}."
                )

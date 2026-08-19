"""
The scripted opening a `/d12ball create_game tutorial:true` game plays
before it becomes an ordinary game against Dinky.

**Every lesson is a real turn, and the five of them are one continuous
play.** The tutorial sets the board **once**, at kickoff (`OPENING`),
and never touches it again: each beat is played from wherever the
previous beat's turn actually left the ball. That is the whole design.
An earlier version re-dealt both sides before every beat, which made
each lesson self-contained at the cost of the story -- a coach drove
Dinky backwards with a Pressure and then found the ball back in
midfield with no explanation. There is no such seam now, and there must
not be one again: **nothing here may move a meeple between beats.**

What that costs is determinism. A chained script only works if every
step of it lands where the next beat expects, so:

- **The rails cover every choice that moves the ball**, not just the
  maneuver: the turn action, the card, and the dribble distance, ball
  speed, pass distance and set-up shot (`choices`). Anything left free
  -- a run-back space, which of two of your own players challenges --
  is free precisely because the beats that follow do not depend on it.
- **Some dice are scripted** (`rolls`). Beat 2 is a tie the coach has
  to *lose*, or the ball never comes free and beats 3 and 4 have
  nothing to defend against; the loose ball behind it has to go Dinky's
  way for the same reason. Injury checks are rigged to pass for the
  whole opening (`BLANKET_ROLLS`) -- an injured card mid-story is a
  mechanic the script never introduces and cannot plan around.
- **The score attempt at the end is not scripted.** It is the one roll
  in the tutorial that decides something the coach actually wants, and
  the position is built so it is a heavy favourite rather than a
  certainty -- a striker's +9 against a lone halved defender, 89.6%.
  A tutorial that cannot lose its last shot is not teaching the game.

**There is no beat for the Coaching Choice**, and there cannot be one:
a new play offers the window to the side *restarting* play, which after
the coach's goal is Dinky -- and an AI window never formally declares,
so no reply comes back the coach's way either. `COACHING_NOTE` is
therefore a one-off explainer fired from `begin_substitution_window` at
the first window this coach is ever offered, whenever the game gets
round to it, and `tutorial_coaching_explained` is what keeps it to one.
Skipping the tutorial suppresses it, which is what `skip_tutorial`
setting that flag is for.

**The coach always plays home**, because the script opens with the ball
theirs: `HomeAwaySelectionView` rails a coach who wins the toss onto
Home, and `CoinFlipView.flip_coin` sends Dinky to the visitors when
Dinky wins it. Shapes are still written from a side's own goal forward
and mirrored by `absolute_index` -- that is how Dinky's half of
`OPENING` is read, and it is the frame a formation is dealt in.

Everything the script leaves the game in is a state the game already
knows: nothing here adds a branch to `pending_turn_view`, and
`/d12ball resume` needs no knowledge of the tutorial at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .components import MatchState, PlayerRole, TeamSide


# Maneuver names, spelled once. They are the catalog's own, out of
# `d12ball/data/maneuvers.json` -- a beat naming one that has been
# renamed upstream should fail loudly rather than silently rail a coach
# onto nothing, which is what `validate_script` is for.
LOW_PASS = "Low Pass"
DRIBBLE_ADVANCE = "Dribble Advance"
HIGH_PASS = "High Pass"
BLOCK_DEFLECT = "Block Deflect"
STEAL_INTERCEPT = "Steal Intercept"
PRESSURE = "Pressure"


# A side's six by role, at a **forward index** counted from that side's
# own goal end. Written out rather than derived: the point of a scripted
# position is that it can be read off the page and checked against the
# board.
Shape = dict[PlayerRole, int]


def absolute_index(board_size: int, side: TeamSide, forward: int) -> int:
    """
    A forward index -- counted from `side`'s own goal end -- as a flat
    index across the board.

    Home attacks from low indices to high, so its forward index *is*
    the flat one; the visitors attack the other way and read mirrored.
    The same convention a formation is dealt in.
    """
    if TeamSide(side) is TeamSide.HOME:
        return forward
    return board_size - 1 - forward


@dataclass(frozen=True)
class OpeningPosition:
    """
    The board the whole script is played from, laid down once at
    kickoff and never again.

    It is not the standard deal, and the welcome says so: the tutorial
    skips setup coaching, so this stands in for the line-ups two
    coaches would have set. Every space in it is load-bearing --

    - The coach's **playmaker has the ball on M1**, two spaces short of
      shooting range, so the maneuvers before the shot happen out of
      range and the Shoot button is not offered until it is earned.
      Beat 2 is the exception and is written to use it.
    - The coach's **striker stands on V1**, which is where beat 5's
      2-space High Pass lands, and is inside shooting range.
    - **Dinky keeps exactly one card in their own goal zone**, on V2,
      which is what makes the shot at the end a striker's +9 against a
      single halved +3 rather than against two of them. Their shape is
      1-3-2, an attacking one, which is also why they have somebody on
      M1 to challenge the opening maneuver.
    - The coach covers **M2**, their kickoff space, because the goal at
      the end restores this arrangement and opens a Coaching Choice --
      and `coaching_finish_refusal` holds a coach there until somebody
      of theirs is standing on it.
    """

    player_shape: Shape
    dinky_shape: Shape
    ball_forward: int


OPENING = OpeningPosition(
    player_shape={
        PlayerRole.FULLBACK: 0,     # H1
        PlayerRole.DEFENDER: 1,     # H2
        PlayerRole.PLAYMAKER: 2,    # M1 -- on the ball
        PlayerRole.MIDFIELDER: 3,   # M2 -- the kickoff space
        PlayerRole.WINGER: 4,       # M3
        PlayerRole.STRIKER: 5,      # V1 -- beat 5 lands here
    },
    dinky_shape={
        PlayerRole.FULLBACK: 0,     # V2 -- the only card in the lane
        PlayerRole.DEFENDER: 2,     # M3
        PlayerRole.MIDFIELDER: 4,   # M1 -- challenges beat 1
        PlayerRole.PLAYMAKER: 3,    # M2
        PlayerRole.WINGER: 5,       # H2
        PlayerRole.STRIKER: 6,      # H1
    },
    ball_forward=2,
)


@dataclass(frozen=True)
class TutorialBeat:
    """
    One scripted turn: what the coach is told, what each side plays,
    and every choice the next beat depends on.

    `player_maneuver` is the card the coach is railed onto and
    `dinky_maneuver` is what Dinky plays against it. Those two settle
    the outcome on rank alone wherever the ranking is decisive; where
    it is a tie, `rolls` settles the test behind it.
    """

    step: int
    title: str
    # Posted before the turn prompt: where the ball is, what just
    # happened, and what the coach is about to press.
    lesson: str
    # Posted before the maneuver menu: the cards, and which one this
    # beat wants.
    maneuver_note: str
    # Which side holds the ball -- True when it is the coach's.
    player_has_ball: bool
    player_maneuver: str
    dinky_maneuver: str
    # The turn actions the coach may press. Everything else is built
    # disabled -- see `allowed_actions`.
    actions: tuple[str, ...] = ("maneuver",)
    # Every other choice this beat pins down, keyed by the view that
    # asks it -- see `railed_choice`. Values compare as strings, which
    # is what a custom_id carries.
    choices: dict[str, str] = field(default_factory=dict)
    # Dice this beat fixes, keyed by contest -- see `scripted_dice`.
    rolls: dict[str, tuple[int, ...]] = field(default_factory=dict)

    def possession(self, player_side: TeamSide) -> TeamSide:
        player_side = TeamSide(player_side)
        if self.player_has_ball:
            return player_side
        return (
            TeamSide.VISITING
            if player_side is TeamSide.HOME
            else TeamSide.HOME
        )

    def maneuver_for(self, side: str) -> Optional[str]:
        """
        The card this beat wants from the *coach*, when `side` -- the
        "offense"/"defense" the maneuver menu is keyed by -- is theirs.
        None when the menu belongs to Dinky, who is written straight
        into the match rather than asked.
        """
        if (side == "offense") == self.player_has_ball:
            return self.player_maneuver
        return None

    def dinky_maneuver_for(self, side: str) -> Optional[str]:
        """The mirror of `maneuver_for`, for the side Dinky picks."""
        if (side == "offense") == self.player_has_ball:
            return None
        return self.dinky_maneuver


# Rolls fixed for the whole opening rather than per beat. An injury
# check is a d12 against the player's token count, so 12 always passes:
# a card going down injured is a mechanic the script never introduces,
# lands on whichever player the dice pick, and would leave every beat
# after it planning around a board it did not expect. The check still
# runs and the coach still watches it -- only the result is settled.
BLANKET_ROLLS: dict[str, int] = {"injury": 12}


BEATS: tuple[TutorialBeat, ...] = (
    TutorialBeat(
        step=1,
        title="Your first turn",
        lesson=(
            "## 1. Your first turn\n"
            "Both line-ups are set and the ball is yours, on **M1** in "
            "midfield.\n\n"
            "The field is **seven spaces** across in three zones: your "
            "own goal (H1-H2), midfield (M1-M3), and the goal you are "
            "attacking (V1-V2). Your six cards are on the board as "
            "meeples and three more wait on your bench. The two numbers "
            "on a card are that player's **offensive** and **defensive "
            "skill**.\n\n"
            "A turn starts with whoever is standing on the ball -- the "
            "**handler**. You have one player there, your playmaker, so "
            "they are chosen for you. Then you decide what they do.\n\n"
            "There are three things a handler can do: shoot, maneuver, "
            "or cede the ball to buy a coaching window. **You are not "
            "offered the shot** -- a shot may only be taken from inside "
            "your shooting range, which is the far third of the field "
            "(M3 and beyond), and you are two spaces short of it.\n\n"
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
            "forward, and you may change the ball's speed.\n"
            "- **High Pass** -- the ball flies 2 or more spaces "
            "forward.\n\n"
            "Which card wins is not a roll. The six form a **cycle**, "
            "like rock-paper-scissors with six hands: each beats one of "
            "the other side's, ties with one, and loses to one. The "
            "Maneuver Reference button draws the whole thing, and you "
            "can open it whenever you like.\n\n"
            "Dinky's midfielder is standing on the ball, so they are "
            "the one challenging you.\n\n"
            "**Pick Dribble Advance.** It beats Block Deflect, which is "
            "what Dinky has played, and it is the card that carries the "
            "ball up the field."
        ),
        player_has_ball=True,
        player_maneuver=DRIBBLE_ADVANCE,
        dinky_maneuver=BLOCK_DEFLECT,
        # Two spaces is the Playmaker's own ability and this beat exists
        # partly to show it. No speed change keeps the ball at 1, which
        # is what the score attempt at the end is priced against.
        choices={"dribble_advance": "2", "speed": "1"},
    ),
    TutorialBeat(
        step=2,
        title="Roles, abilities, and a tie",
        lesson=(
            "## 2. Every role has an ability\n"
            "Dribble Advance beat Block Deflect outright -- no dice, "
            "because the cycle had already settled it -- and your "
            "playmaker carried the ball **two** spaces, to M3.\n\n"
            "Two was not the ordinary move. A dribble advances one "
            "space; the **Playmaker** may make it two, and that is "
            "their role's ability. **Every player has a role and every "
            "role has an ability**, printed on their card and worth "
            "reading before you pick a maneuver -- the Fullback throws "
            "a longer High Pass, the Striker is deadly off a set-up, "
            "the Defender can steal off a won Pressure. Two commands "
            "list them whenever you want: **`/d12ball role_abilities`** "
            "for all six, and **`/d12ball team_roster`** for who on "
            "your team has which.\n\n"
            "You are on M3 now, which is inside your shooting range, so "
            "the **Shoot** button has appeared. It is greyed out here, "
            "and it would be a bad shot anyway: your playmaker's "
            "offensive skill is 4, and Dinky's defender is standing on "
            "the ball with you -- a defender on the ball adds their "
            "**whole** defensive skill to the save. We will make a much "
            "better shot shortly.\n\n"
            "**Press Maneuver.**"
        ),
        maneuver_note=(
            "### When both cards are the same rank\n"
            "Every maneuver has a **rank**, and two cards of the same "
            "rank **tie**. A tie is not a draw -- it goes to a **skill "
            "test**: both players roll a d12 and add their skill, the "
            "attacker their offensive and the defender their defensive, "
            "plus whatever their ability is worth. Highest total takes "
            "it, and both of them pick up an **exhaustion token** for "
            "the effort. Tokens are the game's running cost; enough of "
            "them and a player risks going down injured.\n\n"
            "**Pick Low Pass.** It is rank 1 and so is the Block "
            "Deflect Dinky has played, so this one goes to the dice -- "
            "and Dinky is going to win it. Watch what a won Block "
            "Deflect does: the ball is knocked back a space and comes "
            "**loose**, belonging to nobody, and each side sends "
            "somebody to fight over it.\n\n"
            "Then watch the **run back**. Every zone has to stay "
            "covered -- you may not leave one of your zone's spaces "
            "empty while two of your players share another -- so when "
            "the dust settles you will be asked to send somebody back "
            "to cover M1. That costs **one exhaustion token per "
            "space**, and each button prices the trip. Anyone left "
            "outside their own zone entirely runs back the same way."
        ),
        player_has_ball=True,
        player_maneuver=LOW_PASS,
        dinky_maneuver=BLOCK_DEFLECT,
        # The coach has to lose both of these, or the ball never comes
        # free and beats 3 and 4 -- the two lessons in defending -- have
        # nothing to defend against. See the module docstring.
        rolls={"skill_test": (2, 11), "loose_ball": (2, 11)},
    ),
    TutorialBeat(
        step=3,
        title="Your turn to defend",
        lesson=(
            "## 3. Your turn to defend\n"
            "That is the ball lost. Dinky won the skill test, their "
            "Block Deflect knocked it back a space and loose, and they "
            "won the scramble that followed. They are coming at your "
            "goal now.\n\n"
            "You have a player standing on the ball, so they challenge "
            "without going anywhere. That matters: sending a player who "
            "is **not** already on the ball costs one exhaustion token "
            "for every space they walk, which is why where your meeples "
            "stand is worth thinking about.\n\n"
            "You press nothing to start a turn you are defending -- "
            "Dinky moves first, and then you are asked for a card. Sit "
            "tight."
        ),
        maneuver_note=(
            "### The other three cards\n"
            "Defending, your hand is the other half of the cycle:\n\n"
            "- **Block Deflect** -- knocks the ball back a space and "
            "loose, for either side to fight over. You were on the "
            "wrong end of one last turn.\n"
            "- **Steal Intercept** -- takes the ball outright. A "
            "turnover.\n"
            "- **Pressure** -- drives the handler and the ball back a "
            "space and moves your challenger forward onto them. Push a "
            "handler past their own goal line with it and they have an "
            "**own goal** to roll for.\n\n"
            "**Pick Pressure.** Dinky is dribbling, and Pressure beats "
            "Dribble Advance -- so instead of losing a space you will "
            "take one off them."
        ),
        player_has_ball=False,
        player_maneuver=PRESSURE,
        dinky_maneuver=DRIBBLE_ADVANCE,
    ),
    TutorialBeat(
        step=4,
        title="Winning the ball back",
        lesson=(
            "## 4. Winning the ball back\n"
            "Pressure drove them backwards: their handler and the ball "
            "went back a space, and your challenger moved up onto them. "
            "Dinky still has it -- but they have lost ground, and you "
            "are standing on the ball.\n\n"
            "Now take it off them."
        ),
        maneuver_note=(
            "### Turnovers, and the run back\n"
            "**Pick Steal Intercept.** Dinky is playing Low Pass, and "
            "Steal Intercept beats it -- the ball is yours.\n\n"
            "A steal takes the ball back a space with the player who "
            "won it, and anyone it leaves out of position runs back at "
            "the usual token a space -- Dinky will have to do that, "
            "and you will see them pay for it.\n\n"
            "Not every turnover works this way. A **steal** keeps the "
            "ball live and charges for the scramble. A goal or a "
            "missed shot is a **new play** instead: the ball is dead, "
            "both sides reset to the arrangement their coach set, and "
            "nobody pays anything. You are about to cause one of "
            "each."
        ),
        player_has_ball=False,
        player_maneuver=STEAL_INTERCEPT,
        dinky_maneuver=LOW_PASS,
        # Steal Intercept offers the stealer the same speed dial a
        # dribble does, and the shot two beats later is priced at
        # speed 1.
        choices={"speed": "1"},
    ),
    TutorialBeat(
        step=5,
        title="A shot at goal",
        lesson=(
            "## 5. A shot at goal\n"
            "The ball is yours again, back in midfield, and this is the "
            "last lesson -- it is worth a goal.\n\n"
            "Look at **V1**. Your striker has been standing there all "
            "game, inside your shooting range, and there is exactly one "
            "Dinky card behind them between that space and the goal.\n\n"
            "A High Pass of exactly 2 spaces lands on V1. A pass that "
            "reaches a teammate already inside shooting range is a "
            "**scoring opportunity**: they take a shot immediately, out "
            "of turn. And your striker's ability is worth **+3** on "
            "precisely that shot.\n\n"
            "**Press Maneuver.**"
        ),
        maneuver_note=(
            "### High Pass, and what a shot is up against\n"
            "**Pick High Pass.** Dinky is playing Steal Intercept, and "
            "High Pass beats it, so the pass gets through.\n\n"
            "You will be asked how far to throw. **Take 2 spaces** -- "
            "the longer throws are greyed out this once, because only a "
            "pass of 2 is caught cleanly. A 3-space pass has to be "
            "*won* by whoever it lands near, with the ball's speed "
            "counting against them.\n\n"
            "Then take the shot. A score attempt is your d12 plus the "
            "shooter's offensive skill, against Dinky's d12 plus every "
            "defender in the way -- one standing on the ball adds all "
            "of their defensive skill, one further back adds half, "
            "rounded up. Ties go to the shooter.\n\n"
            "Your striker rolls **d12+9** against their fullback's "
            "**d12+3**. That is a real roll and it can still miss -- "
            "but you should be, about nine times in ten."
        ),
        player_has_ball=True,
        player_maneuver=HIGH_PASS,
        dinky_maneuver=STEAL_INTERCEPT,
        choices={"high_pass": "2", "setup_attempt": "attempt"},
    ),
)


FIRST_STEP = BEATS[0].step
# One past the last beat: the step the tutorial ends on. Reaching it
# posts the handover and clears the flag, so the turn it stages is an
# ordinary one.
HANDOVER_STEP = BEATS[-1].step + 1


WELCOME = (
    "# Welcome to D12 Ball\n"
    "You are playing **Dinky**, and the next five turns are a guided "
    "warm-up. I will tell you what is on the board, what each button "
    "does and which card to pick; everything else is greyed out while "
    "we go, so you cannot get lost.\n\n"
    "**It is one continuous game, not five demonstrations.** Nothing is "
    "reset between lessons -- every turn is played from wherever the "
    "last one left the ball, and the score and the clock carry into the "
    "real game afterwards. Play it well and you will start that game a "
    "goal up.\n\n"
    "The board above is the whole game state: the field with both "
    "sides' meeples, every card with its skills and tokens, the "
    "benches, the clock and the score. It is re-posted as it changes, "
    "and **View full image** under it opens it large. Both line-ups "
    "have been set for you; normally each coach sets their own before "
    "kickoff, in a **Coaching Choice**, which the game will offer you "
    "in its own time.\n\n"
    "*You can leave at any time with `/d12ball skip_tutorial`.*"
)


COACHING_NOTE = (
    "### One more thing: the Coaching Choice\n"
    "This is a **Coaching Choice**, and it is the last thing the "
    "tutorial has to say. A side gets offered one when they restart "
    "play after a new play, at halftime, and whenever they give the "
    "ball up to buy one.\n\n"
    "Inside it you can do four things, in any order, as often as you "
    "like before pressing Done:\n\n"
    "- **Formation** -- re-deal your six into a different shape.\n"
    "- **Substitution** -- bring someone on from your bench.\n"
    "- **Zone assignment** -- move a card to another zone.\n"
    "- **Space positioning** -- move a meeple within its zone.\n\n"
    "Two things to know. You may only *declare* one of these per half, "
    "so taking it now means going without until halftime -- and it is "
    "worth two substitutions. And Done is refused until somebody of "
    "yours is standing on your own kickoff space, M2.\n\n"
    "Take the window or decline it; both are fine."
)


HANDOVER = (
    "# That's the tutorial\n"
    "The rails are off -- every button is live from here, and Dinky is "
    "playing for real.\n\n"
    "What the warm-up did not cover, the game will: halftime, injuries "
    "and recovery, out-of-bounds balls, ceding possession, and the "
    "extreme shootout that settles a level score at full time. The "
    "first time the game offers you a **Coaching Choice** -- your own "
    "window to substitute and rearrange -- I will explain that one "
    "too.\n\n"
    "Worth knowing:\n"
    "- `/d12ball rules_search` -- any one section of the rules.\n"
    "- `/d12ball role_abilities` -- what each role can do.\n"
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


def card_for_role(
    match: MatchState,
    catalog,
    side: TeamSide,
    role: PlayerRole,
) -> str:
    """The card this side has on the field in `role`."""
    for player_id in match.setup_for_side(side).field_players:
        if catalog.player_by_id(player_id).role == role:
            return player_id
    raise LookupError(
        f"The {TeamSide(side).value} side has no {role.value} on the field."
    )


def apply_opening(
    match: MatchState,
    catalog,
    player_side: TeamSide,
) -> None:
    """
    Lay both line-ups down for the start of the script. **The only
    thing in this module that moves a meeple**, and it runs once, at
    kickoff, before the first board is posted.

    Goes through `deploy_side`, which sets each card's zone assignment
    and its meeple's space together and charges nothing, and then
    records the result with `set_assigned_positions` -- which is
    load-bearing twice over: the goal at the end of beat 5 is a new
    play, and a new play both restores this arrangement and opens the
    Coaching Choice the last lesson is written on.
    """
    player_side = TeamSide(player_side)
    dinky_side = (
        TeamSide.VISITING
        if player_side is TeamSide.HOME
        else TeamSide.HOME
    )
    board_size = match.board.layout.board_size

    for side, shape in (
        (player_side, OPENING.player_shape),
        (dinky_side, OPENING.dinky_shape),
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

    ball_flat = absolute_index(
        board_size, player_side, OPENING.ball_forward,
    )
    zone, space_index = match.board.position_at_flat_index(ball_flat)
    match.ball.zone = zone
    match.ball.space_index = space_index
    match.ball.possession = player_side
    match.ball.speed = 1


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
    leaving it out: a coach should see that shooting and ceding exist
    and read in the lesson why neither is theirs yet.
    """
    return None if beat is None else beat.actions


def allowed_maneuvers(
    beat: Optional[TutorialBeat],
    side: str,
) -> Optional[tuple[str, ...]]:
    """
    The maneuver a coach may pick this beat, or None for no rail. Only
    ever one, and only on the coach's own half of the menu -- Dinky's
    card is written straight into the match and never goes through a
    view.
    """
    if beat is None:
        return None
    wanted = beat.maneuver_for(side)
    return None if wanted is None else (wanted,)


def railed_choice(
    beat: Optional[TutorialBeat],
    key: str,
) -> Optional[str]:
    """
    The one value a beat allows for `key`, or None for no rail.

    Keys name the view that asks: `dribble_advance`, `speed`,
    `low_pass`, `high_pass`, `setup_attempt`. Every one of them decides
    where the ball ends up, which is why they are railed at all -- see
    the module docstring on what is deliberately left free.
    """
    return None if beat is None else beat.choices.get(key)


def choice_is_refused(
    beat: Optional[TutorialBeat],
    key: str,
    value,
) -> bool:
    """Whether this beat's rail rules `value` out. False with no rail."""
    wanted = railed_choice(beat, key)
    return wanted is not None and str(value) != wanted


def scripted_dice(
    beat: Optional[TutorialBeat],
    kind: str,
    count: int,
) -> Optional[list[int]]:
    """
    The die values this beat fixes for `kind`, or None to roll.

    `count` is how many the caller needs, so a contest asking for two
    and a check asking for one read the same table. A beat naming
    fewer than the caller wants is a script that has drifted from the
    flow, so it is refused rather than quietly padded.
    """
    if beat is None:
        return None
    if kind in BLANKET_ROLLS:
        return [BLANKET_ROLLS[kind]] * count
    values = beat.rolls.get(kind)
    if values is None:
        return None
    if len(values) < count:
        raise ValueError(
            f"Tutorial beat {beat.step} fixes {len(values)} {kind} "
            f"dice but {count} were rolled."
        )
    return list(values[:count])


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

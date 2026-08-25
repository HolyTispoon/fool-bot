"""
The scripted opening a `/d12ball create_game tutorial:true` game plays
before it becomes an ordinary game against Dinky.

**Every lesson is a real turn, and the five of them are one continuous
play.** The script **places nothing at all**: the game kicks off from
the standard deal and each beat is played from wherever the previous
beat's turn actually left the ball. That is the whole design. An
earlier version re-dealt both sides before every beat, which made each
lesson self-contained at the cost of the story -- a coach drove Dinky
backwards with a Pressure and then found the ball back in midfield with
no explanation. There is no such seam now, and there must not be one
again: **nothing here may move a meeple, at any point.**

What that costs is determinism. A chained script only works if every
step of it lands where the next beat expects, so:

- **The rails cover every choice that moves the ball or prices the
  shot**, not just the maneuver: the turn action, the card, the dribble
  distance, the ball speed, the pass distance, the set-up shot, and
  whether a loose ball may be waved through (`choices`). Anything left
  free -- a run-back space, which player is sent after the loose ball,
  which of two of your own challenges -- is free precisely because the
  beats that follow do not depend on it.
- **Some dice are scripted** (`rolls`). Beat 2 is a tie the coach has
  to *lose*, or the ball never comes free and beats 3 and 4 have
  nothing to defend against; the loose ball behind it has to go Dinky's
  way for the same reason. Injury checks are rigged to pass for the
  whole opening (`BLANKET_ROLLS`) -- an injured card mid-story is a
  mechanic the script never introduces and cannot plan around.
- **The score attempt at the end is not scripted.** It is the one roll
  in the tutorial that decides something the coach actually wants, and
  the play is built so it is a heavy favourite rather than a certainty:
  the striker's d12+11 -- offensive skill 6, the Striker's +3 off a
  set-up, and +2 for the ball speed beat 4 told the coach to crank --
  against the fullback's d12+6, which is **85.4%**. A tutorial that
  cannot lose its last shot is not teaching the game. That the speed
  rail in beat 4 is worth a whole point of that margin is the reason it
  is railed at all, and the reason the lesson explains it rather than
  just greying the buttons.

**There is no beat for the Coaching Choice**, and there cannot be one:
a new play offers the window to the side *restarting* play, which after
the coach's goal is Dinky -- and an AI window never formally declares,
so no reply comes back the coach's way either. `COACHING_NOTE` is
therefore a one-off explainer fired from `begin_substitution_window` at
the first window this coach is ever offered, whenever the game gets
round to it, and `tutorial_coaching_explained` is what keeps it to one.
Skipping the tutorial suppresses it, which is what `skip_tutorial`
setting that flag is for.

**The opening position is the standard deal**, and the script places
nothing. Both sides are dealt 2-2-2 exactly as every game deals them:
the coach's playmaker has the ball on M2 with Dinky's playmaker
standing on it to challenge, the coach's striker is on V2, and Dinky's
fullback is on V2 with them. Writing a position of our own was tried
and dropped -- it put both sides in shapes (2-3-1 and 1-3-2) no game
ever kicks off in, which taught the wrong thing before the first
button was pressed. **A beat that wants a different position has to
play its way there.**

**The coach always plays home**, because the deal gives home the ball:
`HomeAwaySelectionView` rails a coach who wins the toss onto Home, and
`CoinFlipView.flip_coin` sends Dinky to the visitors when Dinky wins
it.

Everything the script leaves the game in is a state the game already
knows: nothing here adds a branch to `pending_turn_view`, and
`/d12ball resume` needs no knowledge of the tutorial at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .components import MatchState, PlayerRole, TeamSide


# Maneuver **keys**, spelled once. They are the catalog's own, out of
# `d12ball/data/maneuvers.json` -- a beat naming one that is not in the
# catalog should fail loudly rather than silently rail a coach onto
# nothing, which is what `validate_script` is for.
#
# Keys rather than printed names, for the reason keys exist at all: the
# author renamed the basic D2 card from "Steal Intercept" to "Steal" on
# 2026-08-18, and under names that rename was five silent rails
# matching nothing. The lesson prose still spells the names out, and it
# has to be edited by hand when one changes -- prose is prose.
LOW_PASS = "low_pass"
DRIBBLE_ADVANCE = "dribble_advance"
HIGH_PASS = "high_pass"
DEFLECT = "deflect"
STEAL = "steal"
PRESSURE = "pressure"


# A rail that cannot name its value up front, because the value
# depends on who is standing where: the ball speed a steal may set is
# capped by the stealer's own defensive skill, so "the highest offered"
# is the only way to write it down.
CHOICE_MAX = "max"


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
            "Both sides are dealt the standard **2-2-2** -- two cards in "
            "your own goal zone, two in midfield, two in the zone you "
            "are attacking -- and the ball is yours, on **M2**.\n\n"
            "The field is **seven spaces** across in three zones: your "
            "own goal (H1-H2), midfield (M1-M3), and the goal you are "
            "attacking (V1-V2). Your six cards are on the board as "
            "meeples and three more wait on your bench. The two numbers "
            "on a card are that player's **offensive** and **defensive "
            "skill**.\n\n"
            "A turn starts with whoever is standing on the ball -- the "
            "**handler**. You have one player there, your playmaker, so "
            "they are chosen for you. Then you decide what they do.\n\n"
            "A handler can do three things: shoot, maneuver, or cede "
            "the ball to buy a coaching window. **You are not offered "
            "the shot** -- a shot may only be taken from inside your "
            "shooting range, which is M3 and beyond, and you are one "
            "space short of it.\n\n"
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
            "Dinky's playmaker is standing on the ball, so they are the "
            "one challenging you.\n\n"
            "**Pick Dribble Advance.** It beats Deflect, which is "
            "what Dinky has played, and it is the card that carries the "
            "ball up the field."
        ),
        player_has_ball=True,
        player_maneuver=DRIBBLE_ADVANCE,
        dinky_maneuver=DEFLECT,
        # Two spaces is the Playmaker's own ability and this beat exists
        # partly to show it. The speed dial is pinned at no change
        # rather than taught here: the turnover in beat 2 resets the
        # ball's speed, so anything set now is thrown away, and beat 4
        # is where a change actually reaches the shot.
        choices={"dribble_advance": "2", "speed": "1"},
    ),
    TutorialBeat(
        step=2,
        title="Roles, abilities, and a tie",
        lesson=(
            "## 2. Every role has an ability\n"
            "Dribble Advance beat Deflect outright -- no dice, "
            "because the cycle had already settled it -- and your "
            "playmaker carried the ball **two** spaces, from M2 to "
            "**V1**.\n\n"
            "Moving forward two spaces is not the ordinary move. "
            "A dribble advances typically moves the playerone "
            "space. But your **Playmaker** is a skilled dribbler and "
            "can move up to two: that is "
            "the Playmaker role ability. **Every player has a role and every "
            "role has an ability**, printed on their card and worth "
            "reading before you pick a maneuver -- the Fullback throws "
            "a longer High Pass, the Midfielder gets +3 on a Low Pass "
            "or Pressure test, the Defender steals the ball off a won "
            "Pressure. Two commands list them whenever you want: "
            "**`/d12ball role_abilities`** for all six, and **`/d12ball "
            "team_roster`** gives you a list of your team with their roles.\n\n"
            "You are on V1 now, which is inside your shooting range, so "
            "the **Shoot** button has appeared. It is greyed out here, "
            "and it would be a poor shot anyway: your playmaker's "
            "offensive skill is 4, Dinky's defender is standing on the "
            "ball and their fullback is behind them -- roughly d12+4 "
            "against d12+8. We will make a much better one shortly.\n\n"
            "**Press Maneuver.**"
        ),
        maneuver_note=(
            "### When both cards are the same rank\n"
            "Every maneuver has a **rank**, and two cards of the same "
            "rank **tie**. A tie is not a draw -- it goes to a **skill "
            "test**: both players roll a d12 and add their skill, the "
            "attacker their offensive and the defender their defensive, "
            "plus whatever their ability is worth. Highest total takes "
            "it, and both players pick up an **exhaustion token** for "
            "the effort. Tokens are the game's running cost; enough of "
            "them and a player risks getting injured.\n\n"
            "**Pick Low Pass.** It is rank 1, just like the "
            "Deflect Dinky has played, so this one goes to the dice -- "
            "and Dinky is going to win it. Watch what a won "
            "Deflect does: the ball is knocked back a space and comes "
            "**loose**, belonging to nobody. Dinky already has a "
            "midfielder standing right where it lands, so they simply "
            "keep it -- no roll, no contest. A loose ball only opens up "
            "to both sides when the space it lands on is empty."
        ),
        player_has_ball=True,
        player_maneuver=LOW_PASS,
        dinky_maneuver=DEFLECT,
        # The coach has to lose this, or the ball never comes free and
        # beats 3 and 4 -- the two lessons in defending -- have nothing
        # to defend against. See the module docstring. There is no
        # loose-ball roll to rig any more: Dinky's own midfielder is
        # already standing on M3 where the beaten Deflect lands, so
        # since 2026-08-24 they keep it outright and nothing is asked
        # of either coach.
        rolls={"skill_test": (2, 11)},
    ),
    TutorialBeat(
        step=3,
        title="Your turn to defend",
        lesson=(
            "## 3. Your turn to defend\n"
            "Dang it. You lost possession. Dinky won the skill test, their "
            "Deflect knocked it back to **M3** and loose -- right onto "
            "one of their own midfielders, who was already standing "
            "there. Nobody of yours was, so they kept it outright, no "
            "roll needed. Your playmaker, left standing outside her own "
            "zone at V1, has run back into midfield -- and paid an "
            "exhaustion token per space to do it.\n\n"
            "Dinky is coming at your goal now, and this time **nobody "
            "of yours is anywhere near the ball**. Before anything "
            "else, you'll be asked to send a challenger to it -- pick "
            "either of the two offered, it costs the same either way. "
            "Sending nobody would let Dinky's maneuver straight "
            "through unchallenged, so that button is greyed out here.\n\n"
            "Once your challenger is in position, Dinky moves, and "
            "then you are asked for a card."
        ),
        maneuver_note=(
            "### The other three cards\n"
            "Defending, your hand is the other half of the cycle:\n\n"
            "- **Deflect** -- knocks the ball back a space and loose. "
            "Land it somewhere empty and either side may send someone "
            "after it; land it on a side that's already there and it's "
            "theirs outright, no contest. You were on the wrong end of "
            "one last turn.\n"
            "- **Steal** -- takes the ball outright. A "
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
        # Beat 2 no longer leaves a defeated contestant standing on the
        # ball for this challenge to fall to automatically -- see the
        # 2026-08-24 entry in the rules log. The coach now has to send
        # one of two equally-near players in; which of them goes is
        # free (neither beat downstream cares), but declining and
        # letting Pressure through unchallenged would leave nothing to
        # defend against, so that alone is railed.
        choices={"challenge_decline": "never"},
    ),
    TutorialBeat(
        step=4,
        title="Winning the ball back",
        lesson=(
            "## 4. Winning the ball back\n"
            "Pressure drove them backwards: their handler and the ball "
            "went back a space to **V1**, and your challenger moved up "
            "onto them. Dinky still has it -- but they have lost "
            "ground, and you are standing on the ball.\n\n"
            "Now take it off them."
        ),
        maneuver_note=(
            "### Turnovers, the run back, and ball speed\n"
            "**Pick Steal.** Dinky is playing Low Pass, and "
            "Steal beats it -- the ball will be yours again!\n\n"
            "Two things happen after it. Your player takes the ball "
            "back a space with them, and **anyone left standing outside "
            "their own zone runs back into it** =gainin an exhaustion per space, the "
            "same cost you watched Dinky pay two turns ago.\n\n"
            "Then you get to set the **ball's speed**, up to your "
            "stealer's defensive skill. Speed is worth half itself, "
            "rounded down, **added to a score attempt** -- and it is "
            "reset by every turnover, so a speed set now is one that "
            "survives. You are about to shoot. **Take the highest "
            "number offered**; the rest are greyed out."
        ),
        player_has_ball=False,
        player_maneuver=STEAL,
        dinky_maneuver=LOW_PASS,
        # The one speed change in the script that survives to the shot:
        # a turnover resets the ball's speed and this is set *after*
        # the reset, so it is still on the ball when the striker takes
        # aim a beat later. CHOICE_MAX because the cap is the stealer's
        # own defensive skill, and who does the stealing is not
        # something the script fixes. (Steal beats Low Pass decisively
        # -- there is no loose ball here to rail.)
        choices={"speed": CHOICE_MAX},
    ),
    TutorialBeat(
        step=5,
        title="A shot at goal",
        lesson=(
            "## 5. A shot at goal\n"
            "The ball is yours again, on **M3**, and moving fast. This "
            "is the last lesson, and it is worth a goal.\n\n"
            "M3 is inside your shooting range, so **Shoot** is offered "
            "again -- and again it is the wrong button. Your midfielder "
            "has an offensive skill of 3 and Dinky's players are between "
            "you and the goal.\n\n"
            "Look at **V2** instead. Your striker has been standing "
            "there all game, inside shooting range, offensive skill "
            "**6** -- the best on your team.\n\n"
            "A High Pass of exactly 2 spaces lands on V2. A pass that "
            "reaches a teammate already inside shooting range is a "
            "**scoring opportunity**: they shoot immediately, out of "
            "turn. And the Striker's ability is worth **+3** on "
            "precisely that shot.\n\n"
            "**Press Maneuver.**"
        ),
        maneuver_note=(
            "### High Pass, and what a shot is up against\n"
            "**Pick High Pass.** Dinky is playing Steal, and "
            "High Pass beats it, so the pass gets through.\n\n"
            "You will be asked how far to throw. **2 spaces** is the "
            "only distance offered here -- a longer throw would run off "
            "the end of the field, and the menu never offers one that "
            "would. It is also the distance you want: a pass of 2 is "
            "caught cleanly, where a 3-space throw has to be *won* by "
            "whoever it lands near, with the ball's speed counting "
            "against them.\n\n"
            "Then take the shot. A score attempt is your d12 plus the "
            "shooter's offensive skill and half the ball's speed, "
            "against Dinky's d12 plus every defender in the way -- one "
            "standing **on** the ball adds all of their defensive "
            "skill, one further back adds half, rounded up. Ties go to "
            "the shooter.\n\n"
            "Their fullback is standing on V2, so you get their whole "
            "defensive skill of 6 against you. Even so: your striker "
            "rolls **d12+11** against their **d12+6**. That is a real "
            "roll and it can miss -- but you should score about six "
            "times in seven."
        ),
        player_has_ball=True,
        player_maneuver=HIGH_PASS,
        dinky_maneuver=STEAL,
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


def resolve_choice(
    beat: Optional[TutorialBeat],
    key: str,
    options,
) -> Optional[object]:
    """
    The one option out of `options` this beat allows, or None for no
    rail.

    Keys name the view that asks: `dribble_advance`, `speed`,
    `high_pass`, `setup_attempt`, `loose_ball_decline`,
    `challenge_decline`. Every one of them decides where the ball ends
    up, what it is worth, or whether a maneuver gets contested at all,
    which is why they are railed at all -- see the module docstring on
    what is deliberately left free.

    **A rail matching nothing on offer is no rail**, rather than a
    prompt with every button dead. The script and the flow can only
    disagree by mistake, and a coach stuck with nothing to press is a
    worse failure than a lesson that did not land.
    """
    wanted = None if beat is None else beat.choices.get(key)
    if wanted is None:
        return None
    options = list(options)
    if wanted == CHOICE_MAX:
        return max(options) if options else None
    for option in options:
        if str(option) == wanted:
            return option
    return None


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
        maneuver.key
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

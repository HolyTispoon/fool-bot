"""
The contested rolls, with no dice image in them.

Four rolls in this game are two-sided -- a maneuver's skill test, the
contest for a loose ball (which the long High Pass comes through), a
score attempt against the wall of defenders, and a shootout test -- and
until Phase 6 of docs/model-discord-split.md all four lived in a
`discord.ui.View`. The arithmetic and the verdict were interleaved with
rendering the dice, so a second frontend could not roll a skill test
without reimplementing what a skill test *is*.

**Each of them returns two things, and that is the shape
`own_goal_roll_step` settled.** The `StepResult` is the sentences --
what the roll came to, and what happens because of it -- and the
`ContestDice` beside it is the same numbers for the picture. They are
separate because the frontend puts the image *between* two of the
lines: a message's attachments render below its content, so a verdict
written above the roll would be read before it. How the lines and the
picture go together is the frontend's (principle 8 in CLAUDE.md); what
they say is not.

**Nothing here draws anything.** `render_contest_dice` in
`cogs/d12ball_views/base.py` takes `ContestDice.contestants` and is the
whole of the Discord half, and the tuple it takes is the one these
functions already built -- so the move is the arithmetic crossing the
seam and the Pillow staying where it is.

The four differ in ways worth holding in mind, because each difference
is a rule rather than an accident:

- **Injury withholds a contestant's own skill in the loose ball and
  the shootout, and not in the skill test or the score attempt.** See
  "Injured players" in docs/living-rules.md.
- **A tie is re-rolled in the skill test and the loose ball**, at a
  token each; a score attempt goes to the attacker on level totals, and
  a shootout tie simply scores for nobody.
- **The tutorial scripts the skill test's dice and the loose ball's**,
  and deliberately scripts neither of the other two -- a beat only
  fixes a roll the next beat depends on. See
  "Determinism: rails and dice" in docs/design/tutorial.md.
- **Only the skill test and the score attempt write an event**, which
  is what `stats.py` folds over.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional, Sequence

from d12ball import tutorial
from d12ball.components import (
    EVENT_SHOT,
    EVENT_SKILL_TEST,
    MatchState,
    PlayerDefinition,
    PlayerRole,
    SPECIES_CYBORG,
    TeamSide,
)
from d12ball.engine import RulesEngine
from d12ball.flow import injuries
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.flow.turn import tutorial_beat
from d12ball.formatting import (
    contest_noun,
    contestant_detail,
    format_goal_time,
    format_player_with_team,
    player_with_role,
)
from d12ball.game import D12BallGame, Team
from d12ball.prompts import PendingPrompt, PromptKind


#: One side of a contest, exactly as `render_contest_dice` draws it.
#: A tuple rather than a dataclass because that is the shape the
#: renderer has always taken and the move is not the place to change
#: it: `(roll, team, detail lines, total, overdriven, merge
#: contributors)`.
Contestant = tuple[int, Team, list[str], int, bool, list[tuple[str, int]]]


@dataclass(frozen=True)
class ContestDice:
    """
    The numbers behind a two-sided roll, for the picture of it.

    **Not narration and not a `StepResult`.** What the roll *means* is
    in the result beside this; what is here is what a die shows and
    what was added to it, which a frontend with no dice image ignores
    entirely -- the image carries the whole arithmetic, which is why no
    message that posts one repeats it in text.

    `ignites` is `(player_id, IgnitedRoll)` a side, in the order they
    rolled, because Volatile's second die goes up on an image of its
    own between the roll and the verdict. A roll with one side (the
    score attempt: the wall of defenders has no species) carries one.
    """

    contestants: list[Contestant]
    ignites: tuple[tuple[str, object], ...] = ()


def _scripted_or_random(
    game: D12BallGame,
    kind: str,
    count: int,
) -> list[int]:
    """
    The dice the tutorial's script fixes for this contest, or real
    ones.

    `D12Ball.tutorial_dice` was this, and it was two lines over
    `tutorial.scripted_dice` -- which reads the beat and nothing else,
    so it was already on the model's side of the line in everything but
    its address.
    """
    scripted = tutorial.scripted_dice(tutorial_beat(game), kind, count)
    if scripted:
        return list(scripted)
    return [random.randint(1, 12) for _ in range(count)]


def _with_extras(
    engine: RulesEngine,
    match: MatchState,
    detail: list[str],
    ignite: object,
    player_id: str,
) -> None:
    """
    Add the two lines every contestant can carry beyond their own
    skill: an ignition and an Overdrive.

    Both are asked of every roller in every game -- a basic game gets
    an ignite that is the face and nothing else, and a side with no
    Cyborg gets no Overdrive line -- because asking per side is what
    makes "if both are Fire Demons, each checks their own" fall out
    rather than be written twice.
    """
    for line in (
        getattr(ignite, "detail", None),
        engine.overdrive_detail(match, player_id),
    ):
        if line:
            detail.append(line)


def pay_contest_tie(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    first_player_id: str,
    second_player_id: str,
    offense_total: int,
    defense_total: int,
) -> str:
    """
    Charge both contestants the re-roll's exhaustion token and word the
    tie -- shared by the maneuver skill test and the loose ball (which
    the long High Pass also comes through).

    The token counts towards Exhausted straight away, so whoever it
    pushes over is already flagged when the test finally resolves and
    hands out its injury checks.

    **It no longer saves.** `SafeView.pay_skill_test_tie` did, and a
    step does not (principle 9): the two callers here are steps
    themselves, and their frontend writes the match once after them.
    """
    exhaustion_text = "\n".join(
        [
            engine.apply_exhaustion(game, match, first_player_id, 1),
            engine.apply_exhaustion(game, match, second_player_id, 1),
        ]
    )
    # Headed like the outcome it is: a tie is one of the four ways a
    # skill test lands, and every other one is announced at `##`. Left
    # as bold body text it read as a footnote to the dice rather than
    # the result of them.
    return (
        f"## **It's a tie ({offense_total}-{defense_total})!**\n"
        f"The skill test must be rolled again.\n"
        f"{exhaustion_text}\n\nRoll again:"
    )


# -- The maneuver skill test -------------------------------------------


def score_skill_test(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    offense_player: PlayerDefinition,
    defense_player: PlayerDefinition,
) -> tuple[list[Contestant], int, int, object, object]:
    """
    Roll the maneuver skill test and add everything that counts
    towards it, as the two sides the dice image draws plus the totals
    the outcome is read off.

    The dice image carries the whole arithmetic -- who rolled, what
    they rolled, every modifier and the total -- which is why no
    message that posts one repeats it in text.

    Nothing here is withheld for injury. What an injured player loses
    is their own offensive or defensive skill and only in a contest,
    which is the loose ball and the shootout; a maneuver's skill test
    pays every modifier to an injured player. See "Injured players" in
    docs/living-rules.md.

    **Both ignites come back with the totals**, because this is the one
    roll site where Volatile does something besides arithmetic: the
    caller needs to know which side surged or backfired to set the tier
    rider once it knows who won. See `RulesEngine.volatile_raises_tier`.
    """
    offense_skill = engine.player_catalog.effective_profile(
        offense_player,
    ).offense
    defense_skill = engine.player_catalog.effective_profile(
        defense_player,
    ).defense

    offense_roll, defense_roll = _scripted_or_random(game, "skill_test", 2)

    # Volatile, on each side's own die and before any skill is added --
    # the ignite reads the natural face.
    offense_ignite = engine.ignite(
        game, offense_player.player_id, offense_roll,
    )
    defense_ignite = engine.ignite(
        game, defense_player.player_id, defense_roll,
    )

    # Overdrive was declared and paid before the button was pressed;
    # what is left is to add it and clear the declaration, which
    # `skill_test_step` does once both sides have been read.
    offense_overdrive = match.overdrive_modifier(offense_player.player_id)
    defense_overdrive = match.overdrive_modifier(defense_player.player_id)

    offense_total = (
        offense_roll + offense_skill + offense_ignite.modifier
        + offense_overdrive
    )
    defense_total = (
        defense_roll + defense_skill + defense_ignite.modifier
        + defense_overdrive
    )

    offense_detail = contestant_detail(
        offense_player, "Offensive", offense_skill,
    )
    defense_detail = contestant_detail(
        defense_player, "Defensive", defense_skill,
    )
    _with_extras(
        engine, match, offense_detail, offense_ignite,
        offense_player.player_id,
    )
    _with_extras(
        engine, match, defense_detail, defense_ignite,
        defense_player.player_id,
    )

    # Role ability -- Midfielder: +3 on a skill test when attempting
    # Low Pass (offense) or Pressure (defense).
    #
    # **Read by rank, so a gambit inherits it.** The Midfielder's +3
    # and the ball speed modifier below are listed against both cards
    # on their rank in the sheet's own `Interactions` column, and
    # neither contradicts what the gambit does. The three that *do*
    # contradict -- the Fullback on Clear, the Playmaker on Dribble
    # Burst, the Fullback's pass distance on Setup Pass -- are the
    # author's to settle and are deliberately not inherited anywhere;
    # see "Still open" in docs/gambit-matrix.md.
    if (
        offense_player.role == PlayerRole.MIDFIELDER
        and match.offense_maneuver in ("low_pass", "skilled_pass")
    ):
        offense_total += 3
        offense_detail.append("+3 Midfielder ability")

    if (
        defense_player.role == PlayerRole.MIDFIELDER
        and match.defense_maneuver in ("pressure", "double_team")
    ):
        defense_total += 3
        defense_detail.append("+3 Midfielder ability")

    if match.defense_maneuver in ("steal", "intercept"):
        modifier = match.ball.speed // 2
        defense_total += modifier
        defense_detail.append(f"+{modifier} ball speed modifier")

    # **Merge**: an Ooze standing on the ball who is not one of the two
    # rolling adds to their own side -- offensive skill on the attack,
    # defensive on the defence. A maneuver's skill test is always
    # fought on the ball's space, so it always qualifies.
    rolling = (offense_player.player_id, defense_player.player_id)
    (
        offense_merge, offense_merge_lines, offense_merge_contributors,
    ) = engine.merge_bonus(
        game, match, match.ball.possession, rolling, "offense",
    )
    (
        defense_merge, defense_merge_lines, defense_merge_contributors,
    ) = engine.merge_bonus(
        game, match, match.defending_side(), rolling, "defense",
    )
    offense_total += offense_merge
    defense_total += defense_merge
    offense_detail.extend(offense_merge_lines)
    defense_detail.extend(defense_merge_lines)

    # **A won Double Team lands on the *next* maneuver**: both
    # defenders challenge the ball holder, and both add their defensive
    # skill. `double_team_defenders` is challenger-first and holds the
    # second only while `pending_double_team` is set, which one card
    # sets and a new play clears -- so this is a no-op in every game
    # that never played it.
    double_team_detail = ""
    partners = [
        player_id
        for player_id in engine.double_team_defenders(match)
        if player_id != match.challenger_id
    ]
    for player_id in partners:
        partner = engine.get_player_definition(player_id)
        partner_skill = engine.player_catalog.effective_profile(
            partner
        ).defense
        defense_total += partner_skill
        double_team_detail = f"+{partner_skill} {partner.name} (Double Team)"
    if double_team_detail:
        defense_detail.append(double_team_detail)

    return (
        [
            (
                offense_roll,
                match.team_for_player(offense_player.player_id),
                offense_detail,
                offense_total,
                bool(offense_overdrive),
                offense_merge_contributors,
            ),
            (
                defense_roll,
                match.team_for_player(defense_player.player_id),
                defense_detail,
                defense_total,
                bool(defense_overdrive),
                defense_merge_contributors,
            ),
        ],
        offense_total,
        defense_total,
        offense_ignite,
        defense_ignite,
    )


def skill_test_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> tuple[ContestDice, StepResult]:
    """
    The maneuver skill test, off the button either coach may press:
    roll, settle who won, and queue whatever injury tests the contest
    owes.

    **A tie comes back as the same prompt worded by what happened.**
    Both contestants are charged a token and the test is rolled again,
    which leaves the match in exactly the state `pending_prompt` reads
    as `SKILL_TEST` -- so the result's `next` is that prompt, with the
    tie as its `ask`. A frontend re-puts the question; it does not have
    to know that a tie is a thing.

    **The winner's line is the first narration block**, and what the
    injury queue says follows it, because the frontend posts the first
    as its own message under the dice and hands the rest on. Same
    unpacking as `own_goal_roll_step`.
    """
    offense_player = engine.get_player_definition(match.active_player_id)
    defense_player = engine.get_player_definition(match.challenger_id)

    (
        contestants,
        offense_total,
        defense_total,
        offense_ignite,
        defense_ignite,
    ) = score_skill_test(
        engine, game, match, offense_player, defense_player,
    )
    dice = ContestDice(
        contestants,
        (
            (offense_player.player_id, offense_ignite),
            (defense_player.player_id, defense_ignite),
        ),
    )
    # Spent, win, lose or tie: a tie that is re-rolled is a fresh roll
    # and has to be Overdriven again.
    match.consume_overdrive()
    # Logged before either branch, so a tie that re-rolls is in the
    # record as well as the roll that settles it -- a maneuver decided
    # on the third attempt cost three rolls and six exhaustion tokens,
    # and only the log says so. It is also what `record_maneuver` reads
    # to tell a win on the dice from a win on the cards, so it has to
    # be written before the effect is dispatched.
    match.record_event(
        EVENT_SKILL_TEST,
        side=match.ball.possession,
        player_id=match.active_player_id,
        offense_total=offense_total,
        defense_total=defense_total,
        tied=offense_total == defense_total,
        offense_key=match.offense_maneuver,
        defense_key=match.defense_maneuver,
    )

    if offense_total == defense_total:
        return dice, StepResult(
            board_changed=True,
            next=PendingPrompt(
                PromptKind.SKILL_TEST,
                pay_contest_tie(
                    engine,
                    game,
                    match,
                    match.active_player_id,
                    match.challenger_id,
                    offense_total,
                    defense_total,
                ),
            ),
        )

    outcome = "offense" if offense_total > defense_total else "defense"
    winner_key = (
        match.offense_maneuver
        if outcome == "offense"
        else match.defense_maneuver
    )
    winner_name = engine.maneuver_name(winner_key)

    # **Volatile's tier rider**, settled here because this is the first
    # point that knows who won. Both of the rules' two cases raise the
    # winner's card, so this is one flag -- see
    # `RulesEngine.volatile_raises_tier`. It is written onto the match
    # rather than passed down to the effect because the injury tests
    # run in between: `resolving_maneuver` is asked on the far side of
    # them, possibly after a restart.
    winner_ignite, loser_ignite = (
        (offense_ignite, defense_ignite)
        if outcome == "offense"
        else (defense_ignite, offense_ignite)
    )
    match.volatile_tier_upgrade = engine.volatile_raises_tier(
        game, winner_ignite, loser_ignite,
    )
    # The other half: the losing side's own ignite decides whether they
    # pay their gambit's cost, whatever the cards said.
    match.volatile_loser_cost = engine.volatile_loser_cost(
        game, loser_ignite,
    )
    volatile_lines = []
    if match.volatile_tier_upgrade:
        raised = engine.maneuver_name(
            engine.resolving_maneuver(match, winner_key),
        )
        volatile_lines.append(
            "🔥 **Volatile** — "
            + ("the surge" if winner_ignite.surge else "the backfire")
            + f" raises it to **{raised}**."
        )
    # Said only where there is a gambit's cost for it to have changed:
    # a coach told "the surge spares them the cost" of a card that
    # carried none is being answered a question nobody asked (see "What
    # a message says" in docs/design/naming-and-wording.md).
    loser_card = engine.maneuver_catalog.get(
        match.opposing_maneuver(winner_key) or "",
    )
    if (
        match.volatile_loser_cost is not None
        and loser_card is not None
        and loser_card.is_gambit
    ):
        volatile_lines.append(
            "🔥 **Volatile** — the backfire also costs them their "
            "gambit's price."
            if match.volatile_loser_cost
            else "🔥 **Volatile** — the surge spares them their "
            "gambit's cost."
        )
    volatile_note = "\n" + "\n".join(volatile_lines) if volatile_lines else ""

    exhausted_participants = [
        player
        for player in (offense_player, defense_player)
        if player.player_id in match.exhausted
    ]

    # The effect is on the far side of the injury tests now that each
    # of those is a click of its own, so it is handed over as the
    # queue's continuation rather than run here -- see
    # `injuries.begin_injury_tests`. With nobody exhausted this still
    # resolves in the same breath as the roll.
    result = injuries.begin_injury_tests(
        engine,
        game,
        match,
        exhausted_participants,
        {"kind": "maneuver_effect", "winner_key": winner_key},
    )
    result.narration.insert(
        0, f"## **{winner_name}** wins the skill test!{volatile_note}",
    )
    result.board_changed = True
    return dice, result


# -- The loose ball, and the long High Pass --------------------------


def score_loose_ball(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    offense_player: PlayerDefinition,
    defense_player: PlayerDefinition,
) -> tuple[list[Contestant], int, int, object, object]:
    """
    Roll the contest for the ball and add what counts towards it, as
    the two sides the dice image draws plus the totals the winner is
    read off. Serves the loose ball and the long High Pass alike, which
    is the only contest injury and the ball speed modifier both bite
    in.

    No text breakdown goes alongside it: the dice image already names
    both players and shows every modifier that built the totals.
    **Both ignites come back with them**, because the second die each
    one rolled is posted on an image of its own.
    """
    # An injured contestant adds no skill modifier -- their own
    # offensive or defensive skill stays off the roll, and that is the
    # whole of the disadvantage here (see "Injured players" in
    # docs/living-rules.md). It is only the skill: every other modifier
    # still applies, which is why the ball speed modifier below is
    # added without asking about injury.
    offense_injured = match.loose_ball_offense_player in match.injured
    defense_injured = match.loose_ball_defense_player in match.injured
    offense_skill = (
        0
        if offense_injured
        else engine.player_catalog.effective_profile(offense_player).offense
    )
    defense_skill = (
        0
        if defense_injured
        else engine.player_catalog.effective_profile(defense_player).defense
    )

    offense_roll, defense_roll = _scripted_or_random(game, "loose_ball", 2)

    # Volatile, per side and on the natural face. **Injury does not
    # withhold it**: what an injured contestant loses here is their own
    # skill modifier and only that, and an ignite is the die rather
    # than a modifier the player brings -- the same reading that leaves
    # the ball speed modifier below alone.
    offense_ignite = engine.ignite(
        game, offense_player.player_id, offense_roll,
    )
    defense_ignite = engine.ignite(
        game, defense_player.player_id, defense_roll,
    )

    offense_overdrive = match.overdrive_modifier(offense_player.player_id)
    defense_overdrive = match.overdrive_modifier(defense_player.player_id)
    offense_total = (
        offense_roll + offense_skill + offense_ignite.modifier
        + offense_overdrive
    )
    defense_total = (
        defense_roll + defense_skill + defense_ignite.modifier
        + defense_overdrive
    )

    offense_detail = contestant_detail(
        offense_player, "Offensive", offense_skill,
        injured=offense_injured,
        cyborg=engine.has_species_ability(
            game, offense_player.player_id, SPECIES_CYBORG,
        ),
    )
    defense_detail = contestant_detail(
        defense_player, "Defensive", defense_skill,
        injured=defense_injured,
        cyborg=engine.has_species_ability(
            game, defense_player.player_id, SPECIES_CYBORG,
        ),
    )
    _with_extras(
        engine, match, offense_detail, offense_ignite,
        offense_player.player_id,
    )
    _with_extras(
        engine, match, defense_detail, defense_ignite,
        defense_player.player_id,
    )

    # A High Pass's receiver adds the ball speed modifier to keep what
    # the pass delivered (2026-08-07). A genuine loose ball is nobody's
    # yet, so neither side gets it there.
    #
    # The modifier is signed: this contest is also where a declined
    # overshoot set-up lands, and an overshoot pays the modifier
    # against the receiver in the contest exactly as it would have
    # against the shot (2026-08-10). See `ball_speed_modifier`.
    if match.pending_loose_ball_is_high_pass:
        modifier = match.ball_speed_modifier()
        offense_total += modifier
        offense_detail.append(f"{modifier:+d} ball speed modifier")

    # **Merge**, for a contest fought on the ball's space -- which this
    # always is: both contestants have been walked onto it by the time
    # the roll happens. An Ooze of either side standing there who is
    # not one of the two rolling adds to their own.
    rolling = (
        match.loose_ball_offense_player,
        match.loose_ball_defense_player,
    )
    offense_merge, offense_lines, offense_contributors = engine.merge_bonus(
        game, match, match.ball.possession, rolling, "offense",
    )
    defense_merge, defense_lines, defense_contributors = engine.merge_bonus(
        game, match, match.defending_side(), rolling, "defense",
    )
    offense_total += offense_merge
    defense_total += defense_merge
    offense_detail.extend(offense_lines)
    defense_detail.extend(defense_lines)

    return (
        [
            (
                offense_roll,
                match.team_for_player(offense_player.player_id),
                offense_detail,
                offense_total,
                bool(offense_overdrive),
                offense_contributors,
            ),
            (
                defense_roll,
                match.team_for_player(defense_player.player_id),
                defense_detail,
                defense_total,
                bool(defense_overdrive),
                defense_contributors,
            ),
        ],
        offense_total,
        defense_total,
        offense_ignite,
        defense_ignite,
    )


def settle_loose_ball_winner(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    offense_player: PlayerDefinition,
    defense_player: PlayerDefinition,
    offense_total: int,
    defense_total: int,
) -> tuple[str, list[PlayerDefinition], int, bool]:
    """
    Give the ball to whoever won the contest and word the result: the
    announcement, who owes an injury test, and the two things the run
    back behind it needs -- both read off the match before this clears
    them.
    """
    outcome = "offense" if offense_total > defense_total else "defense"
    winner_side = (
        match.ball.possession
        if outcome == "offense"
        else match.defending_side()
    )
    turnover_occurred = winner_side != match.ball.possession
    winner_number = (
        engine.possession_player_number(game, match)
        if outcome == "offense"
        else engine.defending_player_number(game, match)
    )
    winner_mention = format_player_with_team(
        game, winner_number, engine.team_emojis, mention=True,
    )
    winner_player = offense_player if outcome == "offense" else defense_player

    exhausted_participants = [
        player
        for player in (offense_player, defense_player)
        if player.player_id in match.exhausted
    ]
    distance_moved = match.pending_loose_ball_distance
    is_high_pass = match.pending_loose_ball_is_high_pass
    # Read with the rest of the position, before anything below clears
    # it: what the ball was is a fact about where it came down, and
    # only a space nobody was standing on makes it loose (the author,
    # 2026-08-26). Two players rolling for it is a contest, and calling
    # that a loose ball in the result told a coach the opposite of what
    # they had just watched.
    noun = contest_noun(match)

    match.ball.possession = winner_side
    if turnover_occurred:
        match.ball.speed = 1
    # Whoever won the contest is holding the ball, and takes the next
    # turn -- the receiver who kept a long High Pass, or either side's
    # contestant who won a loose ball. Confirmed by the author
    # 2026-08-09; see "Choosing the handler" in docs/living-rules.md.
    match.set_ball_carrier(winner_player.player_id)
    match.pending_loose_ball = False
    match.loose_ball_offense_player = None
    match.loose_ball_defense_player = None

    turnover_line = "# Turnover!\n\n" if turnover_occurred else ""
    winner_bracket = engine.format_player_label(match, winner_player)
    if is_high_pass:
        outcome_line = (
            f"{winner_bracket} wins possession off the high pass! "
            f"{winner_mention} has possession."
            if turnover_occurred
            else f"{winner_bracket} keeps possession after the high "
            f"pass! {winner_mention} has possession."
        )
    else:
        outcome_line = (
            f"{winner_bracket} wins the {noun}! {winner_mention} "
            "has possession."
        )

    return (
        f"{turnover_line}{outcome_line}",
        exhausted_participants,
        distance_moved,
        turnover_occurred,
    )


def loose_ball_test_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> tuple[ContestDice, StepResult]:
    """
    The contest for the ball, off the button either coach may press.

    The same shape as `skill_test_step` and for the same reasons: a tie
    comes back as the prompt this position reads as, worded by what
    happened, and the winner's line is the first narration block with
    the injury queue's own behind it.

    **Winning a live ball off the other side is a steal however it was
    contested**, so no substitution window either way. The run back
    waits behind whatever injury tests this contest owes and carries
    its two arguments through the queue, because nothing left in the
    match still says what they were.
    """
    offense_player = engine.get_player_definition(
        match.loose_ball_offense_player,
    )
    defense_player = engine.get_player_definition(
        match.loose_ball_defense_player,
    )

    (
        contestants,
        offense_total,
        defense_total,
        offense_ignite,
        defense_ignite,
    ) = score_loose_ball(
        engine, game, match, offense_player, defense_player,
    )
    dice = ContestDice(
        contestants,
        (
            (offense_player.player_id, offense_ignite),
            (defense_player.player_id, defense_ignite),
        ),
    )
    match.consume_overdrive()

    if offense_total == defense_total:
        return dice, StepResult(
            board_changed=True,
            next=PendingPrompt(
                PromptKind.LOOSE_BALL_SKILL_TEST,
                pay_contest_tie(
                    engine,
                    game,
                    match,
                    match.loose_ball_offense_player,
                    match.loose_ball_defense_player,
                    offense_total,
                    defense_total,
                ),
            ),
        )

    (
        announcement,
        exhausted_participants,
        distance_moved,
        turnover_occurred,
    ) = settle_loose_ball_winner(
        engine, game, match, offense_player, defense_player,
        offense_total, defense_total,
    )
    result = injuries.begin_injury_tests(
        engine,
        game,
        match,
        exhausted_participants,
        {
            "kind": "run_back",
            "distance_moved": distance_moved,
            "turnover_occurred": turnover_occurred,
        },
    )
    result.narration.insert(0, announcement)
    result.board_changed = True
    return dice, result

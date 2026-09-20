"""
The front half of a turn: the AI's own maneuver picks, and the reveal
that settles a maneuver on the cards.

**This is the part of the spine nothing in Phases 1 to 3 touched.** The
ranks lifted the twelve *effects* -- what a card does once it has won --
and left everything in front of them where it was, so `resolve_maneuver`
was still the cog deciding which maneuver won and wording it. Both
routes go through here: a human's pick from the maneuver prompt, and
`play_ai_turn`'s.

A step takes the engine and the match, mutates, and says what happened
-- see "The model and the Discord layer" in CLAUDE.md, and
docs/model-discord-split.md for what is still in `cogs/`.
"""

from __future__ import annotations

from typing import Optional

from d12ball.components import MatchState
from d12ball.engine import RulesEngine
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.formatting import format_player_with_team
from d12ball.game import D12BallGame


def write_ai_maneuver_picks(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> None:
    """
    Dinky answers before the prompt is built, which is what makes a
    solo game's prompt one hand and one row --
    `RulesEngine.maneuver_pick_sides` is read afterwards, so it already
    knows the AI has picked.

    A tutorial beat names the card Dinky plays, and it is written
    straight into the match here rather than through the strategy:
    `choose_maneuver_action` takes a side and nothing else, so it has
    no way to know which beat is running, and changing its signature
    for one caller would put the script inside the AI. Dinky's pick is
    made before the coach's exactly as it always is -- the rails decide
    what the coach may answer with, not the other way round.
    """
    if not game.is_solo_game:
        return

    ai_strategy = engine.get_ai_strategy(game)
    beat = engine.tutorial_beat(game)

    if engine.possession_player_number(game, match) == 2:
        scripted = beat.dinky_maneuver_for("offense") if beat else None
        match.choose_offense_maneuver(
            scripted
            or ai_strategy.choose_maneuver_action(
                "offense",
                engine.maneuver_hand(game, match, "offense"),
            )
        )
    if (
        not match.maneuver_uncontested
        and engine.defending_player_number(game, match) == 2
    ):
        scripted = beat.dinky_maneuver_for("defense") if beat else None
        match.choose_defense_maneuver(
            scripted
            or ai_strategy.choose_maneuver_action(
                "defense",
                engine.maneuver_hand(game, match, "defense"),
            )
        )


def maneuver_winner_text(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    reveal: str,
    outcome: Optional[str],
    winner_name: str,
    offense_name: str,
    defense_name: str,
) -> str:
    """
    How a maneuver settled on the cards reads. Two wordings: an
    ordinary decisive win, and a tie one injured participant loses
    outright.
    """
    if outcome != "tie":
        # Headed the same way a won skill test is (see
        # SkillTestView.roll), so the two ways a maneuver can be won
        # read alike. Whoever resolves the effect isn't named here: an
        # effect with a choice in it prompts them by name itself, and
        # one without needs nobody to do anything.
        return f"{reveal}\n\n## **{winner_name}** wins!"

    # A tie with exactly one injured participant: they lose it
    # outright. Nothing is rolled, so neither side pays the token a
    # skill test would have cost them.
    injured_player_id = (
        match.challenger_id
        if match.challenger_id in match.injured
        else match.active_player_id
    )
    injured_player = engine.get_player_definition(injured_player_id)
    word, emoji = engine.injured_word_and_emoji(game, injured_player_id)
    return (
        f"{reveal}\n\n"
        f"**{offense_name}** ties with **{defense_name}**, but "
        f"{engine.format_player_label(match, injured_player)}"
        f" is **{word}** "
        f"{emoji} and "
        "automatically loses the tie.\n\n"
        f"## **{winner_name}** wins!"
    )


def skill_test_headline(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    reveal: str,
    outcome: Optional[str],
    offense_name: str,
    defense_name: str,
) -> str:
    """
    Why a maneuver the cards did not settle is going to a skill test:
    the two ranked the same, or the one that would have won is owed to
    an injured player.
    """
    if outcome == "tie":
        # An ordinary tie -- both or neither participant is injured.
        return (
            f"{reveal}\n\n"
            f"**{offense_name}** ties with **{defense_name}** — skill "
            "test!\n\n"
        )

    # An injured player's maneuver never wins outright -- they still
    # have to win a skill test to make it stick.
    would_be_winner = (
        offense_name if outcome == "offense" else defense_name
    )
    injured_player_id = (
        match.active_player_id
        if outcome == "offense"
        else match.challenger_id
    )
    injured_player = engine.get_player_definition(injured_player_id)
    word, emoji = engine.injured_word_and_emoji(game, injured_player_id)
    return (
        f"{reveal}\n\n"
        f"**{would_be_winner}** would win, but "
        f"{engine.format_player_label(match, injured_player)} is "
        f"**{word}** {emoji} -- "
        "a skill test decides it instead!\n\n"
    )


def resolve_maneuver_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Both picks are in: reveal them, say which way the maneuver landed,
    and name what settles it.

    Three ways out, and the narration is the whole of what this step
    produces -- nothing here changes the match. The reveal is worded
    before anything is dispatched because it is one message either way:
    a decisive win opens its effect's message with it, and a tie opens
    the skill test's.

    - **Unchallenged.** Nothing to reveal against and nothing to rank:
      the offense's pick is the winner, and its effect runs the same
      pipeline a decisive win always does.
    - **Decided on the cards**, including a tie one injured participant
      loses outright. `settled_maneuver_winner` is the whole of who
      wins -- this may not re-derive it from the ranking, which
      disagrees with the turn in both directions once injury is in it.
    - **Undecided**, so a skill test does it.

    `outcome` is the ranking on its own, which is what separates a win
    on the cards from a win handed over by the other player's injury;
    it is only ever read to decide how the four ways a maneuver can
    land are *worded*.
    """
    # Keys are what the match holds and what everything below
    # dispatches on; the names are only ever printed.
    offense_key = match.offense_maneuver
    defense_key = match.defense_maneuver
    offense_name = engine.maneuver_name(offense_key)
    defense_name = engine.maneuver_name(defense_key)
    offense_display = format_player_with_team(
        game,
        engine.possession_player_number(game, match),
        engine.team_emojis,
    )
    defense_display = format_player_with_team(
        game,
        engine.defending_player_number(game, match),
        engine.team_emojis,
    )

    if match.maneuver_uncontested:
        return StepResult(
            narration=[
                f"{offense_display} chose **{offense_name}**, "
                f"unchallenged.\n\n## **{offense_name}** succeeds!"
            ],
            next=FollowOn(
                FollowOnStep.BEGIN_EFFECT_RESOLUTION,
                {"winner_key": offense_key},
            ),
        )

    reveal = (
        f"{offense_display} chose **{offense_name}**.\n"
        f"{defense_display} chose **{defense_name}**."
    )

    outcome = engine.cards_outcome(match)
    winner_key = engine.settled_maneuver_winner(match)

    if winner_key is not None:
        return StepResult(
            narration=[
                maneuver_winner_text(
                    engine,
                    game,
                    match,
                    reveal,
                    outcome,
                    engine.maneuver_name(winner_key),
                    offense_name,
                    defense_name,
                )
            ],
            next=FollowOn(
                FollowOnStep.BEGIN_EFFECT_RESOLUTION,
                {"winner_key": winner_key},
            ),
        )

    return StepResult(
        narration=[
            skill_test_headline(
                engine, game, match, reveal, outcome,
                offense_name, defense_name,
            )
        ],
        next=FollowOn(FollowOnStep.BEGIN_MANEUVER_SKILL_TEST),
    )


def maneuver_selection_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Write whatever Dinky picks for itself, and answer whether this
    maneuver is ready to resolve.

    **A result with nothing in `next` is "somebody is still to be
    asked", and that is deliberate rather than a gap.** What is owed
    then is the maneuver prompt, and the maneuver prompt is the one
    piece of narration in this stretch that is genuinely the
    frontend's: it words itself as "choose a maneuver from the red
    row", which is a fact about Discord's own button rows and not
    about the position (see `MANEUVER_ROW_COLOURS`, and principle 2 in
    CLAUDE.md -- the line is between *what* and *how*). A web app asks
    the same question of the same state and words it for whatever it
    draws. So the model says the turn stops here; it does not say what
    the stopping looks like.

    An uncontested maneuver comes through here too and waits on the
    offense alone -- there is no defender to pick a defensive maneuver,
    and `maneuver_pick_sides` has already taken that side off the
    prompt.
    """
    write_ai_maneuver_picks(engine, game, match)

    if match.maneuver_selections_complete:
        return resolve_maneuver_step(engine, game, match)

    return StepResult()

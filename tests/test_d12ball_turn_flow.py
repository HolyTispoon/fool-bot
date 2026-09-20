"""
`d12ball/flow/turn.py` -- the front half of a turn, asked of the model
with no `discord` in scope.

The twin of `tests/test_d12ball_low_pass_flow.py` and
`tests/test_d12ball_dribble_flow.py`, for the two steps the front half
of Phase 4 lifted: `resolve_maneuver_step`, which says which way a
maneuver landed and words the reveal, and `maneuver_selection_step`,
which writes whatever Dinky picks for itself and answers whether
anybody is left to ask.

**What is asserted about the narration is what the data cannot
contradict**, not the prose: the headings, whose pick is named, and
that an injured player's automatic loss says so. The two goldens hold
the wording byte for byte -- `tests/test_golden_transcript.py` for the
tutorial and `tests/test_golden_advanced_transcript.py` for an
advanced game that reaches this on every turn -- which is what a
fixture quoting a sentence would only duplicate badly.

The follow-on is named by `FollowOnStep` member, which is the record of
what the cog still dispatches (see `d12ball/flow/result.py`); the cog's
own table is asserted against the enum in
`tests/test_d12ball_package_shape.py`, so nothing here needs the cog.
"""

from __future__ import annotations

import unittest

from d12ball.ai import build_ai_strategies
from d12ball.components import (
    MatchState,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.flow import FollowOn, FollowOnStep
from d12ball.flow.turn import (
    maneuver_selection_step,
    resolve_maneuver_step,
    write_ai_maneuver_picks,
)
from d12ball.game import (
    AIOpponent,
    D12BallGame,
    Formation,
    GameMode,
    GameStatus,
    Team,
)
from d12ball.prompts import pending_prompt

CATALOG = load_player_catalog()
RULESET = load_basic_ruleset()
MANEUVERS = load_maneuver_catalog()
ENGINE = RulesEngine(
    CATALOG, RULESET, MANEUVERS, build_ai_strategies(CATALOG, MANEUVERS),
)


def build_game(**overrides) -> D12BallGame:
    fields = dict(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=111,
        player_2_id=222,
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        home_player_number=1,
        visiting_player_number=2,
        status=GameStatus.IN_PROGRESS,
        mode=GameMode.ADVANCED,
    )
    fields.update(overrides)
    return D12BallGame(**fields)


def build_match() -> MatchState:
    return MatchState.standard(
        catalog=CATALOG,
        ruleset=RULESET,
        board_size=7,
        home_team=Team.ORANGE,
        visiting_team=Team.PURPLE,
        home_formation=Formation.TWO_TWO_TWO,
    )


def a_contest() -> tuple[D12BallGame, MatchState]:
    """A maneuver under way, with a handler and a challenger picked."""
    game = build_game()
    match = build_match()
    match.active_player_id = match.eligible_ball_handlers()[0]
    match.challenger_id = match.visiting.field_players[0]
    return game, match


def go_unchallenged(match: MatchState) -> None:
    """
    Move every defender off the ball's space and take the challenge
    away, which is the only way into an uncontested maneuver now: a
    defender standing on the ball challenges, and
    `begin_uncontested_maneuver` refuses while one is there. See
    "The maneuver with nobody to challenge it" in
    docs/design/sending-a-player.md.
    """
    for player_id in list(
        match.board.spaces[match.ball.zone][match.ball.space_index]
    ):
        if player_id in match.visiting.field_players:
            match.move_meeple(
                player_id,
                Zone.VISITORS_GOAL,
                match.board.layout.zone_spaces[Zone.VISITORS_GOAL] - 1,
            )
    match.challenger_id = None
    match.begin_uncontested_maneuver()


def a_pairing(outcome: str) -> tuple[str, str]:
    """
    The first offense/defense pair the catalog ranks the given way --
    named by key rather than written down, because which cards beat
    which is data the author revises (see `maneuvers.json`).
    """
    for offense in (card.key for card in MANEUVERS.offense):
        for defense in (card.key for card in MANEUVERS.defense):
            if MANEUVERS.resolve(offense, defense) == outcome:
                return offense, defense
    raise AssertionError(f"no pairing ranks {outcome!r}")


class ResolveManeuverStepTests(unittest.TestCase):
    """The three ways a maneuver leaves the reveal."""

    def test_a_decisive_win_heads_the_winner_and_runs_its_effect(
        self,
    ) -> None:
        game, match = a_contest()
        offense, defense = a_pairing("offense")
        match.choose_offense_maneuver(offense)
        match.choose_defense_maneuver(defense)

        result = resolve_maneuver_step(ENGINE, game, match)

        self.assertEqual(
            result.next,
            FollowOn(
                FollowOnStep.BEGIN_EFFECT_RESOLUTION,
                {"winner_key": offense},
            ),
        )
        narration = " ".join(result.narration)
        self.assertIn(
            f"## **{ENGINE.maneuver_name(offense)}** wins!", narration,
        )
        # Both picks are revealed, whichever won.
        self.assertIn(f"**{ENGINE.maneuver_name(defense)}**", narration)

    def test_an_undecided_maneuver_goes_to_a_skill_test(self) -> None:
        game, match = a_contest()
        offense, defense = a_pairing("tie")
        match.choose_offense_maneuver(offense)
        match.choose_defense_maneuver(defense)

        result = resolve_maneuver_step(ENGINE, game, match)

        self.assertEqual(
            result.next, FollowOn(FollowOnStep.BEGIN_MANEUVER_SKILL_TEST),
        )
        self.assertIn("skill test!", " ".join(result.narration))

    def test_a_tie_one_injured_player_loses_says_which_and_why(
        self,
    ) -> None:
        """
        The one branch that decides a maneuver with nothing rolled, so
        the message has to say what took the tie away -- see "Injured
        players" in docs/living-rules.md.
        """
        game, match = a_contest()
        offense, defense = a_pairing("tie")
        match.choose_offense_maneuver(offense)
        match.choose_defense_maneuver(defense)
        match.injured.add(match.challenger_id)

        result = resolve_maneuver_step(ENGINE, game, match)

        self.assertEqual(
            result.next,
            FollowOn(
                FollowOnStep.BEGIN_EFFECT_RESOLUTION,
                {"winner_key": offense},
            ),
        )
        narration = " ".join(result.narration)
        word, _ = ENGINE.injured_word_and_emoji(game, match.challenger_id)
        self.assertIn(f"**{word}**", narration)
        self.assertIn("automatically loses the tie", narration)

    def test_an_unchallenged_maneuver_succeeds_without_a_ranking(
        self,
    ) -> None:
        """
        Nothing to reveal against and nothing to rank: the offense's
        pick is the winner. "succeeds" rather than "wins" because
        there was no contest to win -- see
        docs/design/sending-a-player.md.
        """
        game, match = a_contest()
        go_unchallenged(match)
        offense, _ = a_pairing("offense")
        match.choose_offense_maneuver(offense)

        result = resolve_maneuver_step(ENGINE, game, match)

        self.assertEqual(
            result.next,
            FollowOn(
                FollowOnStep.BEGIN_EFFECT_RESOLUTION,
                {"winner_key": offense},
            ),
        )
        narration = " ".join(result.narration)
        self.assertIn("unchallenged", narration)
        self.assertIn(
            f"## **{ENGINE.maneuver_name(offense)}** succeeds!", narration,
        )

    def test_nothing_in_the_match_changes(self) -> None:
        """
        The step is a reading. `resolve_maneuver` is the one wrapper in
        the front half with no `persist` after it, and this is why --
        so a save that does not happen cannot lose anything.
        """
        game, match = a_contest()
        offense, defense = a_pairing("offense")
        match.choose_offense_maneuver(offense)
        match.choose_defense_maneuver(defense)
        before = match.to_dict()

        resolve_maneuver_step(ENGINE, game, match)

        self.assertEqual(match.to_dict(), before)


class ManeuverSelectionStepTests(unittest.TestCase):
    """Dinky's own picks, and whether anybody is left to ask."""

    def solo(self) -> tuple[D12BallGame, MatchState]:
        game, match = a_contest()
        game.player_2_id = None
        game.ai_opponent = AIOpponent.DINKY
        return game, match

    def test_two_coaches_are_both_still_to_be_asked(self) -> None:
        game, match = a_contest()

        result = maneuver_selection_step(ENGINE, game, match)

        self.assertIsNone(result.next)
        self.assertEqual(result.narration, [])
        self.assertFalse(match.maneuver_selections_complete)

    def test_dinky_picks_for_itself_and_the_human_is_still_asked(
        self,
    ) -> None:
        """
        A solo game's prompt is one hand and one row, and this is what
        makes it: the AI's card is written into the match before
        `maneuver_pick_sides` is ever read.
        """
        game, match = self.solo()

        result = maneuver_selection_step(ENGINE, game, match)

        # Dinky defends here -- player 2, and the ball is the home
        # side's off the standard deal.
        self.assertIsNotNone(match.defense_maneuver)
        self.assertIsNone(match.offense_maneuver)
        self.assertIsNone(result.next)
        self.assertEqual(
            ENGINE.maneuver_pick_sides(game, match), ("offense",),
        )

    def test_the_last_pick_hands_straight_on_to_the_reveal(self) -> None:
        """
        No second reading of "are we ready": the step calls
        `resolve_maneuver_step` and returns its result, so what the
        frontend receives is the reveal itself.
        """
        game, match = self.solo()
        offense, _ = a_pairing("offense")
        match.choose_offense_maneuver(offense)

        result = maneuver_selection_step(ENGINE, game, match)

        self.assertTrue(match.maneuver_selections_complete)
        self.assertIsInstance(result.next, FollowOn)
        self.assertIn(
            result.next.step,
            {
                FollowOnStep.BEGIN_EFFECT_RESOLUTION,
                FollowOnStep.BEGIN_MANEUVER_SKILL_TEST,
            },
        )
        self.assertTrue(result.narration)

    def test_two_coaches_leave_the_match_untouched(self) -> None:
        """
        Nothing is written where there is no AI to write for -- the
        wrapper saves either way, and a step that wrote here would be
        charging a human game for a branch it never takes.
        """
        game, match = a_contest()
        before = match.to_dict()

        maneuver_selection_step(ENGINE, game, match)

        self.assertEqual(match.to_dict(), before)


class TutorialRailTests(unittest.TestCase):
    """
    A beat names the card Dinky plays, and the rail still reaches it
    through the engine rather than through the cog.
    """

    def test_a_scripted_beat_is_what_dinky_plays(self) -> None:
        from d12ball import tutorial

        game, match = a_contest()
        game.player_2_id = None
        game.ai_opponent = AIOpponent.DINKY
        game.tutorial = True
        game.tutorial_step = tutorial.FIRST_STEP

        beat = ENGINE.tutorial_beat(game)
        self.assertIsNotNone(beat)
        scripted = beat.dinky_maneuver_for("defense")

        write_ai_maneuver_picks(ENGINE, game, match)

        if scripted is not None:
            self.assertEqual(match.defense_maneuver, scripted)
        else:
            # A beat that scripts nothing for this side leaves the
            # strategy's own pick standing, which is the point of the
            # `or` rather than a branch.
            self.assertIsNotNone(match.defense_maneuver)

    def test_an_ordinary_game_has_no_beat(self) -> None:
        game, _ = a_contest()
        self.assertIsNone(ENGINE.tutorial_beat(game))


class RoundTripTests(unittest.TestCase):
    """
    What a restart is handed, in the states the front half can leave a
    match in.

    `pending_prompt` is the one reading of "what is this match waiting
    on" (principle 3), so the assertion is that a save and a load of a
    match this step left behind answers the same way -- which is what
    stands between the prompt a coach was looking at and the one they
    are handed back.
    """

    def reload(self, match: MatchState) -> MatchState:
        return MatchState.from_dict(match.to_dict(), RULESET)

    def test_a_prompt_still_owed_survives_the_round_trip(self) -> None:
        game, match = a_contest()
        maneuver_selection_step(ENGINE, game, match)

        before = pending_prompt(ENGINE, game, match)
        after = pending_prompt(ENGINE, game, self.reload(match))

        self.assertEqual(before.kind, after.kind)
        self.assertEqual(before.ask, after.ask)

    def test_dinkys_written_pick_survives_the_round_trip(self) -> None:
        """
        The AI's card is state now, not a decision remade on the next
        click: a restart between the write and the human's answer has
        to hand back the same one-row prompt.
        """
        game, match = a_contest()
        game.player_2_id = None
        game.ai_opponent = AIOpponent.DINKY
        maneuver_selection_step(ENGINE, game, match)

        reloaded = self.reload(match)

        self.assertEqual(reloaded.defense_maneuver, match.defense_maneuver)
        self.assertEqual(
            ENGINE.maneuver_pick_sides(game, reloaded),
            ENGINE.maneuver_pick_sides(game, match),
        )
        self.assertEqual(
            pending_prompt(ENGINE, game, reloaded).kind,
            pending_prompt(ENGINE, game, match).kind,
        )

    def test_an_uncontested_maneuver_survives_the_round_trip(self) -> None:
        game, match = a_contest()
        go_unchallenged(match)

        reloaded = self.reload(match)

        self.assertTrue(reloaded.maneuver_uncontested)
        self.assertEqual(
            pending_prompt(ENGINE, game, reloaded).kind,
            pending_prompt(ENGINE, game, match).kind,
        )


if __name__ == "__main__":
    unittest.main()

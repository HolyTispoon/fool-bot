"""
An **advanced** game played through the real cog, recorded, and
compared word for word against `tests/golden/advanced_*`.

The twin of `tests/test_golden_transcript.py`, and it exists because
that one covers one basic-mode solo game on board 7 -- "no gambit, no
species ability, no halftime, no shootout, no time out", as its own
docstring says. Phase 4 of `docs/model-discord-split.md` moves the
**spine**: the front half of a turn, the three arrival points and the
two gates each opens with, the loose ball, the run-back cascade, the
injury tests. Almost none of that is on the tutorial's path, so a
mechanical move of it would have had nothing watching the wording it
carries. This is that something.

What it plays, and why each of those was chosen:

- **Advanced mode, both modules on.** Gambits are in the hand, so
  `maneuver_tiers` is asked for six cards rather than three and the
  prompt carries `describe_gambit_access`; species abilities are on, so
  the arrival gate has something to find.
- **The Telekinetics, as the human side.** Mind Pull and Smooth are
  the two halves of `check_for_ball_arrival`, and they are the only
  ability that interrupts a maneuver rather than modifying one -- see
  "Mind Pull, and the arrival gate" in
  docs/design/species-abilities.md. **Dinky never pulls**, so an AI
  side's Telekinetics are skipped rather than prompted: a recording
  that wanted to watch the gate had to put the ability in the hands of
  the side that is asked.
- **Board 9**, the biggest. It is the board where a run back has the
  furthest to travel, and it is what reaches the branch this phase's
  brief singles out as the fragile one: a cascade that stops to ask a
  coach *which space*, where `continue_run_back` returns from inside
  its own loop and the placements it has already made have to be on
  disk before the prompt goes out.
- **Solo against Dinky**, so the recording is one side's presses. Both
  control paths are exercised anyway -- the AI answers inline for its
  own turns and the human is prompted for theirs.

What the recorded run reaches is asserted, not hoped for, in
`test_the_recorded_run_still_reaches_the_spine`: the seed is a choice
and a change that quietly stopped the run reaching Mind Pull would
leave the transcript green and no longer covering the thing it was
recorded for. That is the same job `GOLDEN_SEED`'s
"the run that scores" assertion does for the tutorial.

**What it still does not reach**, so nobody reads a green run as more
than it is: no own-goal roll, no shootout, no time out, no substitution
window taken up (the coaching windows are opened and passed on), no
stacked run back -- the *space* question is asked, the "which of these
players goes" question is not -- and of the twelve cards it plays
Low Pass, Skilled Pass, Dribble Advance, Dribble Burst, Deflect, Steal
and Intercept. Phase 5 should add its own for the periods and windows.

Regenerating is the same as the tutorial's, and means the same thing:

    FOOLBOT_UPDATE_GOLDEN=1 python3 -m unittest discover -s tests \\
        -p 'test_golden_advanced_transcript.py'

and the diff goes in the pull request, where somebody can say whether
the game was meant to change. It is `discover -s tests` rather than
`unittest tests.<module>` because the suite's own helpers
(`save_patches`, `roster`) are imported as top-level modules, which
only resolve with `tests/` on `sys.path` -- which is what `-s tests`
does and what the dotted form does not.
"""

import asyncio
import os
import pathlib
import random
import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import presentation as presentation_mod
from cogs.d12ball_views import runback as runback_views
from cogs.d12ball_views import turn as turn_views
from save_patches import (
    suppressed_cog_saves,
    suppressed_full_image_links,
    suppressed_view_saves,
)

# `build_cog` and `build_interaction` are the tutorial suite's, the
# same way the basic golden borrows them: one home for "how you stand a
# cog up with Discord mocked". The game and the match are this file's
# own, because an advanced solo game on board 9 is exactly what the
# tutorial's fixtures are not.
from test_d12ball_tutorial import build_cog, build_interaction
from test_golden_transcript import golden_diff, render_final_match

from d12ball.components import (
    MatchState,
    load_basic_ruleset,
    load_player_catalog,
)
from d12ball.game import (
    AIOpponent,
    D12BallGame,
    Formation,
    GameMode,
    GameStatus,
    Team,
)

CATALOG = load_player_catalog()
RULES = load_basic_ruleset()

GOLDEN_DIR = pathlib.Path(__file__).resolve().parent / "golden"
TRANSCRIPT_FILE = GOLDEN_DIR / "advanced_transcript.txt"
FINAL_MATCH_FILE = GOLDEN_DIR / "advanced_final_match.json"

#: Chosen for what it reaches rather than for how it ends -- see the
#: module docstring and `test_the_recorded_run_still_reaches_the_spine`.
#: Seeding the module rather than patching `randint` is what makes the
#: run reproducible at all: the flow also reaches `random.shuffle` and
#: `random.choice`, which a patch on `randint` leaves free.
ADVANCED_GOLDEN_SEED = 11

#: The biggest board, for the run back with the furthest to go.
BOARD_SIZE = 9

#: One press per pass. The game does not finish inside this -- it is a
#: recording of a real stretch of play rather than a whole match, and
#: where it stops is arbitrary but pinned.
MAX_STEPS = 120

#: The prompts the recording exists to watch. Every one of them is a
#: branch of the spine Phase 4 moves, and none is on the tutorial's
#: path. Asserted against the recorded run so a change that stops
#: reaching one fails here rather than quietly narrowing the golden.
SPINE_PROMPTS = frozenset({
    "InjuryTestView",
    "LooseBallChoiceView",
    "LooseBallSkillTestView",
    "ManeuverChallengeView",
    "MindPullView",
    "RunBackChoiceView",
    "SmoothView",
})

UPDATING = os.environ.get("FOOLBOT_UPDATE_GOLDEN") == "1"


def build_game(**overrides) -> D12BallGame:
    """
    An advanced solo game: the human coaches the Telekinetics, Dinky
    the Fire Demons, on board 9.

    `mode=GameMode.ADVANCED` is both modules at once --
    `advanced_maneuvers` and `species_abilities` default True and the
    mode is what turns them on together (see `D12BallGame`). Nothing
    here reads either flag to decide a rule; `RulesEngine.gambits_apply`
    and `species_abilities_apply` are the answers, and this is only the
    record they read.
    """
    fields = dict(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=111,
        player_2_id=None,
        player_1_name="One",
        player_1_team=Team.TELEKINETICS,
        player_2_team=Team.FIRE_DEMONS,
        home_player_number=1,
        visiting_player_number=2,
        status=GameStatus.IN_PROGRESS,
        mode=GameMode.ADVANCED,
        ai_opponent=AIOpponent.DINKY,
        board_size=BOARD_SIZE,
        tutorial=False,
        tutorial_step=None,
    )
    fields.update(overrides)
    return D12BallGame(**fields)


def build_match() -> MatchState:
    return MatchState.standard(
        catalog=CATALOG,
        ruleset=RULES,
        board_size=BOARD_SIZE,
        home_team=Team.TELEKINETICS,
        visiting_team=Team.FIRE_DEMONS,
        home_formation=Formation.TWO_TWO_TWO,
    )


async def record_playthrough() -> tuple[str, dict, list[str]]:
    """
    Play an advanced solo game through the real cog, pressing the first
    enabled button at every step, and return the transcript, the final
    match state, and the prompts that were pressed.

    **The press rule is "the first live button", and with no rails that
    is a choice rather than a script.** The tutorial's playthrough
    takes the first because the rails leave exactly one; here it is
    taking the leftmost offer every time, which is arbitrary and is
    exactly why it is reproducible. What makes the recording worth
    comparing against is the seed and this rule together, not either
    alone.

    The third return value is what `SPINE_PROMPTS` is checked against;
    it is read off the same presses the transcript records, so the two
    cannot disagree about what the run reached.
    """
    recorder = SimpleNamespace(messages=[], views=[])
    cog = build_cog()
    game = build_game()
    game.match_state = build_match().to_dict()
    cog.games["g1"] = game

    lines: list[str] = []
    pressed: list[str] = []
    seen = 0

    def drain() -> None:
        nonlocal seen
        for message in recorder.messages[seen:]:
            lines.append("--- message")
            lines.append(message.rstrip())
        seen = len(recorder.messages)

    with suppressed_cog_saves(), \
            suppressed_view_saves(), \
            suppressed_full_image_links(), \
            mock.patch.object(
                runback_views, "add_full_image_button", mock.AsyncMock()), \
            mock.patch.object(
                turn_views,
                "add_full_image_button_to_response",
                mock.AsyncMock()), \
            mock.patch.object(
                presentation_mod, "pin_board_message", mock.AsyncMock()):

        await cog.finish_setup_coaching(
            build_interaction(recorder),
            game,
            cog.engine.load_match_state(game),
        )
        drain()

        for step in range(MAX_STEPS):
            if not recorder.views:
                break
            view = recorder.views.pop()
            recorder.views.clear()
            live = [
                item for item in view.children
                if not getattr(item, "disabled", False)
                and item.label != "Maneuver Reference"
            ]
            if not live:
                raise AssertionError(
                    f"{type(view).__name__} had nothing enabled"
                )
            pressed.append(type(view).__name__)
            lines.append(
                f"=== press {step + 1}: {type(view).__name__} "
                f"-> {live[0].label!r}"
            )
            await live[0].callback(build_interaction(recorder))
            drain()

    return (
        "\n".join(lines) + "\n",
        cog.engine.load_match_state(game).to_dict(),
        pressed,
    )


class AdvancedGoldenTranscriptTests(unittest.IsolatedAsyncioTestCase):
    """One real advanced game, recorded and compared."""

    async def asyncSetUp(self) -> None:
        # The module-level RNG is global, so seeding it here would leak
        # into whatever unittest runs next. Saved and restored rather
        # than left set.
        self._random_state = random.getstate()
        random.seed(ADVANCED_GOLDEN_SEED)
        self.addCleanup(random.setstate, self._random_state)

        (
            self.transcript,
            self.final_match,
            self.pressed,
        ) = await record_playthrough()

    async def test_the_narration_and_prompts_are_unchanged(self) -> None:
        """
        Every message the game posts, and the prompt each was posted
        under, against the recorded run.
        """
        if UPDATING:
            GOLDEN_DIR.mkdir(exist_ok=True)
            TRANSCRIPT_FILE.write_text(self.transcript)
            self.skipTest("FOOLBOT_UPDATE_GOLDEN=1: transcript rewritten")

        self.assertTrue(
            TRANSCRIPT_FILE.exists(),
            f"{TRANSCRIPT_FILE} is missing -- regenerate with "
            "FOOLBOT_UPDATE_GOLDEN=1",
        )
        recorded = TRANSCRIPT_FILE.read_text()
        if recorded != self.transcript:
            self.fail(
                "the advanced game no longer says what it used to. If "
                "that is deliberate, regenerate with "
                "FOOLBOT_UPDATE_GOLDEN=1 and put the diff in the pull "
                "request.\n\n"
                + golden_diff(recorded, self.transcript, "transcript")
            )

    async def test_the_final_save_is_unchanged(self) -> None:
        """
        The whole of `MatchState.to_dict()` at the end of the run --
        the save format, which a refactor may not change.
        """
        rendered = render_final_match(self.final_match)
        if UPDATING:
            GOLDEN_DIR.mkdir(exist_ok=True)
            FINAL_MATCH_FILE.write_text(rendered)
            self.skipTest("FOOLBOT_UPDATE_GOLDEN=1: final match rewritten")

        self.assertTrue(
            FINAL_MATCH_FILE.exists(),
            f"{FINAL_MATCH_FILE} is missing -- regenerate with "
            "FOOLBOT_UPDATE_GOLDEN=1",
        )
        recorded = FINAL_MATCH_FILE.read_text()
        if recorded != rendered:
            self.fail(
                "the saved match state changed. A refactor may not "
                "change the save format -- see principle 6 in "
                "CLAUDE.md.\n\n"
                + golden_diff(recorded, rendered, "final match")
            )

    async def test_the_recorded_run_still_reaches_the_spine(self) -> None:
        """
        The seed is doing its job.

        The transcript on its own cannot say this: a change that made
        the run stop reaching Mind Pull would rewrite the golden's
        contents, and a regenerated golden would be green again --
        still deterministic, still a real game, and no longer covering
        the branch it was recorded for. So what the run reaches is
        asserted separately from what it says, exactly as the basic
        golden asserts that its recorded run is the one that scores.
        """
        missing = sorted(SPINE_PROMPTS - set(self.pressed))
        self.assertEqual(
            missing,
            [],
            f"ADVANCED_GOLDEN_SEED={ADVANCED_GOLDEN_SEED} no longer "
            f"reaches {', '.join(missing)}, so the golden would stop "
            "covering it. Pick a seed that does and regenerate.",
        )


class AdvancedGoldenDeterminismTests(unittest.TestCase):
    """
    The same claim the basic golden rests on, for a game with far more
    branching in it: the same seed replays the same game.

    Worth its own test here for a reason the basic one does not have --
    an advanced game reads `maneuver_tiers` per side, and the two hands
    on one prompt can be six cards and three. A set iterated into a
    button order would make this vary between machines rather than on
    the change that broke it.
    """

    def test_two_runs_on_one_seed_agree(self) -> None:
        first_t, first_m, first_p = self._run()
        second_t, second_m, second_p = self._run()
        if first_t != second_t:
            self.fail(
                "the same seed replayed a different game:\n\n"
                + golden_diff(first_t, second_t, "transcript")
            )
        self.assertEqual(first_m, second_m)
        self.assertEqual(first_p, second_p)

    def _run(self) -> tuple[str, dict, list[str]]:
        state = random.getstate()
        try:
            random.seed(ADVANCED_GOLDEN_SEED)
            return asyncio.run(record_playthrough())
        finally:
            random.setstate(state)


if __name__ == "__main__":
    unittest.main()

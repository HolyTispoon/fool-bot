"""
A whole game played through the real cog, recorded, and compared word
for word against a file in `tests/golden/`.

**This is the guard the model/Discord split is built on top of.** Every
phase of that split (see `docs/model-discord-split.md`) is a large
mechanical move of flow code out of `cogs/` and into `d12ball/`, and a
mechanical move needs something that fails loudly the moment it stops
being mechanical. The rest of the suite asserts rules in isolation; this
asserts that a real game, played end to end, still says the same things
in the same order and finishes in the same state.

What it compares, in order of how likely each is to catch something:

- **the narration, byte for byte.** The wording rules in CLAUDE.md
  ("What a message says") are rules, so a refactor that rewords a result
  has changed the game and should have to say so in review.
- **the sequence of prompts**, which is the turn's shape -- the thing
  `pending_prompt` will own after Phase 1 and the thing a second copy of
  that chain would quietly fork.
- **the final `MatchState.to_dict()`, key for key**, which is the save
  format and is a contract the refactor may not touch.

**A changed golden file is not a failure, it is a review
conversation.** Regenerate with

    FOOLBOT_UPDATE_GOLDEN=1 python3 -m unittest tests.test_golden_transcript

and put the diff in the pull request, where somebody can say whether the
game was meant to change.

**The dice are pinned, and that is allowed here.** CLAUDE.md is explicit
that the tutorial's closing shot is deliberately *not* scripted -- it is
a heavy favourite and not a certainty -- so a test that plays the script
may not assert a goal. The rule it also states is that "a test that
needs the goal pins the dice", which is this one: a transcript is only a
transcript if it is the same every time. `GOLDEN_SEED` is chosen so the
run scores, because that is the path the script is built to reach; a
seed that missed would pin the unusual branch as the reference.

**There are two goldens, and the second is Phase 4's.** The tutorial
is one basic-mode solo game on board 7: no advanced maneuver, no
species ability, no halftime, no shootout, no time out. That was the
only multi-turn game the suite could drive until Phase 4 needed the
spine covered -- the arrival gates, the loose ball, the run back, the
injury queue and the own-goal roll are all things the tutorial never
reaches. `ADVANCED_*` below is a whole advanced solo game on board 9,
kickoff to full time, with both modules on and a Telekinetic side, and
it was recorded on the code as it stood before that phase moved
anything. See `record_advanced_playthrough` for the press rule and
for what it still does not reach.
"""

import asyncio
import difflib
import json
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

# The fixtures are the tutorial suite's, deliberately: one home for
# "how you stand a cog up with Discord mocked". What is not shared is
# the loop below, because that suite's own `play()` records what its
# assertions need (how many deals, which steps had two live buttons)
# and this one needs the interleaving of messages and presses.
from test_d12ball_tutorial import (
    build_cog,
    build_game,
    build_interaction,
    build_match,
)

from d12ball.components import (
    MatchState,
    load_basic_ruleset,
    load_player_catalog,
)
from d12ball.game import (
    AIOpponent,
    Formation,
    GameMode,
    GameStatus,
    Team,
)

GOLDEN_DIR = pathlib.Path(__file__).resolve().parent / "golden"
TRANSCRIPT_FILE = GOLDEN_DIR / "tutorial_transcript.txt"
FINAL_MATCH_FILE = GOLDEN_DIR / "tutorial_final_match.json"
ADVANCED_TRANSCRIPT_FILE = GOLDEN_DIR / "advanced_transcript.txt"
ADVANCED_FINAL_MATCH_FILE = GOLDEN_DIR / "advanced_final_match.json"

# Chosen so the closing score attempt goes in -- see the module
# docstring. Seeding the module rather than patching `randint` is what
# makes the run reproducible at all: the flow also reaches
# `random.shuffle` and `random.choice`, which a patch on `randint`
# leaves free.
GOLDEN_SEED = 2

# The playthrough presses one button per pass; the script is five beats
# and a handover, so this is roughly double what it needs.
MAX_STEPS = 40

# The advanced game's own seed, chosen the way GOLDEN_SEED was: not for
# a score line but for what it *reaches*. It is the one in the first
# sixteen that puts every prompt in
# `ADVANCED_VIEWS_THE_RUN_MUST_REACH` up at least once while still
# finishing inside 140 presses -- the own-goal roll and the stacked run
# back are the two that most seeds miss. A test asserts the coverage,
# so the golden cannot quietly become a run that stops watching them.
ADVANCED_SEED = 1

# The advanced run plays a whole game rather than a script, so the
# bound is "more than a game takes" rather than "twice the script".
# Seed 1 reaches full time in 90.
ADVANCED_MAX_STEPS = 140

#: The prompts the advanced golden exists to keep an eye on -- every
#: one of them is a branch the tutorial never reaches, and most are
#: Phase 4's own. Asserted rather than described, because a seed that
#: stopped reaching one would still be a green golden.
ADVANCED_VIEWS_THE_RUN_MUST_REACH = frozenset({
    # The arrival gate, both halves of it.
    "MindPullView",
    "SmoothView",
    # The loose ball, both the pick and the contest.
    "LooseBallChoiceView",
    "LooseBallSkillTestView",
    # The run back's two questions -- which player (a stack) and which
    # space.
    "RunBackPlayerChoiceView",
    "RunBackChoiceView",
    # The two rolls a coach presses that the tutorial never owes.
    "InjuryTestView",
    "OwnGoalRollView",
    # The spine either side of them.
    "ManeuverChallengeView",
    "SkillTestView",
    "ScoreAttemptView",
    "SetUpAttemptChoiceView",
    # The coaching window, which a new play opens.
    "CoachingHubView",
})

UPDATING = os.environ.get("FOOLBOT_UPDATE_GOLDEN") == "1"


async def record_playthrough() -> tuple[str, dict]:
    """
    Play the tutorial script through the real cog, pressing the first
    enabled button at every step, and return the transcript and the
    final match state.

    The press rule is the tutorial suite's: the rails leave exactly one
    button live at every scripted step, and the two places they
    deliberately leave a free choice have no wrong answer. Taking the
    first is what makes the run reproducible without the script having
    to fix things it means to leave open.
    """
    recorder = SimpleNamespace(messages=[], views=[])
    cog = build_cog()
    game = build_game(tutorial_step=None)
    game.match_state = build_match().to_dict()
    cog.games["g1"] = game

    lines: list[str] = []
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
            if not recorder.views or not game.in_tutorial:
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
            lines.append(
                f"=== press {step + 1}: {type(view).__name__} "
                f"-> {live[0].label!r}"
            )
            await live[0].callback(build_interaction(recorder))
            drain()

    return "\n".join(lines) + "\n", cog.engine.load_match_state(game).to_dict()


def build_advanced_interaction(
    recorder,
    custom_id: str = "",
) -> SimpleNamespace:
    """
    The tutorial's interaction with the two things a free advanced
    game reaches and a scripted basic one does not.

    `data` is read by `declare_overdrive`, which pulls the player out
    of the button's own custom_id rather than closing over it, and
    `channel.get_partial_message` is how a couple of the flows edit a
    message they are not replying to. Added here rather than in
    `test_d12ball_tutorial.build_interaction` so the shared fixture
    keeps saying exactly what the tutorial needs -- a fixture that
    grows an attribute per caller stops being evidence about any of
    them.
    """
    interaction = build_interaction(recorder)
    interaction.data = {"custom_id": custom_id}
    interaction.channel.get_partial_message = mock.Mock(
        return_value=SimpleNamespace(
            edit=mock.AsyncMock(), delete=mock.AsyncMock(),
        ),
    )
    return interaction


def build_advanced_game():
    """
    A solo advanced game on board 9: both modules on, the human
    coaching the Telekinetics.

    Four choices, and each is the golden's coverage rather than
    taste. **Solo**, because the run has one presser and a two-human
    game would have it answering for both sides -- it also puts
    `play_ai_turn` and every "Dinky answers inline" branch under the
    recorder. **Advanced with both modules**, because the gambits and
    the species abilities are most of what the tutorial cannot see.
    **Telekinetics**, because they are the side that can Mind Pull and
    Smooth, which are the two halves of the arrival gate Phase 4
    moves; the Cyborgs opposite them bring Lithium Powered, so the
    other ability funnel is watched too. **Board 9**, because its
    zones hold three spaces and its formations can stack two players
    on one -- which is the only way the run back's *which player*
    question is ever asked.
    """
    catalog = load_player_catalog()
    ruleset = load_basic_ruleset()
    game = build_game(
        tutorial=False,
        tutorial_step=None,
        player_2_id=None,
        ai_opponent=AIOpponent.DINKY,
        mode=GameMode.ADVANCED,
        player_1_team=Team.TELEKINETICS,
        player_2_team=Team.CYBORGS,
    )
    match = MatchState.standard(
        catalog=catalog,
        ruleset=ruleset,
        board_size=9,
        home_team=Team.TELEKINETICS,
        visiting_team=Team.CYBORGS,
        home_formation=Formation.TWO_TWO_TWO,
    )
    game.match_state = match.to_dict()
    return game


async def record_advanced_playthrough() -> tuple[str, dict]:
    """
    Play a whole advanced solo game through the real cog and return
    the transcript and the final match state.

    **The press rule is the tutorial's, with two exceptions, and each
    is a thing the tutorial's rails did for it.** The rails leave one
    button live per step, so "press the first enabled one" is a script
    there and an arbitrary-but-reproducible walk here. Two places it
    walks badly:

    - **The card is rotated on `ManeuverActionPromptView`.** Pressing
      the first enabled button there plays Low Pass every turn, so
      eight of the twelve cards and every branch behind them are never
      reached. The k-th prompt takes the k-th card, which is still one
      rule and still reproducible, and it is what puts High Pass,
      Setup Pass and the gambits into the transcript.
    - **`CoachingHubView` presses Done coaching.** The window is a
      menu a coach leaves rather than a step that advances the game:
      its first button re-opens the formation picker, whose answer
      re-opens the hub, and the run never comes out. Taking Done is
      the only press that treats the window as one step.

    The run **stops when the game does** rather than at
    `ADVANCED_MAX_STEPS`: full time puts a rematch button up, and a
    rematch is a different game.

    **What it still does not reach**, for the same reason the tutorial
    does not reach what it does not: the run is one game and a game is
    not every branch. There is no shootout (the seed does not finish
    level), no time out, and no `BallRecoveryView` -- the pickup after
    a ball goes out, a shot misses, or an own goal is avoided. Those
    are the honest gaps, and a phase that moves one of them should
    close it rather than read this file as cover.
    """
    recorder = SimpleNamespace(messages=[], views=[])
    cog = build_cog()
    # Only `RematchView` reaches for it, at full time, to ask whether
    # the channel has been archived; None is "not archived".
    cog.bot = mock.Mock(get_channel=mock.Mock(return_value=None))
    game = build_advanced_game()
    cog.games["g1"] = game

    lines: list[str] = []
    seen = 0
    cards_played = 0

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
            build_advanced_interaction(recorder),
            game,
            cog.engine.load_match_state(game),
        )
        drain()

        for step in range(ADVANCED_MAX_STEPS):
            if not recorder.views:
                break
            if game.status is not GameStatus.IN_PROGRESS:
                break
            view = recorder.views.pop()
            recorder.views.clear()
            name = type(view).__name__
            live = [
                item for item in view.children
                if not getattr(item, "disabled", False)
                and item.label != "Maneuver Reference"
            ]
            if name == "CoachingHubView":
                live = [
                    item for item in live
                    if item.label == "Done coaching"
                ] or live
            if not live:
                raise AssertionError(f"{name} had nothing enabled")

            if name == "ManeuverActionPromptView":
                pressed = live[cards_played % len(live)]
                cards_played += 1
            else:
                pressed = live[0]

            lines.append(
                f"=== press {step + 1}: {name} -> {pressed.label!r}"
            )
            await pressed.callback(
                build_advanced_interaction(
                    recorder, getattr(pressed, "custom_id", "") or "",
                ),
            )
            drain()

    return "\n".join(lines) + "\n", cog.engine.load_match_state(game).to_dict()


def render_final_match(state: dict) -> str:
    """
    The saved match as the golden file holds it. `sort_keys` because a
    dict's order is not part of the save format and a reordering is not
    a change anybody should have to review.
    """
    return json.dumps(state, indent=2, sort_keys=True, default=str) + "\n"


def golden_diff(expected: str, actual: str, name: str, limit: int = 60) -> str:
    """
    A unified diff of the two, cut to `limit` lines.

    `assertMultiLineEqual` on a 300-line transcript reports "Diff is
    18081 characters long" and stops, which is the opposite of useful
    for a guard whose whole purpose is to start a conversation about
    what changed. This shows the changed regions and says how much it
    left out.
    """
    diff = list(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile=f"{name} (recorded)",
            tofile=f"{name} (this run)",
            lineterm="",
            n=2,
        )
    )
    shown = diff[:limit]
    if len(diff) > limit:
        shown.append(f"... and {len(diff) - limit} more diff lines")
    return "\n".join(shown)


class GoldenTranscriptTests(unittest.IsolatedAsyncioTestCase):
    """One real game, recorded and compared."""

    async def asyncSetUp(self) -> None:
        # The module-level RNG is global, so seeding it here would leak
        # into whatever unittest runs next. Saved and restored rather
        # than left set.
        self._random_state = random.getstate()
        random.seed(GOLDEN_SEED)
        self.addCleanup(random.setstate, self._random_state)

        self.transcript, self.final_match = await record_playthrough()

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
                "the game no longer says what it used to. If that is "
                "deliberate, regenerate with FOOLBOT_UPDATE_GOLDEN=1 and "
                "put the diff in the pull request.\n\n"
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
                "the saved match state changed. A refactor may not change "
                "the save format -- see principle 6 in "
                "docs/model-discord-split.md.\n\n"
                + golden_diff(recorded, rendered, "final match")
            )

    async def test_the_recorded_run_is_the_one_that_scores(self) -> None:
        """
        The seed is doing its job.

        Without this the golden could silently be pinned to the branch
        where the shot misses -- still deterministic, still green, and
        the wrong reference: the transcript would stop covering the
        goal, the restart and everything the script is built to end on.
        """
        self.assertEqual(
            len(self.final_match.get("goals", [])),
            1,
            f"GOLDEN_SEED={GOLDEN_SEED} no longer scores, so the golden "
            "would be pinned to the missed-shot branch -- pick a seed "
            "that scores and regenerate.",
        )


class AdvancedGoldenTranscriptTests(unittest.IsolatedAsyncioTestCase):
    """
    One whole advanced game, recorded and compared.

    The tutorial golden above is a basic solo game and watches the
    spine only where a five-beat script happens to walk over it. This
    one is the guard under Phase 4 of
    `docs/model-discord-split.md`: the arrival gate, the loose ball,
    the run back, the injury queue and the own-goal roll are all
    reached here and nowhere else in the suite as a *sequence*. Every
    other test in the suite asserts one of them standing still.
    """

    async def asyncSetUp(self) -> None:
        self._random_state = random.getstate()
        random.seed(ADVANCED_SEED)
        self.addCleanup(random.setstate, self._random_state)

        self.transcript, self.final_match = (
            await record_advanced_playthrough()
        )

    async def test_the_narration_and_prompts_are_unchanged(self) -> None:
        """Every message the game posts, and the prompt it was posted under."""
        if UPDATING:
            GOLDEN_DIR.mkdir(exist_ok=True)
            ADVANCED_TRANSCRIPT_FILE.write_text(self.transcript)
            self.skipTest("FOOLBOT_UPDATE_GOLDEN=1: transcript rewritten")

        self.assertTrue(
            ADVANCED_TRANSCRIPT_FILE.exists(),
            f"{ADVANCED_TRANSCRIPT_FILE} is missing -- regenerate with "
            "FOOLBOT_UPDATE_GOLDEN=1",
        )
        recorded = ADVANCED_TRANSCRIPT_FILE.read_text()
        if recorded != self.transcript:
            self.fail(
                "the advanced game no longer says what it used to. If "
                "that is deliberate, regenerate with "
                "FOOLBOT_UPDATE_GOLDEN=1 and put the diff in the pull "
                "request.\n\n"
                + golden_diff(
                    recorded, self.transcript, "advanced transcript",
                )
            )

    async def test_the_final_save_is_unchanged(self) -> None:
        """
        The whole of `MatchState.to_dict()` at full time -- the save
        format, which a refactor may not change, over a game that has
        actually set most of it.
        """
        rendered = render_final_match(self.final_match)
        if UPDATING:
            GOLDEN_DIR.mkdir(exist_ok=True)
            ADVANCED_FINAL_MATCH_FILE.write_text(rendered)
            self.skipTest("FOOLBOT_UPDATE_GOLDEN=1: final match rewritten")

        self.assertTrue(
            ADVANCED_FINAL_MATCH_FILE.exists(),
            f"{ADVANCED_FINAL_MATCH_FILE} is missing -- regenerate with "
            "FOOLBOT_UPDATE_GOLDEN=1",
        )
        recorded = ADVANCED_FINAL_MATCH_FILE.read_text()
        if recorded != rendered:
            self.fail(
                "the saved match state changed. A refactor may not "
                "change the save format -- see principle 6 in "
                "docs/model-discord-split.md.\n\n"
                + golden_diff(recorded, rendered, "final match")
            )

    async def test_the_run_reaches_the_prompts_it_is_here_for(self) -> None:
        """
        The seed is doing its job, which here is coverage rather than
        a goal.

        Without this the golden could drift into a short, quiet game
        -- still deterministic, still green, and no longer watching
        the branches Phase 4 moved. It fails naming what went missing,
        which is the one thing a coverage assertion has to do to be
        worth keeping.
        """
        reached = {
            line.split(" -> ")[0].rsplit(" ", 1)[-1]
            for line in self.transcript.splitlines()
            if line.startswith("=== press ")
        }
        missing = ADVANCED_VIEWS_THE_RUN_MUST_REACH - reached
        self.assertFalse(
            missing,
            f"ADVANCED_SEED={ADVANCED_SEED} no longer reaches "
            f"{sorted(missing)} -- pick a seed that does and "
            "regenerate, or say in the pull request why the branch is "
            "gone.",
        )

    async def test_the_game_is_played_to_full_time(self) -> None:
        """
        That the run is a whole game and not a walk that got stuck.

        `ADVANCED_MAX_STEPS` bounds the loop, so a flow change that
        left a prompt asking the same question forever would otherwise
        show up as a transcript diff rather than as the hang it is.
        """
        self.assertEqual(
            self.final_match["scoreboard"]["period"], "second_half",
        )
        self.assertGreaterEqual(
            len(self.final_match.get("goals", [])), 1,
        )


class GoldenTranscriptDeterminismTests(unittest.TestCase):
    """
    The claim the whole file rests on: the same seed replays the same
    game.

    Worth a test of its own because the ways it could stop being true
    are invisible in the transcript itself -- a set of player ids
    iterated into a message, a `dict` ordered by insertion somewhere it
    used to be sorted -- and would show up as a golden that fails on
    another machine rather than on the change that broke it.
    """

    def test_two_runs_on_one_seed_agree(self) -> None:
        first_t, first_m = self._run(GOLDEN_SEED, record_playthrough)
        second_t, second_m = self._run(GOLDEN_SEED, record_playthrough)
        if first_t != second_t:
            self.fail(
                f"the same seed replayed a different game:\n\n"
                + golden_diff(first_t, second_t, "transcript")
            )
        self.assertEqual(first_m, second_m)

    def test_two_advanced_runs_on_one_seed_agree(self) -> None:
        """
        The same claim for the advanced golden, and it is the one that
        needs asserting: that run is four times as long, reaches the
        species abilities and the AI's own choices, and rotates the
        card it plays -- three more ways for a set iterated into a
        message to make the transcript depend on the machine rather
        than on the change.
        """
        first_t, first_m = self._run(
            ADVANCED_SEED, record_advanced_playthrough,
        )
        second_t, second_m = self._run(
            ADVANCED_SEED, record_advanced_playthrough,
        )
        if first_t != second_t:
            self.fail(
                f"the same seed replayed a different advanced game:\n\n"
                + golden_diff(first_t, second_t, "advanced transcript")
            )
        self.assertEqual(first_m, second_m)

    def _run(self, seed: int, record) -> tuple[str, dict]:
        state = random.getstate()
        try:
            random.seed(seed)
            return asyncio.run(record())
        finally:
            random.setstate(state)


if __name__ == "__main__":
    unittest.main()

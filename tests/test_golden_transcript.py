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

    FOOLBOT_UPDATE_GOLDEN=1 python3 -m unittest discover -s tests \
        -p 'test_golden_transcript.py'

and put the diff in the pull request, where somebody can say whether the
game was meant to change. It is `discover -s tests` and not
`unittest tests.test_golden_transcript`, which is what this line said
until the advanced golden was recorded beside it and found the
difference: the suite's own helpers (`save_patches`, `roster`) are
imported as top-level modules, so they only resolve with `tests/` on
`sys.path` -- which `-s tests` does and the dotted form does not.

**The dice are pinned, and that is allowed here.** CLAUDE.md is explicit
that the tutorial's closing shot is deliberately *not* scripted -- it is
a heavy favourite and not a certainty -- so a test that plays the script
may not assert a goal. The rule it also states is that "a test that
needs the goal pins the dice", which is this one: a transcript is only a
transcript if it is the same every time. `GOLDEN_SEED` is chosen so the
run scores, because that is the path the script is built to reach; a
seed that missed would pin the unusual branch as the reference.

**What it does not cover, and Phase 5 will want to.** This golden is
one basic-mode solo game on board 7, because the tutorial was the only
multi-turn game the suite could drive when it was written. It watches
no advanced maneuver, no species ability, no halftime, no shootout and
no time out.

**The advanced half of that gap is now
`tests/test_golden_advanced_transcript.py`**, recorded for Phase 4:
an advanced solo game on board 9 with the Telekinetics in a human's
hands, which reaches the arrival gate (Mind Pull and Smooth), the loose
ball both ways, the injury tests and a run back that stops to ask. The
periods and windows are still nobody's -- no halftime played through,
no shootout, no time out -- and the phase that moves each of them is
the phase to add one. A game that is not the tutorial does not need
rails to be reproducible: a seed and "press the first live button" is
enough, which is what that file does.
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

GOLDEN_DIR = pathlib.Path(__file__).resolve().parent / "golden"
TRANSCRIPT_FILE = GOLDEN_DIR / "tutorial_transcript.txt"
FINAL_MATCH_FILE = GOLDEN_DIR / "tutorial_final_match.json"

# Chosen so the closing score attempt goes in -- see the module
# docstring. Seeding the module rather than patching `randint` is what
# makes the run reproducible at all: the flow also reaches
# `random.shuffle` and `random.choice`, which a patch on `randint`
# leaves free.
GOLDEN_SEED = 2

# The playthrough presses one button per pass; the script is five beats
# and a handover, so this is roughly double what it needs.
MAX_STEPS = 40

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
        first_t, first_m = self._run()
        second_t, second_m = self._run()
        if first_t != second_t:
            self.fail(
                f"the same seed replayed a different game:\n\n"
                + golden_diff(first_t, second_t, "transcript")
            )
        self.assertEqual(first_m, second_m)

    def _run(self) -> tuple[str, dict]:
        state = random.getstate()
        try:
            random.seed(GOLDEN_SEED)
            return asyncio.run(record_playthrough())
        finally:
            random.setstate(state)


if __name__ == "__main__":
    unittest.main()

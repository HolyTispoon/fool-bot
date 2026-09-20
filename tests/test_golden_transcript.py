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

**What it does not cover, and Phases 4 and 5 will want to.** The
tutorial is the only multi-turn game the suite can drive today, so this
golden is one basic-mode solo game on board 7. It watches no advanced
maneuver, no species ability, no halftime, no shootout and no time out.
Those want goldens of their own, and the phase that moves each of them
is the phase to add one.
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
from d12ball.game import AIOpponent, GameMode, Team
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

# The advanced games end themselves at full time, in well under a
# hundred and fifty presses; this is the runaway guard, not the length
# of the run. `test_the_recorded_game_finishes` asserts the cap was
# never what stopped it.
ADVANCED_MAX_STEPS = 400

# One game per board, and the pair is chosen for what it covers
# between them rather than for either half: board 6 is the board the
# deal stacks players on (see docs/design/formations-and-occupancy.md)
# and board 9 is the widest there is, so the two disagree about how
# much field a pass can run out of. The seeds are the best-covering
# pair of the first forty on each -- between them they reach fifteen
# of the nineteen prompt views a solo game can put up; see the pull
# request for the four they do not.
ADVANCED_GAMES = {6: 2, 9: 33}

UPDATING = os.environ.get("FOOLBOT_UPDATE_GOLDEN") == "1"


async def _play(
    cog,
    game,
    *,
    press,
    keep_going,
    max_steps: int,
    interaction_factory=build_interaction,
) -> tuple[str, dict]:
    """
    Drive a game through the real cog from the kickoff, recording every
    message it posts and every button the run presses, and hand back
    the transcript and the final match state.

    The loop itself is shared by both goldens; what they differ in is
    the three arguments. `press` picks a button out of the live ones,
    `keep_going` is asked before each press, and the game is built by
    the caller -- which is the whole of the difference between a
    scripted tutorial and an ordinary advanced game.

    `interaction_factory` exists because an unscripted game reaches
    buttons the tutorial never does, and two of them ask the
    interaction for a little more than the tutorial's fixture offers.
    """
    recorder = SimpleNamespace(messages=[], views=[])

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
            interaction_factory(recorder),
            game,
            cog.engine.load_match_state(game),
        )
        drain()

        for step in range(max_steps):
            if not recorder.views or not keep_going():
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
            pick = press(live, step)
            lines.append(
                f"=== press {step + 1}: {type(view).__name__} "
                f"-> {pick.label!r}"
            )
            await pick.callback(interaction_factory(recorder))
            drain()

    return "\n".join(lines) + "\n", cog.engine.load_match_state(game).to_dict()


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
    cog = build_cog()
    game = build_game(tutorial_step=None)
    game.match_state = build_match().to_dict()
    cog.games["g1"] = game

    return await _play(
        cog,
        game,
        press=lambda live, step: live[0],
        keep_going=lambda: game.in_tutorial,
        max_steps=MAX_STEPS,
    )


def build_advanced_interaction(recorder=None, user_id: int = 111):
    """
    The tutorial's interaction with the two attributes an unscripted
    game reaches for and the script never does.

    `channel.get_partial_message` is the score attempt's "change my
    mind" button deleting the composition image it posted, and
    `guild` is read on the way out of a finished game. Both are
    additions to *this* fixture rather than to the shared one, so the
    tutorial golden is recorded against exactly the fixture it was
    recorded against before.
    """
    interaction = build_interaction(recorder, user_id)
    interaction.channel.get_partial_message = mock.Mock(
        return_value=SimpleNamespace(delete=mock.AsyncMock()),
    )
    return interaction


async def record_advanced_playthrough(board_size: int) -> tuple[str, dict]:
    """
    Play a whole advanced solo game through the real cog and record it
    the same way.

    **This is the golden the spine has, and the tutorial does not
    cover.** The tutorial is one basic-mode game on board 7: no
    gambit, no species ability, no Mind Pull, no injury test, no own
    goal, no stacked run back. This is advanced mode with both modules
    on, the human side Telekinetic so the arrival gate has somebody to
    offer a pull and a Smooth to, and a board the deal stacks players
    on.

    **The press rule is round-robin rather than first-enabled**, and
    that is the one deliberate difference from the tutorial's loop.
    Taking the first button every time picks the first card in the
    hand every turn, which plays the same maneuver for a whole game
    and reaches almost none of the flow this phase moves; stepping
    through the live buttons by the step number is just as
    deterministic and plays a varied game. It deliberately does **not**
    draw from `random`: a rule that spent the module RNG would make
    every choice downstream of every die, so a change to one roll
    would rewrite the whole transcript instead of the part it touched.

    The game runs to **full time** rather than to a step cap -- an
    ordinary game ends itself, and `test_the_recorded_game_finishes`
    is what keeps the golden from quietly becoming a truncated run.
    """
    cog = build_cog()
    # Reached only on the way out of a finished game, which the
    # tutorial never is inside its own transcript.
    cog.bot = SimpleNamespace(
        get_channel=mock.Mock(return_value=None),
        fetch_channel=mock.AsyncMock(return_value=None),
        get_guild=mock.Mock(return_value=None),
    )
    game = build_game(
        tutorial=False,
        tutorial_step=None,
        mode=GameMode.ADVANCED,
        board_size=board_size,
        player_1_team=Team.TELEKINETICS,
        player_2_team=Team.FIRE_DEMONS,
        player_2_id=None,
        ai_opponent=AIOpponent.DINKY,
    )
    game.match_state = cog.engine.initialize_standard_match(game).to_dict()
    cog.games["g1"] = game

    return await _play(
        cog,
        game,
        press=lambda live, step: live[step % len(live)],
        keep_going=lambda: True,
        max_steps=ADVANCED_MAX_STEPS,
        interaction_factory=build_advanced_interaction,
    )


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


class AdvancedGoldenHarness:
    """
    A whole advanced solo game per board, recorded and compared.

    **This is the golden Phase 4 of the model/Discord split added, and
    what it exists to watch is the spine.** The tutorial golden covers
    one basic game on board 7 and reaches none of it -- no gambit, no
    species ability, no arrival gate, no injury test, no own goal, no
    stacked run back, no loose-ball contest. Every one of those is a
    function that phase moved out of `cogs/` and into
    `d12ball/flow/`, so a golden that cannot see them is not a guard
    on the move.

    Recorded on the unmoved code, before anything was lifted, which is
    what makes it evidence rather than the new code agreeing with
    itself.

    One subclass per board so a failure names the board in the test
    id; the run is `asyncSetUp`'s because all three assertions below
    read the same recording. A plain mixin rather than a `TestCase`,
    the shape `GambitHarness` already uses, so the base does not
    collect three tests of its own that can only skip.
    """

    board_size: int = 0

    async def asyncSetUp(self) -> None:
        # Saved and restored: the module RNG is global and seeding it
        # here would otherwise leak into whatever runs next.
        state = random.getstate()
        random.seed(ADVANCED_GAMES[self.board_size])
        self.addCleanup(random.setstate, state)

        self.transcript, self.final_match = await record_advanced_playthrough(
            self.board_size,
        )

    @property
    def transcript_file(self) -> pathlib.Path:
        return GOLDEN_DIR / f"advanced_board{self.board_size}_transcript.txt"

    @property
    def match_file(self) -> pathlib.Path:
        return GOLDEN_DIR / f"advanced_board{self.board_size}_final_match.json"

    async def test_the_narration_and_prompts_are_unchanged(self) -> None:
        """Every message the game posts, and the prompt each came under."""
        if UPDATING:
            GOLDEN_DIR.mkdir(exist_ok=True)
            self.transcript_file.write_text(self.transcript)
            self.skipTest("FOOLBOT_UPDATE_GOLDEN=1: transcript rewritten")

        self.assertTrue(
            self.transcript_file.exists(),
            f"{self.transcript_file} is missing -- regenerate with "
            "FOOLBOT_UPDATE_GOLDEN=1",
        )
        recorded = self.transcript_file.read_text()
        if recorded != self.transcript:
            self.fail(
                f"the advanced game on board {self.board_size} no longer "
                "says what it used to. If that is deliberate, regenerate "
                "with FOOLBOT_UPDATE_GOLDEN=1 and put the diff in the pull "
                "request.\n\n"
                + golden_diff(
                    recorded,
                    self.transcript,
                    f"board {self.board_size} transcript",
                )
            )

    async def test_the_final_save_is_unchanged(self) -> None:
        """The save format, which a refactor may not change."""
        rendered = render_final_match(self.final_match)
        if UPDATING:
            GOLDEN_DIR.mkdir(exist_ok=True)
            self.match_file.write_text(rendered)
            self.skipTest("FOOLBOT_UPDATE_GOLDEN=1: final match rewritten")

        self.assertTrue(
            self.match_file.exists(),
            f"{self.match_file} is missing -- regenerate with "
            "FOOLBOT_UPDATE_GOLDEN=1",
        )
        recorded = self.match_file.read_text()
        if recorded != rendered:
            self.fail(
                "the saved match state changed. A refactor may not change "
                "the save format -- see principle 6 in "
                "docs/model-discord-split.md.\n\n"
                + golden_diff(
                    recorded,
                    rendered,
                    f"board {self.board_size} final match",
                )
            )

    async def test_the_recorded_game_finishes(self) -> None:
        """
        The run ended because the game did, not because the step cap
        cut it off.

        Without this the golden could quietly become a truncated run --
        still deterministic, still green, and a reference that stops
        somewhere arbitrary rather than at full time. The tutorial
        golden's own version of this assertion is that the recorded
        run is the one that scores.
        """
        presses = self.transcript.count("=== press ")
        self.assertLess(
            presses,
            ADVANCED_MAX_STEPS,
            f"the board {self.board_size} game hit the step cap, so the "
            "golden is a truncated run rather than a whole game",
        )


class AdvancedGoldenBoard6Tests(
    AdvancedGoldenHarness, unittest.IsolatedAsyncioTestCase
):
    """The stacking board -- see docs/design/formations-and-occupancy.md."""

    board_size = 6


class AdvancedGoldenBoard9Tests(
    AdvancedGoldenHarness, unittest.IsolatedAsyncioTestCase
):
    """The widest board there is, where a pass has field to run out of."""

    board_size = 9


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

    def test_two_advanced_runs_on_one_seed_agree(self) -> None:
        """
        The same, for the two advanced goldens.

        Worth asserting separately because their press rule is not the
        tutorial's: stepping round the live buttons by the step index
        depends on the order a view builds its children in, which is
        the kind of thing a set iterated into a row of buttons would
        make machine-dependent without changing anything visible.
        """
        for board_size in sorted(ADVANCED_GAMES):
            with self.subTest(board=board_size):
                first_t, first_m = self._run_advanced(board_size)
                second_t, second_m = self._run_advanced(board_size)
                if first_t != second_t:
                    self.fail(
                        "the same seed replayed a different game on "
                        f"board {board_size}:\n\n"
                        + golden_diff(first_t, second_t, "transcript")
                    )
                self.assertEqual(first_m, second_m)

    def _run_advanced(self, board_size: int) -> tuple[str, dict]:
        state = random.getstate()
        try:
            random.seed(ADVANCED_GAMES[board_size])
            return asyncio.run(record_advanced_playthrough(board_size))
        finally:
            random.setstate(state)


if __name__ == "__main__":
    unittest.main()

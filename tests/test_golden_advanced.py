"""
An **advanced** game played through the real cog, recorded, and compared
word for word against a file in `tests/golden/`.

The twin of `tests/test_golden_transcript.py`, and it exists because
that one's own docstring asked for it: the tutorial golden is one
*basic*-mode solo game on board 7, so it watches no gambit, no species
ability, no Mind Pull, no injury test, no own goal and no stacked run
back. Phase 4 of `docs/design/model-discord-split.md` moves the spine of a turn
-- the arrival gates, the run-back cascade, the injury tests, the own
goal roll -- and a mechanical move needs a guard over the code it is
moving, not beside it.

**What this game is, and why each choice.**

- **Advanced mode with both modules on** (`GameMode.ADVANCED`,
  `advanced_maneuvers`, `species_abilities`), because
  `RulesEngine.gambits_apply` and `species_abilities_apply` both read
  `game.mode` as well as their own flag -- a game with the flags set and
  `mode` left at its `BASIC` default plays a basic game and the golden
  would quietly cover nothing this file is for.
- **Telekinetics against Fire Demons**, because Mind Pull and Smooth are
  the two halves of the arrival gate and a whole-species team puts one
  on every space. The human coaches the Telekinetics: Dinky never pulls
  and never takes a Smooth (see "Mind Pull, and the arrival gate" in
  docs/design/species-abilities.md), so an AI Telekinetic would be
  skipped rather than asked and the gate would go unrecorded.
- **Board 7 in 2-3-1**, because 2-3-1 leaves each two-space goal zone
  holding exactly two cards: both spaces are covered from the deal, so
  a displaced player running back into one has to stack, which is the
  second question a run back asks. (It was board 6 in 2-3-1 until the
  six-space board went -- 2026-09-22 in docs/rules-log.md.)
- **Solo against Dinky**, so one user id presses every button. A
  two-human game would need the presser to change hands with possession,
  and `SafeView.may_act_for` would reject half the presses.

**The press rule is the script.** There are no tutorial rails here, so
the run needs a rule that is deterministic *and* makes progress:

- `"Done coaching"` wins whenever a coaching hub offers it. Taking the
  first enabled button instead walks into the Formation menu, comes back
  to the hub, and walks into it again forever -- the window has no
  natural end.
- **"Back" is never pressed.** It is the one button that undoes rather
  than advances: a retracted score attempt is the set-up choice again,
  whose first button takes the shot again, and a rotating press
  ping-pongs between the two for the rest of the budget. That is the
  second circle in the game and it is a button rather than a view.
- Otherwise the press **rotates**: `live[step % len(live)]`. Always
  taking the first enabled button is deterministic too, and it plays Low
  Pass and Deflect for the whole game -- the first card of each hand --
  so ten of the twelve maneuvers, every gambit and most of the spine
  never run. Rotating is what gets all twelve played.

`ADVANCED_SEED` was picked by sweeping seeds and scoring the run on how
much of the spine it reaches; see `test_the_recorded_run_still_covers_the_spine`,
which asserts the coverage rather than trusting the seed, so a change
that quietly stops reaching the own-goal roll fails here rather than
going unnoticed.

**What it reaches**: all twelve maneuvers, the Mind Pull offer and the
Smooth offer, a loose-ball skill test, an injury test, an own-goal roll,
a run back that stops to ask **both** of its questions (which space, and
which of a stack goes), a score attempt, a set-up, a time-out, the
halftime extra token and a coaching window.

**What it still does not.** The loose ball's *contest pick*
(`LooseBallChoiceView`, "choose who goes after it") -- this run's loose
balls all come down where somebody is already standing, which
pre-declines the other side and settles without asking; the choice of
ball handler (`BallHandlerSelectionView`), which wants two of the side
in possession on the ball's own space with nobody carrying it, and no
deal on either board puts two on the kickoff space any more (it did on
board 6, under 2-3-1) -- `tests/test_d12ball_driver_actions.py` and
`tests/prompt_fixtures.py` ask that prompt directly instead; the free
pickup after a time-out (`begin_ball_recovery`), which needs the ball
loose at the moment a coach calls one; and full time and the shootout,
which are past where the step budget stops. Those are Phase 5's ground and want a
golden of their own.

**The seed has been re-picked six times.** Once when PR #243 and PR
#244 landed on main under this branch: both are rule changes in the code
this phase moves, so the game seed 44 had played was no longer the game
it plays. Again when the six-space board was withdrawn (2026-09-22 in
docs/rules-log.md) and this game moved to board 7, which is a different
game from the first roll. Again when Volatile stopped reaching the
injury check and the own-goal roll (2026-09-23 in docs/rules-log.md): an
ignite there no longer draws a second die, which shifts every draw after
it, and seed 134's game stopped reaching the own-goal roll. And when
Smooth stopped reading the spaces the ball passes through and Mind Pull
came to be asked before it (2026-09-24), which changed which offers the
game makes. And when advanced mode took on the personal abilities and
the advanced skill scores (Law 21, 2026-09-25): Hellguard's 8 and the
Fire Demons' own ignites change the game from the first skill test, and
seed 11 stopped reaching the Setup Pass choice and Clear. And again the
same day, when the sheet gave Dravox, Hexis and Emberdash abilities of
their own and Spectra's changed (seed 226 to 69). Each time the seed was
swept and scored on the coverage below, not chosen.

Regenerating is the tutorial golden's rule, and for the same reason --
see that module's docstring:

    FOOLBOT_UPDATE_GOLDEN=1 python3 -m unittest tests.test_golden_advanced
"""

import asyncio
import os
import pathlib
import re
import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import presentation as presentation_mod
from cogs.d12ball_views import turn as turn_views
from save_patches import (
    suppressed_cog_saves,
    suppressed_full_image_links,
)

from d12ball.components import MatchState
from d12ball.game import Formation, GameMode, Team

# The fixtures are the tutorial suite's, the same way
# `test_golden_transcript` takes them: one home for "how you stand a cog
# up with Discord mocked". `golden_diff` and `render_final_match` come
# from the tutorial golden for the same reason -- a diff a reviewer
# reads should look the same whichever golden failed.
from test_d12ball_tutorial import (
    CATALOG,
    RULES,
    build_cog,
    build_game,
    build_interaction,
)
from test_golden_transcript import golden_diff, render_final_match
from cog_steps import finish_setup_coaching

GOLDEN_DIR = pathlib.Path(__file__).resolve().parent / "golden"
TRANSCRIPT_FILE = GOLDEN_DIR / "advanced_transcript.txt"
FINAL_MATCH_FILE = GOLDEN_DIR / "advanced_final_match.json"

#: Picked by sweeping seeds and scoring each run on how much of the
#: spine it reaches -- all twelve maneuvers, both halves of the arrival
#: gate, the own-goal roll and a run back that stops to ask. It seeds
#: the engine's own `rng`, where every draw the game makes comes from
#: (the dice, the shuffle, the AI's picks), rather than the module
#: `random`, which nothing in the model reads.
ADVANCED_SEED = 69

#: The game is not played to full time: the budget stops it in the
#: second half, which is as far as Phase 4's ground goes. Full time and
#: the shootout are Phase 5's and want a golden of their own.
MAX_STEPS = 90

#: The hub is one of two views in the game that can be walked in a
#: circle, so the script leaves it deliberately rather than by rotation.
COACHING_ESCAPE = "Done coaching"

#: The other circle, and it is not a view but a button. "Back" undoes
#: rather than advances -- a score attempt retracted is the set-up
#: choice again, whose first button takes the shot again -- so a
#: rotating press ping-pongs between the two until the budget runs out.
#: A script trying to play a game never wants it, which is the whole
#: rule: **press nothing that goes backwards.**
NEVER_PRESSED = ("Back",)

UPDATING = os.environ.get("FOOLBOT_UPDATE_GOLDEN") == "1"


def build_advanced_cog():
    """
    The tutorial suite's cog with `bot` stood up.

    An advanced game reaches `restore_saved_views` and the channel
    lookups, which a tutorial game on the rails never does; the three
    methods that touches are all "hand this to Discord" and answer
    nothing the flow reads.
    """
    cog = build_cog()
    cog.bot = SimpleNamespace(
        add_view=lambda *args, **kwargs: None,
        get_guild=lambda *args: None,
        get_channel=lambda *args: None,
    )
    return cog


def build_advanced_game():
    """
    A solo advanced game, human on the Telekinetics -- see the module
    docstring for why each of those is load-bearing.
    """
    return build_game(
        tutorial=False,
        tutorial_step=None,
        player_1_team=Team.TELEKINETICS,
        player_2_team=Team.FIRE_DEMONS,
        mode=GameMode.ADVANCED,
        advanced_maneuvers=True,
        species_abilities=True,
    )


def build_advanced_match() -> MatchState:
    """
    Board 7 in 2-3-1: each goal zone holds two cards on its two
    spaces, so both are covered from the deal and a displaced player
    running back into one has to stack -- the run back's second
    question, which is what this game is here to reach.
    """
    return MatchState.standard(
        catalog=CATALOG,
        ruleset=RULES,
        board_size=7,
        home_team=Team.TELEKINETICS,
        visiting_team=Team.FIRE_DEMONS,
        home_formation=Formation.TWO_THREE_ONE,
    )


def choose_button(live: list, step: int):
    """
    Which of the enabled buttons this step presses -- the script, in one
    function, so the rule a reviewer has to trust is short.
    """
    for item in live:
        if item.label == COACHING_ESCAPE:
            return item
    forward = [item for item in live if item.label not in NEVER_PRESSED]
    # A view offering nothing but "Back" would deadlock the script
    # rather than the game; take it and let the budget stop the run.
    return (forward or live)[step % len(forward or live)]


async def record_playthrough(seed: int = ADVANCED_SEED) -> tuple[str, dict]:
    """
    Play an advanced game through the real cog and return the
    transcript and the final match state.

    The loop is `test_golden_transcript.record_playthrough`'s with two
    differences, both of which are "there are no rails here": the press
    is `choose_button` rather than the first enabled item, and the run
    stops when nothing is left to press or the budget runs out rather
    than when the tutorial ends.
    """
    recorder = SimpleNamespace(messages=[], views=[])
    cog = build_advanced_cog()
    cog.engine.rng.seed(seed)
    game = build_advanced_game()
    game.match_state = build_advanced_match().to_dict()
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
            suppressed_full_image_links(), \
            mock.patch.object(
                turn_views,
                "add_full_image_button_to_response",
                mock.AsyncMock()), \
            mock.patch.object(
                presentation_mod, "pin_board_message", mock.AsyncMock()):

        await finish_setup_coaching(cog, 
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
            pressed = choose_button(live, step)
            lines.append(
                f"=== press {step + 1}: {type(view).__name__} "
                f"-> {pressed.label!r}"
            )
            await pressed.callback(build_interaction(recorder))
            drain()

    return "\n".join(lines) + "\n", cog.engine.load_match_state(game).to_dict()


def views_pressed(transcript: str) -> set[str]:
    """The view classes the recorded run actually put in front of a coach."""
    return set(re.findall(r"press \d+: (\w+)", transcript))


class AdvancedGoldenTranscriptTests(unittest.IsolatedAsyncioTestCase):
    """One real advanced game, recorded and compared."""

    async def asyncSetUp(self) -> None:
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

    async def test_the_recorded_run_still_covers_the_spine(self) -> None:
        """
        The seed is doing its job.

        Asserted rather than trusted, for the reason the tutorial golden
        asserts that its run scores: a transcript that stopped reaching
        the own-goal roll would still be deterministic, still green, and
        would have quietly stopped guarding the code this file exists
        for. Each name below is a branch Phase 4 moved.
        """
        pressed = views_pressed(self.transcript)
        for view_name in (
            "MindPullView",
            "SmoothView",
            "OwnGoalRollView",
            "RunBackChoiceView",
            "RunBackPlayerChoiceView",
            "LooseBallSkillTestView",
            "ScoreAttemptView",
            "SetupPassChoiceView",
            "ManeuverChallengeView",
        ):
            self.assertIn(
                view_name,
                pressed,
                f"the recorded run no longer reaches {view_name}, so the "
                "golden has stopped covering the branch behind it -- pick "
                "a seed that reaches it and regenerate.",
            )

    async def test_every_maneuver_is_played(self) -> None:
        """
        All twelve cards resolve somewhere in the run.

        This is what the rotating press rule buys, and it is the reason
        the rule is not "take the first enabled button": the hand is
        ordered, so first-always plays two cards and the golden would
        cover a tenth of `d12ball/flow/effects.py`.
        """
        for card in (
            "Low Pass", "Skilled Pass", "High Pass", "Setup Pass",
            "Dribble Advance", "Dribble Burst", "Deflect", "Clear",
            "Steal", "Intercept", "Pressure", "Double Team",
        ):
            self.assertIn(
                f"**{card}**",
                self.transcript,
                f"{card} is no longer played in the recorded run.",
            )


class AdvancedGoldenDeterminismTests(unittest.TestCase):
    """
    The claim the file rests on: the same seed replays the same game.

    The tutorial golden's reasoning, and it matters more here -- this
    run is twice as long, reaches two ordered queues (the Smooth offer
    and the pull) and a run-back cascade, and every one of those is a
    place an insertion-ordered `dict` or an iterated `set` could make
    the transcript machine-dependent.
    """

    def test_two_runs_on_one_seed_agree(self) -> None:
        first_t, first_m = self._run()
        second_t, second_m = self._run()
        if first_t != second_t:
            self.fail(
                "the same seed replayed a different game:\n\n"
                + golden_diff(first_t, second_t, "transcript")
            )
        self.assertEqual(first_m, second_m)

    def _run(self) -> tuple[str, dict]:
        return asyncio.run(record_playthrough())


if __name__ == "__main__":
    unittest.main()

"""
A whole game played to **full time and through the shootout**, recorded
and compared word for word against a file in `tests/golden/`.

The third golden, and the one Phase 5 of `docs/design/model-discord-split.md`
is moved under. `test_golden_transcript.py` plays the tutorial and
`test_golden_advanced.py` plays a free advanced game, and the second
one's own docstring says what neither reaches: "full time and the
shootout, which are past where the step budget stops. Those are Phase
5's ground and want a golden of their own." This is that file. What it
guards is every window the phase moves -- the pre-kickoff Coaching
Choice, a time out in each half, halftime with its extra token and a
substitution on **both** sides, the window before the shootout, and the
shootout itself into sudden death.

**It is the advanced golden's harness with a longer script**, not a
third way of driving the cog: `build_cog`, `build_interaction` and the
diff come from the tutorial suite exactly as that one takes them, and
the loop is the same "press a button, drain the messages" loop. The two
things that differ are the game and the press rule, and both are here
because of what this file has to reach.

**What this game is, and why each choice.**

- **Solo against Dinky**, the advanced golden's choice and for its
  reason: one user id presses every button, where a two-human game
  would need the presser to change hands with possession and
  `SafeView.may_act_for` would refuse half the presses. `D12BallGame`
  refuses two coaches on one id outright, so "two humans" is not
  available to a script at all.
- **Basic mode on board 7 in 2-2-2**, the standard deal. The advanced
  modules are the advanced golden's ground, and every press spent on a
  gambit or a Mind Pull offer here is a press not spent getting to
  minute 30. This game plays both halves out, so it is deliberately the
  plainest game the bot can play.
- **A level score at full time**, which is the one thing the script
  cannot arrange and the whole reason the seed is what it is:
  `test_the_game_is_level_at_full_time` asserts it, because a game that
  finishes 2-1 ends at the whistle and guards none of
  `begin_full_time_coaching`, `begin_shootout` or `advance_shootout`.
  The recorded run is 1-1 and the shootout settles it 3-4 in sudden
  death.

**The AI side's halftime substitution is pinned here**, which the seed
before this one could not manage: Dinky substitutes only to get an
injured player off, so a script cannot make it swap anybody, and
whether one of its players is hurt at the break is the dice's to
decide. On seed 39 one is -- Zytheris comes on for the injured Tachyon
in Purple's halftime window -- so both sides' halftime windows run
here *and* both move a player. The old seed covered Dinky's
substitution routine only in a time out it called itself.

**The press rule is the script**, and it has four rules on top of the
advanced golden's two ("never press Back", "leave a coaching hub by
Done"), each one there to reach a window:

- **A time out is taken the moment it is offered.** `may_call_time_out`
  is once a half and refuses under last possession, so "always press
  it" is exactly one time out per half and needs no counting. It is
  taken early in each half, which is what makes this file the
  regression test for a new play's window as well: every restart
  Orange makes after press 2 offers them a Coaching Choice they had
  a spent time out at the time of, and the first is at press 16.
- **A halftime window makes one substitution**, read off the match
  rather than counted in the script: a hub whose side is on a halftime
  coaching stage with nothing yet in `pending_coaching_swaps` goes to
  the substitution menu, and the same hub a moment later -- now with a
  swap on it -- takes Done.
- **A shootout menu takes its first player.** Both are ephemeral and
  rebuilt after every pick (see `ShootoutOrderSelectView`), so the
  script re-reads the view each press like every other one.
- **The roll prompt rolls.** `ShootoutTestView` carries "Your Order"
  and, in an advanced game, Overdrive buttons beside the roll; a
  rotating press would read the order six times instead of shooting.
  "Your Order", "Start Over" and "Team roster" join "Back" in
  `NEVER_PRESSED` for that reason: none of the four advances anything.

**Where it stops.** The run ends when the game record says the game is
over, which is the shootout settling it -- and that is what stops the
script pressing Rematch and playing a second game into the same
transcript.

Regenerating is the other two goldens' rule, and for the same reason --
see `test_golden_transcript`'s docstring:

    FOOLBOT_UPDATE_GOLDEN=1 python3 -m unittest tests.test_golden_windows
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
    suppressed_view_saves,
)

from d12ball.components import MatchState
from d12ball.game import Formation, GameMode, GameStatus, Team

# The fixtures are the tutorial suite's, the same way the advanced
# golden takes them -- one home for "how you stand a cog up with
# Discord mocked", and a diff that looks the same whichever golden
# failed.
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
TRANSCRIPT_FILE = GOLDEN_DIR / "windows_transcript.txt"
FINAL_MATCH_FILE = GOLDEN_DIR / "windows_final_match.json"

#: Picked by sweeping seeds 0-39 and keeping the one whose game is
#: **level at full time** and whose first shootout round is **level
#: too** -- the two things the script cannot arrange, since both are
#: dice. Eleven of the forty were level at full time and two of those
#: eleven went to sudden death. Every other window this file names is
#: reached by the press rule and would be reached on any seed. It
#: seeds the engine's own `rng`, where every draw the game makes comes
#: from (the dice, the shuffle, the AI's picks), rather than the module
#: `random`, which nothing in the model reads.
#:
#: **It was 31 until a new play's window stopped being gated on the
#: half's time out** (see docs/rules-log.md, 2026-09-21). Every seed's
#: game changed with it -- the restarting coach now gets a window they
#: were being skipped past, and a window is presses and dice -- so the
#: sweep was re-run rather than the old seed re-recorded. 39 is the
#: shorter of the two that still land level and still go to sudden
#: death, and it lands on the same 1-1 and the same 3-4 the old run
#: did, which is coincidence rather than a property of the change.
WINDOWS_SEED = 39

#: A whole game, both halves, and a shootout -- so the budget is an
#: order of magnitude past the advanced golden's. It is a backstop
#: against a script that starts walking in a circle, not a stop the run
#: is expected to hit: `test_the_run_finishes_the_game` fails if it is.
MAX_STEPS = 1500

#: The hub is one of two views in the game that can be walked in a
#: circle, so the script leaves it deliberately rather than by rotation.
COACHING_ESCAPE = "Done coaching"

#: The other circle, and it is a button rather than a view. See the
#: advanced golden.
NEVER_PRESSED = ("Back", "Start Over", "Your Order", "Team roster")

#: What the substitution button's `custom_id` starts with. The label
#: carries the allowance ("Substitution (2 left at halftime)"), so it is
#: not a key.
SUBSTITUTION_CUSTOM_ID = "d12ball:coach_sub:"

UPDATING = os.environ.get("FOOLBOT_UPDATE_GOLDEN") == "1"


def build_windows_cog():
    """The tutorial suite's cog with `bot` stood up -- the advanced
    golden's, and for its reason: a game off the rails reaches
    `restore_saved_views` and the channel lookups."""
    cog = build_cog()
    cog.bot = SimpleNamespace(
        add_view=lambda *args, **kwargs: None,
        get_guild=lambda *args: None,
        get_channel=lambda *args: None,
    )
    return cog


def build_windows_game():
    """
    A solo basic game -- see the module docstring for why it is not two
    humans and not advanced.
    """
    return build_game(
        tutorial=False,
        tutorial_step=None,
        player_1_id=111,
        player_2_id=None,
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        mode=GameMode.BASIC,
    )


def build_windows_match() -> MatchState:
    """The standard deal on board 7."""
    return MatchState.standard(
        catalog=CATALOG,
        ruleset=RULES,
        board_size=7,
        home_team=Team.ORANGE,
        visiting_team=Team.PURPLE,
        home_formation=Formation.TWO_TWO_TWO,
    )


def wants_a_substitution(match) -> bool:
    """
    Whether the hub in front of the script is the halftime window that
    still owes its one substitution.

    Read off the match rather than counted in the script, so a window
    re-entered after a restart -- or a hub returned to after the swap --
    answers correctly without the script remembering anything.
    """
    stage = match.pending_halftime_stage
    return (
        stage in ("coaching_home", "coaching_visiting")
        and not match.pending_coaching_swaps
    )


def choose_button(live: list, step: int, match):
    """
    Which of the enabled buttons this step presses -- the script, in one
    function, so the rule a reviewer has to trust is short. See the
    module docstring for what each clause is reaching.
    """
    by_label = {item.label: item for item in live}

    if "Time out" in by_label:
        return by_label["Time out"]
    if "Take the time out" in by_label:
        return by_label["Take the time out"]

    if COACHING_ESCAPE in by_label:
        if wants_a_substitution(match):
            for item in live:
                if (item.custom_id or "").startswith(SUBSTITUTION_CUSTOM_ID):
                    return item
        return by_label[COACHING_ESCAPE]

    for label in (
        "Set Your Shooting Order",
        "Choose Your Shooter",
        "Roll the skill test",
    ):
        if label in by_label:
            return by_label[label]

    forward = [item for item in live if item.label not in NEVER_PRESSED]
    # A view offering nothing but a button the script refuses would
    # deadlock the script rather than the game; take it and let the
    # budget stop the run.
    return (forward or live)[step % len(forward or live)]


async def record_playthrough(seed: int = None) -> tuple[str, dict, dict]:
    """
    Play the game through the real cog and return the transcript, the
    final match state, and a few facts about the run the tests assert
    on.

    The loop is the advanced golden's, with one difference: it stops
    when the game record says the game is over rather than only when
    nothing is left to press. The shootout's last message carries the
    rematch buttons, and a script that pressed one would play a second
    game into the same transcript.
    """
    recorder = SimpleNamespace(messages=[], views=[])
    cog = build_windows_cog()
    cog.engine.rng.seed(WINDOWS_SEED if seed is None else seed)
    game = build_windows_game()
    game.match_state = build_windows_match().to_dict()
    cog.games["g1"] = game

    lines: list[str] = []
    seen = 0
    presses = 0

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
            if game.status == GameStatus.FINISHED:
                break
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
            pressed = choose_button(
                live, step, cog.engine.load_match_state(game),
            )
            lines.append(
                f"=== press {step + 1}: {type(view).__name__} "
                f"-> {pressed.label!r}"
            )
            await pressed.callback(build_interaction(recorder))
            presses += 1
            drain()

    match = cog.engine.load_match_state(game)
    facts = {
        "presses": presses,
        "finished": game.status == GameStatus.FINISHED,
        "home_score": match.scoreboard.home_score,
        "visiting_score": match.scoreboard.visiting_score,
        "shootout_home": match.shootout_goals_for(match.home.side),
        "shootout_visiting": match.shootout_goals_for(match.visiting.side),
    }
    return "\n".join(lines) + "\n", match.to_dict(), facts


def views_pressed(transcript: str) -> set[str]:
    """The view classes the recorded run actually put in front of a coach."""
    return set(re.findall(r"press \d+: (\w+)", transcript))


class WindowsGoldenTranscriptTests(unittest.IsolatedAsyncioTestCase):
    """One whole game, recorded and compared."""

    async def asyncSetUp(self) -> None:
        self.transcript, self.final_match, self.facts = (
            await record_playthrough()
        )

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
                "deliberate, regenerate with FOOLBOT_UPDATE_GOLDEN=1 "
                "and put the diff in the pull request.\n\n"
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

    async def test_the_run_finishes_the_game(self) -> None:
        """
        The run reaches a settled game rather than running out of
        budget. A transcript that stopped at press 1500 would still be
        deterministic and would guard nothing past wherever it stopped.
        """
        self.assertTrue(
            self.facts["finished"],
            "the run no longer finishes the game -- it stopped after "
            f"{self.facts['presses']} presses with the game still in "
            "progress.",
        )
        self.assertLess(self.facts["presses"], MAX_STEPS)

    async def test_the_game_is_level_at_full_time(self) -> None:
        """
        The one thing the script cannot arrange, and the reason this
        seed and not another: a game that is not level at full time
        never opens the shootout, so every window past the whistle
        would go unguarded.
        """
        self.assertEqual(
            self.facts["home_score"] - self.facts["shootout_home"],
            self.facts["visiting_score"] - self.facts["shootout_visiting"],
            "the recorded game is no longer level at full time, so it "
            "no longer reaches the shootout -- pick a seed that is and "
            "regenerate.",
        )

    async def test_the_recorded_run_covers_every_window(self) -> None:
        """
        The seed and the script are doing their job.

        Asserted rather than trusted, for the reason the other two
        goldens assert their own coverage: a transcript that stopped
        reaching the shootout would still be deterministic, still
        green, and would have quietly stopped guarding the code this
        file exists for. Each name below is a window Phase 5 moves.
        """
        pressed = views_pressed(self.transcript)
        for view_name in (
            "CoachingHubView",
            "CoachingSubstitutionOutView",
            "CoachingSubstitutionInView",
            "PlayerActionView",
            "TimeOutConfirmView",
            "HalftimeExtraTokenView",
            "ShootoutOrderPromptView",
            "ShootoutOrderSelectView",
            "ShootoutTestView",
        ):
            self.assertIn(
                view_name,
                pressed,
                f"the recorded run no longer reaches {view_name}, so "
                "the golden has stopped covering the window behind it "
                "-- pick a seed that reaches it and regenerate.",
            )

    async def test_a_time_out_is_taken_in_each_half(self) -> None:
        """
        The coach takes one in each half, which is the most
        `may_call_time_out` allows.

        Counted off the transcript's own presses rather than off the
        event log: `EVENT_TIME_OUT` records Dinky's as well, and what
        this is asserting is that the **script** reached the button
        twice -- once before the break and once after.
        """
        confirmations = self.transcript.count(
            "TimeOutConfirmView -> 'Take the time out'"
        )
        self.assertEqual(
            confirmations,
            2,
            "the recorded run no longer takes a time out in each half "
            f"-- it took {confirmations}.",
        )

    async def test_the_shootout_reaches_sudden_death(self) -> None:
        """
        A level first round, which is the second thing the script
        cannot arrange -- and what `ShootoutPickPromptView` exists for.
        """
        self.assertIn("ShootoutPickPromptView", views_pressed(self.transcript))


class WindowsGoldenDeterminismTests(unittest.TestCase):
    """
    The claim the file rests on: the same seed replays the same game.

    The other two goldens' reasoning, and it matters most here -- this
    run is the longest of the three and reaches two ephemeral menus
    rebuilt from a shrinking list on every press, which is exactly
    where an iterated `set` would make the transcript
    machine-dependent.
    """

    def test_two_runs_on_one_seed_agree(self) -> None:
        first_t, first_m, _ = self._run()
        second_t, second_m, _ = self._run()
        if first_t != second_t:
            self.fail(
                "the same seed replayed a different game:\n\n"
                + golden_diff(first_t, second_t, "transcript")
            )
        self.assertEqual(first_m, second_m)

    def _run(self) -> tuple[str, dict, dict]:
        return asyncio.run(record_playthrough())


if __name__ == "__main__":
    unittest.main()

"""
The fourth golden, and the first with no frontend in it: the tutorial
played through `GameService.apply_action` with the default `Batching()`,
every `GameResult` written down as the service handed it back, and the
final save beside it -- decision 9 of docs/web-app.md, landed with
step 9 of docs/architecture-migration.md once the tokens had settled.

**It pins the model's voice, tokens and all.** The three cog goldens
record what the bot *posted*, after `D12Ball.rendered` has drawn every
`{team:...}`, `{role:...}`, `{condition:...}`, `{species:...}` and
`{coach:...}` for Discord; this one records what the service *said*,
which is what a web page would receive. A wording change shows here
as a diff in a pull request, the same as in the other three; a token
that changes its spelling shows here and nowhere else.

    FOOLBOT_UPDATE_GOLDEN=1 python3 -m unittest tests.test_golden_service

rewrites the two files. It plays the tutorial rather than a free game
because the rails leave exactly one answer at nearly every step, so
the run is reproducible off the seed alone (`GOLDEN_SEED` below is the
tutorial golden's: one the closing shot scores on). The policy is
`test_driver_full_game.TutorialPolicy`, which reads `PendingPrompt.options`
and nothing else -- so what is pinned is what a frontend that reads
only the result can reach.
"""

import json
import unittest

from d12ball import tokens
from d12ball.components import MatchState
from d12ball.flow import FollowOnStep
from gamesaves.d12ball.service import GameResult, GameService
from prompt_fixtures import RULESET
from test_driver_full_game import (
    TutorialPolicy,
    build_engine,
    build_tutorial_game,
    build_tutorial_match,
)
from test_golden_transcript import (
    GOLDEN_DIR,
    GOLDEN_SEED,
    UPDATING,
    golden_diff,
    render_final_match,
)

TRANSCRIPT_FILE = GOLDEN_DIR / "service_tutorial_transcript.txt"
FINAL_MATCH_FILE = GOLDEN_DIR / "service_tutorial_final_match.json"

#: More than the tutorial takes to reach its handover and one turn past.
MAX_ACTIONS = 200


def describe(result: GameResult) -> list[str]:
    """One `GameResult`, as lines: what was answered, each closed group
    tagged with its step and whether it was drawn, what was still
    carried, and the prompt the run stopped on."""
    lines: list[str] = []
    if result.answer:
        lines.append("--- answer")
        lines.extend(result.answer)
    for group in result.groups:
        tag = group.step.name if group.step is not None else "caller"
        if group.prompt is not None:
            tag = f"prompt {group.prompt.name}"
        elif group.action is not None:
            tag = f"action {group.action.kind.name} {group.action.choice!r}"
        flags = "".join(
            (" drawn" if group.drawn else "", " new-play" if group.new_play else ""),
        )
        lines.append(f"--- group {tag}{flags}")
        lines.extend(group.lines)
    if result.narration:
        lines.append("--- narration")
        lines.extend(result.narration)
    if result.prompt is not None:
        lines.append(f"--- prompt {result.prompt.kind.name}")
        lines.append(result.prompt.ask)
    if result.board_changed:
        lines.append("--- board changed")
    return lines


def record_playthrough() -> tuple[str, dict]:
    """Play the tutorial through the service and return the transcript
    and the final save."""
    engine = build_engine()
    engine.rng.seed(GOLDEN_SEED)
    game = build_tutorial_game()
    game.match_state = build_tutorial_match().to_dict()
    games = {game.game_id: game}
    service = GameService(engine, games, save=lambda games: None)
    policy = TutorialPolicy(engine, game)
    lines: list[str] = []

    result = service.run_step(
        game.game_id, FollowOnStep.FINISH_SETUP_COACHING,
    )
    lines.append("=== kickoff")
    lines.extend(describe(result))

    for step in range(MAX_ACTIONS):
        done = not game.in_tutorial and game.tutorial_gate is None
        if done or result.prompt is None:
            break
        match = MatchState.from_dict(game.match_state, RULESET)
        action = policy.action(match, result.prompt)
        lines.append(
            f"=== action {step + 1}: {action.kind.name} "
            f"{action.choice!r} {json.dumps(action.arguments, default=str)}"
        )
        result = service.apply_action(game.game_id, action)
        assert not result.refused, (
            f"{action} refused on {result.waiting_on}: {result.refusal}"
        )
        lines.extend(describe(result))
    else:
        raise AssertionError("the tutorial did not hand over in budget")

    return "\n".join(lines) + "\n", game.match_state


class ServiceGoldenTests(unittest.TestCase):
    """The tutorial through the service, byte for byte."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.transcript, cls.final_match = record_playthrough()

    def test_the_transcript_matches_the_golden(self) -> None:
        if UPDATING:
            TRANSCRIPT_FILE.write_text(self.transcript)
            self.skipTest("FOOLBOT_UPDATE_GOLDEN=1: transcript rewritten")
        recorded = TRANSCRIPT_FILE.read_text()
        if recorded != self.transcript:
            self.fail(
                "the service no longer says what it used to. If that is "
                "deliberate, regenerate with FOOLBOT_UPDATE_GOLDEN=1 and put "
                "the diff in the pull request.\n\n"
                + golden_diff(recorded, self.transcript, "transcript")
            )

    def test_the_final_match_matches_the_golden(self) -> None:
        rendered = render_final_match(self.final_match)
        if UPDATING:
            FINAL_MATCH_FILE.write_text(rendered)
            self.skipTest("FOOLBOT_UPDATE_GOLDEN=1: final match rewritten")
        recorded = FINAL_MATCH_FILE.read_text()
        if recorded != rendered:
            self.fail(
                "the tutorial ends on a different position than it used to."
                "\n\n" + golden_diff(recorded, rendered, "final match")
            )

    def test_the_voice_is_the_models(self) -> None:
        """
        What the service says carries tokens and no Discord: no
        mention, no custom emoji, and the coach addressed by number.
        """
        self.assertNotIn("<@", self.transcript)
        self.assertNotIn("<:", self.transcript)
        kinds = {kind for kind, _ in tokens.find(self.transcript)}
        self.assertEqual(kinds, {"team", "role", "condition", "coach"})
        self.assertIn("{coach:1}, it is your turn.", self.transcript)

    def test_two_runs_on_one_seed_agree(self) -> None:
        second, second_match = record_playthrough()
        self.assertEqual(second, self.transcript)
        self.assertEqual(second_match, self.final_match)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

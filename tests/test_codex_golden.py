"""
The Codex bot's golden (docs/codex-bot.md, step 8): a seeded whole game
of Bashing against Finesse played through the Codex `GameService` --
`create_game`, the two seats, `start`, then `apply_action` for every
answer and `resume` for every step the bot owes -- with the default
`Batching()`, every `GameResult` written down as the service handed it
back, and the final save beside it. D12 Ball's `test_golden_service.py`
copied (docs/design/codex.md, "The golden").

**It pins the model's voice, tokens and all**: `{player:1}`,
`{card:iron_man}`, `{gold:3}` as the service says them, before any
frontend draws one. So:

- **a faithful change to rendering leaves it alone** -- the cog's
  emoji, its mentions, its message layout, the board's picture are all
  past the service and none of them is here;
- **a change to the model's wording, or to what the game does,
  re-records it** -- and the pull request that does so says it did, and
  shows the diff, the same as for D12 Ball's four goldens.

    FOOLBOT_UPDATE_GOLDEN=1 python3 -m unittest tests.test_codex_golden

rewrites the two files. The policy is `test_codex_driver_full_game.choose`,
which reads `PendingPrompt.options` and nothing else, so what is pinned is
what a frontend that reads only the result can reach. `GOLDEN_SEED` is the
full-game test's seed, on which the game ends on a destroyed base well
inside the bound.

What it does not cover: a concession, an undo, an abandon or a rematch
(`tests/test_codex_ending.py`, `tests/test_codex_history.py`); a test
game, whose tech is chosen in each side's own ready phase; anything the
policy never does -- detecting with the tower, an ability it does not
reach, a menu it never opens; and anything the cog renders.
"""

from __future__ import annotations

import json
import unittest

from codex import tokens
from codex.engine import RulesEngine
from codex.prompts import PromptKind
from gamesaves.codex.service import GameResult, GameService
from test_codex_driver_full_game import SEED, TURN_LIMIT, choose
from test_golden_transcript import GOLDEN_DIR, UPDATING, golden_diff, render_final_match

TRANSCRIPT_FILE = GOLDEN_DIR / "codex_service_transcript.txt"
FINAL_MATCH_FILE = GOLDEN_DIR / "codex_service_final_match.json"

GOLDEN_SEED = SEED

#: More answers than the game takes to reach a destroyed base.
MAX_ACTIONS = 5000


def describe(result: GameResult) -> list[str]:
    """
    One `GameResult`, as lines: each closed group tagged with its step
    and whether it was drawn, what was still carried, the prompt the run
    stopped on and the standing prompts' kinds. **Never a prompt's
    options**: a hand and a codex are their asked player's alone, as the
    result's own JSON leaves them out (`GameResult.to_dict`).
    """
    lines: list[str] = []
    for group in result.groups:
        tag = group.step.name if group.step is not None else "caller"
        lines.append(f"--- group {tag}{' drawn' if group.drawn else ''}")
        lines.extend(group.lines)
    if result.narration:
        lines.append("--- narration")
        lines.extend(result.narration)
    if result.prompt is not None:
        lines.append(f"--- prompt {result.prompt.kind.name} (player {result.prompt.asked_player})")
        lines.append(result.prompt.ask)
    for standing in result.standing:
        lines.append(f"--- standing {standing.kind.name} (player {standing.asked_player})")
    if result.board_changed:
        lines.append("--- board changed")
    return lines


def action_line(number: int, action) -> str:
    """What was answered, as one line -- **the arguments left out where
    they are hidden**: the card a worker is hired with and a tech
    choice's picks are their player's alone."""
    hidden = action.kind is PromptKind.TECH_CHOICE or action.choice == "hire"
    arguments = "(hidden)" if hidden else json.dumps(action.arguments, sort_keys=True, default=str)
    return f"=== action {number}: {action.kind.name} {action.choice!r} {arguments}"


def record_playthrough(seed: int = GOLDEN_SEED) -> tuple[str, dict]:
    """Play a whole game through the service; return the transcript and
    the final save."""
    engine = RulesEngine(seed=seed)
    games: dict = {}
    service = GameService(engine, games, save=lambda games: None)
    game = service.create_game(guild_id=1, game_number=1)
    service.take_seat(game.game_id, 101, "basher", "bashing")
    service.take_seat(game.game_id, 202, "fencer", "finesse")
    lines = ["=== start"]
    result = service.start(game.game_id)
    lines.extend(describe(result))

    for step in range(MAX_ACTIONS):
        match = service.load(game)
        if match.winner is not None:
            break
        assert match.turn <= TURN_LIMIT, "the game ran past its bound"
        waiting = service.waiting_on(game, match)
        if waiting is None:
            found, result = service.resume(game.game_id)
            lines.append(f"=== resume: {found}")
            lines.extend(describe(result))
            continue
        # The other player's tech choice, answered once it is offered,
        # as the full-game test answers it.
        unpicked = [
            prompt for prompt in service.standing(game, match)
            if match.player(prompt.asked_player).tech_choice is None
        ]
        prompt = unpicked[0] if unpicked else waiting
        action = choose(engine, match, prompt)
        lines.append(action_line(step + 1, action))
        result = service.apply_action(game.game_id, action)
        assert not result.refused, f"{action} refused: {result.refusal}"
        lines.extend(describe(result))
    else:
        raise AssertionError("the game did not end in budget")
    return "\n".join(lines) + "\n", game.match_state


class CodexGoldenTests(unittest.TestCase):
    """A whole game through the service, byte for byte."""

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
                "the Codex service no longer says what it used to. A faithful "
                "change to rendering cannot do this -- nothing rendered is here; "
                "a change to the model's wording or to the game does. If that is "
                "deliberate, regenerate with FOOLBOT_UPDATE_GOLDEN=1 and say so in "
                "the pull request, with the diff.\n\n"
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
                "the game ends on a different position than it used to."
                "\n\n" + golden_diff(recorded, rendered, "final match")
            )

    def test_the_game_ends_on_a_destroyed_base(self) -> None:
        self.assertIsNotNone(self.final_match["winner"])
        self.assertIsNone(self.final_match["conceded"])
        self.assertIn("--- prompt GAME_OVER", self.transcript)
        self.assertIn("the opposing base is destroyed.", self.transcript)

    def test_the_voice_is_the_models(self) -> None:
        """What the service says carries tokens and no Discord: no
        mention, no custom emoji, each player a seat."""
        self.assertNotIn("<@", self.transcript)
        self.assertNotIn("<:", self.transcript)
        kinds = {kind for kind, _ in tokens.find(self.transcript)}
        self.assertTrue({"player", "card", "gold"} <= kinds, kinds)

    def test_nothing_hidden_is_written(self) -> None:
        """A hired worker's card and a tech choice are never in the
        transcript -- neither said by the model nor written down by this
        test's own action lines."""
        for line in self.transcript.splitlines():
            if "hires a worker" in line or "tech card" in line:
                self.assertNotIn("{card:", line, line)
            if line.startswith("=== action") and ("TECH_CHOICE" in line or "'hire'" in line):
                self.assertTrue(line.endswith("(hidden)"), line)

    def test_two_runs_on_one_seed_agree(self) -> None:
        second, second_match = record_playthrough()
        self.assertEqual(second, self.transcript)
        self.assertEqual(second_match, self.final_match)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

"""
TNP's golden (step 8 of docs/tnp-bot.md): a seeded whole basic game --
Blue's Raider against Green's Turtle, `test_tnp_driver_full_game`'s
base game -- played through TNP's `GameService`: `create_game`, the two
seats, `start`, then `apply_action` for every answer and `resume` for
every step the bot owes, with the default `Batching()`. Every
`GameResult` is written down as the service handed it back, and the
final save beside it, byte for byte, in
`tests/golden/tnp_service_transcript.txt` and
`tnp_service_final_match.json`. Codex's `test_codex_golden.py` copied
(docs/design/tnp.md, "The golden").

**It pins the model's voice, tokens and all**: `{seat:blue}`,
`{unit:mercenary}`, `{area:14}` as the service says them, before any
frontend draws one. So:

- **a faithful change to rendering leaves it alone** -- the seat's
  player's name, the battle message, the pictures are all past the
  service and none of them is here;
- **a change to the model's wording, or to what the game does,
  re-records it** -- and the pull request that does so says it did, and
  shows the diff.

    FOOLBOT_UPDATE_GOLDEN=1 python3 -m unittest discover -s tests -p test_tnp_golden.py

rewrites the two files. The policy is `tests/tnp_games.py`'s, which
reads `PendingPrompt.options` and nothing else.

**Nothing hidden is written into it**: a prompt's options are never
described -- a plan prompt carries its seat's saved plan -- and the
test's own action lines leave out a plan's and a trade's contents, each
its seat's until the phase reveals it (TNP 5.2, 5.3, 5.9).

What it does not cover: a concession, an abandon or a rematch
(`tests/test_tnp_cog_ending.py`); a win at 51% harvested
(`test_tnp_driver_full_game`'s harvest game); and anything the cog
renders.
"""

from __future__ import annotations

import json
import unittest

from gamesaves.tnp.service import GameResult, GameService
from test_golden_transcript import GOLDEN_DIR, UPDATING, golden_diff, render_final_match
from test_tnp_driver_full_game import SEED, TURN_LIMIT
from tnp.engine import RulesEngine
from tnp.prompts import SIMULTANEOUS
from tnp_games import Raider, Turtle, answer

import random

TRANSCRIPT_FILE = GOLDEN_DIR / "tnp_service_transcript.txt"
FINAL_MATCH_FILE = GOLDEN_DIR / "tnp_service_final_match.json"
GOLDEN_SEED = SEED
#: More answers than the game takes to reach a fallen base.
MAX_ACTIONS = 5000


def describe(result: GameResult) -> list[str]:
    """One `GameResult` as lines: each closed group tagged with its step
    and part, what was still carried, the questions open and their
    asks. **Never a prompt's options.**"""
    lines: list[str] = []
    for group in result.groups:
        tag = group.step.name if group.step is not None else "caller"
        part = f" part {group.part}" if group.part is not None else ""
        lines.append(f"--- group {tag}{part}")
        lines.extend(group.lines)
    if result.narration:
        lines.append("--- narration")
        lines.extend(result.narration)
    for prompt in result.prompts:
        lines.append(f"--- prompt {prompt.kind.name} ({prompt.asked_seat})")
        lines.append(prompt.ask)
    if result.board_changed:
        lines.append("--- board changed")
    return lines


def action_line(number: int, action) -> str:
    """What was answered, as one line -- a plan's and a trade's contents
    left out, each its seat's alone until revealed."""
    hidden = action.kind in SIMULTANEOUS
    arguments = "(hidden)" if hidden else json.dumps(action.arguments, sort_keys=True, default=str)
    return f"=== action {number}: {action.kind.name} {action.choice!r} {action.seat} {arguments}"


def record_playthrough(seed: int = GOLDEN_SEED) -> tuple[str, dict]:
    """Play a whole basic game through the service; the transcript and
    the final save."""
    engine = RulesEngine(rng=random.Random(seed))
    games: dict = {}
    service = GameService(engine, games, save=lambda games: None)
    game = service.create_game(guild_id=1, game_number=1)
    service.take_seat(game.game_id, 1, "Blue's player", "blue")
    service.take_seat(game.game_id, 2, "Green's player", "green")
    strategies = {"blue": Raider(), "green": Turtle()}
    lines = ["=== start"]
    lines.extend(describe(service.start(game.game_id)))
    for number in range(1, MAX_ACTIONS + 1):
        match = service.load(game)
        if match.winner is not None:
            break
        assert match.turn <= TURN_LIMIT, "the game ran past its bound"
        prompts = service.prompts(game, match)
        if not prompts:
            found, result = service.resume(game.game_id)
            lines.append(f"=== resume: {found}")
            lines.extend(describe(result))
            continue
        prompt = prompts[0]
        action = answer(engine, match, strategies[prompt.asked_seat], prompt)
        lines.append(action_line(number, action))
        result = service.apply_action(game.game_id, action)
        assert not result.refused, f"{action} refused: {result.refusal}"
        lines.extend(describe(result))
    else:
        raise AssertionError("the game did not end in budget")
    return "\n".join(lines) + "\n", game.match_state


class TnpGoldenTests(unittest.TestCase):
    """A whole basic game through the service, byte for byte."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.transcript, cls.final_match = record_playthrough()

    def test_the_game_is_won_by_a_fallen_base(self) -> None:
        self.assertEqual((self.final_match["winner"], self.final_match["won_by"]), ("blue", "base"))

    def test_the_transcript_matches_the_golden(self) -> None:
        if UPDATING:
            TRANSCRIPT_FILE.write_text(self.transcript)
            self.skipTest("FOOLBOT_UPDATE_GOLDEN=1: transcript rewritten")
        recorded = TRANSCRIPT_FILE.read_text()
        if recorded != self.transcript:
            self.fail(
                "TNP's service no longer says what it used to. A faithful change to "
                "rendering cannot do this -- nothing rendered is here; a change to the "
                "model's wording or to the game does. If that is deliberate, regenerate "
                "with FOOLBOT_UPDATE_GOLDEN=1 and say so in the pull request, with the "
                "diff.\n\n" + golden_diff(recorded, self.transcript, "transcript")
            )

    def test_the_final_save_matches_the_golden(self) -> None:
        rendered = render_final_match(self.final_match)
        if UPDATING:
            FINAL_MATCH_FILE.write_text(rendered)
            self.skipTest("FOOLBOT_UPDATE_GOLDEN=1: final match rewritten")
        recorded = FINAL_MATCH_FILE.read_text()
        if recorded != rendered:
            self.fail(
                "TNP's final save is no longer what it was; regenerate with "
                "FOOLBOT_UPDATE_GOLDEN=1 if the change is deliberate, and say so.\n\n"
                + golden_diff(recorded, rendered, "final match")
            )

    def test_no_plan_or_trade_is_written(self) -> None:
        for line in self.transcript.splitlines():
            if line.startswith("=== action") and (" PLAN " in line or " TRADE " in line):
                self.assertTrue(line.endswith("(hidden)"), line)

    def test_two_runs_on_one_seed_agree(self) -> None:
        second, second_match = record_playthrough()
        self.assertEqual(second, self.transcript)
        self.assertEqual(second_match, self.final_match)


if __name__ == "__main__":
    unittest.main()

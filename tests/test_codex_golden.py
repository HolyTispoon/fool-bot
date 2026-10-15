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

rewrites the two files. The policy is `test_codex_driver_full_game.choose`
(through `answer`), which reads `PendingPrompt.options` and nothing else,
so what is pinned is what a frontend that reads only the result can
reach. `GOLDEN_SEED` is the
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
from codex.game import CodexGame
from codex.prompts import PromptKind
from gamesaves.codex.service import GameResult, GameService
from test_codex_driver_full_game import SEED, TURN_LIMIT, answer, numbered_seats
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
    # A two-headed dragon's team is asked one question a seat.
    for prompt in result.prompts or ((result.prompt,) if result.prompt is not None else ()):
        lines.append(f"--- prompt {prompt.kind.name} (player {prompt.asked_player})")
        lines.append(prompt.ask)
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


def record_playthrough(seed: int = GOLDEN_SEED, players=None, dragon=None) -> tuple[str, dict]:
    """Play a whole game through the service; return the transcript and
    the final save. `players`, a spec per seat, plays a free-for-all
    (docs/codex-multiplayer.md, step 2); `dragon`, four, a two-headed
    dragon (step 5), whose record the lobby cannot open until step 6 and
    is built here."""
    engine = RulesEngine(seed=seed)
    games: dict = {}
    service = GameService(engine, games, save=lambda games: None)
    if dragon is not None:
        game = CodexGame("codex-golden-dragon", 1, variant="two_headed_dragon")
        games[game.game_id] = game
        for user_id, name, spec in numbered_seats(dragon):
            service.take_seat(game.game_id, user_id, name, spec)
    else:
        game = service.create_game(guild_id=1, game_number=1)
        if players is None:
            service.take_seat(game.game_id, 101, "basher", "bashing")
            service.take_seat(game.game_id, 202, "fencer", "finesse")
        else:
            service.set_variant(game.game_id, "free_for_all")
            for user_id, name, spec in numbered_seats(players):
                service.take_seat(game.game_id, user_id, name, spec)
    lines = ["=== start"]
    result = service.start(game.game_id)
    lines.extend(describe(result))

    for step in range(MAX_ACTIONS):
        match = service.load(game)
        if match.winner is not None:
            break
        assert match.turn <= TURN_LIMIT, "the game ran past its bound"
        asked = service.waiting_all(game, match) if match.dragons else ()
        waiting = asked[step % len(asked)] if asked else (
            None if match.dragons else service.waiting_on(game, match))
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
        action = answer(engine, match, prompt)
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


#: The free-for-all's golden (docs/codex-multiplayer.md, step 2): three
#: players, Bashing, Finesse and Bashing, seeded, through the service.
FFA_TRANSCRIPT_FILE = GOLDEN_DIR / "codex_ffa_transcript.txt"
FFA_FINAL_MATCH_FILE = GOLDEN_DIR / "codex_ffa_final_match.json"
FFA_PLAYERS = ("bashing", "finesse", "bashing")
FFA_SEED = GOLDEN_SEED


class CodexFreeForAllGoldenTests(unittest.TestCase):
    """A seeded three-player game through the service, byte for byte --
    re-recorded with `FOOLBOT_UPDATE_GOLDEN=1` as the duel's is, and only
    for a change to the model's wording or the game."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.transcript, cls.final_match = record_playthrough(FFA_SEED, FFA_PLAYERS)

    def test_the_transcript_matches_the_golden(self) -> None:
        if UPDATING:
            FFA_TRANSCRIPT_FILE.write_text(self.transcript)
            self.skipTest("FOOLBOT_UPDATE_GOLDEN=1: transcript rewritten")
        recorded = FFA_TRANSCRIPT_FILE.read_text()
        if recorded != self.transcript:
            self.fail(
                "the free-for-all no longer says what it used to; regenerate with "
                "FOOLBOT_UPDATE_GOLDEN=1 if that is deliberate, and say so in the pull request.\n\n"
                + golden_diff(recorded, self.transcript, "transcript")
            )

    def test_the_final_match_matches_the_golden(self) -> None:
        rendered = render_final_match(self.final_match)
        if UPDATING:
            FFA_FINAL_MATCH_FILE.write_text(rendered)
            self.skipTest("FOOLBOT_UPDATE_GOLDEN=1: final match rewritten")
        recorded = FFA_FINAL_MATCH_FILE.read_text()
        if recorded != rendered:
            self.fail("the free-for-all ends on a different position.\n\n"
                      + golden_diff(recorded, rendered, "final match"))

    def test_the_game_ends_on_the_most_base_hp(self) -> None:
        self.assertEqual(self.final_match["variant"], "free_for_all")
        self.assertEqual(len(self.final_match["players"]), 3)
        self.assertIsNotNone(self.final_match["winner"])
        self.assertIn(" base HP: ", self.transcript)
        self.assertIn("--- prompt GAME_OVER", self.transcript)

    def test_nothing_hidden_is_written(self) -> None:
        for line in self.transcript.splitlines():
            if "hires a worker" in line or "tech card" in line:
                self.assertNotIn("{card:", line, line)
            if line.startswith("=== action") and ("TECH_CHOICE" in line or "'hire'" in line):
                self.assertTrue(line.endswith("(hidden)"), line)


#: The two-headed dragon's golden (docs/codex-multiplayer.md, step 5):
#: four players in two teams, Bashing and Finesse against the same,
#: seeded, through the service -- the transcript of a team's turn reads as
#: one turn with two players' actions in it.
DRAGON_TRANSCRIPT_FILE = GOLDEN_DIR / "codex_dragon_transcript.txt"
DRAGON_FINAL_MATCH_FILE = GOLDEN_DIR / "codex_dragon_final_match.json"
DRAGON_PLAYERS = (("bashing",), ("finesse",), ("bashing",), ("finesse",))
DRAGON_SEED = GOLDEN_SEED


class CodexDragonGoldenTests(unittest.TestCase):
    """A seeded dragon through the service, byte for byte -- re-recorded
    with `FOOLBOT_UPDATE_GOLDEN=1` as the others are, and only for a
    change to the model's wording or the game."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.transcript, cls.final_match = record_playthrough(DRAGON_SEED, dragon=DRAGON_PLAYERS)

    def test_the_transcript_matches_the_golden(self) -> None:
        if UPDATING:
            DRAGON_TRANSCRIPT_FILE.write_text(self.transcript)
            self.skipTest("FOOLBOT_UPDATE_GOLDEN=1: transcript rewritten")
        recorded = DRAGON_TRANSCRIPT_FILE.read_text()
        if recorded != self.transcript:
            self.fail(
                "the dragon no longer says what it used to; regenerate with "
                "FOOLBOT_UPDATE_GOLDEN=1 if that is deliberate, and say so in the pull request.\n\n"
                + golden_diff(recorded, self.transcript, "transcript")
            )

    def test_the_final_match_matches_the_golden(self) -> None:
        rendered = render_final_match(self.final_match)
        if UPDATING:
            DRAGON_FINAL_MATCH_FILE.write_text(rendered)
            self.skipTest("FOOLBOT_UPDATE_GOLDEN=1: final match rewritten")
        recorded = DRAGON_FINAL_MATCH_FILE.read_text()
        if recorded != rendered:
            self.fail("the dragon ends on a different position.\n\n"
                      + golden_diff(recorded, rendered, "final match"))

    def test_the_game_ends_on_a_destroyed_shared_base(self) -> None:
        self.assertEqual(self.final_match["variant"], "two_headed_dragon")
        self.assertEqual(self.final_match["dragons"], [[1, 2], [3, 4]])
        self.assertIsNotNone(self.final_match["winner"])
        self.assertIn("--- prompt GAME_OVER", self.transcript)
        self.assertIn("base is destroyed.", self.transcript)

    def test_a_teams_turn_is_one_turn_with_two_players_actions(self) -> None:
        """The first team turn: both players' upkeeps, both players'
        actions and one end of the turn, naming both."""
        first = self.transcript.split("**End of turn 1**")[0]
        names = [line for line in first.splitlines() if "collects" in line]
        self.assertEqual(len(names), 2)
        self.assertEqual(self.transcript.count("**End of turn 1**"), 1)

    def test_the_questions_are_asked_a_seat_each(self) -> None:
        self.assertIn("--- prompt MAIN_ACTION (player 1)", self.transcript)
        self.assertIn("--- prompt MAIN_ACTION (player 2)", self.transcript)

    def test_nothing_hidden_is_written(self) -> None:
        for line in self.transcript.splitlines():
            if "hires a worker" in line or "tech card" in line:
                self.assertNotIn("{card:", line, line)
            if line.startswith("=== action") and ("TECH_CHOICE" in line or "'hire'" in line):
                self.assertTrue(line.endswith("(hidden)"), line)

    def test_two_runs_on_one_seed_agree(self) -> None:
        second, second_match = record_playthrough(DRAGON_SEED, dragon=DRAGON_PLAYERS)
        self.assertEqual(second, self.transcript)
        self.assertEqual(second_match, self.final_match)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

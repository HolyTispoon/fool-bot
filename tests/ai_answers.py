"""
Asking the AI the way the service does -- the one shape a test of a
strategy's decision takes since step 7 of docs/architecture-migration.md.

The AI answers prompts (`AIStrategy.choose`), so a test of what Dinky
does in a position builds the position, reads the prompt off it with
the one chain (`d12ball.prompts.pending`) and asks `driver.ai_action`
for the answer -- exactly what `GameService.run` does at that point.
A test that called a `choose_*` method by hand was asserting a policy
the game might never put to it; this asserts the answer to the
question the game actually asks.
"""

from typing import Optional

from d12ball.components import MatchState
from d12ball.engine import RulesEngine
from d12ball.flow import driver
from d12ball.game import D12BallGame, GameStatus, Team
from d12ball.prompts import Action, PendingPrompt, pending_prompt


def solo_game(ai_home: bool = False, **overrides) -> D12BallGame:
    """
    A solo game record: player 1 is the human and player 2 the AI,
    visiting unless `ai_home`.
    """
    fields = dict(
        game_id="solo",
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=111,
        player_2_id=None,
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        home_player_number=2 if ai_home else 1,
        visiting_player_number=1 if ai_home else 2,
        status=GameStatus.IN_PROGRESS,
    )
    fields.update(overrides)
    return D12BallGame(**fields)


def asked(
    engine: RulesEngine, game: D12BallGame, match: MatchState,
) -> PendingPrompt:
    """What the match is waiting on, which must be a question."""
    prompt = pending_prompt(engine, game, match)
    assert prompt is not None, "nobody is asked anything here"
    return prompt


def ai_answer(
    engine: RulesEngine, game: D12BallGame, match: MatchState,
) -> Optional[Action]:
    """
    The AI's answer to what `match` is waiting on, or `None` where the
    question is not the AI's -- `driver.ai_action` over the one chain.
    """
    return driver.ai_action(engine, game, match, asked(engine, game, match))


def ai_answers(
    engine: RulesEngine, game: D12BallGame, match: MatchState,
) -> Action:
    """The AI's answer, which the position must put to it."""
    action = ai_answer(engine, game, match)
    assert action is not None, "the question is not the AI's"
    return action


def let_the_ai_answer(
    engine: RulesEngine, game: D12BallGame, match: MatchState,
) -> list[Action]:
    """
    Answer for the AI until the position is somebody else's, or the
    bot's, running what each answer starts through `driver.apply` --
    the loop `GameService.run` makes, for a test with no service.
    Returns the actions taken.
    """
    taken: list[Action] = []
    while True:
        prompt = pending_prompt(engine, game, match)
        if prompt is None:
            return taken
        action = driver.ai_action(engine, game, match, prompt)
        if action is None:
            return taken
        outcome = driver.apply(engine, game, match, action)
        assert not isinstance(outcome, driver.Refusal), outcome.reason
        taken.append(action)

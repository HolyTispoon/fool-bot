"""
What the model writes down for a frontend that talks over a wire.

Finding 10 of docs/web-app.md, and step 10 of
docs/architecture-migration.md: a `GameResult`, the `PendingPrompt`
inside it and a roll's numbers go out as JSON, and an `Action` comes
back. **This module imports no `discord` and no `aiohttp`**: what it
measures is the model's half of the web app, over the same fixtures
the bot's own prompts are measured on (`tests/prompt_fixtures.py`), so
a prompt the bot can put up is one a web page can render.

**It is testing a format with a consumer** (decision 3 of
docs/web-app-next.md, step 10): the web page reads exactly these
shapes -- its controls are built from `PendingPrompt.to_dict()`, its
log and its dice from `GameResult.to_dict()` -- so a field that goes
missing here is a control or a die that goes missing there.

Two things it is here to catch. A field added to a prompt, an option
or a group and left out of its `to_dict` -- every dataclass on the
wire is walked, not a sample. And a value that is not JSON reaching a
frontend as the repr of an object: `d12ball.wire.jsonable` raises for
one, and `json.dumps` over every fixture is what proves none gets
through.
"""

from __future__ import annotations

import dataclasses
import json
import typing
import unittest

from d12ball.components import TeamSide
from d12ball.engine import IgnitedRoll
from d12ball.flow import driver
from d12ball.flow.arrivals import MindPullRoll
from d12ball.flow.effects import OwnGoalRoll
from d12ball.flow.injuries import InjuryRoll
from d12ball.flow.rolls import ContestDice, ShotDice
from d12ball.game import Team
from d12ball.prompts import (
    Action,
    PendingPrompt,
    PromptKind,
    PromptOptions,
    pending_prompt,
)
from d12ball.wire import jsonable
from gamesaves.d12ball.service import GameResult, GameService, Narration
from prompt_fixtures import CASES, ENGINE, PromptFixture


def service_over(fixture: PromptFixture) -> GameService:
    """A service over one fixture that writes to nothing."""
    fixture.game.match_state = fixture.match.to_dict()
    return GameService(
        ENGINE, {fixture.game.game_id: fixture.game}, save=lambda games: None,
    )


class PromptWireTests(unittest.TestCase):
    """Every prompt the chain can hand back, written down."""

    def setUp(self) -> None:
        ENGINE.rng.seed(11)

    def test_every_prompt_is_json(self) -> None:
        for case in CASES:
            if not case.asked:
                continue
            with self.subTest(case.name):
                fixture = case.build()
                prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
                written = prompt.to_dict()

                json.dumps(written)
                self.assertEqual(written["kind"], prompt.kind.value)
                self.assertEqual(written["ask"], prompt.ask)
                self.assertEqual(
                    written["options"] is None, prompt.options is None,
                )

    def test_every_option_shape_names_itself(self) -> None:
        """
        A prompt's options say which shape they are, so a page that
        renders controls reads the kind *or* the tag and never guesses
        from the keys it happens to find.
        """
        seen = set()
        for case in CASES:
            if not case.asked:
                continue
            fixture = case.build()
            prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
            if prompt.options is None:
                continue
            with self.subTest(case.name):
                written = prompt.options.to_dict()
                self.assertIn("shape", written)
                seen.add(written["shape"])
        # The fixtures cover every kind the bot can put up, so this is
        # a floor on the shapes rather than a count of them.
        self.assertGreaterEqual(len(seen), 10)

    def test_every_options_dataclass_can_be_written_down(self) -> None:
        """
        `PromptOptions` is the union a prompt may carry; a member
        added without a `to_dict` fails here rather than on the one
        request that reaches it.
        """
        for shape in typing.get_args(PromptOptions):
            with self.subTest(shape.__name__):
                self.assertTrue(
                    callable(getattr(shape, "to_dict", None)),
                    f"{shape.__name__} has no to_dict",
                )

    def test_every_field_of_a_prompt_is_on_the_wire(self) -> None:
        written = PendingPrompt(PromptKind.GAME_OVER, "over").to_dict()
        for field in dataclasses.fields(PendingPrompt):
            self.assertIn(field.name, written)


class ActionWireTests(unittest.TestCase):
    """The one thing a frontend sends back."""

    def test_an_action_round_trips(self) -> None:
        action = Action(
            PromptKind.COACHING_HUB,
            "reposition",
            {"side": TeamSide.HOME, "player_id": "p1", "space_index": 2},
        )
        written = json.loads(json.dumps(action.to_dict()))

        read = Action.from_dict(written)

        self.assertIs(read.kind, PromptKind.COACHING_HUB)
        self.assertEqual(read.choice, "reposition")
        # The side went out as the string it is worth and came back as
        # one: what it means is the adapter's, not the wire's.
        self.assertEqual(
            read.arguments,
            {"side": "home", "player_id": "p1", "space_index": 2},
        )

    def test_a_kind_off_the_wire_is_the_member_it_names(self) -> None:
        """
        The whole point of `from_dict`: a kind left as a string is not
        the member the prompt is compared to, so every such action
        would be refused as a stale click.
        """
        read = Action.from_dict({"kind": "player_action"})

        self.assertIs(read.kind, PromptKind.PLAYER_ACTION)
        self.assertEqual(read.choice, "")
        self.assertEqual(read.arguments, {})

    def test_a_kind_the_game_does_not_have_is_refused_at_the_door(self) -> None:
        with self.assertRaises(ValueError):
            Action.from_dict({"kind": "not_a_prompt"})


class DetailWireTests(unittest.TestCase):
    """A roll's numbers, for the frontend that draws no dice."""

    def test_a_contest_carries_both_sides_and_its_ignites(self) -> None:
        dice = ContestDice(
            contestants=[
                (7, Team.ORANGE, ["+2 Midfielder"], 9, False, [("p1", 2)]),
                (4, Team.PURPLE, [], 4, True, []),
            ],
            ignites=(("p1", IgnitedRoll(7, 9, 9, True)),),
        )

        written = json.loads(json.dumps(dice.to_dict()))

        self.assertEqual(written["shape"], "contest")
        self.assertEqual(written["contestants"][0]["total"], 9)
        self.assertEqual(written["contestants"][1]["team"], "purple")
        self.assertEqual(written["ignites"][0]["ignite"]["second"], 9)

    def test_a_shot_says_whether_it_went_in(self) -> None:
        written = ShotDice([], scored=True, shooter_id="p1").to_dict()

        self.assertEqual(written["shape"], "shot")
        self.assertTrue(written["scored"])
        self.assertEqual(written["shooter_id"], "p1")

    def test_the_single_die_rolls_are_json(self) -> None:
        for detail in (
            OwnGoalRoll((3, 9), 2, True, 0),
            MindPullRoll("p1", 8, True, None),
            InjuryRoll("p1", 4, False, 3),
        ):
            with self.subTest(type(detail).__name__):
                json.dumps(detail.to_dict())

    def test_a_mind_pull_carries_the_band_its_die_names(self) -> None:
        # The web app draws the die off the wire, so the band is worded
        # once, by the model, rather than again at the other end.
        self.assertIsNone(
            MindPullRoll("p1", 8, True, None).to_dict()["target_label"],
        )
        self.assertEqual(
            MindPullRoll("p1", 8, True, None, minimum=8).to_dict()[
                "target_label"
            ],
            "pulls on 8+",
        )


class ResultWireTests(unittest.TestCase):
    """What one call to the service looks like over a wire."""

    def setUp(self) -> None:
        ENGINE.rng.seed(11)

    def test_a_result_off_a_real_run_is_json(self) -> None:
        for case in CASES:
            if not case.asked or case.ai:
                continue
            with self.subTest(case.name):
                fixture = case.build()
                service = service_over(fixture)

                _, result = service.resume(fixture.game.game_id)

                json.dumps(result.to_dict())

    def test_the_position_is_left_out_unless_it_is_asked_for(self) -> None:
        """
        A result is what one person is shown, and the match holds what
        the game keeps from them -- see `GameResult.to_dict`.
        """
        fixture = CASES[0].build()
        service = service_over(fixture)

        _, result = service.resume(fixture.game.game_id)

        self.assertIsNotNone(result.match)
        self.assertIsNone(result.to_dict()["match"])
        self.assertEqual(
            result.to_dict(match=True)["match"], result.match.to_dict(),
        )

    def test_a_refusal_carries_what_the_match_is_waiting_on(self) -> None:
        fixture = CASES[0].build()
        service = service_over(fixture)
        # A question this position is not being asked.
        refused = service.apply_action(
            fixture.game.game_id, Action(PromptKind.SHOOTOUT_TEST, "roll"),
        )

        written = json.loads(json.dumps(refused.to_dict()))

        self.assertIsNotNone(written["refusal"])
        self.assertIsNotNone(written["waiting_on"])
        self.assertEqual(written["prompt"], None)

    def test_a_group_carries_its_step_and_what_it_said(self) -> None:
        written = Narration(
            ("A line.",),
            step=driver.FollowOnStep.BEGIN_LOOSE_BALL,
            board={"spaces": []},
            arguments={"side": TeamSide.HOME},
            prompt=PromptKind.PLAYER_ACTION,
            action=Action(PromptKind.PLAYER_ACTION, "maneuver"),
        ).to_dict()

        self.assertEqual(written["step"], "BEGIN_LOOSE_BALL")
        self.assertEqual(written["arguments"], {"side": "home"})
        self.assertEqual(written["prompt"], "player_action")
        self.assertEqual(written["action"]["choice"], "maneuver")

    def test_every_field_of_a_group_is_on_the_wire(self) -> None:
        written = Narration(()).to_dict()
        for field in dataclasses.fields(Narration):
            self.assertIn(field.name, written)

    def test_every_field_of_a_result_is_on_the_wire(self) -> None:
        written = GameResult().to_dict()
        for field in dataclasses.fields(GameResult):
            self.assertIn(field.name, written)


class JsonableTests(unittest.TestCase):
    """The one conversion, and what it refuses."""

    def test_the_model_s_own_values_come_through(self) -> None:
        self.assertEqual(jsonable(TeamSide.HOME), "home")
        self.assertEqual(jsonable({"a": (1, 2)}), {"a": [1, 2]})
        self.assertEqual(jsonable(frozenset({"b", "a"})), ["a", "b"])
        self.assertEqual(jsonable(IgnitedRoll(3))["face"], 3)

    def test_something_that_is_not_json_raises_rather_than_reprs(self) -> None:
        with self.assertRaises(TypeError):
            jsonable(object())

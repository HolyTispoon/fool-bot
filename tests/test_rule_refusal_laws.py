"""
A refusal cites its Law -- `RuleRefusal.law`, proposed on step 10 of
docs/web-app-redesign.md as a model change of its own.

- **Every Law a raise site names is a heading the living rules have**,
  read the way `/d12ball rules_search` reads them (`rules_doc`), so a
  heading renamed upstream fails here rather than leaving a page linking
  nowhere. The slugs are read off the source, since a raise site that is
  never reached by a test is still one a coach can reach.
- **The citation travels the one door**: a step's `RuleRefusal` comes
  back from `driver.answer` as a `Refusal` carrying it, and out of the
  service as `GameResult.refusal_law`, on the wire beside the sentence.
- **Nothing else changes**: the sentence is the same string, and a
  refusal that names no Law cites none.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest import mock

from d12ball.components import RuleRefusal
from d12ball.flow import driver
from d12ball.prompts import Action, PromptKind, pending_prompt
from d12ball.rules_doc import load_rules_document
from gamesaves.d12ball.service import GameResult
from prompt_fixtures import CASES, ENGINE

ROOT = Path(__file__).resolve().parent.parent
MODEL = (ROOT / "d12ball", ROOT / "gamesaves" / "d12ball")


def cited_laws() -> dict[str, list[str]]:
    """Every `law="..."` a `RuleRefusal` or `_refuse` is raised with in
    the model, by slug, with where."""
    cited: dict[str, list[str]] = {}
    for folder in MODEL:
        for path in sorted(folder.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "id", None)
                if name not in ("RuleRefusal", "_refuse"):
                    continue
                for keyword in node.keywords:
                    if keyword.arg != "law":
                        continue
                    if isinstance(keyword.value, ast.Name):
                        # `_refuse` handing its own argument on.
                        continue
                    if not isinstance(keyword.value, ast.Constant):
                        raise AssertionError(
                            f"{path}:{node.lineno}: a Law is written as "
                            "a literal slug, so it can be checked here."
                        )
                    cited.setdefault(keyword.value.value, []).append(
                        f"{path.relative_to(ROOT)}:{node.lineno}"
                    )
    return cited


class CitedLawTests(unittest.TestCase):
    def test_every_cited_law_is_a_heading_of_the_living_rules(self) -> None:
        cited = cited_laws()
        self.assertTrue(cited, "no raise site cites a Law")
        headings = {section.slug for section in load_rules_document().sections}
        for slug, where in sorted(cited.items()):
            with self.subTest(slug):
                self.assertIn(slug, headings, where)

    def test_the_sentence_is_unchanged_and_the_law_optional(self) -> None:
        cited = RuleRefusal("No.", law="winning-the-toss")
        self.assertEqual(str(cited), "No.")
        self.assertEqual(cited.law, "winning-the-toss")
        self.assertIsNone(RuleRefusal("No.").law)
        self.assertIsInstance(cited, ValueError)


class CitationTravelsTests(unittest.TestCase):
    def fixture(self):
        return next(case for case in CASES if case.name == "smooth").build()

    def test_a_step_s_citation_comes_back_on_the_refusal(self) -> None:
        fixture = self.fixture()
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        refusing = RuleRefusal("Not that one.", law="the-two-nearest")

        def refuse(*args, **kwargs):
            raise refusing

        # The answer is replaced by one that refuses, and the two checks
        # before it let the made-up choice through: what is watched is
        # the door, not a rule.
        with mock.patch.dict(driver.ANSWERS, {prompt.kind: refuse}), \
                mock.patch.object(
                    driver, "_choice_is_offered", return_value=True,
                ), mock.patch.object(
                    driver, "_argument_mismatch", return_value=None,
                ):
            refused = driver.answer(
                ENGINE, fixture.game, fixture.match, Action(prompt.kind, "x"),
            )
        self.assertIsInstance(refused, driver.Refusal)
        self.assertEqual(refused.reason, "Not that one.")
        self.assertEqual(refused.law, "the-two-nearest")

    def test_the_driver_s_own_refusals_cite_nothing(self) -> None:
        fixture = self.fixture()
        refused = driver.answer(
            ENGINE, fixture.game, fixture.match,
            Action(PromptKind.SHOOTOUT_TEST, "roll"),
        )
        self.assertIsInstance(refused, driver.Refusal)
        self.assertIsNone(refused.law)

    def test_the_wire_carries_it_beside_the_sentence(self) -> None:
        written = GameResult(
            refusal="No.", refusal_law="winning-the-toss",
        ).to_dict()
        self.assertEqual(written["refusal"], "No.")
        self.assertEqual(written["refusal_law"], "winning-the-toss")
        self.assertIsNone(GameResult().to_dict()["refusal_law"])


if __name__ == "__main__":
    unittest.main()

"""
A rule reads a role through `RulesEngine.role_of`, never off the card.

In 1.0 a player's role is their card's; in 2.0 it is the formation's,
assigned by the coach (docs/rules-2.1.md, section 4). The two can only
be told apart in one place, so every rule that asks "which role is
this card playing" asks `role_of` -- or `has_role_ability`, which
asks it -- and nothing in the rules reads `PlayerDefinition.role`
itself. See "Roles" in docs/design/maneuver-deck.md.

This is a ratchet on something already true, the way
`test_model_purity.py` is: it walks the modules that decide rules and
fails on any attribute read named `role`, outside the few that are
allowed and say why.
"""

import ast
import pathlib
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
D12BALL = PROJECT_ROOT / "d12ball"

# The modules that decide rules or answer for a coach. The printed
# things (cards, boards, the box, the rulebooks' figures), the renderer
# and `formatting.py` draw and word a role rather than deciding by it.
RULE_MODULES = (
    D12BALL / "engine.py",
    D12BALL / "prompts.py",
    D12BALL / "ai.py",
    D12BALL / "dice_brief.py",
    *sorted((D12BALL / "flow").glob("*.py")),
)

# (module, function) pairs allowed to read `.role`, each with its reason.
ALLOWED = {
    # The one reading.
    ("engine.py", "role_of"),
    # Dinky's substitute choice ranks the bench by the skill profile
    # each card is printed with -- a card's scores, which 2.0 keeps --
    # not by the role anybody is playing.
    ("ai.py", "role_rank"),
}


def role_reads(path: pathlib.Path) -> list[tuple[str, int]]:
    """Every `<expr>.role` load in a module, as (enclosing function, line)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []

    def walk(node, function):
        for child in ast.iter_child_nodes(node):
            name = function
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = child.name
            if (
                isinstance(child, ast.Attribute)
                and child.attr == "role"
                and isinstance(child.ctx, ast.Load)
            ):
                found.append((function, child.lineno))
            walk(child, name)

    walk(tree, "<module>")
    return found


class RoleReadingTests(unittest.TestCase):
    def test_no_rule_reads_a_role_off_the_card(self) -> None:
        offenders = [
            f"{path.relative_to(PROJECT_ROOT)}:{line} in {function}"
            for path in RULE_MODULES
            for function, line in role_reads(path)
            if (path.name, function) not in ALLOWED
        ]
        self.assertEqual(
            offenders, [],
            "Ask RulesEngine.role_of / has_role_ability instead of "
            "reading PlayerDefinition.role.",
        )

    def test_the_allowed_readers_still_exist(self) -> None:
        """An allowance for a function that has gone is a hole."""
        present = {
            (path.name, function)
            for path in RULE_MODULES
            for function, _ in role_reads(path)
        }
        self.assertEqual(ALLOWED - present, set())


if __name__ == "__main__":
    unittest.main()

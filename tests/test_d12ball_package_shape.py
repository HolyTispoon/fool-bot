"""
What has to stay true about the shape of `cogs/d12ball_views`.

The package replaced one 6,531-line module, and the two things that
would quietly undo that are a name going missing from the re-export --
which breaks an import nobody notices until that view is reached -- and
a cycle between submodules, which breaks the whole package on import.
Neither is visible in a test of any one view.
"""

import ast
import importlib
import os
import pkgutil
import unittest
from pathlib import Path

import cogs.d12ball_views as views
from cogs.d12ball import D12Ball
from d12ball.flow.result import FollowOnStep
from d12ball.flow import driver
from save_patches import (
    LINKING_COG_MODULES,
    SAVING_COG_MODULES,
    SAVING_MODULES,
    SAVING_VIEW_MODULES,
    refuse_stray_save,
    suppressed_cog_saves,
)

PACKAGE = Path(views.__file__).parent
SUBMODULES = sorted(
    m.name for m in pkgutil.iter_modules([str(PACKAGE)])
)


def own_python_files(root: Path) -> list:
    """
    Every `.py` under `root` that belongs to *this* checkout.

    A directory holding a `.git` entry is a checkout of its own -- a
    clone carries a `.git` directory and a linked worktree a `.git`
    file -- and the desktop app puts its worktrees under
    `.claude/worktrees/`, inside the repository. `Path.glob("**/*.py")`
    walked into one and read a second copy of every module against
    exemptions written for this checkout's paths: `d12ball/render.py`
    was exempt and `.claude/worktrees/x/d12ball/render.py` was an
    offender, so the guards below failed on `main` for as long as a
    worktree sat there. Pruning on the `.git` entry rather than on the
    `.claude` name is what covers a checkout nested anywhere else too.
    """
    found = []
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = sorted(
            name for name in subdirectories
            if name != ".git"
            and not (Path(directory) / name / ".git").exists()
        )
        found.extend(
            Path(directory) / name for name in sorted(files)
            if name.endswith(".py")
        )
    return found


class ViewsPackageTests(unittest.TestCase):
    def test_every_public_name_is_re_exported(self) -> None:
        """
        `from cogs.d12ball_views import X` has to keep working for
        every X the single module used to hold, which is what let the
        split move no call site.
        """
        for module in SUBMODULES:
            mod = importlib.import_module(f"cogs.d12ball_views.{module}")
            for name, value in vars(mod).items():
                if name.startswith("_") or getattr(value, "__module__", "") != mod.__name__:
                    continue
                with self.subTest(module=module, name=name):
                    self.assertIs(getattr(views, name, None), value)
                    self.assertIn(name, views.__all__)

    def test_the_package_is_a_dag(self) -> None:
        """
        A cycle between two submodules is an ImportError for the whole
        package, so it cannot be left to be found by whoever imports it
        next. `base` is the one every other module may lean on.
        """
        edges: dict[str, set[str]] = {}
        for module in SUBMODULES:
            tree = ast.parse((PACKAGE / f"{module}.py").read_text())
            edges[module] = {
                node.module.rsplit(".", 1)[-1]
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                and (node.module or "").startswith("cogs.d12ball_views.")
            }

        self.assertEqual(edges.get("base"), set(), "base may import no sibling")

        seen: set[str] = set()

        def visit(node: str, path: tuple[str, ...]) -> None:
            self.assertNotIn(node, path, f"import cycle: {' -> '.join(path + (node,))}")
            if node in seen:
                return
            seen.add(node)
            for nxt in edges.get(node, ()):
                visit(nxt, path + (node,))

        for module in SUBMODULES:
            visit(module, ())

    def test_every_saving_submodule_is_patched_in_tests(self) -> None:
        """
        `suppressed_view_saves` names the submodules that call
        `save_games` themselves. A view moving into a module not on
        that list would write `data/d12ball_games.json` during the
        suite -- and pass, because not one of those forty-odd patches
        is ever asserted on. See tests/view_patches.py.
        """
        saving = {
            f"cogs.d12ball_views.{module}"
            for module in SUBMODULES
            if "save_games" in vars(
                importlib.import_module(f"cogs.d12ball_views.{module}")
            )
        }
        self.assertEqual(saving, set(SAVING_VIEW_MODULES))


if __name__ == "__main__":
    unittest.main()


class CogPackageTests(unittest.TestCase):
    """
    `cogs/d12ball` is six mixins assembled into one class, so the two
    things that would go wrong quietly are a method defined in two of
    them -- where the MRO silently picks one -- and a mixin that starts
    saving without being named in `save_patches`.
    """

    MIXINS = (
        "core", "effects", "turnovers", "periods",
        "presentation", "slash_commands",
    )

    def test_no_method_is_defined_by_two_mixins(self) -> None:
        """
        The mixin order is the order the single file read in and is
        meant to carry no resolution. A name in two of them means one
        of the two is dead, and which one is decided by the MRO rather
        than by anybody.
        """
        seen: dict[str, str] = {}
        for module in self.MIXINS:
            mod = importlib.import_module(f"cogs.d12ball.{module}")
            cls = next(
                value for name, value in vars(mod).items()
                if name.endswith("Mixin")
            )
            for name, value in vars(cls).items():
                if name.startswith("__") or not callable(value):
                    continue
                with self.subTest(method=name):
                    self.assertNotIn(
                        name, seen,
                        f"{name} is defined by both {seen.get(name)} "
                        f"and {module}",
                    )
                seen[name] = module

    def test_every_saving_mixin_is_patched_in_tests(self) -> None:
        """
        The same silent failure the views have: a suppression patch
        that no longer intercepts leaves the real save writing
        `data/d12ball_games.json` while the test goes on passing.
        """
        saving = {
            f"cogs.d12ball.{module}"
            for module in self.MIXINS
            if "save_games" in vars(
                importlib.import_module(f"cogs.d12ball.{module}")
            )
        }
        self.assertEqual(saving, set(SAVING_COG_MODULES))

    def test_every_description_discord_is_sent_fits(self) -> None:
        """
        Discord refuses a description over 100 characters with a 400,
        and `tree.sync()` raises it out of `setup_hook` -- so the bot
        does not start at all. The group's own description is the one
        nobody writes deliberately: discord.py falls back to the class
        docstring for it, which is how the package split broke a
        startup that had been fine for as long as the class had no
        docstring to fall back to.
        """
        import cogs.d12ball as pkg

        def walk(command, path: str):
            yield path, command.description
            for child in getattr(command, "commands", ()):
                yield from walk(child, f"{path} {child.name}")
            for parameter in getattr(command, "parameters", ()):
                yield f"{path}:{parameter.name}", parameter.description

        descriptions = [("d12ball", pkg.D12Ball.__cog_group_description__)]
        for command in pkg.D12Ball.__cog_app_commands__:
            descriptions.extend(walk(command, f"d12ball {command.name}"))

        for name, description in descriptions:
            with self.subTest(command=name):
                self.assertTrue(description)
                self.assertLessEqual(len(description), 100)

    def test_the_cog_is_assembled_from_exactly_those_mixins(self) -> None:
        """
        A mixin added to the package but left out of the class is a
        module of dead code that imports and tests clean.
        """
        import cogs.d12ball as pkg

        bases = [
            base.__name__ for base in pkg.D12Ball.__mro__
            if base.__name__.endswith("Mixin")
        ]
        self.assertEqual(len(bases), len(self.MIXINS))


class FollowOnStepTests(unittest.TestCase):
    """
    `FollowOnStep` is the record of where one step ends and the next
    begins -- see `d12ball/flow/result.py`. Every member is run by
    `d12ball.flow.driver` since Phase 6 of docs/design/model-discord-split.md
    collapsed the cog's own dispatch table, so what is in it is
    asserted here, once, rather than inside any one rank's own tests.
    """

    #: Every step of a turn that is named rather than called inline.
    #:
    #: A step is named rather than called where the frontend has
    #: something to decide at the boundary -- a message of its own, a
    #: picture, a board to put up before anything else moves -- or
    #: where the caller is already on the far side of a prompt. A
    #: phase that hands off to a new step adds its member here and a
    #: row to `driver.MODEL_STEPS`.
    EXPECTED = {
        # Phase 3's.
        "FINISH_MANEUVER_RESOLUTION",
        "OFFER_SCORING_ATTEMPT_CHOICE",
        "OFFER_SPEED_CHOICE",
        "BEGIN_RUN_BACK",
        "BEGIN_SHOOTER_CHOICE",
        "BEGIN_OWN_GOAL_ROLL",
        "BEGIN_LOOSE_BALL",
        "OFFER_SETUP_PASS_PUSH_BACK",
        "BEGIN_HIGH_PASS_CONTEST",
        # Phase 4's. The enum grew rather than shrank, which is the
        # honest reading of the phase: the spine's decisions moved and
        # the frontend edges they end on are named.
        "SEND_TURN_PROMPT",
        "START_SET_UP_SHOT",
        "CONTINUE_RUN_BACK",
        "RESOLVE_LOOSE_BALL",
        "ANNOUNCE_RUN_BACK",
        "FINISH_RUN_BACK",
        "APPLY_BALL_RECOVERY",
        # The front half of a turn.
        "BEGIN_MANEUVER_ACTION_SELECTION",
        "SEND_MANEUVER_ACTION_PROMPT",
        "RESOLVE_MANEUVER",
        "BEGIN_EFFECT_RESOLUTION",
        "CONTINUE_EFFECT",
        "BEGIN_MANEUVER_SKILL_TEST",
        # Phase 5's.
        "END_PERIOD",
        "BEGIN_SUBSTITUTION_WINDOW",
        "FINISH_SETUP_COACHING",
        "FINISH_HALFTIME",
        "ANNOUNCE_GAME_OVER",
        # Phase 6's third increment: three callers crossed the seam
        # ahead of the thing they called.
        "CONTINUE_SHOOTOUT",
        "AUTO_RESOLVE_CHALLENGER",
        "FINISH_SUBSTITUTION_WINDOW",
        # Phase 6's last increment: the turn prompt is two steps,
        # because the tutorial's Continue gate needs a continuation
        # that does not stage the beat a second time -- see
        # `d12ball/flow/gates.py`.
        "START_TURN",
        # Step 5 of docs/architecture-migration.md: the steps the bot
        # owes on a position nobody is asked anything on, named by
        # `d12ball.prompts.owed_step` and run by `GameService.resume`.
        # Step 7 took `RUN_AI_COACHING_WINDOW` back out: an AI side's
        # window is a prompt it answers through the service.
        "ADVANCE_SETUP_STAGE",
        "ADVANCE_HALFTIME_STAGE",
        "ADVANCE_FULL_TIME_STAGE",
        "FINISH_TIME_OUT",
        "BEGIN_BALL_RECOVERY",
    }

    def test_the_enum_holds_exactly_the_steps_recorded_here(self) -> None:
        self.assertEqual(
            {member.name for member in FollowOnStep}, self.EXPECTED,
        )

    def test_the_driver_runs_every_member(self) -> None:
        """
        A member with no row raises a `KeyError` in the middle of a
        turn, one card at a time, so the table is asserted to cover
        the enum **exactly** rather than merely to contain it. There is
        one table since Phase 6 collapsed `D12Ball.follow_on_methods`:
        a second one would be two answers to what happens next, which
        is the failure this whole split is against.
        """
        self.assertEqual(set(driver.MODEL_STEPS), set(FollowOnStep))
        self.assertFalse(hasattr(D12Ball, "follow_on_methods"))


class StraySaveGuardTests(unittest.TestCase):
    """
    What keeps the suppression helpers from being quietly optional.

    A patch on the wrong binding is invisible: it applies, the test
    passes, and the real `save_games` writes
    `data/d12ball_games.json` underneath it -- which is a developer's
    own saved games, since `PROJECT_ROOT` is resolved per checkout.
    Nineteen call sites were doing exactly that, on `main`, and
    nothing in the suite said so. `save_patches.guard_stray_saves`
    makes it raise instead; these are what stop the guard itself
    going missing.
    """

    def test_every_module_that_saves_is_named_in_saving_modules(self) -> None:
        """
        The guard arms a list, so a binding the list does not name is
        a binding the guard cannot see -- and `cogs/debug.py` is the
        reminder that they are not all in the two packages.
        """
        binding = {
            path
            for path in (
                *own_python_files(Path("cogs")),
                *own_python_files(Path("gamesaves")),
            )
            if path.name != "storage.py" and "save_games" in vars(
                importlib.import_module(
                    str(path.with_suffix("")).replace("/", ".")
                )
            )
        }
        named = {
            Path(module.replace(".", "/")).with_suffix(".py")
            for module in SAVING_MODULES
        }
        self.assertEqual(binding, named)

    def test_the_guard_is_armed_on_every_one_of_them(self) -> None:
        """
        Importing `save_patches` is what arms it. A test module that
        never imports it is still covered, because `unittest discover`
        imports every module before running any test -- but only for
        as long as the call at the foot of that file is there.
        """
        for module in SAVING_MODULES:
            with self.subTest(module=module):
                self.assertIs(
                    vars(importlib.import_module(module))["save_games"],
                    refuse_stray_save,
                )

    def test_a_suppression_helper_puts_the_guard_back(self) -> None:
        """
        `mock.patch` restores what it replaced, which is what lets the
        guard survive the four hundred-odd suppressions in the suite.
        """
        module = importlib.import_module(SAVING_COG_MODULES[0])
        with suppressed_cog_saves():
            self.assertIsNot(vars(module)["save_games"], refuse_stray_save)
        self.assertIs(vars(module)["save_games"], refuse_stray_save)

    def test_an_unsuppressed_save_raises_where_it_happens(self) -> None:
        """
        The point of the whole thing: the failure names the test that
        owes the suppression, rather than being found by a script
        months later.
        """
        module = importlib.import_module(SAVING_COG_MODULES[0])
        with self.assertRaises(AssertionError) as caught:
            vars(module)["save_games"]({})
        self.assertIn("suppressed_cog_saves", str(caught.exception))

    def test_every_mixin_that_links_is_named_in_linking_modules(self) -> None:
        """
        `suppressed_full_image_links` patches a list of bindings, and
        `mock.patch` of a name a module does not bind raises rather
        than doing nothing -- so a mixin dropping its last
        `add_full_image_button` call breaks every test that suppresses
        one, and a mixin gaining a call is an unsuppressed Discord
        edit. Either way the list has to track the imports, which is
        what this reads.
        """
        binding = {
            module
            for module in SAVING_COG_MODULES
            if "add_full_image_button" in vars(
                importlib.import_module(module)
            )
        }
        self.assertEqual(binding, set(LINKING_COG_MODULES))

    def test_the_storage_module_itself_is_left_alone(self) -> None:
        """
        `tests/test_game_storage.py` is the one place that means to
        reach the disk, and it goes through `storage.save_games` with
        `GAMES_FILE` pointed at a tempdir. Arming that would break the
        tests for the thing being guarded.
        """
        from gamesaves.d12ball import storage

        self.assertIsNot(storage.save_games, refuse_stray_save)


class NamingAPlayerTests(unittest.TestCase):
    """
    **A player is never named without their role** -- see "Naming a
    player" in docs/design/naming-and-wording.md. `player_with_role` is the whole of the
    `Hellguard [FB]` spelling and `format_role_bracket` is that with
    the team emoji in front; nothing else may build either by hand.

    The rule arrived because the run back's own player buttons were
    the one place in the game that named a card and left the role off,
    and it was invisible precisely because every *other* site spelled
    the brackets out for itself -- nine copies, so no one of them
    looked like the odd one out.
    """

    # Where the initials are a drawn glyph rather than a name: the
    # meeple tokens, the card header badges and the printed cards.
    # Those are pictures of a role, not a player's name, and they are
    # measured and placed rather than interpolated.
    DRAWING_MODULES = ("d12ball/render.py", "d12ball/cards.py",
                       "d12ball/player_cards.py", "d12ball/boards.py",
                       "d12ball/species_cards.py")

    def test_only_the_formatter_spells_the_role_brackets(self) -> None:
        """
        A second implementation of `{name} [{ROLE}]` is how the two
        drift: the sweep that added the role to the run back's buttons
        is only permanent if there is one place left to change.
        """
        offenders = []
        for path in own_python_files(Path(".")):
            text = path.as_posix()
            if (
                text.startswith("tests/")
                or text in self.DRAWING_MODULES
                or text == "d12ball/formatting.py"
            ):
                continue
            source = path.read_text()
            if "ROLE_INITIALS[" in source:
                offenders.append(text)

        self.assertEqual(
            offenders, [],
            "These read ROLE_INITIALS directly. Use "
            "formatting.player_with_role (or role_brackets for the "
            "text a token falls back to) so the spelling has one home.",
        )

    def test_the_roster_form_is_the_button_form(self) -> None:
        """
        There is one spelling, and `format_roster_player` is it for a
        caller holding a card id. It printed the role in parentheses
        until 2026-09-16 -- a second form of the same thing, which
        collided with whatever each caller put after it.
        """
        from d12ball.components import (
            load_basic_ruleset,
            load_maneuver_catalog,
            load_player_catalog,
        )
        from d12ball.engine import RulesEngine
        from d12ball.formatting import player_with_role
        from d12ball.game import Team

        catalog = load_player_catalog()
        engine = RulesEngine(
            catalog, load_basic_ruleset(), load_maneuver_catalog(), {},
        )
        player = catalog.teams[Team.ORANGE].players[0]

        self.assertEqual(
            engine.format_roster_player(player.player_id),
            player_with_role(player),
        )
        # The team is the only thing the wider form adds, and it is
        # the one thing left in parentheses.
        self.assertEqual(
            engine.format_roster_player_with_team(
                player.player_id, Team.ORANGE,
            ),
            f"{player_with_role(player)} (Orange)",
        )

    def test_the_message_form_is_the_button_form_plus_the_emoji(
        self,
    ) -> None:
        """
        The two differ by the team mark and the badge and by nothing
        else, which is what lets "outside a button, a player also
        carries their team emoji" be one rule rather than two
        formatters agreeing by hand. The message form is tokens, and
        Discord with nothing uploaded draws them as the circle and
        the brackets.
        """
        from cogs.d12ball_helpers import DiscordTokens
        from d12ball.components import (
            load_basic_ruleset,
            load_maneuver_catalog,
            load_player_catalog,
        )
        from d12ball.engine import RulesEngine
        from d12ball.formatting import player_with_role
        from d12ball.game import Team

        catalog = load_player_catalog()
        engine = RulesEngine(
            catalog, load_basic_ruleset(), load_maneuver_catalog(), {},
        )
        player = catalog.teams[Team.ORANGE].players[0]
        plain = player_with_role(player)

        class FakeMatch:
            def team_for_player(self, player_id: str) -> Team:
                return Team.ORANGE

        self.assertTrue(plain.endswith("]"))
        self.assertIn(player.name, plain)
        message = engine.format_player_label(FakeMatch(), player)
        self.assertEqual(
            message,
            f"{{team:orange}} {player.name} {{role:{player.role.value}:orange}}",
        )
        self.assertEqual(
            DiscordTokens({}, {}, {}, {}).render(message), f"🟠 {plain}",
        )

    def test_a_message_writes_the_role_emoji_and_a_button_the_brackets(
        self,
    ) -> None:
        """
        The role badge is an application emoji, and custom emoji render
        in exactly one of the places a player is named: a message. A
        button label and an autocomplete choice show the raw
        `<:...:>`, so the plain form keeps the brackets whatever has
        been uploaded, and only the message forms carry the token the
        badge is drawn from.
        """
        from cogs.d12ball_helpers import DiscordTokens
        from d12ball.components import (
            load_basic_ruleset,
            load_maneuver_catalog,
            load_player_catalog,
        )
        from d12ball.engine import RulesEngine
        from d12ball.formatting import player_with_role, role_initials
        from d12ball.game import Team

        catalog = load_player_catalog()
        engine = RulesEngine(
            catalog, load_basic_ruleset(), load_maneuver_catalog(), {},
        )
        player = catalog.teams[Team.ORANGE].players[0]
        badge = f"<:role_{player.role.value}_orange:100>"
        discord = DiscordTokens({}, {(player.role, Team.ORANGE): badge}, {}, {})
        token = f"{{role:{player.role.value}:orange}}"
        plain = f"{player.name} [{role_initials(player)}]"

        # The message forms carry the badge, in the side's own colour.
        self.assertEqual(
            player_with_role(player, badge=True, team=Team.ORANGE),
            f"{player.name} {token}",
        )
        self.assertEqual(
            engine.format_roster_player_for_message(
                player.player_id, Team.ORANGE,
            ),
            f"{player.name} {token}",
        )
        self.assertEqual(
            discord.render(f"{player.name} {token}"), f"{player.name} {badge}",
        )
        # The button and autocomplete forms do not, however the cog
        # has been loaded.
        self.assertEqual(player_with_role(player), plain)
        self.assertEqual(engine.format_roster_player(player.player_id), plain)
        self.assertEqual(
            engine.format_roster_player_with_team(player.player_id, Team.ORANGE),
            f"{plain} (Orange)",
        )
        self.assertEqual(engine.shootout_button_label(
            None, None, player.player_id,
        )[: len(plain)], plain)

    def test_format_player_label_renders_under_every_upload(self) -> None:
        """
        `RulesEngine.format_player_label` writes the same two tokens
        whatever has been uploaded, and `DiscordTokens` draws them
        from whatever has: a player with a team emoji and one without,
        crossed with a role with an uploaded badge and one without. A
        divergence would otherwise only show up as a wording change in
        the golden transcript, which does not cover every combination
        below.
        """
        from cogs.d12ball_helpers import DiscordTokens
        from d12ball.components import (
            load_basic_ruleset,
            load_maneuver_catalog,
            load_player_catalog,
        )
        from d12ball.engine import RulesEngine
        from d12ball.formatting import role_initials
        from d12ball.game import Team

        catalog = load_player_catalog()
        engine = RulesEngine(
            catalog, load_basic_ruleset(), load_maneuver_catalog(), {},
        )
        player = catalog.teams[Team.ORANGE].players[0]
        badge = f"<:role_{player.role.value}_orange:100>"
        team_emoji = "<:team_orange:1>"

        class FakeMatch:
            def team_for_player(self, player_id: str) -> Team:
                return Team.ORANGE

        match = FakeMatch()
        label = engine.format_player_label(match, player)

        for team_emojis, role_emojis, expected in (
            ({}, {}, f"🟠 {player.name} [{role_initials(player)}]"),
            ({Team.ORANGE: team_emoji}, {},
             f"{team_emoji} {player.name} [{role_initials(player)}]"),
            ({}, {(player.role, Team.ORANGE): badge},
             f"🟠 {player.name} {badge}"),
            ({Team.ORANGE: team_emoji}, {(player.role, Team.ORANGE): badge},
             f"{team_emoji} {player.name} {badge}"),
        ):
            self.assertEqual(
                DiscordTokens(team_emojis, role_emojis, {}, {}).render(label),
                expected,
            )

    def test_a_role_with_no_upload_keeps_its_brackets(self) -> None:
        """
        Three of six uploaded is three badges and three bracketed
        roles, not three blanks -- the fallback is per role, on the
        dict's own missing entry.
        """
        from cogs.d12ball_helpers import DiscordTokens
        from d12ball.components import PlayerRole, load_player_catalog
        from d12ball.formatting import player_with_role, role_initials
        from d12ball.game import Team

        catalog = load_player_catalog()
        players = catalog.teams[Team.ORANGE].players
        striker = next(p for p in players if p.role == PlayerRole.STRIKER)
        fullback = next(p for p in players if p.role == PlayerRole.FULLBACK)
        discord = DiscordTokens(
            {}, {(PlayerRole.STRIKER, None): "<:role_striker:100>"}, {}, {},
        )

        self.assertEqual(
            discord.render(player_with_role(striker, badge=True)),
            f"{striker.name} <:role_striker:100>",
        )
        self.assertEqual(
            discord.render(player_with_role(fullback, badge=True)),
            f"{fullback.name} [{role_initials(fullback)}]",
        )

    def test_a_team_without_its_colour_cut_falls_back_to_the_plain_badge(
        self,
    ) -> None:
        """
        Three steps down, not two: the colour cut, then the plain
        badge, then the brackets. An application holding the six plain
        badges and none of the twenty-four reads exactly as it did
        before the colours existed -- which is what it is doing until
        somebody uploads the rest.
        """
        from cogs.d12ball_helpers import DiscordTokens
        from d12ball.components import PlayerRole, load_player_catalog
        from d12ball.formatting import player_with_role, role_initials
        from d12ball.game import Team

        catalog = load_player_catalog()
        striker = next(
            p
            for p in catalog.teams[Team.ORANGE].players
            if p.role == PlayerRole.STRIKER
        )
        role_emojis = {
            (PlayerRole.STRIKER, None): "<:role_striker:100>",
            (PlayerRole.STRIKER, Team.ORANGE): "<:role_striker_orange:101>",
        }
        discord = DiscordTokens({}, role_emojis, {}, {})

        # The colour it has.
        self.assertEqual(
            discord.render(player_with_role(striker, badge=True, team=Team.ORANGE)),
            f"{striker.name} <:role_striker_orange:101>",
        )
        # A colour it does not: the plain badge, never a blank.
        self.assertEqual(
            discord.render(player_with_role(striker, badge=True, team=Team.TEAL)),
            f"{striker.name} <:role_striker:100>",
        )
        # And with neither, the brackets.
        self.assertEqual(
            DiscordTokens({}, {}, {}, {}).render(
                player_with_role(striker, badge=True, team=Team.TEAL),
            ),
            f"{striker.name} [{role_initials(striker)}]",
        )

    def test_the_goal_log_names_a_scorer_with_the_plain_badge(self) -> None:
        """
        The one message in the game that names a player and passes no
        team. Every line of the log is under the heading of the side
        the goal counts for, which for an own goal is not the
        scorer's -- so a badge in the scorer's own colour would say
        exactly what the team emoji was left off for saying. See
        `format_goal_scorer`.
        """
        from cogs.d12ball_helpers import DiscordTokens, format_goal_scorer
        from d12ball.components import (
            GoalRecord,
            MatchPeriod,
            PlayerRole,
            TeamSide,
            load_player_catalog,
        )
        from d12ball.game import Team

        catalog = load_player_catalog()
        striker = next(
            p
            for p in catalog.teams[Team.ORANGE].players
            if p.role == PlayerRole.STRIKER
        )
        role_emojis = {
            (PlayerRole.STRIKER, None): "<:role_striker:100>",
            (PlayerRole.STRIKER, Team.ORANGE): "<:role_striker_orange:101>",
        }
        goal = GoalRecord(
            side=TeamSide.HOME,
            player_id=striker.player_id,
            time=7,
            period=MatchPeriod.FIRST_HALF,
        )

        self.assertEqual(
            format_goal_scorer(goal, catalog), f"{striker.name} {{role:striker}}",
        )
        self.assertEqual(
            DiscordTokens({}, role_emojis, {}, {}).render(
                format_goal_scorer(goal, catalog),
            ),
            f"{striker.name} <:role_striker:100>",
        )

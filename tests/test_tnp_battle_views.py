"""
The battle's controls (`cogs/tnp_views/battle.py`) against the real
driver: battles staged by unit slug (`tests/tnp_battles.py`) and fought
to their end with every answer made by clicking a view built from the
prompt's options -- every battle prompt kind among them -- and each
action the views send applied through `tnp.flow.driver.apply`, which
must refuse none. The cog is a stand-in that records what a view sends
and holds what a view would redraw with.
"""

from __future__ import annotations

import itertools
import unittest

import discord

from codex_cog_fakes import FakeChannel, FakeInteraction, find_button, find_select, user
from cogs.tnp_views.battle import (
    BattleHeld, DestroyView, EmergencyView, PlaceView, RepairView, RepositionView, RetreatView,
    RoleView, SplashView, TargetView, battle_view,
)
from tnp.flow import driver
from tnp.game import TnpGame
from tnp.prompts import PromptKind
from tnp.tokens import plain
from tnp_battles import asked, scripted, stage

PLAYER = user(101, "Alice")


class StandIn:
    """What a battle view asks of the cog: the catalog, words, its game,
    and the two calls a click ends in."""

    def __init__(self, engine) -> None:
        self.catalog = engine.catalog
        self.service = object()
        self.game = TnpGame(game_id="g", test_game=True)
        self.game.seats = {"blue": {"id": PLAYER.id, "name": "Alice"},
                           "green": {"id": PLAYER.id, "name": "Alice"}}
        self.games = {"g": self.game}
        self.sent = []
        self.held = None

    def plain_words(self, text: str) -> str:
        return plain(text, self.catalog)

    def render_text(self, text: str, game=None) -> str:
        return plain(text, self.catalog)

    async def answer_battle(self, interaction, view, action) -> None:
        self.sent.append(action)

    async def redraw_battle(self, interaction, view, held) -> None:
        self.held = held


async def click(view, item, *values):
    call = FakeInteraction(PLAYER, FakeChannel(1))
    if isinstance(item, discord.ui.Select):
        call.data = {"custom_id": item.custom_id, "component_type": 3, "values": list(values)}
    else:
        call.data = {"custom_id": item.custom_id, "component_type": 2}
    await view._scheduled_task(item, call)
    return call


def option(menu, starts: str = "") -> str:
    """A menu's first value starting `starts`, or its first."""
    for one in menu.options:
        if one.value.split("|", 1)[-1].startswith(starts):
            return one.value
    return menu.options[0].value


async def one_click(view) -> None:
    """The click a player who wants to see every control makes: a second
    force where there is one, a flanking slot, a carried unit, Workers
    given, a splash taken, a unit produced."""
    held = view.held
    if isinstance(view, RoleView):
        await click(view, find_button(view, "Attack"))
    elif isinstance(view, EmergencyView):
        if not held.counts:
            menu = view.children[0]
            await click(view, menu, menu.options[1].value)
        else:
            await click(view, find_button(view, "Produce these"))
    elif isinstance(view, RepositionView):
        menu = find_select(view, "Flanking forces")
        await click(view, menu, menu.options[0].value)
    elif isinstance(view, PlaceView):
        forces = view.options.forces
        if len(forces) > 1 and held.force is None:
            await click(view, find_select(view, "Force to place"), forces[-1].force)
        else:
            menu = find_select(view, "Where")
            await click(view, menu, option(menu, "flank"))
    elif isinstance(view, RetreatView):
        if not view.options.path_home and view.options.carry and not held.counts:
            menu = view.children[0]
            await click(view, menu, menu.options[1].value)
        elif not view.options.path_home:
            await click(view, find_button(view, "Retreat"))
        else:
            await click(view, find_button(view, "Fight on"))
    elif isinstance(view, TargetView):
        forces = view.options.forces
        if len(forces) > 1 and held.force is None:
            await click(view, find_select(view, "Force to roll"), forces[-1].force)
        else:
            menu = find_select(view, "Target for")
            # A base card, else a Tank, where there is one: so a base
            # card's hits are destroyed and a Tank's hits repaired.
            preferred = [one.value for one in menu.options
                         if one.value.split("|")[1].startswith(("base_", "blue:tank"))]
            await click(view, menu, (preferred or [menu.options[0].value])[0])
    elif isinstance(view, RepairView):
        if not held.counts:
            menu = view.children[0]
            await click(view, menu, menu.options[1].value)
        else:
            await click(view, find_button(view, "Repair"))
    elif isinstance(view, SplashView):
        menu = find_select(view, "Force to splash")
        await click(view, menu, menu.options[0].value)
    elif isinstance(view, DestroyView):
        menu = find_select(view, "What is destroyed")
        await click(view, menu, menu.options[0].value)
    else:  # pragma: no cover
        raise AssertionError(type(view))


async def answer_by_view(test, cog, engine, match, prompt) -> None:
    """One question answered by clicking its view -- redrawn with what it
    holds until a click sends an answer -- and the answer applied, which
    the driver must not refuse."""
    held = BattleHeld()
    for _ in range(10):
        view = battle_view(cog, "g", prompt, match.battle, held)
        test.assertIsNotNone(view, prompt.kind)
        for item in view.children:
            test.assertTrue(item.custom_id.startswith("tnp:battle:g:"))
            test.assertLessEqual(len(item.custom_id), 100)
        before = len(cog.sent)
        await one_click(view)
        if len(cog.sent) > before:
            break
        test.assertIsNotNone(cog.held, "a click that sends nothing redraws")
        held, cog.held = cog.held, None
    else:  # pragma: no cover
        test.fail(f"no answer came of {prompt.kind}")
    run = driver.apply(engine, None, match, cog.sent[-1])
    test.assertNotIsInstance(run, driver.Refusal, getattr(run, "reason", None))


async def fight_by_views(test, engine, match, rolls) -> set:
    """The battle fought to its end through the views; the kinds asked."""
    cog = StandIn(engine)
    seen = set()
    with scripted(engine, rolls):
        for _ in range(500):
            prompt = asked(engine, match)
            if prompt is None:
                test.assertIsNotNone(match.battle.outcome)
                return seen
            seen.add(prompt.kind)
            await answer_by_view(test, cog, engine, match, prompt)
    test.fail("the battle did not end")


class BattleViewsTests(unittest.IsolatedAsyncioTestCase):
    STRUCTURES = {
        "facilities": ["barracks", "factory", "airport", "base_defenses"],
        "upgrades": ["factory_upgrade", "robotic_facility"],
    }

    async def test_every_battle_question_answered_through_its_view(self) -> None:
        seen = set()
        battles = [
            # Both seats at a neutral territory: the side chosen (TNP 6.1).
            (stage({"jeep": 1}, {"mercenary": 1}, contested=True, territory="1"), itertools.repeat(7)),
            # A base's emergency defense (TNP 6.2), then its base cards
            # hit twice (TNP 6.9).
            (stage({"cyborg_soldier": 3}, {}, territory="green_base", structures=self.STRUCTURES,
                   emergency={"pool": {"materials": 10, "gold": 10},
                              "supply_room": {"smart_mines": 8, "rocket_launcher": 8, "laser_cannon": 6}}),
             itertools.repeat(12)),
            # No path home: the Chopper Carrier takes a Mercenary (TNP 6.6, 7).
            (stage({"chopper_carrier": 1, "mercenary": 4}, {"mercenary": 1},
                   paths_home={"blue": False, "green": True}), itertools.repeat(2)),
            # Tanks splash and Workers repair them (TNP 6.8).
            (stage({"tank": 2, "worker": 3}, {"mercenary": 4, "worker": 2}), itertools.repeat(12)),
            # Flankers kept or repositioned from round 2 (TNP 6.5).
            (stage({"mercenary": 2, "jeep": 1, "worker": 1}, {"mercenary": 2, "worker": 1}),
             itertools.repeat(2)),
        ]
        for (engine, match), rolls in battles:
            seen |= await fight_by_views(self, engine, match, rolls)
        self.assertEqual({
            PromptKind.CHOOSE_ROLE, PromptKind.EMERGENCY_DEFENSE, PromptKind.REPOSITION_FLANKERS,
            PromptKind.PLACE_FORCE, PromptKind.DECLARE_RETREAT, PromptKind.CHOOSE_TARGET,
            PromptKind.REPAIR, PromptKind.SPLASH, PromptKind.DESTROY,
        }, seen)

    async def test_a_target_says_why_before_the_roll(self) -> None:
        engine, match = stage({"tank": 1}, {"mercenary": 1})
        cog = StandIn(engine)
        with scripted(engine, itertools.repeat(2)):
            while (prompt := asked(engine, match)).kind is not PromptKind.CHOOSE_TARGET:
                await answer_by_view(self, cog, engine, match, prompt)
        view = battle_view(cog, "g", prompt, match.battle)
        menu = find_select(view, "Target for")
        self.assertIn("each hits on", menu.options[0].label)
        self.assertIn("against", menu.options[0].description)

    async def test_a_restarted_view_shows_the_question_afresh_before_sending_what_it_held(self) -> None:
        engine, match = stage({"chopper_carrier": 1, "mercenary": 4}, {"mercenary": 1},
                              paths_home={"blue": False, "green": True})
        cog = StandIn(engine)
        with scripted(engine, itertools.repeat(2)):
            while (prompt := asked(engine, match)).kind is not PromptKind.DECLARE_RETREAT \
                    or prompt.asked_seat != "blue":
                await answer_by_view(self, cog, engine, match, prompt)
        sent = len(cog.sent)
        view = battle_view(cog, "g", prompt, match.battle, BattleHeld(counts=(("blue:mercenary", 1),)),
                           restored=True)
        await click(view, find_button(view, "Retreat"))
        self.assertEqual(sent, len(cog.sent))
        self.assertIn("restarted", cog.held.notice)


if __name__ == "__main__":
    unittest.main()

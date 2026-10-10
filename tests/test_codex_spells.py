"""
The spells, the triggers, the abilities and the static texts of the basic
set (docs/codex-bot.md, step 6): each spell's happy path and its
refusals -- no hero, the wrong spec, the ultimate too soon, nothing to
target -- targeting with resist and the flagbearer, and the turns the
step names: a Virtuoso arriving free under Maestro and exhausting at once
beside Nimble Fencer; Harmony across a turn; Two Step's sacrifice when a
partner is Booted; Final Smash against a flagbearer.

The rulings themselves are `tests/test_codex_card_rulings.py`'s, one test
each; this file is everything else the cards say.
"""

from __future__ import annotations

import unittest

from codex.components import AddOnState
from codex.flow import board, driver, resolve
from codex.prompts import Action, PromptKind, pending_prompt

from codex_positions import RIVER, TROQ, built, hand, hero_in_play, put
from test_codex_card_rulings import (
    apply, asked, bashing, cast, finesse, red_green, said, ultimate_ready,
)


def refused(engine, game, match, kind, choice="", **arguments):
    run = driver.apply(engine, game, match, Action(kind, choice, arguments))
    assert isinstance(run, driver.Refusal), run
    return run


def why(engine, match, slug: str) -> str:
    return engine.why_not_playable(match.active_player, slug, match)


class PlayingASpellTests(unittest.TestCase):
    def test_a_spell_needs_a_hero_in_play(self) -> None:
        engine, game, match = bashing()
        put(match, 2, "tenderfoot", patrol="elite")
        hand(match, 1, "spark")
        self.assertIn("needs a hero in play", why(engine, match, "spark"))
        refused(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="spark")

    def test_a_spec_spell_needs_its_specs_hero(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1)
        hand(match, 1, "discord")
        match.player(1).gold = 5
        self.assertIn("Finesse hero", why(engine, match, "discord"))

    def test_an_ultimate_needs_the_hero_at_its_maximum_since_the_turn_began(self) -> None:
        engine, game, match = finesse()
        hero_in_play(match, 2, level=5)
        put(match, 1, "tenderfoot", patrol="elite")
        hand(match, 2, "appel_stomp")
        self.assertIn("maximum level", why(engine, match, "appel_stomp"))
        match.player(2).hero.max_level_since_turn_began = True
        self.assertEqual(why(engine, match, "appel_stomp"), "")

    def test_a_spell_with_nothing_to_target_is_not_playable(self) -> None:
        """"Do as much as you can" plays a spell any of whose parts can
        resolve; a spell none of whose parts can is not playable."""
        engine, game, match = bashing()
        hero_in_play(match, 1)
        hand(match, 1, "spark", "the_boot")
        match.player(1).gold = 10
        self.assertIn("nothing it could target", why(engine, match, "spark"))
        self.assertIn("nothing it could target", why(engine, match, "the_boot"))
        put(match, 2, "tenderfoot")
        self.assertEqual(why(engine, match, "the_boot"), "")

    def test_a_spell_goes_to_the_discard_once_it_has_resolved(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1)
        target = put(match, 2, "iron_man", patrol="elite")
        cast(engine, game, match, "spark", gold=1)
        self.assertEqual(target.damage, 1)
        self.assertEqual(match.player(1).discard[-1], "spark")
        self.assertEqual(match.player(1).gold, 0)
        self.assertEqual(match.resolving, [])


class TheSpellsTests(unittest.TestCase):
    def test_spark_deals_1_to_a_patroller_of_either_side(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1, patrol="elite")
        mine = put(match, 1, "older_brother", patrol="scavenger")
        theirs = put(match, 2, "older_brother", patrol="elite")
        put(match, 2, "iron_man")
        hand(match, 1, "spark")
        match.player(1).gold = 1
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="spark")
        offered = {(row.seat, row.ref) for row in asked(engine, game, match).options.targets}
        self.assertEqual(offered, {(1, TROQ), (1, mine.ref), (2, theirs.ref)})
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{theirs.ref}")
        self.assertEqual(theirs.damage, 1)

    def test_bloom_puts_a_rune_on_a_friend_without_one(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1)
        bloomed = put(match, 1, "iron_man")
        bloomed.plus_runes = 1
        put(match, 2, "iron_man")
        cast(engine, game, match, "bloom")
        hero = match.player(1).hero
        self.assertEqual(hero.plus_runes, 1, "the hero, the one friend without a rune")
        self.assertEqual(engine.hero_stats(hero), (3, 4))

    def test_wither_cancels_a_plus_rune(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1)
        brother = put(match, 2, "older_brother")
        brother.plus_runes = 1
        cast(engine, game, match, "wither", f"2:{brother.ref}")
        self.assertEqual((brother.plus_runes, brother.minus_runes), (0, 0))

    def test_wither_on_a_hero(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1)
        hero_in_play(match, 2, damage=2)
        cast(engine, game, match, "wither", "2:hero")
        river = match.player(2).hero
        self.assertFalse(river.in_play, "2 damage on a 2/2 hero")
        self.assertEqual(river.summoning_runes, 2)
        self.assertEqual(river.minus_runes, 0, "runes go with the hero")

    def test_wrecking_ball_deals_2_to_a_building(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1)
        built(match, 2, "tech1", hp=2)
        cast(engine, game, match, "wrecking_ball", "2:tech1", gold=0)
        self.assertTrue(match.player(2).buildings["tech1"].destroyed)
        self.assertEqual(match.player(2).base_hp, 18)

    def test_the_boot_destroys_a_tech_0_or_i_unit(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1)
        put(match, 2, "eggship")
        fencer = put(match, 2, "nimble_fencer")
        cast(engine, game, match, "the_boot")
        self.assertIsNone(match.player(2).instance(fencer.id))

    def test_intimidate_lasts_the_turn(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1)
        hero_in_play(match, 2, patrol="squad_leader")
        cast(engine, game, match, "intimidate", "2:hero")
        self.assertEqual(engine.hero_stats(match.player(2).hero)[0], 0)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        apply(engine, game, match, PromptKind.PATROL, assignment={})
        self.assertEqual(engine.hero_stats(match.player(2).hero)[0], 2)

    def test_discord_lasts_until_the_end_of_the_turn(self) -> None:
        engine, game, match = finesse()
        hero_in_play(match, 2)
        brother = put(match, 1, "older_brother")
        egg = put(match, 1, "eggship")
        cast(engine, game, match, "discord")
        self.assertEqual(engine.unit_stats(brother, match), (0, 1))
        self.assertEqual(engine.unit_stats(egg, match), (4, 3), "tech II is untouched")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        apply(engine, game, match, PromptKind.PATROL, assignment={})
        self.assertEqual(engine.unit_stats(brother, match), (2, 2))

    def test_final_smash_does_all_three_parts(self) -> None:
        engine, game, match = bashing()
        ultimate_ready(match, 1)
        foot = put(match, 2, "tenderfoot")
        fencer = put(match, 2, "nimble_fencer")
        guide = put(match, 2, "grounded_guide", patrol="elite")
        cast(engine, game, match, "final_smash")
        self.assertIsNone(match.instance(foot.id))
        self.assertIsNone(match.instance(fencer.id))
        self.assertIn("nimble_fencer", match.player(2).hand)
        self.assertEqual(guide.controller, 1)
        self.assertEqual(guide.owner, 2)
        self.assertIsNone(guide.patrol_slot)
        self.assertTrue(guide.arrived_this_turn, "it came under its new controller this turn")
        # Destroyed under its new controller, it still goes to its owner.
        board.destroy(engine, match, [(1, guide.ref)], driver.StepResult())
        self.assertEqual(match.player(2).discard[-1], "grounded_guide")

    def test_appel_stomp_on_top_of_the_draw_pile(self) -> None:
        engine, game, match = finesse()
        ultimate_ready(match, 2)
        leader = put(match, 1, "iron_man", patrol="squad_leader")
        leader.armor = 1
        player = match.player(2)
        deck = len(player.deck)
        cast(engine, game, match, "appel_stomp")
        self.assertIsNone(leader.patrol_slot)
        self.assertEqual(leader.armor, 0, "the squad leader's armor is the slot's")
        self.assertEqual(len(player.deck), deck - 1, "a card drawn")
        self.assertEqual(len(player.hand), 1)
        apply(engine, game, match, PromptKind.APPEL_STOMP_TOP, "top")
        self.assertEqual(player.deck[-1], "appel_stomp")


class TargetingTests(unittest.TestCase):
    def test_resist_is_paid_when_the_target_is_chosen(self) -> None:
        """Resist X (UMR p. 18): the lookout's 1 and Brick Thief's 1
        stack, paid as the target is chosen."""
        engine, game, match = bashing()
        hero_in_play(match, 1)
        thief = put(match, 2, "brick_thief", patrol="lookout")
        other = put(match, 2, "older_brother", patrol="elite")
        hand(match, 1, "spark")
        match.player(1).gold = 3
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="spark")
        rows = {row.ref: row.resist for row in asked(engine, game, match).options.targets}
        self.assertEqual(rows, {thief.ref: 2, other.ref: 0})
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{thief.ref}")
        self.assertEqual(match.player(1).gold, 0)
        self.assertEqual(thief.damage, 1)

    def test_what_cannot_be_paid_for_cannot_be_chosen(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1)
        thief = put(match, 2, "brick_thief", patrol="lookout")
        other = put(match, 2, "older_brother", patrol="elite")
        hand(match, 1, "spark")
        match.player(1).gold = 1
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="spark")
        # The one target left is taken unasked.
        self.assertEqual(other.damage, 1)
        self.assertEqual(thief.damage, 0)

    def test_an_opponents_invisible_card_is_untargetable_and_your_own_is_not(self) -> None:
        engine, game, match = finesse()
        hero_in_play(match, 2)
        mine = put(match, 2, "backstabber")
        theirs = put(match, 1, "backstabber")
        self.assertTrue(engine.targetable(match, 2, 2, mine.ref))
        self.assertFalse(engine.targetable(match, 2, 1, theirs.ref))
        match.player(2).add_on = AddOnState(
            "tower", 4, under_construction=False, detected=theirs.ref,
        )
        self.assertTrue(engine.targetable(match, 2, 1, theirs.ref), "the tower detected it")

    def test_the_flagbearer_is_forced_on_an_opponents_spell(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1)
        flag = put(match, 2, "granfalloon_flagbearer", patrol="elite")
        other = put(match, 2, "iron_man", patrol="squad_leader")
        cast(engine, game, match, "spark")
        self.assertEqual(flag.damage, 1)
        self.assertEqual(other.damage, 0)

    def test_your_own_flagbearer_forces_nothing(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1)
        put(match, 1, "granfalloon_flagbearer", patrol="elite")
        theirs = put(match, 2, "iron_man", patrol="squad_leader")
        hand(match, 1, "spark")
        match.player(1).gold = 1
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="spark")
        options = asked(engine, game, match).options
        self.assertFalse(options.forced)
        self.assertIn(f"2:{theirs.ref}", [row.key for row in options.targets])

    def test_a_flagbearer_whose_resist_cannot_be_paid_forces_nothing(self) -> None:
        """"If you cannot target a flagbearer for some reason, then you
        don't have to" -- the flagbearer ruling, with resist."""
        engine, game, match = bashing()
        hero_in_play(match, 1)
        flag = put(match, 2, "granfalloon_flagbearer", patrol="lookout")
        other = put(match, 2, "iron_man", patrol="squad_leader")
        cast(engine, game, match, "spark", gold=1)
        self.assertEqual(flag.damage, 0)
        self.assertEqual(other.damage, 1)

    def test_final_smash_with_a_flagbearer_on_the_other_side(self) -> None:
        engine, game, match = bashing()
        ultimate_ready(match, 1)
        flag = put(match, 2, "granfalloon_flagbearer")
        put(match, 1, "tenderfoot")
        cast(engine, game, match, "final_smash")
        self.assertIsNone(match.player(2).instance(flag.id), "the flagbearer, not my own tech 0")
        self.assertEqual(len([c for c in match.player(1).play if c.slug == "tenderfoot"]), 1)


class TriggerTests(unittest.TestCase):
    def test_hired_stomper_must_deal_its_3_and_may_take_itself(self) -> None:
        engine, game, match = bashing()
        built(match, 1, "tech1")
        built(match, 1, "tech2")
        brother = put(match, 2, "older_brother")
        hand(match, 1, "hired_stomper")
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="hired_stomper")
        prompt = asked(engine, game, match)
        stomper = match.player(1).play[-1]
        self.assertEqual({row.ref for row in prompt.options.targets}, {brother.ref, stomper.ref})
        apply(engine, game, match, PromptKind.TARGET, target=f"1:{stomper.ref}")
        self.assertIsNone(match.player(1).instance(stomper.id))

    def test_sneaky_pig_has_stealth_on_the_turn_it_arrives(self) -> None:
        engine, game, match = bashing()
        built(match, 1, "tech1")
        built(match, 1, "tech2")
        put(match, 2, "older_brother", patrol="squad_leader")
        hand(match, 1, "sneaky_pig")
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="sneaky_pig")
        pig = match.player(1).play[-1]
        self.assertTrue(engine.has_keyword(pig, "Stealth", match))
        self.assertIn(pig.ref, engine.attackers(match), "haste")
        self.assertIn("base", engine.legal_defenders(match, pig.ref), "it sneaks past")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        apply(engine, game, match, PromptKind.PATROL, assignment={})
        self.assertFalse(engine.has_keyword(pig, "Stealth", match))

    def test_a_trigger_that_destroys_the_defender_asks_for_another(self) -> None:
        engine, game, match = bashing()
        duck = put(match, 1, "trojan_duck")
        built(match, 2, "tech1", hp=3)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=duck.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="tech1")
        apply(engine, game, match, PromptKind.TARGET, target="2:tech1")
        self.assertTrue(match.player(2).buildings["tech1"].destroyed)
        self.assertIs(asked(engine, game, match).kind, PromptKind.CHOOSE_DEFENDER)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="base")
        # The trigger fired once: 2 for the building, 8 for the Duck.
        self.assertEqual(match.player(2).base_hp, 20 - 2 - 8)
        self.assertIsNone(match.combat)

    def test_troq_at_5_names_his_middle_band_and_the_base_now(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1, level=5)
        match.player(2).base_hp = 18
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=TROQ)
        run = apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="base")
        said = [line for group in run.groups for line in group.lines] + list(run.result.narration)
        self.assertIn(
            "{hero:troq_bashar}'s middle level band's ability deals 1 to {player:2}'s base, now at 17/20.", said,
        )

    def test_a_band_is_first_middle_or_max_level(self) -> None:
        engine, game, match = bashing()
        self.assertEqual(
            [resolve.band_name(engine, "troq_bashar", first) for first in (1, 5, 8)],
            ["first level", "middle level", "max level"],
        )

    def test_troq_at_5_can_win_the_game_before_the_damage(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1, level=5)
        match.player(2).base_hp = 1
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=TROQ)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="base")
        self.assertEqual(match.winner, 1)
        self.assertIsNone(match.combat)
        self.assertIs(asked(engine, game, match).kind, PromptKind.GAME_OVER)

    def test_river_sidelines_a_tech_0_or_i_patroller(self) -> None:
        engine, game, match = finesse()
        hero_in_play(match, 2, level=3, arrived=True)
        leader = put(match, 1, "iron_man", patrol="squad_leader")
        put(match, 1, "eggship", patrol="elite")
        option = next(one for one in engine.abilities(match) if one.effect == "river_montoya")
        self.assertIn("arrived this turn", option.why_not)
        match.player(2).hero.arrived_this_turn = False
        apply(engine, game, match, PromptKind.MAIN_ACTION, "ability",
              ability="river_montoya", source=RIVER)
        self.assertIsNone(leader.patrol_slot, "the tech I one; the tech II Eggship is not offered")
        self.assertTrue(match.player(2).hero.exhausted)

    def test_river_at_level_2_has_no_ability(self) -> None:
        engine, game, match = finesse()
        hero_in_play(match, 2, level=2)
        self.assertEqual(engine.abilities(match), ())


class GrantTests(unittest.TestCase):
    def test_maestro_and_nimble_fencer(self) -> None:
        """The Maestro-and-Nimble-Fencer turn: a Virtuoso arrives free,
        and exhausts for 2 at once, hasted."""
        engine, game, match = finesse()
        built(match, 2, "tech1")
        put(match, 2, "maestro")
        put(match, 2, "nimble_fencer")
        hand(match, 2, "tenderfoot")
        player = match.player(2)
        player.gold = 0
        self.assertEqual(engine.effective_cost(player, "tenderfoot"), 0)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="tenderfoot")
        foot = player.play[-1]
        self.assertTrue(foot.arrived_this_turn)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "ability",
              ability="maestro", source=foot.ref)
        apply(engine, game, match, PromptKind.TARGET, target="1:base")
        self.assertEqual(match.player(1).base_hp, 18)
        self.assertTrue(foot.exhausted)

    def test_blademaster_is_free_under_maestro(self) -> None:
        engine, game, match = finesse()
        put(match, 2, "maestro")
        self.assertEqual(engine.effective_cost(match.player(2), "blademaster"), 0)

    def test_blademaster_gives_swift_strike_in_combat(self) -> None:
        engine, game, match = finesse()
        put(match, 2, "blademaster", exhausted=True)
        foot = put(match, 2, "tenderfoot")
        brother = put(match, 1, "older_brother", patrol="squad_leader")
        brother.armor = 0
        foot.plus_runes = 1
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=foot.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender=brother.ref)
        self.assertIsNone(match.player(1).instance(brother.id))
        self.assertEqual(foot.damage, 0, "it struck first and killed")

    def test_losing_grounded_guide_can_kill(self) -> None:
        engine, game, match = finesse()
        guide = put(match, 2, "grounded_guide")
        foot = put(match, 2, "tenderfoot", damage=2)
        self.assertEqual(engine.unit_stats(foot, match), (3, 3))
        result = driver.StepResult()
        board.leave_play(engine, match, guide, "discard")
        board.settle(engine, match, result)
        self.assertIsNone(match.player(2).instance(foot.id))


class HarmonyAcrossATurnTests(unittest.TestCase):
    def test_three_spells_three_dancers_and_a_fourth_none(self) -> None:
        engine, game, match = finesse()
        hero_in_play(match, 2)
        cast(engine, game, match, "harmony")
        put(match, 1, "iron_man", patrol="elite")
        for _ in range(4):
            cast(engine, game, match, "spark")
        dancers = [card for card in match.player(2).play if card.slug == "dancer"]
        self.assertEqual(len(dancers), 3, "the limit is three")
        song = next(card for card in match.player(2).play if card.slug == "harmony")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "ability",
              ability="stop_the_music", source=song.ref)
        self.assertEqual(
            [card.slug for card in match.player(2).play if "dancer" in card.slug],
            ["angry_dancer"] * 3,
        )

    def test_the_hero_dies_and_harmony_goes_without_a_flip(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1)
        hero_in_play(match, 2, damage=2)
        put(match, 2, "harmony")
        dancer = put(match, 2, "dancer")
        cast(engine, game, match, "wither", "2:hero")
        self.assertFalse(match.player(2).hero.in_play)
        self.assertNotIn("harmony", [card.slug for card in match.player(2).play])
        self.assertIn("harmony", match.player(2).discard)
        self.assertEqual(dancer.slug, "dancer")


class TwoStepAndTheBootTests(unittest.TestCase):
    def test_two_steps_sacrifice_when_a_partner_is_booted(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1)
        hero_in_play(match, 2)
        first = put(match, 2, "tenderfoot")
        second = put(match, 2, "nimble_fencer")
        step = put(match, 2, "two_step")
        step.attached = [first.id, second.id]
        self.assertEqual(engine.unit_stats(second, match), (4, 5))
        hand(match, 1, "the_boot")
        match.player(1).gold = 3
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="the_boot")
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{second.ref}")
        self.assertIsNone(match.player(2).instance(step.id))
        self.assertIn("two_step", match.player(2).discard)
        self.assertEqual(engine.unit_stats(first, match), (1, 2))


class UpkeepTests(unittest.TestCase):
    def test_the_surplus_draws_a_card_at_upkeep(self) -> None:
        engine, game, match = bashing()
        match.player(2).add_on = AddOnState("surplus", 4, under_construction=False)
        before = len(match.player(2).hand)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        apply(engine, game, match, PromptKind.PATROL, assignment={})
        self.assertEqual(len(match.player(2).hand), before + 1)

    def test_the_order_is_not_asked_where_it_changes_nothing(self) -> None:
        engine, game, match = bashing()
        put(match, 2, "starcrossed_starlet")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        apply(engine, game, match, PromptKind.PATROL, assignment={})
        self.assertIs(pending_prompt(engine, game, match).kind, PromptKind.MAIN_ACTION)
        self.assertEqual(match.player(2).play[-1].damage, 1)

    def test_the_turn_starts_once_the_order_is_answered(self) -> None:
        """The turn-start snapshot is taken once the upkeep is done, so an
        undo to the start of the turn never asks the order again."""
        engine, game, match = bashing()
        put(match, 2, "helpful_turtle")
        put(match, 2, "starcrossed_starlet")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        apply(engine, game, match, PromptKind.PATROL, assignment={})
        self.assertEqual(match.phase, "upkeep")
        snapshots = len(match.turn_snapshots)
        apply(engine, game, match, PromptKind.UPKEEP_ORDER, first="healing")
        self.assertEqual(match.phase, "main")
        self.assertEqual(len(match.turn_snapshots), min(snapshots + 1, 3))
        self.assertEqual(match.turn_snapshots[-1]["phase"], "main")


def staged(match) -> None:
    """The hand-staged position as the turn's start: a cancel replays
    the turn from its snapshot, which staging by hand would bypass."""
    from codex import history

    match.turn_snapshots[-1] = history.position(match)
    match.journal = []


class CancelTests(unittest.TestCase):
    """A spell or an ability may be taken back while it asks a target
    (the author, 2026-10-08): the turn is replayed to just before it."""

    def test_a_spell_is_taken_back_at_its_first_target(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1)
        put(match, 2, "older_brother", patrol="elite")
        put(match, 2, "iron_man", patrol="squad_leader")
        hand(match, 1, "iron_man", "spark", "older_brother")
        match.player(1).gold = 4
        staged(match)
        before = match.to_dict()
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="spark")
        options = asked(engine, game, match).options
        self.assertTrue(options.cancellable)
        run = apply(engine, game, match, PromptKind.TARGET, "cancel")
        self.assertIn("takes back {card:spark}", " ".join(run.result.narration))
        after = match.to_dict()
        for key in ("players", "resolving", "journal"):
            self.assertEqual(after[key], before[key], key)
        self.assertIs(asked(engine, game, match).kind, PromptKind.MAIN_ACTION)

    def test_a_part_that_resolved_unasked_comes_back(self) -> None:
        """Final Smash's first part took the one tech 0 unit without
        asking; cancelling at the second part puts it back."""
        engine, game, match = bashing()
        ultimate_ready(match, 1)
        foot = put(match, 2, "tenderfoot")
        put(match, 2, "nimble_fencer")
        put(match, 2, "starcrossed_starlet")
        hand(match, 1, "final_smash")
        match.player(1).gold = 6
        staged(match)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="final_smash")
        self.assertIsNone(match.player(2).instance(foot.id))
        self.assertEqual(asked(engine, game, match).options.part, 1)
        apply(engine, game, match, PromptKind.TARGET, "cancel")
        self.assertEqual(match.player(2).instance(foot.id).slug, "tenderfoot")
        self.assertNotIn("tenderfoot", match.player(2).discard)
        self.assertEqual(match.player(1).hand, ["final_smash"])
        self.assertEqual(match.player(1).gold, 6)

    def test_an_ability_is_taken_back_and_its_card_readied(self) -> None:
        engine, game, match = finesse()
        put(match, 2, "maestro")
        foot = put(match, 2, "tenderfoot")
        built(match, 1, "tech1")
        staged(match)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "ability",
              ability="maestro", source=foot.ref)
        self.assertTrue(foot.exhausted)
        apply(engine, game, match, PromptKind.TARGET, "cancel")
        foot = match.player(2).instance(foot.id)
        self.assertFalse(foot.exhausted)

    def test_a_trigger_is_not_taken_back(self) -> None:
        engine, game, match = bashing()
        hand(match, 1, "brick_thief")
        built(match, 2, "tech1")
        match.player(1).gold = 5
        staged(match)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="brick_thief")
        self.assertFalse(asked(engine, game, match).options.cancellable)
        refused(engine, game, match, PromptKind.TARGET, "cancel")

    def test_the_other_players_tech_choice_survives_a_cancel(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1)
        put(match, 2, "older_brother", patrol="elite")
        put(match, 2, "iron_man", patrol="squad_leader")
        hand(match, 1, "spark")
        match.player(1).gold = 1
        match.player(2).tech_owed = True
        staged(match)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="spark")
        apply(engine, game, match, PromptKind.TECH_CHOICE,
              player=2, picks=["maestro", "cloud_sprite"])
        apply(engine, game, match, PromptKind.TARGET, "cancel")
        self.assertEqual(match.player(2).tech_choice, ["maestro", "cloud_sprite"])
        self.assertEqual(match.player(1).hand, ["spark"])

    def test_a_turn_with_a_cancel_replays_byte_for_byte(self) -> None:
        import json
        from codex import history
        from codex.engine import RulesEngine

        engine, game, match = bashing()
        hero_in_play(match, 1)
        put(match, 2, "older_brother", patrol="elite")
        put(match, 2, "iron_man", patrol="squad_leader")
        hand(match, 1, "spark")
        match.player(1).gold = 1
        staged(match)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="spark")
        apply(engine, game, match, PromptKind.TARGET, "cancel")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="spark")
        options = asked(engine, game, match).options
        apply(engine, game, match, PromptKind.TARGET, target=options.targets[0].key)
        self.assertEqual(len(match.journal), 2, "the cancel and what it took back are gone")
        replayed = history.replay(RulesEngine(seed=3), game, match.turn_snapshots[-1],
                                  match.journal, history=match.turn_snapshots)
        self.assertEqual(json.dumps(replayed.to_dict(), sort_keys=True),
                         json.dumps(match.to_dict(), sort_keys=True))


class TwoStepNeedsTwoTests(unittest.TestCase):
    def test_two_step_is_not_played_with_one_unit(self) -> None:
        """"Sacrifice this spell if either partner leaves play or leaves
        your control" (UMR p. 22, the Card FAQ): Two Step partners two
        units, or it is not played (the author, 2026-10-08)."""
        engine, game, match = finesse()
        hero_in_play(match, 2)
        put(match, 2, "tenderfoot")
        hand(match, 2, "two_step")
        match.player(2).gold = 5
        self.assertIn("nothing it could target", why(engine, match, "two_step"))
        put(match, 2, "older_brother")
        self.assertEqual(why(engine, match, "two_step"), "")


class RulebookTests(unittest.TestCase):
    def test_a_building_under_construction_cannot_be_damaged(self) -> None:
        """"You can't ... deal damage to a tech building on the turn that
        you constructed it" (UMR p. 8)."""
        engine, game, match = bashing()
        hero_in_play(match, 1)
        built(match, 1, "tech1", finished=False)
        hand(match, 1, "wrecking_ball")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="wrecking_ball")
        offered = {row.key for row in asked(engine, game, match).options.targets}
        self.assertEqual(offered, {"2:base", "1:base"})

    def test_your_own_hero_killed_by_your_spell_gives_no_levels(self) -> None:
        """"When you destroy an opponent's hero, one of your heroes
        immediately gains 2 levels" (UMR p. 10): an opponent's hero."""
        engine, game, match = bashing()
        hero_in_play(match, 1, damage=2)
        hero_in_play(match, 2)
        cast(engine, game, match, "wither", "1:hero")
        self.assertFalse(match.player(1).hero.in_play)
        self.assertEqual(match.player(2).hero.level, 1)

    def test_an_opponents_hero_killed_by_your_spell_gives_you_levels(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1)
        hero_in_play(match, 2, damage=2)
        cast(engine, game, match, "wither", "2:hero")
        self.assertEqual(match.player(1).hero.level, 3)

# -- Red and green: the costs and the resources (step 11) -----------------------


class ResourcesTests(unittest.TestCase):
    def test_rickety_mines_coin_is_replayed_byte_for_byte(self) -> None:
        """The coin is `engine.rng`'s, journalled beside the shuffles, so a
        replay by an engine of another seed lands the same side."""
        import json

        from codex import history
        from codex.engine import RulesEngine
        from codex_positions import begin, new_game

        for seed in range(6):
            engine, game, match = new_game(seed=seed, teams=(("blood",), ("growth",)))
            mine = put(match, 1, "rickety_mine")
            begin(engine, game, match)
            apply(engine, game, match, PromptKind.MAIN_ACTION, "ability",
                  ability="rickety_mine", source=mine.ref)
            outcome = match.journal[-1]["outcomes"]
            self.assertEqual(outcome[0][0], "@coin")
            replayed = history.replay(
                RulesEngine(seed=seed + 100), game, match.turn_snapshots[-1],
                match.journal, history=match.turn_snapshots,
            )
            self.assertEqual(json.dumps(replayed.to_dict(), sort_keys=True),
                             json.dumps(match.to_dict(), sort_keys=True))

    def test_tails_sacrifices_the_mine_and_hurts_the_base(self) -> None:
        from unittest import mock

        from test_codex_card_rulings import red_green

        engine, game, match = red_green(teams=(("blood",), ("growth",)))
        mine = put(match, 1, "rickety_mine")
        with mock.patch.object(engine, "flip_coin", return_value="tails"):
            apply(engine, game, match, PromptKind.MAIN_ACTION, "ability",
                  ability="rickety_mine", source=mine.ref)
        self.assertIsNone(match.player(1).instance(mine.id))
        self.assertIn("rickety_mine", match.player(1).discard)
        self.assertEqual(match.player(1).base_hp, 18)

    def test_tails_gets_hotter_fires_one_more(self) -> None:
        """Rickety Mine is red, so its tails' 2 gets Hotter Fire's +1 (the
        author, 2026-10-09)."""
        from unittest import mock

        from test_codex_card_rulings import red_green

        engine, game, match = red_green(teams=(("blood", "fire", "anarchy"), ("growth", "feral", "balance")))
        put(match, 1, "hotter_fire")
        mine = put(match, 1, "rickety_mine")
        with mock.patch.object(engine, "flip_coin", return_value="tails"):
            apply(engine, game, match, PromptKind.MAIN_ACTION, "ability",
                  ability="rickety_mine", source=mine.ref)
        self.assertEqual(match.player(1).base_hp, 17)

    def test_pirategangs_granted_line_is_hotter_only_on_a_red_unit(self) -> None:
        """"Your units have 'Dies: deal 1 damage to each opposing base'" --
        the line is the dying unit's, so Hotter Fire adds to it only where
        that unit is red (the author, 2026-10-09)."""
        from codex.flow import resolve
        from test_codex_card_rulings import red_green

        engine, game, match = red_green(teams=(("blood", "fire", "anarchy"), ("growth", "feral", "balance")))
        put(match, 1, "pirategang_commander")
        put(match, 1, "hotter_fire")
        for slug, damage in (("pirate", 2), ("tenderfoot", 1)):
            with self.subTest(dying=slug):
                hp = match.player(2).base_hp
                dying = put(match, 1, slug)
                result = driver.StepResult()
                board.destroy(engine, match, [(1, dying.ref)], result)
                resolve.run(engine, match, result)
                self.assertEqual(match.player(2).base_hp, hp - damage)

    def test_merfolk_prospector_gains_a_gold_for_its_exhaust(self) -> None:
        from test_codex_card_rulings import red_green

        engine, game, match = red_green(first=2)
        merfolk = put(match, 2, "merfolk_prospector")
        match.player(2).gold = 0
        apply(engine, game, match, PromptKind.MAIN_ACTION, "ability",
              ability="merfolk_prospector", source=merfolk.ref)
        self.assertEqual(match.player(2).gold, 1)
        self.assertTrue(merfolk.exhausted)

    def test_pirategang_plays_blood_tech_i_and_ii_units_free_without_buildings(self) -> None:
        from test_codex_card_rulings import red_green

        engine, game, match = red_green(teams=(("anarchy",), ("growth",)))
        player = match.player(1)
        hand(match, 1, "crash_bomber", "land_octopus", "marauder")
        self.assertIn("needs a finished", why(engine, match, "crash_bomber"))
        put(match, 1, "pirategang_commander")
        player.gold = 0
        self.assertEqual(why(engine, match, "crash_bomber"), "")
        self.assertEqual(why(engine, match, "land_octopus"), "")
        self.assertEqual(engine.effective_cost(player, "land_octopus"), 0)
        self.assertNotEqual(why(engine, match, "marauder"), "", "Anarchy is not Blood")

    def test_boost_is_offered_with_its_cost_and_refused_where_it_cannot_be_paid(self) -> None:
        from codex_positions import built
        from test_codex_card_rulings import red_green

        engine, game, match = red_green(teams=(("anarchy",), ("growth",)))
        built(match, 1, "tech1")
        built(match, 1, "tech2")
        hand(match, 1, "marauder")
        player = match.player(1)
        player.gold = 4
        row = next(row for row in engine.playable(player, match) if row.slug == "marauder")
        self.assertEqual((row.cost, row.boost), (3, 3))
        self.assertEqual(row.boost_why_not, "not enough gold to boost")
        refused(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="marauder", boost=True)
        player.gold = 6
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="marauder", boost=True)
        self.assertEqual(player.gold, 0)


# -- Red and green: the spells' shapes (step 11) --------------------------------


class RedGreenSpellTests(unittest.TestCase):
    def feral(self):
        from test_codex_card_rulings import red_green

        engine, game, match = red_green(teams=(("feral",), ("anarchy",)))
        hero_in_play(match, 1)
        return engine, game, match

    def test_a_modal_spell_asks_one_unboosted_and_does_both_boosted(self) -> None:
        engine, game, match = self.feral()
        hand(match, 1, "murkwood_allies", "murkwood_allies")
        match.player(1).gold = 14
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="murkwood_allies")
        prompt = asked(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.MODE_CHOICE)
        self.assertEqual([key for key, _ in prompt.options.modes], ["beast", "frogs"])
        apply(engine, game, match, PromptKind.MODE_CHOICE, mode="beast")
        self.assertEqual(sorted(card.slug for card in match.player(1).play), ["beast"])
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="murkwood_allies", boost=True)
        self.assertEqual(sorted(card.slug for card in match.player(1).play),
                         ["beast", "beast", "frog", "frog", "frog", "frog"])
        self.assertEqual(match.player(1).gold, 0)

    def test_a_modal_spell_is_cancelled_from_its_choice(self) -> None:
        engine, game, match = self.feral()
        from codex import history

        hand(match, 1, "murkwood_allies")
        match.player(1).gold = 5
        match.turn_snapshots[-1] = history.position(match)
        match.journal = []
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="murkwood_allies")
        apply(engine, game, match, PromptKind.MODE_CHOICE, "cancel")
        self.assertEqual((match.player(1).hand, match.player(1).gold), (["murkwood_allies"], 5))

    def test_a_mode_not_offered_is_refused(self) -> None:
        engine, game, match = self.feral()
        hand(match, 1, "murkwood_allies")
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="murkwood_allies")
        refused(engine, game, match, PromptKind.MODE_CHOICE, mode="both")

    def test_done_is_offered_only_once_enough_is_chosen(self) -> None:
        from test_codex_card_rulings import red_green

        engine, game, match = red_green(teams=(("fire",), ("growth",)))
        hero_in_play(match, 1)
        put(match, 2, "tiger_cub", patrol="squad_leader")
        put(match, 2, "tiger_cub", patrol="elite")
        hand(match, 1, "ember_sparks")
        match.player(1).gold = 3
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="ember_sparks")
        self.assertFalse(asked(engine, game, match).options.done)
        refused(engine, game, match, PromptKind.TARGET, "done")
        apply(engine, game, match, PromptKind.TARGET, target="2:base")
        self.assertTrue(asked(engine, game, match).options.done)
        # A pick stays where it is, so it is not offered twice.
        self.assertNotIn("2:base", [row.key for row in asked(engine, game, match).options.targets])

    def test_a_spell_putting_a_card_into_play_takes_no_boost(self) -> None:
        engine, game, match = self.feral()
        match.player(1).hero.level = 5
        match.player(1).hero.max_level_since_turn_began = True
        hand(match, 1, "feral_strike", "tiger_cub")
        match.player(1).gold = 4
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="feral_strike")
        apply(engine, game, match, PromptKind.MODE_CHOICE, mode="put")
        apply(engine, game, match, PromptKind.TARGET, target="1:hand:tiger_cub")
        self.assertIn("tiger_cub", [card.slug for card in match.player(1).play])
        self.assertEqual(match.player(1).gold, 0)


class RedGreenUpkeepTests(unittest.TestCase):
    """Step 11's upkeep: which orders are asked (docs/design/codex.md, "Red
    and green")."""

    def next_upkeep(self, engine, game, match) -> None:
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        apply(engine, game, match, PromptKind.PATROL, assignment={})

    def test_the_owls_gold_is_never_asked(self) -> None:
        """A gain beside a death changes nothing either way, so the Owl's
        gold is run, not asked -- while Starlet beside healing still is."""
        engine, game, match = red_green()
        put(match, 2, "gemscout_owl")
        put(match, 2, "starcrossed_starlet")
        gold = match.player(2).gold
        self.next_upkeep(engine, game, match)
        self.assertIs(asked(engine, game, match).kind, PromptKind.MAIN_ACTION)
        self.assertEqual(match.player(2).gold, gold + match.player(2).workers + 1)

        engine, game, match = red_green()
        put(match, 2, "gemscout_owl")
        put(match, 2, "helpful_turtle")
        put(match, 2, "starcrossed_starlet")
        self.next_upkeep(engine, game, match)
        prompt = asked(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.UPKEEP_ORDER)
        self.assertNotIn("owl", prompt.options.effects)
        self.assertEqual(set(prompt.options.effects), {"healing", "starlet"})

    def test_land_octopus_is_asked_and_its_sacrifice_trashes_nothing_more(self) -> None:
        engine, game, match = red_green()
        octopus = put(match, 2, "land_octopus")
        self.next_upkeep(engine, game, match)
        self.assertIs(asked(engine, game, match).kind, PromptKind.MODE_CHOICE)
        apply(engine, game, match, PromptKind.MODE_CHOICE, mode="itself")
        self.assertIsNone(match.player(2).instance(octopus.id))
        self.assertIn("land_octopus", match.player(2).discard)

    def test_dothram_changes_sides_at_his_controllers_upkeep(self) -> None:
        engine, game, match = red_green()
        dothram = put(match, 2, "dothram_horselord")
        put(match, 1, "oversized_rhinoceros")
        put(match, 1, "iron_man")
        self.next_upkeep(engine, game, match)
        self.assertEqual(match.active, 2)
        self.assertEqual(dothram.controller, 1)


class LegendaryArrivalTests(unittest.TestCase):
    def test_a_second_galina_played_is_destroyed_on_arrival(self) -> None:
        engine, game, match = red_green(first=2)
        hero_in_play(match, 2)
        built(match, 2, "tech1")
        first = put(match, 2, "galina_glimmer")
        hand(match, 2, "galina_glimmer")
        match.player(2).gold = 5
        run = apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="galina_glimmer")
        galinas = [card for card in match.player(2).play if card.slug == "galina_glimmer"]
        self.assertEqual([card.id for card in galinas], [first.id])
        self.assertIn("galina_glimmer", match.player(2).discard)
        self.assertIn("{card:galina_glimmer}", said(run))


class ContinuousYourUnitsTests(unittest.TestCase):
    """Stampede's and Ferocity's "your units get" is continuous: a unit
    that comes under their caster while it lasts has it too (the author,
    2026-10-09)."""

    def test_a_unit_arriving_after_stampede_gets_it(self) -> None:
        from test_codex_card_rulings import at_max, red_green

        engine, game, match = red_green(first=2)
        at_max(engine, match, 2)
        before = put(match, 2, "tiger_cub")
        cast(engine, game, match, "stampede", gold=6)
        later = board.put_into_play(engine, match, "tiger_cub", 2, from_hand=False)
        for cub in (before, later):
            self.assertEqual(engine.unit_stats(cub, match)[0], 2 + 3)
            self.assertEqual(cub.armor, 3)
            self.assertTrue(engine.stampedes(match, cub))
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        apply(engine, game, match, PromptKind.PATROL, assignment={})
        self.assertEqual(engine.unit_stats(later, match)[0], 2)
        self.assertEqual(later.armor, 0)
        self.assertFalse(engine.stampedes(match, later))
        self.assertEqual(match.player(2).lasting, [])

    def test_a_unit_taken_from_a_stampeding_side_loses_it(self) -> None:
        from test_codex_card_rulings import at_max, red_green

        engine, game, match = red_green(first=2)
        at_max(engine, match, 2)
        cub = put(match, 2, "tiger_cub")
        cast(engine, game, match, "stampede", gold=6)
        board.gain_control(match, cub, 1)
        self.assertEqual(engine.unit_stats(cub, match)[0], 2)
        self.assertFalse(engine.stampedes(match, cub))

    def test_a_unit_arriving_after_ferocity_gets_it_until_the_next_upkeep(self) -> None:
        from test_codex_card_rulings import red_green

        engine, game, match = red_green(teams=(("feral",), ("anarchy",)))
        hero_in_play(match, 1)
        cast(engine, game, match, "ferocity", gold=2)
        later = board.put_into_play(engine, match, "tiger_cub", 1, from_hand=False)
        self.assertTrue(engine.has_keyword(later, "Armor piercing", match))
        self.assertTrue(engine.has_keyword(later, "Swift strike", match))
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        apply(engine, game, match, PromptKind.PATROL, assignment={})
        self.assertTrue(engine.has_keyword(later, "Swift strike", match), "through their turn")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        apply(engine, game, match, PromptKind.PATROL, assignment={})
        picks = [slug for slug, _ in asked(engine, game, match).options.codex[:2]]
        apply(engine, game, match, PromptKind.TECH_CHOICE, player=1, picks=picks)
        apply(engine, game, match, PromptKind.TECH_CONFIRM, "confirm", player=1)
        self.assertEqual((match.active, match.phase), (1, "main"))
        self.assertFalse(engine.has_keyword(later, "Swift strike", match))
        self.assertEqual(match.player(1).lasting, [])


if __name__ == "__main__":
    unittest.main()


#: The hero each purple and black spec's spells ask for (step 12), and the
#: seat that side sits in under `pb`.
SPEC_HEROES = {
    "Past": (1, "prynn_pasternaak"), "Present": (1, "max_geiger"),
    "Future": (1, "vir_garbarean"), "Demonology": (2, "vandy_anadrose"),
    "Disease": (2, "orpal_gloor"), "Necromancy": (2, "garth_torken"),
}


def _spells(*, ultimate: bool):
    from codex import effects
    from codex.cards import catalog

    cards = catalog()
    for slug in sorted(effects.PURPLE | effects.BLACK):
        card = cards.by_slug(slug)
        kind = str(getattr(card, "type", ""))
        if "Spell" in kind and card.spec and ("Ultimate" in kind) == ultimate:
            yield slug, card.spec


class PurpleAndBlackRefusalTests(unittest.TestCase):
    """Each purple and black spell refused where the UMR refuses it (p. 7):
    a spec spell without its spec's hero, an ultimate before its hero has
    stood at its maximum since the turn began, a minor spell with no hero
    at all (step 12)."""

    def test_a_spec_spell_needs_its_specs_hero(self) -> None:
        from test_codex_card_rulings import pb

        for slug, spec in _spells(ultimate=False):
            with self.subTest(spell=slug):
                seat, wanted = SPEC_HEROES[spec]
                engine, game, match = pb(first=seat)
                other = next(h.slug for h in match.player(seat).heroes if h.slug != wanted)
                hero_in_play(match, seat, slug=other)
                hand(match, seat, slug)
                match.player(seat).gold = 20
                self.assertIn(f"{spec} hero", why(engine, match, slug))
                refused(engine, game, match, PromptKind.MAIN_ACTION, "play", slug=slug)

    def test_an_ultimate_waits_for_its_hero_at_the_maximum(self) -> None:
        from test_codex_card_rulings import pb

        for slug, spec in _spells(ultimate=True):
            with self.subTest(spell=slug):
                seat, wanted = SPEC_HEROES[spec]
                engine, game, match = pb(first=seat)
                hero_in_play(match, seat, slug=wanted, level=3)
                hand(match, seat, slug)
                match.player(seat).gold = 20
                self.assertIn("maximum level", why(engine, match, slug))
                refused(engine, game, match, PromptKind.MAIN_ACTION, "play", slug=slug)

    def test_a_minor_spell_needs_a_hero_in_play(self) -> None:
        from test_codex_card_rulings import pb

        for slug in ("deteriorate", "forgotten_fighter", "sacrifice_the_weak",
                     "summon_skeletons", "temporal_research", "time_spiral"):
            with self.subTest(spell=slug):
                engine, game, match = pb()
                hand(match, 1, slug)
                match.player(1).gold = 20
                self.assertIn("needs a hero in play", why(engine, match, slug))
                refused(engine, game, match, PromptKind.MAIN_ACTION, "play", slug=slug)


class PurpleSpellTests(unittest.TestCase):
    """Each purple spell's happy path (step 12)."""

    def setUp(self) -> None:
        from test_codex_card_rulings import pb

        self.engine, self.game, self.match = pb()
        for spec in ("Past", "Present", "Future"):
            hero_in_play(self.match, 1, slug=SPEC_HEROES[spec][1])

    def cast(self, slug, *targets) -> None:
        cast(self.engine, self.game, self.match, slug, *targets)

    def test_now_gives_haste(self) -> None:
        unit = put(self.match, 1, "argonaut", arrived=True)
        self.cast("now", f"1:{unit.ref}")
        self.assertTrue(self.engine.has_keyword(unit, "Haste", self.match))

    def test_undo_returns_a_unit_to_its_owners_hand(self) -> None:
        unit = put(self.match, 2, "skeleton")
        target = put(self.match, 2, "hooded_executioner")
        del unit
        self.cast("undo", f"2:{target.ref}")
        self.assertIn("hooded_executioner", self.match.player(2).hand)

    def test_origin_story_sends_a_hero_home(self) -> None:
        hero_in_play(self.match, 2, slug="garth_torken")
        self.cast("origin_story", "2:hero:garth_torken")
        self.assertEqual(self.match.player(2).hero_of("garth_torken").zone, "command")

    def test_promise_of_payment_makes_the_next_card_free_and_owed(self) -> None:
        built(self.match, 1, "tech1")
        self.cast("promise_of_payment")
        hand(self.match, 1, "argonaut")
        self.match.player(1).gold = 0
        apply(self.engine, self.game, self.match, PromptKind.MAIN_ACTION, "play", slug="argonaut")
        self.assertEqual(self.match.player(1).debt, 3)

    def test_temporal_research_draws_by_the_time_runes(self) -> None:
        player = self.match.player(1)
        player.deck = ["argonaut"] * 5
        for _ in range(3):
            put(self.match, 1, "fading_argonaut").time_runes = 1
        self.cast("temporal_research")
        self.assertEqual(player.hand, ["argonaut"] * 2, "3 time runes: a second card, not a third")

    def test_research_and_development_draws_five(self) -> None:
        from test_codex_card_rulings import at_max

        at_max(self.engine, self.match, 1, "max_geiger")
        player = self.match.player(1)
        player.deck = ["argonaut"] * 8
        self.cast("research__development")
        self.assertEqual(player.hand, ["argonaut"] * 5)

    def test_rewind_returns_every_low_tech_unit(self) -> None:
        from test_codex_card_rulings import at_max

        at_max(self.engine, self.match, 1, "prynn_pasternaak")
        put(self.match, 1, "argonaut")
        put(self.match, 2, "hooded_executioner")
        self.cast("rewind")
        self.assertIn("argonaut", self.match.player(1).hand)
        self.assertIn("hooded_executioner", self.match.player(2).hand)


class BlackSpellTests(unittest.TestCase):
    """Each black spell's happy path (step 12)."""

    def setUp(self) -> None:
        from test_codex_card_rulings import pb

        self.engine, self.game, self.match = pb(first=2)
        for spec in ("Demonology", "Disease", "Necromancy"):
            hero_in_play(self.match, 2, slug=SPEC_HEROES[spec][1])

    def cast(self, slug, *targets) -> None:
        cast(self.engine, self.game, self.match, slug, *targets)

    def test_dark_pact_hurts_a_base_and_draws_its_player_two(self) -> None:
        player = self.match.player(1)
        player.deck = ["argonaut"] * 4
        before = len(player.hand)
        prompt_target = "1:base"
        hand(self.match, 2, "dark_pact")
        self.match.player(2).gold = 0
        apply(self.engine, self.game, self.match, PromptKind.MAIN_ACTION, "play", slug="dark_pact")
        prompt = asked(self.engine, self.game, self.match)
        if prompt.kind is PromptKind.TARGET:
            apply(self.engine, self.game, self.match, PromptKind.TARGET, target=prompt_target)
        self.assertEqual(player.base_hp, 18)
        self.assertEqual(len(player.hand), before + 2)

    def test_sickness_puts_two_minus_runes(self) -> None:
        a = put(self.match, 1, "argonaut")
        b = put(self.match, 1, "neo_plexus")
        self.cast("sickness", f"1:{a.ref}", f"1:{b.ref}")
        self.assertEqual((a.minus_runes, b.minus_runes), (1, 1))

    def test_summon_skeletons_summons_two(self) -> None:
        self.cast("summon_skeletons")
        self.assertEqual(sum(card.slug == "skeleton" for card in self.match.player(2).play), 2)

    def test_spreading_plague_destroys_the_runed(self) -> None:
        runed = put(self.match, 1, "argonaut")
        runed.minus_runes = 1
        clean = put(self.match, 1, "neo_plexus")
        self.cast("spreading_plague")
        self.assertIsNone(self.match.player(1).instance(runed.id))
        self.assertIsNotNone(self.match.player(1).instance(clean.id))

    def test_death_and_decay_weakens_and_burns(self) -> None:
        from test_codex_card_rulings import at_max

        at_max(self.engine, self.match, 2, "orpal_gloor")
        put(self.match, 1, "neo_plexus")
        before = self.match.player(1).base_hp
        self.cast("death_and_decay")
        self.assertFalse(any(card.slug == "neo_plexus" for card in self.match.player(1).play))
        self.assertEqual(self.match.player(1).base_hp, before - 3)

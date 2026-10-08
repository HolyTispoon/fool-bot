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

from codex.components import HERO, AddOnState
from codex.flow import board, driver
from codex.prompts import Action, PromptKind, pending_prompt

from codex_positions import built, hand, hero_in_play, put
from test_codex_card_rulings import apply, asked, bashing, cast, finesse, ultimate_ready


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
        self.assertEqual(offered, {(1, HERO), (1, mine.ref), (2, theirs.ref)})
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

    def test_troq_at_5_can_win_the_game_before_the_damage(self) -> None:
        engine, game, match = bashing()
        hero_in_play(match, 1, level=5)
        match.player(2).base_hp = 1
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=HERO)
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
              ability="river_montoya", source=HERO)
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


if __name__ == "__main__":
    unittest.main()

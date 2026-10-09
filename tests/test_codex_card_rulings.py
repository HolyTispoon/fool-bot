"""
The cards' own rulings, **one test per ruling** (docs/codex-bot.md,
step 6).

Sirlin's rulings are official rules of the game (decision 7): each ruling
`codex/data/rulings.json` makes about a card of the basic set is a test
below, named `test_<the card's slug>_<its number in the file>` with the
ruling as its docstring, and `EveryCardRulingIsPinnedTests` holds the
two together -- it fails if a ruling has no test, if a test's docstring
is not its ruling's words, or if a re-import changes how many rulings
the set's cards carry. **There are 28 at the pinned import**: the step's
prompt counted 26, before the Dancer and the Angry Dancer were counted as
the two records their one shared ruling names.

Positions are staged by slug (`tests/codex_positions.py`), and every
action goes through `codex.flow.driver.apply`, the one door.
"""

from __future__ import annotations

import re
import unittest
from unittest import mock

from codex import effects, rulings
from codex.components import AddOnState
from codex.effects import BASIC_SET, BLACK, GREEN, PURPLE, RED
from codex.flow import board, driver
from codex.prompts import Action, PromptKind, pending_prompt

from codex_positions import TROQ, begin, built, hand, hero, hero_in_play, new_game, put

#: How many rulings the basic set's cards carry at the pinned import
#: (`SOURCE_SHA` in `scripts/import_codex_cards.py`).
CARD_RULINGS = 28

#: Step 11: the rulings on red's and green's cards, heroes and tokens --
#: 88 on the cards and 13 on the four heroes.
RED_GREEN_RULINGS = 101


def bashing():
    """Bashing (seat 1) in its first main phase."""
    engine, game, match = new_game()
    begin(engine, game, match)
    return engine, game, match


def finesse():
    """Finesse (seat 2) in its first main phase: it goes first."""
    engine, game, match = new_game(first=2)
    begin(engine, game, match)
    return engine, game, match


def apply(engine, game, match, kind, choice="", **arguments):
    run = driver.apply(engine, game, match, Action(kind, choice, arguments))
    assert not isinstance(run, driver.Refusal), run
    return run


def asked(engine, game, match):
    return pending_prompt(engine, game, match)


def cast(engine, game, match, slug, *targets, gold: int = 20):
    """`slug` from the active player's hand, each target answered in
    turn where the spell asks one."""
    seat = match.active
    hand(match, seat, slug)
    match.player(seat).gold = gold
    apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug=slug)
    for target in targets:
        prompt = asked(engine, game, match)
        assert prompt.kind is PromptKind.TARGET, prompt
        apply(engine, game, match, PromptKind.TARGET, target=target)


def ultimate_ready(match, seat: int) -> None:
    hero_in_play(match, seat, level=match.player(seat).hero.level)
    hero = match.player(seat).hero
    hero.level = 8 if hero.slug == "troq_bashar" else 5
    hero.max_level_since_turn_began = True


def harmony(match, seat: int):
    return put(match, seat, "harmony")


class DancerTests(unittest.TestCase):
    def test_angry_dancer_1(self) -> None:
        """When you flip over a Dancer to become an Angry Dancer (by using
        Harmony's sacrifice ability), this does not count as a new unit
        entering play. No "arrive" happens here. If the Dancer had any
        baggage, such as +1/+1 runes, an ongoing spell such as a Soul Stone
        or Spirit of the Panda, or damage on it, all of that will still be
        on it when it flips over."""
        engine, game, match = finesse()
        hero_in_play(match, 2)
        song = harmony(match, 2)
        dancer = put(match, 2, "dancer", damage=1)
        dancer.plus_runes = 1
        apply(engine, game, match, PromptKind.MAIN_ACTION, "ability",
              ability="stop_the_music", source=song.ref)
        self.assertEqual(dancer.slug, "angry_dancer")
        self.assertEqual((dancer.plus_runes, dancer.damage), (1, 1))
        self.assertEqual(engine.unit_stats(dancer, match), (3, 2))
        # No arrival: it was ready, and it still is, so it may attack.
        self.assertFalse(dancer.arrived_this_turn)
        self.assertIn(dancer.ref, engine.attackers(match))

    def test_dancer_1(self) -> None:
        """When you flip over a Dancer to become an Angry Dancer (by using
        Harmony's sacrifice ability), this does not count as a new unit
        entering play. No "arrive" happens here. If the Dancer had any
        baggage, such as +1/+1 runes, an ongoing spell such as a Soul Stone
        or Spirit of the Panda, or damage on it, all of that will still be
        on it when it flips over."""
        engine, game, match = finesse()
        hero_in_play(match, 2)
        song = harmony(match, 2)
        first = put(match, 2, "dancer")
        second = put(match, 2, "dancer", arrived=True)
        second.minus_runes = 0
        before = match.next_instance_id
        apply(engine, game, match, PromptKind.MAIN_ACTION, "ability",
              ability="stop_the_music", source=song.ref)
        self.assertEqual([first.slug, second.slug], ["angry_dancer", "angry_dancer"])
        self.assertTrue(first.flipped and second.flipped)
        # The same cards: nothing new entered play.
        self.assertEqual(match.next_instance_id, before)
        self.assertTrue(second.arrived_this_turn)
        self.assertFalse(first.arrived_this_turn)


class AppelStompTests(unittest.TestCase):
    def test_appel_stomp_1(self) -> None:
        """If you choose not to put Appel Stomp on top of your draw pile, it
        will go to your discard pile."""
        engine, game, match = finesse()
        ultimate_ready(match, 2)
        lizard = put(match, 1, "leaping_lizard", patrol="squad_leader")
        player = match.player(2)
        cast(engine, game, match, "appel_stomp")
        self.assertIsNone(lizard.patrol_slot, "the one patroller is sidelined")
        self.assertIs(asked(engine, game, match).kind, PromptKind.APPEL_STOMP_TOP)
        apply(engine, game, match, PromptKind.APPEL_STOMP_TOP, "discard")
        self.assertEqual(player.discard[-1], "appel_stomp")
        self.assertNotIn("appel_stomp", player.deck)


class BlademasterTests(unittest.TestCase):
    def test_blademaster_1(self) -> None:
        """Your units and heroes only keep swift strike from Blademaster's
        ability while he's still in play under your control. If he leaves
        play or leaves your control, he won't continue to grant swift
        strike."""
        engine, game, match = finesse()
        hero_in_play(match, 2)
        master = put(match, 2, "blademaster")
        foot = put(match, 2, "tenderfoot")
        river = match.player(2).hero
        for body in (master, foot, river):
            self.assertTrue(engine.has_keyword(body, "Swift strike", match))
        board.gain_control(match, master, 1)
        self.assertFalse(engine.has_keyword(foot, "Swift strike", match))
        self.assertFalse(engine.has_keyword(river, "Swift strike", match))
        board.gain_control(match, master, 2)
        board.leave_play(engine, match, master, "discard")
        self.assertFalse(engine.has_keyword(foot, "Swift strike", match))


class BrickThiefTests(unittest.TestCase):
    def test_brick_thief_1(self) -> None:
        """When his ability has you "repair 1 damage from a building", you
        can choose one of your own buildings that is not damaged. If you
        do, nothing happens to your building (your building does not get
        extra hit points above its max HP)."""
        engine, game, match = bashing()
        built(match, 2, "tech1")
        hand(match, 1, "brick_thief")
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="brick_thief")
        apply(engine, game, match, PromptKind.TARGET, target="2:tech1")
        offered = [row.key for row in asked(engine, game, match).options.targets]
        self.assertIn("1:base", offered)
        apply(engine, game, match, PromptKind.TARGET, target="1:base")
        self.assertEqual(match.player(1).base_hp, 20)
        self.assertEqual(match.player(2).buildings["tech1"].hp, 4)

    def test_brick_thief_2(self) -> None:
        """"Arrives or attacks:" means you get the effect when he arrives,
        AND you also get the effect each time he attacks. You don't have to
        choose."""
        engine, game, match = bashing()
        hand(match, 1, "brick_thief")
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="brick_thief")
        apply(engine, game, match, PromptKind.TARGET, target="2:base")
        # The repair's one other building is his own base: taken unasked.
        self.assertEqual(match.player(2).base_hp, 19)
        thief = match.player(1).play[-1]
        thief.arrived_this_turn = False
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=thief.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="base")
        self.assertIs(asked(engine, game, match).kind, PromptKind.TARGET,
                      "its attacks trigger, before the damage")
        apply(engine, game, match, PromptKind.TARGET, target="2:base")
        self.assertEqual(match.player(2).base_hp, 19 - 1 - 2)


class DiscordTests(unittest.TestCase):
    def test_discord_1(self) -> None:
        """If a unit with only 1 HP is affected by this, it will die
        (because it has 0 HP) even if it had armor."""
        engine, game, match = finesse()
        hero_in_play(match, 2)
        messenger = put(match, 1, "timely_messenger", patrol="squad_leader")
        messenger.armor = 1
        cast(engine, game, match, "discord")
        self.assertIsNone(match.player(1).instance(messenger.id))
        self.assertIn("timely_messenger", match.player(1).discard)


class FinalSmashTests(unittest.TestCase):
    def test_final_smash_1(self) -> None:
        """You "do as much as you can" when playing this. For example, if
        there is no tech 0 in play, you still do the rest of the spell."""
        engine, game, match = bashing()
        ultimate_ready(match, 1)
        fencer = put(match, 2, "nimble_fencer")
        guide = put(match, 2, "grounded_guide")
        cast(engine, game, match, "final_smash")
        self.assertIn("nimble_fencer", match.player(2).hand)
        self.assertIsNone(match.instance(fencer.id))
        self.assertEqual(guide.controller, 1)
        self.assertEqual(match.player(1).discard[-1], "final_smash")

    def test_final_smash_2(self) -> None:
        """The effects are not optional. If the only tech 0 unit in play is
        yours, you must destroy it. If the only tech I unit in play is
        yours, you must return it to its owner's hand. If the only tech II
        unit in play is yours, you "gain control of it" which does
        nothing."""
        engine, game, match = bashing()
        ultimate_ready(match, 1)
        foot = put(match, 1, "tenderfoot")
        iron = put(match, 1, "iron_man")
        egg = put(match, 1, "eggship")
        cast(engine, game, match, "final_smash")
        player = match.player(1)
        self.assertIsNone(player.instance(foot.id))
        self.assertIn("tenderfoot", player.discard)
        self.assertIsNone(player.instance(iron.id))
        self.assertIn("iron_man", player.hand)
        self.assertIs(player.instance(egg.id), egg)
        self.assertFalse(egg.arrived_this_turn, "gaining control of your own does nothing")

    def test_final_smash_3(self) -> None:
        """You choose targets as you resolve each part of the spell, not all
        at once before you do anything. That means if there's an opposing
        flagbearer in play that CAN be targeted by the first part of the
        spell (destroy a tech 0 unit) then you must target it. Then after
        that, if there is an opposing flagbearer that CAN be targeted by
        the second part of the spell (return a tech I unit to its owner's
        hand) AND you didn't already target it earlier in resolving this
        same cast of Final Smash, then you MUST target it."""
        engine, game, match = bashing()
        ultimate_ready(match, 1)
        flags = [put(match, 2, "granfalloon_flagbearer"), put(match, 2, "granfalloon_flagbearer")]
        foot = put(match, 2, "tenderfoot")
        fencer = put(match, 2, "nimble_fencer")
        starlet = put(match, 2, "starcrossed_starlet")
        hand(match, 1, "final_smash")
        match.player(1).gold = 20
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="final_smash")
        first = asked(engine, game, match)
        self.assertTrue(first.options.forced)
        self.assertEqual({row.ref for row in first.options.targets}, {flag.ref for flag in flags})
        refused = driver.apply(engine, game, match,
                               Action(PromptKind.TARGET, "", {"target": f"2:{foot.ref}"}))
        self.assertIsInstance(refused, driver.Refusal)
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{flags[0].ref}")
        # The second part chooses as it resolves: no flagbearer can be a
        # tech I unit, so it is not forced.
        second = asked(engine, game, match)
        self.assertEqual(second.options.part, 1)
        self.assertFalse(second.options.forced)
        self.assertEqual({row.ref for row in second.options.targets}, {fencer.ref, starlet.ref})
        self.assertIsNone(match.player(2).instance(flags[0].id))
        self.assertIs(match.player(2).instance(flags[1].id), flags[1])


class GroundedGuideTests(unittest.TestCase):
    def test_grounded_guide_1(self) -> None:
        """This effect stacks if you have two of them. For example, your
        Virtuosos get +4/+2 if you have two Grounded Guides."""
        engine, game, match = finesse()
        foot = put(match, 2, "tenderfoot")
        brother = put(match, 2, "older_brother")
        first = put(match, 2, "grounded_guide")
        second = put(match, 2, "grounded_guide")
        self.assertEqual(engine.unit_stats(foot, match), (1 + 4, 2 + 2))
        self.assertEqual(engine.unit_stats(brother, match), (2 + 2, 2))
        # Each Guide's other units: the other Guide, not itself.
        self.assertEqual(engine.unit_stats(first, match), (5, 4))
        self.assertEqual(engine.unit_stats(second, match), (5, 4))


class HarmonyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine, self.game, self.match = finesse()
        hero_in_play(self.match, 2)

    def dancers(self) -> list:
        return [card for card in self.match.player(2).play if card.slug == "dancer"]

    def test_harmony_1(self) -> None:
        """Harmony does not trigger itself when you play it. You have to
        play another spell after Harmony in order to get your first Dancer
        token."""
        engine, game, match = self.engine, self.game, self.match
        cast(engine, game, match, "harmony")
        self.assertEqual(self.dancers(), [])
        put(match, 1, "older_brother", patrol="elite")
        cast(engine, game, match, "spark")
        self.assertEqual(len(self.dancers()), 1)

    def test_harmony_2(self) -> None:
        """You can't target the Dancer token Harmony summons with the very
        same spell that triggered Harmony. For example, if you play Bloom
        to give a unit +1/+1, that will cause Harmony to give you a new
        Dancer token, but you must completely resolve Bloom BEFORE you even
        get the new Dancer token."""
        engine, game, match = self.engine, self.game, self.match
        harmony(match, 2)
        foot = put(match, 2, "tenderfoot")
        hand(match, 2, "bloom")
        match.player(2).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="bloom")
        offered = [row.ref for row in asked(engine, game, match).options.targets]
        self.assertEqual(sorted(offered), sorted([foot.ref, hero(match, 2)]))
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{foot.ref}")
        (dancer,) = self.dancers()
        self.assertEqual(dancer.plus_runes, 0)
        self.assertEqual(foot.plus_runes, 1)

    def test_harmony_3(self) -> None:
        """If you lose your Finesse hero, that forces you to sacrifice
        Harmony. This does NOT count as paying the cost to "Stop the music"
        so this will not cause your Dancers to flip over to become Angry
        Dancers."""
        engine, game, match = self.engine, self.game, self.match
        song = harmony(match, 2)
        dancer = put(match, 2, "dancer")
        result = driver.StepResult()
        board.destroy(engine, match, [(2, hero(match, 2))], result)
        board.settle(engine, match, result)
        self.assertIsNone(match.player(2).instance(song.id))
        self.assertIn("harmony", match.player(2).discard)
        self.assertEqual(dancer.slug, "dancer")

    def test_harmony_4(self) -> None:
        """The purpose of "stopping the music" is to flip over any Dancers
        you control. Doing this transforms them to Angry Dancers."""
        engine, game, match = self.engine, self.game, self.match
        song = harmony(match, 2)
        dancer = put(match, 2, "dancer")
        theirs = put(match, 1, "dancer")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "ability",
              ability="stop_the_music", source=song.ref)
        self.assertEqual(dancer.slug, "angry_dancer")
        self.assertEqual(theirs.slug, "dancer", "only the Dancers you control")
        self.assertIn("harmony", match.player(2).discard)
        self.assertTrue(engine.has_keyword(dancer, "Unstoppable", match))


class IntimidateTests(unittest.TestCase):
    def test_intimidate_1(self) -> None:
        """0 is the lowest ATK a unit can have."""
        engine, game, match = bashing()
        hero_in_play(match, 1)
        ninja = put(match, 2, "fruit_ninja", patrol="elite")
        cast(engine, game, match, "intimidate", f"2:{ninja.ref}")
        self.assertEqual(engine.unit_stats(ninja, match)[0], 0)
        # Its elite's +1 does not bring it back above 0: 2 - 4 + 1.
        self.assertEqual(engine.attack_value(match, 2, ninja.ref), 0)


class MaestroTests(unittest.TestCase):
    def test_maestro_1(self) -> None:
        """As usual, you can't exhaust a unit as a cost to use its ability
        unless you controlled that unit at the start of your turn or if it
        has haste. So you had to have controlled your Virtuosos at the
        start of your turn in order to exhaust them to do 2 damage. It
        doesn't matter that they got the ability in the middle of the turn
        and it also doesn't matter when Maestro came under your control or
        if Maestro has haste."""
        engine, game, match = finesse()
        put(match, 2, "maestro", arrived=True)
        old = put(match, 2, "tenderfoot")
        new = put(match, 2, "tenderfoot", arrived=True)
        by_source = {one.source: one for one in engine.abilities(match)}
        self.assertTrue(by_source[old.ref].allowed)
        self.assertIn("arrived this turn", by_source[new.ref].why_not)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "ability",
              ability="maestro", source=old.ref)
        apply(engine, game, match, PromptKind.TARGET, target="1:base")
        self.assertEqual(match.player(1).base_hp, 18)
        self.assertTrue(old.exhausted)


class NimbleFencerTests(unittest.TestCase):
    def test_nimble_fencer_1(self) -> None:
        """Nimble Fencer herself is a Virtuoso, so her ability grants
        herself haste."""
        engine, game, match = finesse()
        fencer = put(match, 2, "nimble_fencer", arrived=True)
        self.assertTrue(engine.has_keyword(fencer, "Haste", match))
        self.assertIn(fencer.ref, engine.attackers(match))


class RiverMontoyaTests(unittest.TestCase):
    def test_river_montoya_1(self) -> None:
        """You can only reduce the gold cost of something to 0, not lower
        than that."""
        engine, game, match = finesse()
        hero_in_play(match, 2, level=5)
        player = match.player(2)
        self.assertEqual(engine.effective_cost(player, "timely_messenger"), 0)
        self.assertEqual(engine.effective_cost(player, "brick_thief"), 1)
        self.assertEqual(engine.effective_cost(player, "nimble_fencer"), 2, "tech I is not tech 0")
        hand(match, 2, "timely_messenger")
        player.gold = 0
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="timely_messenger")
        self.assertEqual(player.gold, 0)


class StarCrossedStarletTests(unittest.TestCase):
    def upkeep(self, starlet_damage: int, first: str):
        """Seat 2's upkeep, with a Helpful Turtle and a Starlet, the order
        chosen."""
        engine, game, match = bashing()
        put(match, 2, "helpful_turtle")
        starlet = put(match, 2, "starcrossed_starlet", damage=starlet_damage)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        apply(engine, game, match, PromptKind.PATROL, assignment={})
        self.assertIs(asked(engine, game, match).kind, PromptKind.UPKEEP_ORDER)
        apply(engine, game, match, PromptKind.UPKEEP_ORDER, first=first)
        return engine, game, match, starlet

    def test_starcrossed_starlet_1(self) -> None:
        """If you have a healing effect during your upkeep from another card
        such as Helpful Turtle, you, as the active player, can choose the
        order of your upkeep effects. So you can choose to heal
        Star-Crossed Starlet BEFORE she takes 1 damage from her own upkeep
        ability in that case."""
        engine, game, match, starlet = self.upkeep(1, "healing")
        self.assertIs(match.player(2).instance(starlet.id), starlet)
        self.assertEqual(starlet.damage, 1)
        engine, game, match, starlet = self.upkeep(1, "starlet")
        self.assertIsNone(match.player(2).instance(starlet.id),
                          "her own damage first takes her to 2, which kills her")

    def test_starcrossed_starlet_2(self) -> None:
        """Normally, Star-Crossed Starlet can have only 1 damage on her (and
        therefore +1 ATK from her ability) without dying. 2 damage is
        enough to kill her. But if she has a +1/+1 rune on her, for example
        from Bloom, then she has a total of 3 HP and can therefore have 2
        damage on her (and +2 ATK from her ability) without dying."""
        engine, game, match = finesse()
        hero_in_play(match, 2)
        starlet = put(match, 2, "starcrossed_starlet", damage=1)
        self.assertEqual(engine.unit_stats(starlet, match), (4, 2))
        starlet.plus_runes = 1
        starlet.damage = 2
        result = driver.StepResult()
        board.settle(engine, match, result)
        self.assertIs(match.player(2).instance(starlet.id), starlet)
        self.assertEqual(engine.unit_stats(starlet, match), (3 + 1 + 2, 3))
        starlet.plus_runes = 0
        board.settle(engine, match, result)
        self.assertIsNone(match.player(2).instance(starlet.id))


class TheBootTests(unittest.TestCase):
    def test_the_boot_1(self) -> None:
        """When a unit is "destroyed" it will go to its owner's discard
        pile and also "die" as a consequence of that. Anything that
        triggers on "dies" such as the patrol zone's scavenger and
        technician slots, or a Soul Stone, will trigger."""
        engine, game, match = bashing()
        hero_in_play(match, 1)
        scavenger = put(match, 2, "iron_man", patrol="scavenger")
        gold = match.player(2).gold
        cast(engine, game, match, "the_boot")
        self.assertIsNone(match.player(2).instance(scavenger.id))
        self.assertEqual(match.player(2).discard[-1], "iron_man")
        self.assertEqual(match.player(2).gold, gold + 1)


class TrojanDuckTests(unittest.TestCase):
    def test_trojan_duck_1(self) -> None:
        """Obliterate never targets units in Codex, so it can work even on
        units that are untargetable. The ability that deals 4 damage to a
        building does target the building, so it can't hit Fox's Den
        School (unless you have a detector) or Hero's Monument, for
        example."""
        engine, game, match = bashing()
        duck = put(match, 1, "trojan_duck")
        stabber = put(match, 2, "backstabber")
        self.assertFalse(engine.targetable(match, 1, 2, stabber.ref))
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=duck.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="base")
        self.assertIsNone(match.player(2).instance(stabber.id), "obliterated, untargetable or not")
        prompt = asked(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.TARGET)
        from codex.effects import EFFECTS
        self.assertTrue(EFFECTS["trojan_duck"].parts[0].targeted)

    def test_trojan_duck_2(self) -> None:
        """"Arrives or attacks:" means you get the effect when it arrives,
        AND you also get the effect each time it attacks. You don't have to
        choose."""
        engine, game, match = bashing()
        built(match, 1, "tech3")
        hand(match, 1, "trojan_duck")
        match.player(1).gold = 20
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="trojan_duck")
        apply(engine, game, match, PromptKind.TARGET, target="2:base")
        self.assertEqual(match.player(2).base_hp, 16)
        duck = match.player(1).play[-1]
        duck.arrived_this_turn = False
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=duck.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="base")
        apply(engine, game, match, PromptKind.TARGET, target="2:base")
        self.assertEqual(match.player(2).base_hp, 16 - 4 - 8)


class TroqBasharTests(unittest.TestCase):
    def test_troq_bashar_1(self) -> None:
        """When Troq attacks something, his middle ability is saying to deal
        1 damage to the base controlled by the same player who controls the
        thing he's attacking."""
        engine, game, match = bashing()
        hero_in_play(match, 1, level=5)
        brother = put(match, 2, "older_brother")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=TROQ)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender=brother.ref)
        self.assertEqual(match.player(2).base_hp, 19)
        self.assertEqual(match.player(1).base_hp, 20)


class TwoStepTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine, self.game, self.match = finesse()
        hero_in_play(self.match, 2)

    def test_two_step_1(self) -> None:
        """If a unit is already a dance partner from Two Step, you can't
        legally target it by playing another Two Step."""
        engine, game, match = self.engine, self.game, self.match
        first = put(match, 2, "tenderfoot")
        second = put(match, 2, "older_brother")
        third = put(match, 2, "fruit_ninja")
        fourth = put(match, 2, "helpful_turtle")
        cast(engine, game, match, "two_step", f"2:{first.ref}", f"2:{second.ref}")
        hand(match, 2, "two_step")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="two_step")
        offered = {row.ref for row in asked(engine, game, match).options.targets}
        self.assertEqual(offered, {third.ref, fourth.ref})

    def test_two_step_2(self) -> None:
        """"If you lose one" means if one of your partnered units leaves play
        or leaves your control."""
        engine, game, match = self.engine, self.game, self.match
        first = put(match, 2, "tenderfoot")
        second = put(match, 2, "older_brother")
        # The second partner is the one unit left: taken unasked.
        cast(engine, game, match, "two_step", f"2:{first.ref}")
        step = next(card for card in match.player(2).play if card.slug == "two_step")
        self.assertEqual(engine.unit_stats(first, match), (3, 4))
        board.gain_control(match, second, 1)
        board.settle(engine, match, driver.StepResult())
        self.assertIsNone(match.player(2).instance(step.id))
        self.assertEqual(engine.unit_stats(first, match), (1, 2))


class WitherTests(unittest.TestCase):
    def test_wither_1(self) -> None:
        """If you put the -1/-1 rune on an X/1 unit, that will unit will die
        (because it has 0 HP) even if it had armor."""
        engine, game, match = bashing()
        hero_in_play(match, 1)
        messenger = put(match, 2, "timely_messenger", patrol="squad_leader")
        messenger.armor = 1
        cast(engine, game, match, "wither", f"2:{messenger.ref}")
        self.assertIsNone(match.player(2).instance(messenger.id))


# -- Red and green (step 11) ---------------------------------------------------
#
# Every ruling of the Red, Green and Heroes groups on the pair's cards and
# heroes, one test each, named and pinned as the basic set's are.


def red_green(first: int = 1, teams=(("anarchy",), ("growth",))):
    """A basic game of red against green -- Anarchy (seat 1) against
    Growth by default, or `teams` -- standing in `first`'s main phase."""
    engine, game, match = new_game(first=first, teams=teams)
    begin(engine, game, match)
    return engine, game, match


def ability(engine, game, match, effect: str, source: str):
    return apply(engine, game, match, PromptKind.MAIN_ACTION, "ability",
                 ability=effect, source=source)


def option(engine, match, effect: str, source: str):
    return next(one for one in engine.abilities(match)
                if one.effect == effect and one.source == source)


class CostsAndResourcesRulingTests(unittest.TestCase):
    def test_desperation_1(self) -> None:
        """Desperation only draws cards if it's the only card in your hand
        before you play it. By the time it checks whether your hand it
        empty, it won't be in your hand anymore."""
        engine, game, match = red_green(teams=(("blood",), ("growth",)))
        hero_in_play(match, 1)
        player = match.player(1)
        cast(engine, game, match, "desperation", gold=5)
        self.assertEqual(len(player.hand), 3)
        self.assertNotIn("desperation", player.discard, "it is trashed")
        hand(match, 1, "desperation", "mad_man")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="desperation")
        self.assertEqual(player.hand, ["mad_man"], "another card in hand: no draw")
        self.assertIn("desperation", player.discard)

    def test_desperation_2(self) -> None:
        """You discard your hand before the draw/discard phase. So normally
        you'll discard your hand, then discard 0 and draw 2."""
        engine, game, match = red_green(teams=(("blood",), ("growth",)))
        hero_in_play(match, 1)
        cast(engine, game, match, "desperation", gold=5)
        hand_size = len(match.player(1).hand)
        self.assertTrue(match.player(1).discards_at_main_end)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        run = apply(engine, game, match, PromptKind.PATROL, assignment={})
        lines = " ".join([*(line for group in run.groups for line in group.narration),
                          *run.result.narration])
        self.assertIn(f"discards their hand, {hand_size} cards", lines)
        self.assertIn("discards 0 and draws 2", lines)
        self.assertFalse(match.player(1).discards_at_main_end)

    def test_detonate_1(self) -> None:
        """The point of this spell is to trash an opponent's worker or
        building card, but you can trash your own if you want."""
        engine, game, match = red_green()
        hero_in_play(match, 1)
        before = match.player(1).workers
        cast(engine, game, match, "detonate", "1:workers", gold=5)
        self.assertEqual(match.player(1).workers, before - 1)
        self.assertNotIn("detonate", match.player(1).discard, "then trash this card")

    def test_detonate_2(self) -> None:
        """A "building card" does not mean a base, an add-on (such as the
        Tower or Surplus), and it does not mean your tech I, II, or III
        buildings. It does mean building cards that you can have in your
        deck such as Rickety Mine, Graveyard, Firehouse, etc."""
        engine, game, match = red_green()
        hero_in_play(match, 1)
        built(match, 2, "tech1")
        match.player(2).add_on = AddOnState("tower", 4, under_construction=False)
        tree = put(match, 2, "verdant_tree")
        part = effects.EFFECTS["detonate"].parts[0]
        offered = {row.key for row in engine.target_rows(match, 1, part)}
        self.assertIn(f"2:{tree.ref}", offered)
        for ref in ("2:base", "2:tech1", "2:add_on"):
            self.assertNotIn(ref, offered)
        cast(engine, game, match, "detonate", f"2:{tree.ref}", gold=5)
        self.assertIsNone(match.player(2).instance(tree.id))
        self.assertNotIn("verdant_tree", match.player(2).discard, "trashed, not discarded")

    def test_detonate_3(self) -> None:
        """When you trash an opponent's worker, you don't get to choose
        which worker to destroy (because they're alll considered
        identical) and you don't get to see the front of the destroyed
        worker."""
        engine, game, match = red_green()
        hero_in_play(match, 1)
        match.player(2).workers = 5
        run = None
        hand(match, 1, "detonate")
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="detonate")
        run = apply(engine, game, match, PromptKind.TARGET, target="2:workers")
        self.assertEqual(match.player(2).workers, 4)
        said = " ".join(run.result.narration)
        self.assertIn("trashes one of {player:2}'s workers", said)
        self.assertNotIn("{card:", said.replace("{card:detonate}", ""))

    def test_gigadon_1(self) -> None:
        """Some abilities on cards like Insurance Agent or Garth Torken care
        about the cost of cards. Those abilities will always see Gigadon's
        cost as 9. Gigadon's ability only reduces the cost of playing it."""
        engine, game, match = red_green(first=2, teams=(("anarchy",), ("feral",)))
        for _ in range(3):
            put(match, 2, "tiger_cub")
        self.assertEqual(engine.effective_cost(match.player(2), "gigadon"), 6)
        self.assertEqual(engine.catalog.cards["gigadon"].cost, 9)

    def test_gigadon_2(self) -> None:
        """You can only reduce the gold cost of something to 0, not lower
        than that."""
        engine, game, match = red_green(first=2, teams=(("anarchy",), ("feral",)))
        for _ in range(11):
            put(match, 2, "squirrel")
        self.assertEqual(engine.effective_cost(match.player(2), "gigadon"), 0)

    def test_guargum_eternal_sentinel_1(self) -> None:
        """Guargum can even play an ultimate Growth spell for free. He can
        play it even if you didn't control him at the start of your
        turn."""
        engine, game, match = red_green(first=2)
        put(match, 2, "guargum_eternal_sentinel", arrived=True)
        hand(match, 2, "stampede")
        match.player(2).gold = 0
        self.assertEqual(engine.effective_cost(match.player(2), "stampede"), 0)
        self.assertEqual(engine.why_not_playable(match.player(2), "stampede", match), "")

    def test_nature_reclaims_1(self) -> None:
        """A "building card" does not mean a base, an add-on (such as the
        Tower or Surplus), and it does not mean your tech I, II, or III
        buildings. It does mean building cards that you can have in your
        deck such as Rickety Mine, Graveyard, Firehouse, etc."""
        engine, game, match = red_green(first=2, teams=(("anarchy",), ("balance",)))
        hero_in_play(match, 2)
        built(match, 1, "tech1")
        mine = put(match, 1, "rickety_mine")
        fire = put(match, 1, "hotter_fire")
        part = effects.EFFECTS["nature_reclaims"].parts[0]
        offered = {row.key for row in engine.target_rows(match, 2, part)}
        self.assertEqual(offered, {f"1:{mine.ref}", f"1:{fire.ref}"})
        cast(engine, game, match, "nature_reclaims", f"1:{mine.ref}", gold=5)
        self.assertIsNone(match.player(1).instance(mine.id))
        self.assertNotIn("rickety_mine", match.player(1).discard)
        self.assertNotIn("nature_reclaims", match.player(2).discard)

    def test_pillage_1(self) -> None:
        """If the player has less gold than you're trying to steal, steal as
        much as you can. You can only gain as much gold as you actually
        take from the other player."""
        engine, game, match = red_green()
        hero_in_play(match, 1)
        put(match, 1, "bombaster")
        match.player(2).gold = 1
        cast(engine, game, match, "pillage", "2:base", gold=5)
        self.assertEqual(match.player(2).base_hp, 18, "a Pirate: 2 damage")
        self.assertEqual(match.player(2).gold, 0)
        self.assertEqual(match.player(1).gold, 5 - 1 + 1)

    def test_rich_earth_1(self) -> None:
        """You still have to put a card from your hand into the worker
        zone, even though you don't have to pay gold to hire a worker. And
        you still can only hire one worker per turn."""
        engine, game, match = red_green(first=2)
        put(match, 2, "rich_earth")
        player = match.player(2)
        player.gold = 0
        hand(match, 2, "tiger_cub", "wisp")
        self.assertTrue(engine.hire_option(player).allowed)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "hire", slug="tiger_cub")
        self.assertEqual(player.hand, ["wisp"])
        self.assertEqual(player.gold, 0)
        self.assertFalse(engine.hire_option(player).allowed)
        hand(match, 2)
        player.hired_this_turn = False
        self.assertIn("no card in hand", engine.hire_option(player).why_not)

    def test_rich_earth_2(self) -> None:
        """If an effect increases the cost of hiring workers, you still have
        to pay that cost increase."""
        engine, game, match = red_green(first=2)
        put(match, 2, "rich_earth")
        # Nothing red or green raises it: a worker is 0 with Rich Earth,
        # the 1 it would otherwise be waived and nothing more.
        self.assertEqual(engine.hire_cost(match.player(2)), 0)
        self.assertEqual(engine.hire_cost(match.player(1)), 1)

    def test_rickety_mine_1(self) -> None:
        """You can't use the ability the turn Rickety Mine comes under your
        control because it doesn't have haste."""
        engine, game, match = red_green(teams=(("blood",), ("growth",)))
        mine = put(match, 1, "rickety_mine", arrived=True)
        self.assertEqual(option(engine, match, "rickety_mine", mine.ref).why_not, "it arrived this turn")
        mine.arrived_this_turn = False
        self.assertTrue(option(engine, match, "rickety_mine", mine.ref).allowed)

    def test_rickety_mine_2(self) -> None:
        """"Phew!" has no gameplay effect. It has a psychological effect
        though."""
        engine, game, match = red_green(teams=(("blood",), ("growth",)))
        mine = put(match, 1, "rickety_mine")
        match.player(1).gold = 0
        with mock.patch.object(engine, "flip_coin", return_value="heads"):
            run = ability(engine, game, match, "rickety_mine", mine.ref)
        self.assertEqual(match.player(1).gold, 3)
        self.assertEqual(match.player(1).base_hp, 20)
        self.assertIsNotNone(match.player(1).instance(mine.id))
        self.assertIn("Phew!", " ".join(run.result.narration))


def at_max(engine, match, seat: int, slug=None) -> None:
    """`seat`'s hero in play at its maximum level since the turn began --
    what an ultimate asks (UMR p. 7)."""
    hero_in_play(match, seat, slug=slug)
    hero = match.player(seat).hero_of(slug) if slug else match.player(seat).hero
    hero.level = engine.hero_card(hero).max_level
    hero.max_level_since_turn_began = True


def said(run) -> str:
    """Everything a run said, in one string."""
    lines = [line for group in run.groups for line in group.narration]
    return " ".join([*lines, *run.result.narration])


class SpellAndTriggerRulingTests(unittest.TestCase):
    def test_artisan_mantis_1(self) -> None:
        """If you choose a building with less than 3 damage on it, the
        Mantis will repair as much as he can. He won't increase the max HP
        of a building though, he can only remove damage already on it."""
        engine, game, match = red_green(first=2)
        built(match, 2, "tech1", hp=5)
        built(match, 2, "tech2")
        match.player(2).buildings["tech2"].hp = 7
        match.player(2).base_hp = 19
        hand(match, 2, "artisan_mantis")
        match.player(2).gold = 9
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="artisan_mantis")
        apply(engine, game, match, PromptKind.TARGET, target="2:base")
        self.assertEqual(match.player(2).base_hp, 20)

    def test_bamstamper_lizzo_1(self) -> None:
        """The effect is not optional. If the only units in play are yours,
        you must choose one of those. If the only unit in play is
        Bamstamper Lizzo himself, he deals 3 to himself and dies."""
        engine, game, match = red_green(teams=(("fire",), ("growth",)))
        built(match, 1, "tech1")
        built(match, 1, "tech2")
        hand(match, 1, "bamstamper_lizzo")
        match.player(1).gold = 9
        run = apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="bamstamper_lizzo")
        self.assertFalse(any(card.slug == "bamstamper_lizzo" for card in match.player(1).play))
        self.assertIn("bamstamper_lizzo", match.player(1).discard)
        self.assertIn("deals 3 to {player:1}'s {card:bamstamper_lizzo}", said(run))

    def test_bloodburn_1(self) -> None:
        """You can't exhaust this to use the ability the turn it comes under
        your control because it doesn't have haste."""
        engine, game, match = red_green()
        burn = put(match, 1, "bloodburn", arrived=True)
        burn.runes["blood"] = 2
        self.assertEqual(option(engine, match, "bloodburn", burn.ref).why_not, "it arrived this turn")
        burn.arrived_this_turn = False
        target = put(match, 2, "tiger_cub")
        ability(engine, game, match, "bloodburn", burn.ref)
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{target.ref}")
        self.assertEqual(burn.runes["blood"], 0)
        self.assertEqual(target.damage, 1)

    def test_blooming_elm_1(self) -> None:
        """You can target a unit or a hero which already have +1/+1
        rune(s). It just won't add more runes."""
        engine, game, match = red_green(first=2)
        elm = put(match, 2, "blooming_elm")
        cub = put(match, 2, "tiger_cub")
        cub.plus_runes = 1
        ability(engine, game, match, "blooming_elm", elm.ref)
        self.assertEqual(cub.plus_runes, 1)
        self.assertTrue(elm.exhausted)

    def test_burning_volley_1(self) -> None:
        """You must assign at least 1 damage to each target, so you can
        choose at most five targets."""
        engine, game, match = red_green(teams=(("fire",), ("growth",)))
        at_max(engine, match, 1)
        cubs = [put(match, 2, "tiger_cub") for _ in range(6)]
        hand(match, 1, "burning_volley")
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="burning_volley")
        for cub in cubs[:5]:
            apply(engine, game, match, PromptKind.TARGET, target=f"2:{cub.ref}")
        # Five targets, 1 each: nothing more is asked, and it is dealt.
        self.assertIsNot(asked(engine, game, match).kind, PromptKind.TARGET)
        self.assertEqual([cub.damage for cub in cubs], [1, 1, 1, 1, 1, 0])

    def test_calamandra_moss_1(self) -> None:
        """When her max level ability "puts a Tiger into play," that means
        you don't pay for the Tiger and you don't have to have the
        appropriate tech building for it either."""
        engine, game, match = red_green(teams=(("feral",), ("anarchy",)))
        at_max(engine, match, 1)
        match.player(1).gold = 4
        ability(engine, game, match, "calamandra_moss_max", "hero:calamandra_moss")
        prompt = asked(engine, game, match)
        self.assertEqual({row.key for row in prompt.options.targets},
                         {"1:codex:predator_tiger", "1:codex:stalking_tiger"})
        apply(engine, game, match, PromptKind.TARGET, target="1:codex:predator_tiger")
        self.assertEqual(match.player(1).gold, 0, "the 4 is the ability's, the Tiger free")
        self.assertTrue(any(card.slug == "predator_tiger" for card in match.player(1).play))
        self.assertEqual(match.player(1).codex["predator_tiger"], 1)

    def test_calypso_vystari_1(self) -> None:
        """If you have not played a spell this turn, activating her ability
        does nothing. It will not even kill an Illusion in this case,
        because it doesn't target at all if you haven't played a spell."""
        engine, game, match = red_green()
        calypso = put(match, 1, "calypso_vystari")
        put(match, 2, "tiger_cub", patrol="squad_leader")
        self.assertEqual(option(engine, match, "calypso_vystari", calypso.ref).why_not,
                         "you have not played a spell this turn")
        hero_in_play(match, 1)
        cast(engine, game, match, "pillage", "2:base", gold=5)
        self.assertTrue(option(engine, match, "calypso_vystari", calypso.ref).allowed)

    def test_calypso_vystari_2(self) -> None:
        """A "Spell" says "Spell" on its type line. Units, heroes,
        buildings, upgrades, etc. are not "spells."""
        engine, game, match = red_green()
        calypso = put(match, 1, "calypso_vystari")
        put(match, 2, "tiger_cub", patrol="squad_leader")
        hand(match, 1, "mad_man", "bloodburn")
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="mad_man")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="bloodburn")
        self.assertFalse(option(engine, match, "calypso_vystari", calypso.ref).allowed)

    def test_captain_zane_1(self) -> None:
        """Zane's middle ability requires ZANE to kill a scavenger or
        technician to get a bonus. If Zane himself kills them in combat or
        if Zane uses the damage from his max level ability, that counts.
        If another unit or hero kills them, or if Zane uses a spell to kill
        them, that does not count."""
        engine, game, match = red_green()
        hero_in_play(match, 1, level=4)
        scavenger = put(match, 2, "tiger_cub", patrol="scavenger")
        match.player(1).gold = 0
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker="hero:captain_zane")
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender=scavenger.ref)
        self.assertIsNone(match.player(2).instance(scavenger.id))
        self.assertEqual(match.player(1).gold, 1)
        # Another of his units killing a technician gives nothing.
        technician = put(match, 2, "wisp", patrol="technician")
        mad = put(match, 1, "mad_man")
        hand_size = len(match.player(1).hand)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=mad.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender=technician.ref)
        self.assertEqual(len(match.player(1).hand), hand_size)

    def test_captain_zane_2(self) -> None:
        """Shoving a patroller to another slot means removing it from the
        slot its in and putting it in an empty slot in that same patrol
        zone. It doesn't matter if slots in between are occupied or not."""
        engine, game, match = red_green()
        hero_in_play(match, 1, level=5)
        first = put(match, 2, "iron_man", patrol="squad_leader")
        put(match, 2, "tiger_cub", patrol="elite")
        put(match, 2, "tiger_cub", patrol="scavenger")
        match.player(1).gold = 1
        apply(engine, game, match, PromptKind.MAIN_ACTION, "level", levels=1, hero="captain_zane")
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{first.ref}")
        offered = {row.key for row in asked(engine, game, match).options.targets}
        self.assertEqual(offered, {"2:slot:technician", "2:slot:lookout"})
        apply(engine, game, match, PromptKind.TARGET, target="2:slot:lookout")
        self.assertEqual((first.patrol_slot, first.damage), ("lookout", 1))

    def test_captain_zane_3(self) -> None:
        """If all of an opponent's patrol slots are full, there's nowhere to
        shove a patroller. If you try, it won't go anywhere but you'll
        still deal 1 damage to it because of the "do as much as you can"
        rule."""
        engine, game, match = red_green()
        hero_in_play(match, 1, level=5)
        patrollers = [put(match, 2, "iron_man", patrol=slot) for slot in
                      ("squad_leader", "elite", "scavenger", "technician", "lookout")]
        match.player(1).gold = 1
        apply(engine, game, match, PromptKind.MAIN_ACTION, "level", levels=1, hero="captain_zane")
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{patrollers[1].ref}")
        self.assertEqual((patrollers[1].patrol_slot, patrollers[1].damage), ("elite", 1))

    def test_captured_bugblatter_1(self) -> None:
        """In 2v2 (Two-Headed Dragon) games, each team only has one base.
        When Captured Bugblatter's triggers, it will deal just one damage
        to the other team's base."""
        engine, game, match = red_green(teams=(("blood",), ("growth",)))
        put(match, 1, "captured_bugblatter")
        cub = put(match, 2, "tiger_cub")
        hero_in_play(match, 1)
        cast(engine, game, match, "pillage", "2:base", gold=5)
        base = match.player(2).base_hp
        board.destroy(engine, match, [(2, cub.ref)], driver.StepResult())
        from codex.flow import resolve
        resolve.run(engine, match, driver.StepResult())
        self.assertEqual(match.player(2).base_hp, base - 1)

    def test_captured_bugblatter_2(self) -> None:
        """When Captured Bugblatter itself dies, its ability DOES trigger."""
        engine, game, match = red_green(teams=(("blood",), ("growth",)))
        bug = put(match, 1, "captured_bugblatter")
        guard = put(match, 2, "iron_man", patrol="squad_leader")
        guard.armor = 1
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=bug.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="unit:2")
        self.assertIsNone(match.player(1).instance(bug.id))
        self.assertEqual(match.player(2).base_hp, 19)

    def test_cinderblast_dragon_1(self) -> None:
        """You can play the Fire spell even if you don't have a Fire hero."""
        engine, game, match = red_green(teams=(("blood",), ("growth",)))
        dragon = put(match, 1, "cinderblast_dragon")
        target = put(match, 2, "iron_man")
        hand(match, 1, "fire_dart")
        match.player(1).gold = 0
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=dragon.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="base")
        offered = {row.key for row in asked(engine, game, match).options.targets}
        self.assertEqual(offered, {"1:hand:fire_dart"}, "Blood's codex holds no Fire spell")
        apply(engine, game, match, PromptKind.TARGET, target="1:hand:fire_dart")
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{target.ref}")
        self.assertEqual(target.damage, 3)
        self.assertEqual(match.player(1).gold, 0, "free")
        self.assertIn("fire_dart", match.player(1).discard)

    def test_cinderblast_dragon_2(self) -> None:
        """The Fire spell is played after you declare what you're attacking,
        but before that attack actually happens. If spell kills the thing
        you were attacking, you choose a new thing to attack, but this does
        not trigger the ability a second time that turn."""
        engine, game, match = red_green(teams=(("fire",), ("growth",)))
        dragon = put(match, 1, "cinderblast_dragon")
        guard = put(match, 2, "tiger_cub", patrol="squad_leader")
        hand(match, 1, "fire_dart", "fire_dart")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=dragon.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender=guard.ref)
        apply(engine, game, match, PromptKind.TARGET, target="1:hand:fire_dart")
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{guard.ref}")
        self.assertIsNone(match.player(2).instance(guard.id))
        prompt = asked(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.CHOOSE_DEFENDER)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="base")
        self.assertEqual(match.player(2).base_hp, 14)
        self.assertEqual(match.player(1).hand, ["fire_dart"], "no second spell")

    def test_circle_of_life_1(self) -> None:
        """"One tech higher" means that if you sacrifice a tech 0 unit, you
        can get a tech I unit. If you sacrifice a tech I unit, you can get a
        tech II unit. If you sacrifice a tech II unit, you could get a tech
        III unit, except actually non green tech III units exist that cost
        5 or less."""
        engine, game, match = red_green(teams=(("balance",), ("anarchy",)))
        hero_in_play(match, 1)
        cub = put(match, 1, "tiger_cub")
        hand(match, 1, "circle_of_life")
        match.player(1).gold = 3
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="circle_of_life")
        offered = {row.key for row in asked(engine, game, match).options.targets}
        self.assertEqual(offered, {"1:codex:gemscout_owl", "1:codex:tiny_basilisk"})
        self.assertIsNone(match.player(1).instance(cub.id))
        apply(engine, game, match, PromptKind.TARGET, target="1:codex:tiny_basilisk")
        self.assertTrue(any(card.slug == "tiny_basilisk" for card in match.player(1).play))

    def test_circle_of_life_2(self) -> None:
        """"Cost 5 or less" refers to the printed gold cost in the upper left
        corner of the card. Abilities that reduce costs, such as Gigadons,
        aren't taken into account, so you can never get Gigadon with Circle
        of Life."""
        engine, game, match = red_green(teams=(("balance", "feral", "growth"), ("anarchy", "fire", "blood")))
        hero_in_play(match, 1, slug="master_midori")
        tiger = put(match, 1, "huntress")
        for _ in range(9):
            put(match, 1, "squirrel")
        hand(match, 1, "circle_of_life")
        match.player(1).gold = 3
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="circle_of_life")
        apply(engine, game, match, PromptKind.TARGET, target=f"1:{tiger.ref}")
        offered = {row.key for row in asked(engine, game, match).options.targets}
        self.assertNotIn("1:codex:gigadon", offered)
        self.assertIn("1:codex:predator_tiger", offered)


class MoreSpellAndTriggerRulingTests(unittest.TestCase):
    def test_ember_sparks_1(self) -> None:
        """3 damage divided as choose means it can do a) 1 damage to three
        things, b) 2 damage to one thing and 1 damage to another thing, or
        c) 3 damage to one thing."""
        engine, game, match = red_green(teams=(("fire",), ("growth",)))
        hero_in_play(match, 1)
        first = put(match, 2, "iron_man", patrol="squad_leader")
        second = put(match, 2, "iron_man", patrol="elite")
        hand(match, 1, "ember_sparks", "ember_sparks")
        match.player(1).gold = 6
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="ember_sparks")
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{first.ref}")
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{second.ref}")
        apply(engine, game, match, PromptKind.TARGET, "done")
        prompt = asked(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.DIVIDE_DAMAGE)
        self.assertEqual(prompt.options.left, 1)
        apply(engine, game, match, PromptKind.DIVIDE_DAMAGE, target=f"2:{first.ref}")
        self.assertEqual((first.damage, second.damage), (2, 1))
        # One thing: all 3 to it, nothing asked.
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="ember_sparks")
        apply(engine, game, match, PromptKind.TARGET, target="2:base")
        apply(engine, game, match, PromptKind.TARGET, "done")
        self.assertEqual(match.player(2).base_hp, 17)

    def test_feral_strike_1(self) -> None:
        """"If you have tech buildings of the same tech level as them" means
        that for tech 0 units you only need your base (which you always have
        if you haven't lost the game yet), for tech I units you have a tech
        I building, for tech II units you have a tech II building and for
        tech III units you have a tech III building. Your building does NOT
        need to be the same spec as the units."""
        engine, game, match = red_green(teams=(("feral",), ("anarchy",)))
        at_max(engine, match, 1)
        built(match, 1, "tech1")
        hand(match, 1, "feral_strike", "tiger_cub", "centaur", "land_octopus")
        match.player(1).gold = 4
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="feral_strike")
        apply(engine, game, match, PromptKind.MODE_CHOICE, mode="put")
        offered = {row.key for row in asked(engine, game, match).options.targets}
        self.assertEqual(offered, {"1:hand:tiger_cub", "1:hand:centaur"})
        built(match, 1, "tech2")
        offered = {row.key for row in asked(engine, game, match).options.targets}
        self.assertIn("1:hand:land_octopus", offered, "a Blood unit, on a Feral player's Tech II")

    def test_final_showdown_1(self) -> None:
        """The Hunter tokens an opponent gets do not go to their patrol
        zone. That opponent will have to wait until their turn to patrol the
        Hunters."""
        engine, game, match = red_green(teams=(("balance",), ("anarchy",)))
        at_max(engine, match, 1)
        hand(match, 1, "final_showdown")
        match.player(1).gold = 3
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="final_showdown")
        hunters = [card for card in match.player(2).play if card.slug == "hunter"]
        self.assertEqual(len(hunters), 2)
        self.assertTrue(all(card.patrol_slot is None for card in hunters))
        self.assertTrue(all(card.controller == 2 for card in hunters))
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        self.assertFalse({card.ref for card in hunters} & set(engine.patrol_candidates(match)))

    def test_firehouse_1(self) -> None:
        """You can't exhaust this to use the ability the turn it comes under
        your control because it doesn't have haste."""
        engine, game, match = red_green(teams=(("fire",), ("growth",)))
        house = put(match, 1, "firehouse", arrived=True)
        self.assertEqual(option(engine, match, "firehouse", house.ref).why_not, "it arrived this turn")

    def test_firehouse_2(self) -> None:
        """Yes, you really can gun down an unlimited number of things per
        turn with this. When Firehouse's ability readies Firehouse, you can
        use it again, etc."""
        engine, game, match = red_green(teams=(("fire",), ("growth",)))
        house = put(match, 1, "firehouse")
        wisps = [put(match, 2, "wisp") for _ in range(3)]
        for wisp in wisps:
            ability(engine, game, match, "firehouse", house.ref)
            apply(engine, game, match, PromptKind.TARGET, target=f"2:{wisp.ref}")
        self.assertFalse(any(card.slug == "wisp" for card in match.player(2).play))
        self.assertFalse(house.exhausted)

    def test_firehouse_3(self) -> None:
        """Firehouse cannot kill an unlimited number of Illusions. If you use
        it on an Illusion, that Illusion will die instantly from being
        targeted before it takes any damage. This will NOT ready Firehouse
        because the "if you destroy it this way" clause refers to you
        destroying it using the 2 damage specifically."""
        engine, game, match = red_green(teams=(("fire",), ("growth",)))
        # No Illusion is red or green (they are blue's): what this pins is
        # the clause -- readied only where its 2 destroyed the target.
        house = put(match, 1, "firehouse")
        survivor = put(match, 2, "iron_man")
        ability(engine, game, match, "firehouse", house.ref)
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{survivor.ref}")
        self.assertTrue(house.exhausted)

    def test_gunpoint_taxman_1(self) -> None:
        """His ability to steal gold does nothing against an opponent that
        doesn't have any gold."""
        engine, game, match = red_green()
        taxman = put(match, 1, "gunpoint_taxman")
        put(match, 2, "wisp", patrol="squad_leader")
        match.player(2).gold = 0
        gold = match.player(1).gold
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=taxman.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="unit:2")
        self.assertEqual(match.player(1).gold, gold)
        match.player(2).gold = 4
        taxman.exhausted = False
        put(match, 2, "wisp", patrol="squad_leader")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=taxman.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="unit:3")
        self.assertEqual((match.player(1).gold, match.player(2).gold), (gold + 1, 3))

    def test_kidnapping_2(self) -> None:
        """If the unit you steal dies while under your care, it will go to
        its owner's discard pile (not yours)."""
        engine, game, match = red_green(teams=(("blood",), ("growth",)))
        hero_in_play(match, 1)
        cub = put(match, 2, "tiger_cub")
        cast(engine, game, match, "kidnapping", gold=5)
        self.assertEqual(cub.controller, 1)
        self.assertTrue(engine.may_attack_with(cub, match), "readied, with haste")
        put(match, 2, "iron_man", patrol="squad_leader")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=cub.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="unit:2")
        self.assertIn("tiger_cub", match.player(2).discard)
        self.assertNotIn("tiger_cub", match.player(1).discard)

    def test_marauder_1(self) -> None:
        """The point of boosting him is to trash an opponent's worker, but
        you could trash your own if you want."""
        engine, game, match = red_green()
        built(match, 1, "tech1")
        built(match, 1, "tech2")
        hand(match, 1, "marauder")
        match.player(1).gold = 6
        workers = match.player(1).workers
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="marauder", boost=True)
        offered = {row.key for row in asked(engine, game, match).options.targets}
        self.assertEqual(offered, {"1:workers", "2:workers"})
        apply(engine, game, match, PromptKind.TARGET, target="1:workers")
        self.assertEqual(match.player(1).workers, workers - 1)

    def test_maximum_anarchy_1(self) -> None:
        """This destroys Zane himself, too."""
        engine, game, match = red_green()
        at_max(engine, match, 1)
        cast(engine, game, match, "maximum_anarchy", gold=3)
        self.assertFalse(match.player(1).hero.in_play)

    def test_maximum_anarchy_2(self) -> None:
        """Heroes that are destroyed go to their owner's command zone. Units
        that die go to their owner's discard pile."""
        engine, game, match = red_green()
        at_max(engine, match, 1)
        hero_in_play(match, 2)
        cub = put(match, 2, "tiger_cub")
        board.gain_control(match, cub, 1)
        cast(engine, game, match, "maximum_anarchy", gold=3)
        self.assertEqual(match.player(2).hero.zone, "command")
        self.assertIn("tiger_cub", match.player(2).discard)

    def test_maximum_anarchy_3(self) -> None:
        """When a unit or hero is "destroyed" it will "die" as a consequence
        of that. Anything that triggers on "dies" such as the patrol zone's
        scavenger and technician slots, or a Soul Stone, will trigger."""
        engine, game, match = red_green()
        at_max(engine, match, 1)
        put(match, 2, "tiger_cub", patrol="scavenger")
        match.player(2).gold = 0
        cast(engine, game, match, "maximum_anarchy", gold=3)
        self.assertEqual(match.player(2).gold, 1)

    def test_might_of_leaf_and_claw_1(self) -> None:
        """Dealing 0 combat damage does not count as "dealing combat
        damage." """
        engine, game, match = red_green(first=2)
        might = put(match, 2, "might_of_leaf_and_claw")
        wisp = put(match, 2, "wisp")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=wisp.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="base")
        self.assertEqual(might.runes.get("growth", 0), 0)

    def test_might_of_leaf_and_claw_2(self) -> None:
        """If you deal combat damage to something's armor, that does count as
        "dealing combat damage." """
        engine, game, match = red_green(first=2)
        might = put(match, 2, "might_of_leaf_and_claw")
        cub = put(match, 2, "tiger_cub")
        guard = put(match, 1, "iron_man", patrol="squad_leader")
        guard.armor = 3
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=cub.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender=guard.ref)
        self.assertEqual(guard.damage, 0)
        self.assertEqual(might.runes["growth"], 1)

    def test_might_of_leaf_and_claw_3(self) -> None:
        """Abilities like sparkshot and overpower deal damage at the same
        time as a thing's normal combat damage. All this damage is
        considered a single instance of "dealing damage," so the extra
        damage doesn't add a second rune."""
        engine, game, match = red_green(first=2, teams=(("anarchy",), ("feral",)))
        might = put(match, 2, "might_of_leaf_and_claw")
        huntress = put(match, 2, "huntress")
        attacked = put(match, 1, "iron_man", patrol="elite")
        put(match, 1, "tiger_cub", patrol="squad_leader")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=huntress.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="unit:4")
        self.assertEqual(might.runes["growth"], 1)
        self.assertGreater(attacked.damage, 0, "sparkshot hit the elite")

    def test_moments_peace_1(self) -> None:
        """"Can't attack you" means can't attack anything you control. For
        example, can't attack your base or any of your buildings, and can't
        attack your heroes or units."""
        engine, game, match = red_green(teams=(("anarchy",), ("balance",)), first=2)
        hero_in_play(match, 2)
        cast(engine, game, match, "moments_peace", gold=2)
        cub = put(match, 1, "mad_man")
        match.active = 1
        hero_in_play(match, 1)
        self.assertEqual(engine.attackers(match), ("hero:captain_zane",))
        self.assertNotIn(cub.ref, engine.attackers(match))

    def test_moments_peace_2(self) -> None:
        """In 2v2, none of the other team's units can attack units, heroes,
        or buildings you control, including your team's base. Opposing units
        can still attack units, heroes and buildings your teammate controls
        though, except for your team's base."""
        engine, game, match = red_green(teams=(("anarchy",), ("balance",)), first=2)
        hero_in_play(match, 2)
        wisp = put(match, 2, "wisp")
        cast(engine, game, match, "moments_peace", gold=2)
        # A game of two: their units attack nothing of yours, and yours
        # don't patrol until your next turn begins.
        self.assertNotIn(wisp.ref, engine.patrol_candidates(match))
        self.assertTrue(match.player(2).peace)

    def test_rampant_growth_1(self) -> None:
        """If the unit or hero has any armor left at the end of the turn,
        that armor disappears."""
        engine, game, match = red_green(first=2)
        hero_in_play(match, 2)
        cub = put(match, 2, "tiger_cub")
        cast(engine, game, match, "rampant_growth", f"2:{cub.ref}", gold=2)
        self.assertEqual(cub.armor, 2)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        apply(engine, game, match, PromptKind.PATROL, assignment={})
        self.assertEqual(cub.armor, 0)
        self.assertEqual(engine.unit_stats(cub, match), (2, 2))


class AbilityAndArrivalRulingTests(unittest.TestCase):
    def test_sanatorium_1(self) -> None:
        """When you put units into play with this ability, you don't have
        to pay for them and you don't have to meet the tech requirements
        for them either."""
        engine, game, match = red_green()
        house = put(match, 1, "sanatorium")
        hand(match, 1, "marauder", "gunpoint_taxman")
        match.player(1).gold = 1
        ability(engine, game, match, "sanatorium", house.ref)
        offered = {row.key for row in asked(engine, game, match).options.targets}
        self.assertTrue({"1:hand:marauder", "1:hand:gunpoint_taxman"} <= offered)
        apply(engine, game, match, PromptKind.TARGET, target="1:hand:marauder")
        apply(engine, game, match, PromptKind.TARGET, target="1:hand:gunpoint_taxman")
        self.assertEqual(match.player(1).gold, 0)
        self.assertEqual({card.slug for card in match.player(1).play} - {"sanatorium"},
                         {"marauder", "gunpoint_taxman"})

    def test_sanatorium_2(self) -> None:
        """The units gain haste and ephemeral permanently. So if they don't
        leave play after one turn, they'll keep trying to die every turn,
        and Wandering Mimic will get haste from them."""
        engine, game, match = red_green()
        house = put(match, 1, "sanatorium")
        mimic = put(match, 2, "wandering_mimic")
        hand(match, 1, "tiger_cub")
        match.player(1).gold = 1
        ability(engine, game, match, "sanatorium", house.ref)
        apply(engine, game, match, PromptKind.TARGET, target="1:hand:tiger_cub")
        cub = next(card for card in match.player(1).play if card.slug == "tiger_cub")
        self.assertTrue(engine.has_keyword(cub, "Haste", match))
        self.assertTrue(engine.has_keyword(cub, "Ephemeral", match))
        self.assertTrue(engine.has_keyword(mimic, "Haste", match))
        self.assertTrue(all(modifier["until"] is None for modifier in cub.modifiers))

    def test_spore_shambler_1(self) -> None:
        """Removing a +1/+1 rune can cause Spore Shambler to die if he ends
        up with 0 or less HP (in other words, if he has damage on him
        greater than or equal to his HP)."""
        engine, game, match = red_green(first=2)
        shambler = put(match, 2, "spore_shambler", damage=1)
        shambler.plus_runes = 1
        cub = put(match, 2, "tiger_cub")
        ability(engine, game, match, "spore_shambler_exhaust", shambler.ref)
        self.assertIsNone(match.player(2).instance(shambler.id))
        self.assertEqual(cub.plus_runes, 1, "the rune still goes on")

    def test_spore_shambler_2(self) -> None:
        """To pay the cost of "remove a +1/+1" rune, you must remove the rune
        from Spore Shambler, not from something else."""
        engine, game, match = red_green(first=2)
        shambler = put(match, 2, "spore_shambler")
        cub = put(match, 2, "tiger_cub")
        cub.plus_runes = 2
        self.assertEqual(option(engine, match, "spore_shambler_gold", shambler.ref).why_not,
                         "it needs 1 +1/+1 rune")
        shambler.plus_runes = 2
        match.player(2).gold = 1
        ability(engine, game, match, "spore_shambler_gold", shambler.ref)
        self.assertEqual((shambler.plus_runes, cub.plus_runes), (1, 3))

    def test_stampede_1(self) -> None:
        """Units that have overpower do not LOSE overpower from this spell,
        so a Wandering Mimic would still see those units as having the
        keyword. It's just that Stampedes instructions for where to send the
        excess damage happen, and overpower's instructions don't."""
        engine, game, match = red_green(first=2, teams=(("anarchy",), ("growth",)))
        at_max(engine, match, 2)
        centaur = put(match, 2, "centaur")
        mimic = put(match, 1, "wandering_mimic")
        cast(engine, game, match, "stampede", gold=6)
        self.assertTrue(engine.has_keyword(centaur, "Overpower", match))
        self.assertTrue(engine.has_keyword(mimic, "Overpower", match))
        first = put(match, 1, "wisp", patrol="squad_leader")
        put(match, 1, "wisp", patrol="elite")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=centaur.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender=first.ref)
        # 6 ATK into a 0/1 with 0 armor: 1 kills it, 5 to the base, none
        # to the other patroller.
        self.assertEqual(match.player(1).base_hp, 15)
        self.assertEqual(len([card for card in match.player(1).play if card.slug == "wisp"]), 1)

    def test_tyrannosaurus_rex_1(self) -> None:
        """You can destroy any two of the things listed in any combination.
        For example, you could destroy "one unit and one upgrade" or "two
        workers." """
        engine, game, match = red_green(teams=(("balance",), ("anarchy",)))
        for building in ("tech1", "tech2", "tech3"):
            built(match, 1, building)
        hand(match, 1, "tyrannosaurus_rex")
        match.player(1).gold = 8
        workers = match.player(2).workers
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="tyrannosaurus_rex")
        apply(engine, game, match, PromptKind.TARGET, target="2:workers")
        apply(engine, game, match, PromptKind.TARGET, target="2:workers")
        self.assertEqual(match.player(2).workers, workers - 2)

    def test_tyrannosaurus_rex_2(self) -> None:
        """Destroying a worker aways trashes it, NOT discards it."""
        engine, game, match = red_green(teams=(("balance",), ("anarchy",)))
        for building in ("tech1", "tech2", "tech3"):
            built(match, 1, building)
        hand(match, 1, "tyrannosaurus_rex")
        match.player(1).gold = 8
        discard = list(match.player(2).discard)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="tyrannosaurus_rex")
        apply(engine, game, match, PromptKind.TARGET, target="2:workers")
        apply(engine, game, match, PromptKind.TARGET, "done")
        self.assertEqual(match.player(2).discard, discard)

    def test_tyrannosaurus_rex_3(self) -> None:
        """When you destroy an opponent's worker, you don't get to choose
        which worker to destroy (because they're all considered identical)
        and you don't get to see the front of the destroyed worker."""
        engine, game, match = red_green(teams=(("balance",), ("anarchy",)))
        for building in ("tech1", "tech2", "tech3"):
            built(match, 1, building)
        hand(match, 1, "tyrannosaurus_rex")
        match.player(1).gold = 8
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="tyrannosaurus_rex")
        offered = [row.key for row in asked(engine, game, match).options.targets]
        self.assertEqual(offered.count("2:workers"), 1, "all alike: one choice")
        run = apply(engine, game, match, PromptKind.TARGET, target="2:workers")
        self.assertIn("trashes one of {player:2}'s workers", said(run))

    def test_verdant_tree_1(self) -> None:
        """You can't use the exhaust ability the turn Verdant Tree comes
        under you control because it doesn't have haste."""
        engine, game, match = red_green(first=2)
        tree = put(match, 2, "verdant_tree", arrived=True)
        self.assertEqual(option(engine, match, "verdant_tree", tree.ref).why_not, "it arrived this turn")

    def test_verdant_tree_2(self) -> None:
        """Building tech buildings instantly means it's possible to build
        them all in a row in one turn. For example, you could build your
        tech I, then immediately build your tech II, then immediately build
        your tech III all in the same turn. Each tech building becomes
        operational right as you build it, rather than at the end of your
        main phase."""
        engine, game, match = red_green(first=2)
        tree = put(match, 2, "verdant_tree")
        player = match.player(2)
        player.workers, player.gold = 10, 10
        ability(engine, game, match, "verdant_tree", tree.ref)
        for building in ("tech1", "tech2", "tech3"):
            apply(engine, game, match, PromptKind.MAIN_ACTION, "build", building=building)
            self.assertTrue(player.buildings[building].active)

    def test_drakk_ramhorn_4(self) -> None:
        """In 2v2 (Two-Headed Dragon) games, each team only has one base. If
        Draak dies, he'll deal just one damage to the other team's base."""
        engine, game, match = red_green(teams=(("blood",), ("growth",)))
        hero_in_play(match, 1)
        board.destroy(engine, match, [(1, hero(match, 1))], driver.StepResult(), cause=2)
        from codex.flow import resolve
        resolve.run(engine, match, driver.StepResult())
        self.assertEqual(match.player(2).base_hp, 19)

    def test_ironbark_treant_1(self) -> None:
        """He's a 3/2 on your turn. The -2 ATK / +2 armor only happens on
        opponents turns and only while he's in your patrol zone. If
        something removes him from your patrol zone on an opponent's turn,
        he loses the stat adjustment."""
        engine, game, match = red_green()
        hero_in_play(match, 1)
        treant = put(match, 2, "ironbark_treant", patrol="elite")
        treant.armor = 2
        self.assertEqual(engine.unit_stats(treant, match)[0], 1)
        board.sideline(treant)
        self.assertEqual((engine.unit_stats(treant, match)[0], treant.armor), (3, 0))

    def test_ironbark_treant_2(self) -> None:
        """In a free-for-all game, if one opponent deals enough damage to
        remove some or all of his armor, but not kill him, he will have 2
        new armor on the next opponent's turn."""
        engine, game, match = red_green(first=2)
        treant = put(match, 2, "ironbark_treant")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        apply(engine, game, match, PromptKind.PATROL, assignment={"elite": treant.ref})
        begin(engine, game, match)
        self.assertEqual(match.active, 1)
        self.assertEqual(treant.armor, 2)
        treant.armor = 0
        # The next opponent's turn -- in a game of two, seat 1's again --
        # finds it patrolling, and its 2 new.
        from codex.flow import turn
        match.enter_phase("ready")
        turn.begin_turn(engine, game, match)
        self.assertEqual(treant.armor, 2)

    def test_wandering_mimic_1(self) -> None:
        """If you have two Mimics that have flying because a THIRD unit has
        flying, but then that third unit dies, both your Mimics lose
        flying."""
        engine, game, match = red_green()
        first = put(match, 1, "wandering_mimic")
        second = put(match, 1, "wandering_mimic")
        owl = put(match, 2, "gemscout_owl")
        self.assertTrue(engine.has_keyword(first, "Flying", match))
        board.destroy(engine, match, [(2, owl.ref)], driver.StepResult())
        self.assertFalse(engine.has_keyword(first, "Flying", match))
        self.assertFalse(engine.has_keyword(second, "Flying", match))


def balance_team():
    """A standard game: Balance, Feral and Growth (seat 1) against red,
    in seat 1's main phase, Calamandra in play so Behind the Ferns may
    stand, and Midori in play at 4."""
    engine, game, match = red_green(teams=(("balance", "feral", "growth"), ("anarchy", "blood", "fire")))
    hero_in_play(match, 1, slug="calamandra_moss")
    hero_in_play(match, 1, slug="master_midori", level=4)
    match.player(1).hero_of("master_midori").bands = {"1": 0}
    return engine, game, match


def midori_to_5(engine, game, match) -> None:
    match.player(1).gold = max(match.player(1).gold, 1)
    apply(engine, game, match, PromptKind.MAIN_ACTION, "level", levels=1, hero="master_midori")


class GrantRulingTests(unittest.TestCase):
    def test_behind_the_ferns_1(self) -> None:
        """If you have Behind the Ferns and a Steam Tank (3 ATK), then
        attack a building with Steam Tank, it still does get stealth from
        Behind the Ferns. The extra ATK from Steam Tank's ability kicks in
        after the check that lets it sneak past patrollers."""
        engine, game, match = balance_team()
        put(match, 1, "behind_the_ferns")
        tank = put(match, 1, "steam_tank")
        put(match, 2, "iron_man", patrol="squad_leader")
        self.assertTrue(engine.has_keyword(tank, "Stealth", match))
        self.assertIn("base", engine.legal_defenders(match, tank.ref))
        self.assertEqual(engine.attack_value(match, 1, tank.ref, against="base"), 7)

    def test_behind_the_ferns_2(self) -> None:
        """Interactions between Behind the Ferns and Midori's mid-level
        ability (which gives +2/+2 to units without abilities) depend on
        the order of events. Some examples using those cards and Overeager
        Cadet (a 2/2 with no ability). If you pay Ferns -> Cadet -> Midori
        or Cadet -> Ferns -> Midori, your Overeager Cadet will be a 2/2 with
        stealth. That's what he is at step 2 of those examples, so at step
        3 when Midori's middle ability is involved, it will not buff Cadet
        because at a that point, Cadet does have an ability (stealth from
        Behind the Ferns). Similarly if you get Midori -> Cadet -> Ferns or
        Cadet -> Midori -> Ferns, the Cadet will be a 4/4 before Ferns
        happens, so it will stay a 4/4 with no abilities. However, if you
        play in this order: Ferns -> Midori -> Cadet or Midori -> Ferns ->
        Cadet, then the cadet is arriving while both effects already exist.
        In these cases it is also a 4/4 with no abilities."""
        # Midori gives +1/+1 today: the 2/2 with no ability is a Tiger
        # Cub, and the "4/4 that stays" is a 3/4 Iron Man at 4/5 -- the
        # Cub at 3/3 is still 3 ATK or less, which is the FAQ's example.
        for order in ("ferns, unit, midori", "unit, ferns, midori",
                      "midori, unit, ferns", "unit, midori, ferns",
                      "ferns, midori, unit", "midori, ferns, unit"):
            with self.subTest(order=order):
                engine, game, match = balance_team()
                units = {}
                for step in order.split(", "):
                    if step == "ferns":
                        put(match, 1, "behind_the_ferns")
                    elif step == "midori":
                        midori_to_5(engine, game, match)
                    else:
                        units["man"] = put(match, 1, "iron_man")
                man = units["man"]
                stealth = engine.has_keyword(man, "Stealth", match)
                stats = engine.unit_stats(man, match)
                if order.index("ferns") < order.index("midori") and order.index("unit") < order.index("midori"):
                    self.assertEqual((stats, stealth), ((3, 4), True))
                else:
                    self.assertEqual((stats, stealth), ((4, 5), False))

    def test_the_card_faqs_tiger_cub_and_iron_man_both_ways_round(self) -> None:
        """The Card FAQ (UMR p. 19): a Tiger Cub and an Iron Man, then
        Behind the Ferns, then Midori to 5 -- neither gains +1/+1, both
        have stealth; Midori to 5 first -- the Iron Man is 4/5 without
        stealth, and the Tiger Cub 3/3, then stealth, then loses the +1/+1."""
        engine, game, match = balance_team()
        cub, man = put(match, 1, "tiger_cub"), put(match, 1, "iron_man")
        put(match, 1, "behind_the_ferns")
        midori_to_5(engine, game, match)
        self.assertEqual((engine.unit_stats(cub, match), engine.unit_stats(man, match)), ((2, 2), (3, 4)))
        self.assertTrue(engine.has_keyword(cub, "Stealth", match) and engine.has_keyword(man, "Stealth", match))

        engine, game, match = balance_team()
        cub, man = put(match, 1, "tiger_cub"), put(match, 1, "iron_man")
        midori_to_5(engine, game, match)
        put(match, 1, "behind_the_ferns")
        self.assertEqual((engine.unit_stats(cub, match), engine.unit_stats(man, match)), ((2, 2), (4, 5)))
        self.assertTrue(engine.has_keyword(cub, "Stealth", match))
        self.assertFalse(engine.has_keyword(man, "Stealth", match))

    def test_chaos_mirror_1(self) -> None:
        """The printed ATK means the ATK actually printed on the card. For
        example, a 2/3 unit has "2" as it's printed ATK, even if it gets a
        +1/+1 rune and an additional +2/+2 from Two Step."""
        engine, game, match = red_green()
        hero_in_play(match, 1)
        cub = put(match, 1, "tiger_cub")
        cub.plus_runes = 1
        man = put(match, 2, "iron_man")
        cast(engine, game, match, "chaos_mirror", f"1:{cub.ref}", f"2:{man.ref}", gold=2)
        self.assertEqual(engine.unit_stats(cub, match), (4, 3), "3 printed, its rune on top")
        self.assertEqual(engine.unit_stats(man, match), (2, 4))
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        apply(engine, game, match, PromptKind.PATROL, assignment={})
        self.assertEqual(engine.unit_stats(man, match), (3, 4), "until the end of the turn")

    def test_chaos_mirror_2(self) -> None:
        """Any effects that copy a unit such as Manufactured Truth, copy
        only the printed version of a unit, but they will respect Chaos
        Mirror's swap of the printed values. For example, if you have a 1/1
        and an 8/8, then swap their printed ATK with Chaos Mirror (so you
        have an 8/1 and a 1/8) then you copy the 8/1 with Manufactured
        Truth, your copy will be an 8/1."""
        engine, game, match = red_green()
        hero_in_play(match, 1)
        small = put(match, 1, "mad_man")
        big = put(match, 2, "oversized_rhinoceros")
        cast(engine, game, match, "chaos_mirror", f"1:{small.ref}", f"2:{big.ref}", gold=2)
        # What a copy reads (step 13's Mirror Illusions): the swap.
        self.assertEqual((engine.printed_atk(small), engine.printed_atk(big)), (7, 1))

    def test_fairie_dragon_1(self) -> None:
        """If Fairie Dragon leaves play, units with feather runes no longer
        have flying and are no longer 3/1. If a Fairie Dragon later enters
        play, any units with a feather rune (even from a previous Fairie
        Dragon) will be flying and will be 3/1."""
        engine, game, match = red_green()
        dragon = put(match, 2, "fairie_dragon")
        man = put(match, 1, "iron_man")
        man.runes["feather"] = 1
        self.assertEqual(engine.unit_stats(man, match), (3, 1))
        self.assertTrue(engine.has_keyword(man, "Flying", match))
        board.destroy(engine, match, [(2, dragon.ref)], driver.StepResult())
        self.assertEqual(engine.unit_stats(man, match), (3, 4))
        self.assertFalse(engine.has_keyword(man, "Flying", match))
        put(match, 1, "fairie_dragon")
        self.assertTrue(engine.has_keyword(man, "Flying", match))

    def test_fairie_dragon_2(self) -> None:
        """If something such as Manufactured Truth copies a unit with a
        feather rune, the copy will not have the rune, will not be 3/1 and
        will not have flying."""
        engine, game, match = red_green()
        put(match, 2, "fairie_dragon")
        man = put(match, 1, "iron_man")
        man.runes["feather"] = 1
        # The rune is the unit's, never its printed card's: a copy reads
        # the printed 3.
        self.assertEqual(engine.printed_atk(man), 3)
        self.assertIsNone(man.printed)

    def test_fairie_dragon_3(self) -> None:
        """Fairie Dragon only changes the "base" ATK and health of those
        units; runes and other effects can add or subtract ATK or
        health."""
        engine, game, match = red_green()
        put(match, 2, "fairie_dragon")
        cub = put(match, 1, "tiger_cub")
        cub.runes["feather"] = 1
        cub.plus_runes = 1
        self.assertEqual(engine.unit_stats(cub, match), (4, 2))

    def test_fairie_dragon_4(self) -> None:
        """Units with feather runes gain flying, but don't lose any of their
        other abilities."""
        engine, game, match = red_green()
        put(match, 2, "fairie_dragon")
        taxman = put(match, 1, "gunpoint_taxman")
        taxman.runes["feather"] = 1
        self.assertTrue(engine.has_keyword(taxman, "Flying", match))
        self.assertTrue(engine.has_keyword(taxman, "Anti-air", match))

    def test_hotter_fire_1(self) -> None:
        """This really does apply to all abilities that deal damage on all
        red cards and red spells that deal damage. For example, Molting
        Firebird deals 2 damage to every opposing unit if you have Hotter
        Fire. Zane's max level ability deals 2 damage to the patroller
        shoves. Jaina's max level ability deals 4 damage. Scorch deals 3
        damage. Crash Bomber deals 2 damage when he dies. Careless
        Musketeer deals 2 damage to a unit or building AND 2 damage to your
        base, etc."""
        engine, game, match = red_green(teams=(("fire",), ("growth",)))
        put(match, 1, "hotter_fire")
        hero_in_play(match, 1, level=7)
        target = put(match, 2, "iron_man", patrol="squad_leader")
        cast(engine, game, match, "scorch", f"2:{target.ref}", gold=3)
        self.assertEqual(target.damage, 3)
        musketeer = put(match, 1, "careless_musketeer")
        ability(engine, game, match, "careless_musketeer", musketeer.ref)
        apply(engine, game, match, PromptKind.TARGET, target="2:base")
        self.assertEqual((match.player(2).base_hp, match.player(1).base_hp), (18, 18))
        ability(engine, game, match, "jaina_stormborne_max", "hero:jaina_stormborne")
        apply(engine, game, match, PromptKind.TARGET, target="2:base")
        self.assertEqual(match.player(2).base_hp, 14)

    def test_hotter_fire_2(self) -> None:
        """This does not affect any red units or heroes with abilities that
        simply deal combat damage. For example, it doesn't increase the
        damage from sparkshot, overpower, or anti-air."""
        engine, game, match = red_green(teams=(("fire",), ("growth",)))
        put(match, 1, "hotter_fire")
        hero_in_play(match, 1)
        wisp = put(match, 2, "wisp", patrol="squad_leader")
        neighbour = put(match, 2, "iron_man", patrol="elite")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker="hero:jaina_stormborne")
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender=wisp.ref)
        self.assertEqual(neighbour.damage, 1, "sparkshot's 1, no more")

    def test_hotter_fire_3(self) -> None:
        """If you have more than one Hotter Fire, the effects do stack."""
        engine, game, match = red_green(teams=(("fire",), ("growth",)))
        put(match, 1, "hotter_fire")
        put(match, 1, "hotter_fire")
        hero_in_play(match, 1)
        cast(engine, game, match, "fire_dart", "2:base", gold=2)
        self.assertEqual(match.player(2).base_hp, 16)

    def test_burning_volley_2(self) -> None:
        """If you have the Hotter Fire upgrade, Burning Volley can do a
        total of 6 damage. You can then divide that damage to up to six
        targets."""
        engine, game, match = red_green(teams=(("fire",), ("growth",)))
        put(match, 1, "hotter_fire")
        at_max(engine, match, 1)
        wisps = [put(match, 2, "wisp") for _ in range(7)]
        hand(match, 1, "burning_volley")
        match.player(1).gold = 3
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="burning_volley")
        for wisp in wisps[:6]:
            apply(engine, game, match, PromptKind.TARGET, target=f"2:{wisp.ref}")
        self.assertEqual(sum(card.slug == "wisp" for card in match.player(2).play), 1)

    def test_ember_sparks_2(self) -> None:
        """If you have the Hotter Fire upgrade, Ember Sparks can do a total
        of 4 damage, rather than 3. You can still only divide that damage
        amongst one, two, or three targets though (not four targets)."""
        engine, game, match = red_green(teams=(("fire",), ("growth",)))
        put(match, 1, "hotter_fire")
        hero_in_play(match, 1)
        wisps = [put(match, 2, "wisp", patrol=slot) for slot in ("squad_leader", "elite", "scavenger", "technician")]
        hand(match, 1, "ember_sparks")
        match.player(1).gold = 3
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="ember_sparks")
        for wisp in wisps[:3]:
            apply(engine, game, match, PromptKind.TARGET, target=f"2:{wisp.ref}")
        prompt = asked(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.DIVIDE_DAMAGE, "three targets: no fourth asked")
        self.assertEqual((prompt.options.total, prompt.options.left), (4, 1))

    def test_master_midori_1(self) -> None:
        """"Units with no abilities" means units that don't have any ability
        text at all. Keywords such as haste, swift strike, resist 1, frenzy
        1, etc. do count as abilities. If an effect changes a units stats,
        such as giving it +1/+1, that does not count as an ability. If a
        unit has damage on it, or +1/+1 runes, or any other type of rune,
        that does not count as having an ability."""
        engine, game, match = balance_team()
        midori_to_5(engine, game, match)
        cub = put(match, 1, "tiger_cub", damage=1)
        cub.plus_runes = 1
        cub.runes["growth"] = 1
        dog = put(match, 1, "nautical_dog")
        self.assertEqual(engine.unit_stats(cub, match), (4, 4))
        self.assertEqual(engine.unit_stats(dog, match), (1, 1), "frenzy is an ability")

    def test_master_midori_2(self) -> None:
        """If a unit gets an ability, such as Calamandra giving it resist 1,
        then it loses +2/+2 from Midori. This could cause it to die if it
        then has 0 or less HP."""
        engine, game, match = balance_team()
        midori_to_5(engine, game, match)
        cub = put(match, 1, "tiger_cub", damage=2)
        self.assertEqual(engine.unit_stats(cub, match), (3, 3))
        calamandra = match.player(1).hero_of("calamandra_moss")
        calamandra.level = 3
        calamandra.bands["3"] = match.next_sequence()
        board.settle(engine, match, driver.StepResult())
        self.assertIsNone(match.player(1).instance(cub.id))

    def test_master_midori_3(self) -> None:
        """Units do not lose the benefit of Midori's midband ability for
        being in any patrol slot."""
        engine, game, match = balance_team()
        midori_to_5(engine, game, match)
        cub = put(match, 1, "tiger_cub", patrol="lookout")
        self.assertTrue(engine.has_keyword(cub, "Resist", match))
        self.assertEqual(engine.unit_stats(cub, match), (3, 3))

    def test_master_midori_4(self) -> None:
        """You can only reduce the gold cost of something to 0, not lower
        than that."""
        engine, game, match = red_green(first=2, teams=(("anarchy",), ("feral",)))
        for _ in range(12):
            put(match, 2, "frog")
        self.assertEqual(engine.effective_cost(match.player(2), "gigadon"), 0)

    def test_moss_ancient_1(self) -> None:
        """Your Squirrels only keep haste and invisible from Moss Ancient's
        ability while he's still in play under your control. If he leaves
        play or leaves your control, he won't continue to grant those
        abilities."""
        engine, game, match = red_green(first=2, teams=(("anarchy",), ("feral",)))
        ancient = put(match, 2, "moss_ancient")
        squirrel = put(match, 2, "squirrel", arrived=True)
        self.assertTrue(engine.has_keyword(squirrel, "Invisible", match))
        self.assertIn(squirrel.ref, engine.attackers(match))
        board.gain_control(match, ancient, 1)
        self.assertFalse(engine.has_keyword(squirrel, "Invisible", match))
        self.assertNotIn(squirrel.ref, engine.attackers(match))

    def test_polymorph_squirrel_1(self) -> None:
        """Transforming into a Squirrel does not count as a new unit entering
        play. No "arrive" happens here. If the unit had any baggage, such as
        +1/+1 runes, an ongoing spell such as a Soul Stone or Spirit of the
        Panda, or damage on it, all of that will still be on it when it
        Transforms. Though it loses all printed abilities it has and loses
        all one-time effects that other things might have granted it before
        the transform, it still benefits from one-time effects that happen
        to it after the transform and it still benefits from +1/+1 runes
        that are on it, and attachments such as Spirit of the Panda."""
        engine, game, match = red_green(first=2)
        hero_in_play(match, 2)
        taxman = put(match, 1, "gunpoint_taxman")
        taxman.plus_runes = 1
        taxman.modifiers.append({"kind": "atk", "amount": 2, "until": "end_of_turn"})
        spirit = put(match, 1, "spirit_of_the_panda")
        spirit.attached = [taxman.id]
        before = match.next_instance_id
        cast(engine, game, match, "polymorph_squirrel", gold=3)
        self.assertEqual(match.next_instance_id, before, "nothing arrived")
        self.assertEqual(engine.unit_stats(taxman, match), (4, 4), "1/1, its rune, the Panda's +2/+2")
        self.assertFalse(engine.has_keyword(taxman, "Anti-air", match))
        self.assertEqual(engine.subtype_of(taxman), "Squirrel")

    def test_polymorph_squirrel_2(self) -> None:
        """Transforming the unit to a 1/1 can kill it if it already had
        damage on it."""
        engine, game, match = red_green(first=2)
        hero_in_play(match, 2)
        man = put(match, 1, "iron_man", damage=1)
        cast(engine, game, match, "polymorph_squirrel", gold=3)
        self.assertIsNone(match.player(1).instance(man.id))

    def test_polymorph_squirrel_3(self) -> None:
        """This spell can kill units that usually can't be killed."""
        engine, game, match = red_green(first=2)
        hero_in_play(match, 2)
        # Nothing red or green is indestructible: what this pins is that a
        # Squirrel has no ability left to keep it alive -- the 1 kills it.
        man = put(match, 1, "iron_man")
        cast(engine, game, match, "polymorph_squirrel", gold=3)
        man.damage = 1
        board.settle(engine, match, driver.StepResult())
        self.assertIsNone(match.player(1).instance(man.id))

    def test_polymorph_squirrel_4(self) -> None:
        """The transformed unit is still whatever tech level it was
        before."""
        engine, game, match = red_green(first=2)
        hero_in_play(match, 2)
        taxman = put(match, 1, "gunpoint_taxman")
        cast(engine, game, match, "polymorph_squirrel", gold=3)
        self.assertEqual(engine.catalog.cards[taxman.slug].tech_level, 1)
        self.assertIn((1, taxman.ref), engine.target_candidates(match, 2, "unit_tech_0_1"))
        self.assertFalse(engine.is_tech_0_unit(taxman))

    def test_polymorph_squirrel_5(self) -> None:
        """If something would copy the Squirrel such as Manufactured Truth,
        then the copy is a 1/1 Squirrel with no abilities."""
        engine, game, match = red_green(first=2)
        hero_in_play(match, 2)
        man = put(match, 1, "oversized_rhinoceros")
        cast(engine, game, match, "polymorph_squirrel", gold=3)
        self.assertEqual(engine.printed_atk(man), 1)
        self.assertEqual(man.printed, {"polymorph": 2})

    def test_war_drums_1(self) -> None:
        """Units you "have" refers to units you control. It does not include
        units you own, but that were stolen from you for some reason, and
        it doesn't include units that aren't in play, such as those in
        Jail, Graveyard, or forecasted."""
        engine, game, match = red_green(teams=(("blood",), ("growth",)))
        at_max(engine, match, 1)
        cub = put(match, 1, "mad_man")
        stolen = put(match, 1, "nautical_dog")
        cast(engine, game, match, "war_drums", gold=2)
        self.assertEqual(engine.unit_stats(cub, match)[0], 1 + 2)
        board.gain_control(match, stolen, 2)
        self.assertEqual(engine.unit_stats(cub, match)[0], 1 + 1)


def drakk_at(engine, match, level: int) -> None:
    hero_in_play(match, 1, level=level)


class DrakkRulingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine, self.game, self.match = red_green(teams=(("blood",), ("feral",)))

    def play(self, slug: str):
        match = self.match
        match.player(1).hand.append(slug)
        match.player(1).gold = max(match.player(1).gold, 10)
        apply(self.engine, self.game, match, PromptKind.MAIN_ACTION, "play", slug=slug)
        return [card for card in match.player(1).play if card.slug == slug][-1]

    def test_drakk_ramhorn_1(self) -> None:
        """If a unit arrives from your hand, then after that you control a
        max level Drakk, then another unit arrives from your hand, NEITHER
        of those units will get haste from Drakk's max level ability. The
        second one won't because his ability only ever cares about the
        first unit per turn that arrives from your hand. The first one in
        this example also doesn't because you didn't have a max level Drakk
        when you played that unit, and Drakk's ability can't retroactively
        grant haste to units you played earlier in the turn."""
        drakk_at(self.engine, self.match, 5)
        first = self.play("bloodrage_ogre")
        self.match.player(1).hero.level = 6
        second = self.play("bloodrage_ogre")
        for card in (first, second):
            self.assertFalse(self.engine.has_keyword(card, "Haste", self.match))

    def test_drakk_ramhorn_2(self) -> None:
        """There are many ways to get units other than "arriving from your
        hand." If you play a spell from your hand that summons units, such
        as Murkwood Allies, that does not count as the unit "arriving from
        your hand." If you play a unit and it goes to an opponent's Jail,
        then play another unit so your first unit arrives from Jail, it
        never "arrived from your hand." If you play a forecasted unit, it
        goes to the future, then it later arrives from that zone, so it
        never "arrived from your hand" either. You can get units in these
        various ways and still have Drakk's max level ability trigger that
        turn once you finally have a unit actually arrive from your hand for
        the first time that turn."""
        engine, game, match = red_green(teams=(("blood", "feral", "growth"), ("anarchy", "fire", "balance")))
        hero_in_play(match, 1, slug="drakk_ramhorn", level=6)
        hero_in_play(match, 1, slug="calamandra_moss")
        hand(match, 1, "murkwood_allies", "bloodrage_ogre")
        match.player(1).gold = 20
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="murkwood_allies", boost=True)
        tokens_made = [card for card in match.player(1).play if card.slug in ("beast", "frog")]
        self.assertTrue(tokens_made)
        self.assertFalse(any(engine.has_keyword(card, "Haste", match) for card in tokens_made))
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="bloodrage_ogre")
        ogre = next(card for card in match.player(1).play if card.slug == "bloodrage_ogre")
        self.assertTrue(engine.has_keyword(ogre, "Haste", match))

    def test_drakk_ramhorn_3(self) -> None:
        """Though the unit must "arrive from your hand" to benefit from
        Drakk's max level ability, it doesn't have to be PLAYED from hand.
        Feral Strike and Skeletal Lord's ability, for example, "put
        something into play" from your hand. Even though that's different
        from "playing" those things, Drakk's ability still does work because
        they "arrived from your hand." """
        engine, game, match = red_green(teams=(("blood", "feral", "growth"), ("anarchy", "fire", "balance")))
        hero_in_play(match, 1, slug="drakk_ramhorn", level=6)
        at_max(engine, match, 1, slug="calamandra_moss")
        hand(match, 1, "feral_strike", "tiger_cub")
        match.player(1).gold = 4
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="feral_strike")
        apply(engine, game, match, PromptKind.MODE_CHOICE, mode="put")
        apply(engine, game, match, PromptKind.TARGET, target="1:hand:tiger_cub")
        cub = next(card for card in match.player(1).play if card.slug == "tiger_cub")
        self.assertTrue(engine.has_keyword(cub, "Haste", match))

    def test_drakk_ramhorn_5(self) -> None:
        """Drakk's max level ability grants Haste to units permanently."""
        drakk_at(self.engine, self.match, 6)
        ogre = self.play("bloodrage_ogre")
        self.match.player(1).hero.zone = "command"
        self.assertTrue(self.engine.has_keyword(ogre, "Haste", self.match))
        self.assertIn({"kind": "keyword", "keyword": "Haste", "until": None}, ogre.modifiers)


def end_turn(engine, game, match):
    """The active player's main phase ended, nothing patrolling: the
    draw, the end of the turn, and the next player's upkeep."""
    apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
    return apply(engine, game, match, PromptKind.PATROL, assignment={})


class UpkeepAndEndOfTurnRulingTests(unittest.TestCase):
    def test_bloodrage_ogre_1(self) -> None:
        """He returns to your hand AFTER the draw/discard phase."""
        engine, game, match = red_green()
        ogre = put(match, 1, "bloodrage_ogre")
        hand(match, 1, "mad_man")
        run = end_turn(engine, game, match)
        self.assertIsNone(match.player(1).instance(ogre.id))
        # Discarded 1, drew 3, and the Ogre came back after.
        self.assertEqual(len(match.player(1).hand), 4)
        self.assertIn("bloodrage_ogre", match.player(1).hand)
        text = said(run)
        self.assertLess(text.index("draws 3"), text.index("{card:bloodrage_ogre} returns"))

    def test_bloodrage_ogre_2(self) -> None:
        """The "End of Turn" ability only triggers on his controller's
        turn."""
        engine, game, match = red_green()
        ogre = put(match, 2, "bloodrage_ogre")
        end_turn(engine, game, match)
        self.assertIsNotNone(match.player(2).instance(ogre.id))

    def test_chameleon_lizzo_1(self) -> None:
        """He returns to your hand AFTER the draw/discard phase."""
        engine, game, match = red_green()
        lizzo = put(match, 1, "chameleon_lizzo")
        hand(match, 1)
        end_turn(engine, game, match)
        self.assertIsNone(match.player(1).instance(lizzo.id))
        self.assertEqual(len(match.player(1).hand), 3)
        self.assertIn("chameleon_lizzo", match.player(1).hand)

    def test_chameleon_lizzo_2(self) -> None:
        """He will return to your hand at the end of each turn. So if he's in
        play on your opponent's turn for some reason, he'll return to your
        hand after your opponent's draw/discard phase."""
        engine, game, match = red_green()
        lizzo = put(match, 2, "chameleon_lizzo")
        end_turn(engine, game, match)
        self.assertIsNone(match.player(2).instance(lizzo.id))
        self.assertIn("chameleon_lizzo", match.player(2).hand)

    def test_dothram_horselord_1(self) -> None:
        """Dothram Horselord himself counts in computing a player's total
        ATK."""
        engine, game, match = red_green()
        dothram = put(match, 2, "dothram_horselord")
        put(match, 1, "iron_man")
        put(match, 1, "tiger_cub")
        end_turn(engine, game, match)
        self.assertEqual(match.active, 2)
        self.assertEqual(dothram.controller, 2, "6 against 5: his own 6 counted")

    def test_dothram_horselord_2(self) -> None:
        """Effects that happen once (rather than continuously), such as
        Final Smash stealing control of unit or Community Service giving you
        control of an opponent's unit, DO get overridden by Dothram
        Horselord's ability, because newer triggers beat older triggers."""
        engine, game, match = red_green(first=2)
        dothram = put(match, 2, "dothram_horselord")
        board.gain_control(match, dothram, 1)
        put(match, 2, "oversized_rhinoceros")
        end_turn(engine, game, match)
        self.assertEqual(match.active, 1)
        self.assertEqual(dothram.controller, 2, "7 against his 6: back he goes")

    def test_galina_glimmer_1(self) -> None:
        """Galina Glimmer herself is a green unit, so she counts in the
        total."""
        engine, game, match = red_green()
        put(match, 2, "galina_glimmer")
        put(match, 2, "tiger_cub")
        gold = match.player(2).gold
        end_turn(engine, game, match)
        workers = match.player(2).workers
        self.assertEqual(match.player(2).gold, gold + workers + 1)

    def test_galina_glimmer_2(self) -> None:
        """If you have 3 green units, you still get only 1 gold, not 1.5
        gold."""
        engine, game, match = red_green()
        put(match, 2, "galina_glimmer")
        put(match, 2, "tiger_cub")
        put(match, 2, "wisp")
        put(match, 1, "tiger_cub")
        gold = match.player(2).gold
        end_turn(engine, game, match)
        self.assertEqual(match.player(2).gold, gold + match.player(2).workers + 1)

    def test_kidnapping_1(self) -> None:
        """If the unit you steal does not die (or otherwise leave play) on
        your turn, then whichever player you stole it from regains control
        of it at the end of your turn."""
        engine, game, match = red_green(teams=(("blood",), ("growth",)))
        hero_in_play(match, 1)
        cub = put(match, 2, "tiger_cub")
        cast(engine, game, match, "kidnapping", gold=4)
        self.assertEqual(cub.controller, 1)
        run = end_turn(engine, game, match)
        self.assertEqual(cub.controller, 2)
        self.assertIsNone(cub.returns_to)
        self.assertIn("{card:tiger_cub} goes back to {player:2}", said(run))

    def test_land_octopus_1(self) -> None:
        """If you choose to sacrifice workers, they are trashed. They don't
        go to the discard pile."""
        engine, game, match = red_green()
        octopus = put(match, 2, "land_octopus")
        discard = list(match.player(2).discard)
        workers = match.player(2).workers
        end_turn(engine, game, match)
        prompt = asked(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.MODE_CHOICE)
        self.assertEqual([key for key, _ in prompt.options.modes], ["workers", "itself"])
        apply(engine, game, match, PromptKind.MODE_CHOICE, mode="workers")
        self.assertEqual(match.player(2).workers, workers - 2)
        self.assertIsNotNone(match.player(2).instance(octopus.id))
        self.assertEqual(match.player(2).discard[:len(discard)], discard)
        self.assertIs(asked(engine, game, match).kind, PromptKind.MAIN_ACTION)


# -- Purple and black (step 12) ------------------------------------------------------

#: Step 12: the rulings on purple's and black's cards, heroes and tokens --
#: 107 on the cards and 15 on the six heroes.
PURPLE_BLACK_RULINGS = 122

PB_TEAMS = (("past", "present", "future"), ("demonology", "disease", "necromancy"))


def pb(first: int = 1, teams=PB_TEAMS):
    """Three purple heroes (seat 1) against three black, standing in the
    first player's main phase."""
    engine, game, match = new_game(first=first, teams=teams)
    begin(engine, game, match)
    return engine, game, match


def turn_round(engine, game, match, seat: int) -> None:
    """Turns with nothing done until `seat`'s main phase opens again."""
    from test_codex_keywords import next_upkeep

    next_upkeep(engine, game, match, 2 if seat == 1 else 1)
    next_upkeep(engine, game, match, seat)


def tech(match, seat: int, level: int, spec=None) -> None:
    """`seat`'s tech buildings up to `level`, the Tech II's spec `spec`."""
    for building in ("tech1", "tech2", "tech3")[:level]:
        built(match, seat, building)
    if level >= 2:
        match.player(seat).tech2_spec = spec or match.player(seat).specs[0]


class TimeRulingTests(unittest.TestCase):
    def test_time_spiral_1(self) -> None:
        """You can add or remove time runes from things opponents control,
        if you want."""
        engine, game, match = pb()
        hero_in_play(match, 1)
        argonaut = put(match, 2, "fading_argonaut")
        argonaut.time_runes = 2
        hand(match, 1, "time_spiral")
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="time_spiral")
        apply(engine, game, match, PromptKind.MODE_CHOICE, mode="add")
        self.assertEqual(argonaut.time_runes, 3)

    def test_tinkerer_1(self) -> None:
        """You can add or remove time runes from things opponents control,
        if you want."""
        engine, game, match = pb()
        tinkerer = put(match, 1, "tinkerer")
        board.to_future(engine, match, "plasmodium", 2)
        future = match.player(2).future[0]
        ability(engine, game, match, "tinkerer", tinkerer.ref)
        apply(engine, game, match, PromptKind.MODE_CHOICE, mode="remove")
        self.assertEqual(future.time_runes, 2)
        self.assertTrue(tinkerer.exhausted)

    def test_seer_1(self) -> None:
        """You can add or remove time runes from things opponents control,
        if you want."""
        engine, game, match = pb()
        tech(match, 1, 1)
        board.to_future(engine, match, "plasmodium", 2)
        future = match.player(2).future[0]
        future.time_runes = 1
        hand(match, 1, "seer")
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="seer")
        prompt = asked(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.TARGET)
        self.assertTrue(prompt.options.done, "you may")
        apply(engine, game, match, PromptKind.TARGET, target=f"2:future:{future.id}")
        apply(engine, game, match, PromptKind.MODE_CHOICE, mode="remove")
        self.assertEqual(match.player(2).future, [])
        self.assertTrue(any(card.slug == "plasmodium" for card in match.player(2).play),
                        "its last rune gone, it arrives")

    def test_shimmer_ray_1(self) -> None:
        """You can't discard a card DURING your upkeep to save it from dying
        from fading. You can only use abilities during your own main phase
        unless they are specifically marked otherwise, such as "upkeep"
        abilities."""
        engine, game, match = pb()
        ray = put(match, 1, "shimmer_ray")
        ray.time_runes = 1
        hand(match, 1, "neo_plexus")
        self.assertTrue(option(engine, match, "shimmer_ray", ray.ref).allowed)
        turn_round(engine, game, match, 1)
        self.assertIsNone(match.player(1).instance(ray.id), "it faded in the upkeep, unasked")
        self.assertIn("shimmer_ray", match.player(1).discard)

    def test_omegacron_1(self) -> None:
        """Sacrificed units and upgrades always go to their owner's discard
        pile. Sacrificed workers are always trashed. Sacrificed heroes
        always go to their owner's command zone."""
        engine, game, match = pb()
        board.to_future(engine, match, "omegacron", 1)
        omega = match.player(1).future[0]
        source = f"future:{omega.id}"
        stolen = put(match, 2, "neo_plexus")
        board.gain_control(match, stolen, 1)
        hero_in_play(match, 1)
        workers = match.player(1).workers
        for target in (f"1:{stolen.ref}", "1:workers", f"1:{hero(match, 1)}"):
            ability(engine, game, match, "omegacron", source)
            apply(engine, game, match, PromptKind.TARGET, target=target)
        self.assertIn("neo_plexus", match.player(2).discard)
        self.assertEqual(match.player(1).workers, workers - 1)
        self.assertEqual(match.player(1).hero.zone, "command")
        self.assertEqual(omega.time_runes, 3)

    def test_omegacron_arrives_when_its_last_rune_goes(self) -> None:
        engine, game, match = pb()
        board.to_future(engine, match, "omegacron", 1)
        omega = match.player(1).future[0]
        omega.time_runes = 1
        filler = put(match, 1, "neo_plexus")
        ability(engine, game, match, "omegacron", f"future:{omega.id}")
        apply(engine, game, match, PromptKind.TARGET, target=f"1:{filler.ref}")
        self.assertIsNone(match.player(1).instance(filler.id))
        arrived = next(card for card in match.player(1).play if card.slug == "omegacron")
        self.assertIn(arrived.ref, engine.attackers(match), "haste")

    def test_temporal_research_1(self) -> None:
        """The time runes on your forecasted cards count too, even though
        those are "in the future" and not in play. Time runes from fading
        or from Tricycloid also count."""
        engine, game, match = pb()
        hero_in_play(match, 1)
        board.to_future(engine, match, "plasmodium", 1)
        tricycloid = put(match, 1, "tricycloid")
        tricycloid.time_runes = 3
        put(match, 1, "fading_argonaut").time_runes = 4
        self.assertEqual(engine.time_runes_of(match, 1), 10)
        match.player(1).deck = ["neo_plexus"] * 5
        cast(engine, game, match, "temporal_research")
        self.assertEqual(len(match.player(1).hand), 3)

    def test_temporal_research_2(self) -> None:
        """You resolve a spell's effect before discarding it, so Temporal
        Research cannot draw itself from its own effect. You first draw
        cards from Temporal Research's effect, and you reshuffle your
        discard pile into your draw pile if you would draw from empty draw
        pile. Then, you discard Temporal Research when you have finished
        resolving its effect."""
        engine, game, match = pb()
        hero_in_play(match, 1)
        match.player(1).deck = []
        match.player(1).discard = ["neo_plexus"]
        cast(engine, game, match, "temporal_research")
        self.assertEqual(match.player(1).hand, ["neo_plexus"])
        self.assertEqual(match.player(1).discard, ["temporal_research"])

    def test_nullcraft_1(self) -> None:
        """"Buff or Debuff" spells are spells that have the subtype "Buff"
        or "Debuff" (or both!)."""
        engine, game, match = pb()
        craft = put(match, 2, "nullcraft")
        part = effects.EFFECTS["wither"].parts[0]
        for spell, offered in (("deteriorate", False), ("unphase", False), ("spark", True)):
            with self.subTest(spell=spell):
                rows = engine.target_rows(match, 1, part, frame={"spell": spell})
                self.assertEqual(any(row.ref == craft.ref for row in rows), offered)

    def test_lord_of_shadows_1(self) -> None:
        """Lord of Shadows himself is invisible because he is a black unit."""
        engine, game, match = pb()
        lord = put(match, 2, "lord_of_shadows")
        self.assertTrue(engine.has_keyword(lord, "Invisible", match))
        attacker = put(match, 1, "argonaut")
        self.assertNotIn(lord.ref, engine.legal_defenders(match, attacker.ref))


class DeathRulingTests(unittest.TestCase):
    """The forms of death (step 12, commit 3)."""

    def test_plague_spitter_1(self) -> None:
        """Even though this deals damage in the form of -1/-1 runes, it still
        counts as "dealing combat damage" and anything that checks if it
        died to combat damage, such as Brave Knight, see getting hit by
        this and immediately dying as "dying from combat damage." """
        engine, game, match = pb(first=2)
        spitter = put(match, 2, "plague_spitter")
        target = put(match, 1, "argonaut")
        target.plus_runes = 1
        from codex.flow import combat

        run = combat.declare_attack(engine, game, match, spitter.ref, target.ref)
        # 3 damage as runes: the +1/+1 cancelled, two -1/-1 runes, no chits.
        self.assertEqual((target.plus_runes, target.minus_runes, target.damage), (0, 2, 0))
        self.assertEqual(engine.unit_stats(target, match), (1, 2))
        del run

    def test_poisonblade_rogue_1(self) -> None:
        """Even though this deals damage in the form of -1/-1 runes, it
        still counts as "dealing combat damage" and anything that checks if
        it died to combat damage, such as Brave Knight, see getting hit by
        this and immediately dying as "dying from combat damage." """
        engine, game, match = pb()
        rogue = put(match, 1, "poisonblade_rogue")
        guard = put(match, 2, "neo_plexus", patrol="squad_leader")
        from codex.flow import combat

        combat.declare_attack(engine, game, match, rogue.ref, guard.ref)
        # Armor piercing: the squad leader's armor prevents nothing, and two
        # -1/-1 runes kill a 2/2.
        self.assertIsNone(match.player(2).instance(guard.id))
        self.assertTrue(any(event["kind"] == "destroyed" and event["slug"] == "neo_plexus"
                            for event in match.events))

    def test_graveyard_1(self) -> None:
        """While a unit is buried in Graveyard, that unit is not in play;
        it's in a special Graveyard zone. It loses all properties such as
        attachments, +1/+1 runes, damage, etc. when it goes there. When you
        later play it from Graveyard, it will arrive and trigger any
        "arrive" effects at that time."""
        engine, game, match = pb(first=2)
        yard = put(match, 2, "graveyard")
        imp = put(match, 2, "thieving_imp")
        imp.plus_runes = 2
        board.destroy(engine, match, [(2, imp.ref)], board.StepResult())
        self.assertEqual(yard.buried, [{"slug": "thieving_imp", "owner": 2}])
        self.assertNotIn("thieving_imp", match.player(2).discard)
        match.player(2).gold = 10
        hand(match, 1, "neo_plexus")
        ability(engine, game, match, "graveyard", yard.ref)
        played = next(card for card in match.player(2).play if card.slug == "thieving_imp")
        self.assertEqual((played.plus_runes, played.damage), (0, 0))
        self.assertTrue(played.arrived_this_turn)
        self.assertEqual(match.player(2).gold, 7)
        self.assertEqual(yard.buried, [])

    def test_a_graveyard_with_four_units_is_sacrificed(self) -> None:
        engine, game, match = pb()
        yard = put(match, 1, "graveyard")
        yard.buried = [{"slug": "neo_plexus", "owner": 1}] * 3
        board.destroy(engine, match, [(1, put(match, 1, "argonaut").ref)], board.StepResult())
        board.settle(engine, match, board.StepResult())
        self.assertIsNone(match.player(1).instance(yard.id))
        self.assertEqual(sorted(match.player(1).discard),
                         ["argonaut", "graveyard", "neo_plexus", "neo_plexus", "neo_plexus"])

    def test_sacrifice_the_weak_1(self) -> None:
        """"Lowest tech unit with least ATK" means first you look at the set
        of units the lowest tech, such as "tech 0." Tech 0 is below I is
        below II is below III. Next, choose the unit in that set with the
        least ATK."""
        engine, game, match = pb()
        hero_in_play(match, 1)
        mine = put(match, 1, "neo_plexus")
        put(match, 1, "argonaut")
        theirs_strong_tech0 = put(match, 2, "thieving_imp")
        put(match, 2, "bone_collector")
        cast(engine, game, match, "sacrifice_the_weak")
        self.assertIsNone(match.player(1).instance(mine.id))
        self.assertIsNone(match.player(2).instance(theirs_strong_tech0.id),
                          "a tech 0 unit with more ATK is weaker than a tech I one")

    def test_sacrifice_the_weak_2(self) -> None:
        """If there are any units that are indestructible or that can't be
        sacrificed, ignore them when looking for the weakest unit. If such a
        thing would be your "weakest unit" then instead sacrifice your next
        weakest."""
        engine, game, match = pb()
        hero_in_play(match, 1)
        put(match, 1, "hardened_mox")
        put(match, 1, "pestering_haunt")
        argonaut = put(match, 1, "argonaut")
        cast(engine, game, match, "sacrifice_the_weak")
        self.assertIsNone(match.player(1).instance(argonaut.id))
        self.assertEqual(sorted(card.slug for card in match.player(1).play),
                         ["hardened_mox", "pestering_haunt"])

    def test_pestering_haunt_1(self) -> None:
        """"Can't be sacrificed" means you ignore it completely when
        choosing things to sacrifice. If you would sacrifice your "weakest"
        thing and this is it, then you sacrifice your second weakest thing,
        not sacrifice nothing."""
        engine, game, match = pb(first=2)
        hero_in_play(match, 2)
        haunt = put(match, 2, "pestering_haunt")
        imp = put(match, 2, "thieving_imp")
        cast(engine, game, match, "sacrifice_the_weak")
        self.assertIsNotNone(match.player(2).instance(haunt.id))
        self.assertIsNone(match.player(2).instance(imp.id))

    def test_a_tie_for_the_weakest_is_its_casters_to_choose(self) -> None:
        engine, game, match = pb()
        hero_in_play(match, 1)
        put(match, 1, "argonaut")
        first = put(match, 2, "neo_plexus")
        second = put(match, 2, "neo_plexus")
        hand(match, 1, "sacrifice_the_weak")
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="sacrifice_the_weak")
        prompt = asked(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.TARGET)
        self.assertEqual({row.ref for row in prompt.options.targets}, {first.ref, second.ref})
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{second.ref}")
        self.assertIsNotNone(match.player(2).instance(first.id))

    def test_hooded_executioner_1(self) -> None:
        """"Lowest tech unit with least ATK" means first you look at the set
        of units the lowest tech, such as "tech 0." Tech 0 is below I is
        below II is below III. Next, choose the unit in that set with the
        least ATK."""
        engine, game, match = pb(first=2)
        tech(match, 2, 1)
        put(match, 1, "argonaut")
        weak = put(match, 1, "fading_argonaut")
        strong = put(match, 1, "plasmodium")
        hand(match, 2, "hooded_executioner")
        match.player(2).gold = 10
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="hooded_executioner", boost=True)
        self.assertIsNone(match.player(1).instance(weak.id))
        self.assertIsNotNone(match.player(1).instance(strong.id))
        self.assertEqual(match.player(2).gold, 10 - 5)

    def test_hooded_executioner_2(self) -> None:
        """If there are any units that are indestructible or that can't
        leave play, ignore them when looking for the weakest unit. If such
        a thing would be their "weakest unit" then instead destroy their
        next weakest."""
        engine, game, match = pb(first=2)
        tech(match, 2, 1)
        mox = put(match, 1, "hardened_mox")
        next_weakest = put(match, 1, "argonaut")
        hand(match, 2, "hooded_executioner")
        match.player(2).gold = 10
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="hooded_executioner", boost=True)
        self.assertIsNotNone(match.player(1).instance(mox.id))
        self.assertIsNone(match.player(1).instance(next_weakest.id))

    def test_death_rites_1(self) -> None:
        """If there are any units that are indestructible or that can't
        leave play, ignore them when looking for the weakest unit. If such
        a thing would be their "lowest tech unit" then instead destroy their
        next weakest."""
        engine, game, match = pb(first=2)
        at_max(engine, match, 2, "garth_torken")
        put(match, 1, "hardened_mox")
        lowest = put(match, 1, "argonaut")
        mine = put(match, 2, "neo_plexus")
        cast(engine, game, match, "death_rites")
        board.destroy(engine, match, [(2, mine.ref)], board.StepResult())
        from codex.flow import resolve

        resolve.run(engine, match, board.StepResult())
        self.assertIsNone(match.player(1).instance(lowest.id))

    def test_doom_grasp_1(self) -> None:
        """The "if you do" clause is not satisfied if you try to sacrifice
        something that can't be sacrificed such a Gilded Glaxx that "can't
        leave play." You can't even get close to satisfying "if you do" on
        something like Pestering Haunt or Immortal that "can't be
        sacrificed" because you can't even attempt to sacrifice those in
        the first place, so the "if you do" clause is also not satisfied."""
        engine, game, match = pb(first=2)
        at_max(engine, match, 2, "garth_torken")
        put(match, 2, "pestering_haunt")
        put(match, 2, "hardened_mox")
        victim = put(match, 1, "argonaut")
        hand(match, 2, "doom_grasp")
        self.assertIn("nothing it could target",
                      engine.why_not_playable(match.player(2), "doom_grasp", match),
                      "nothing of theirs can be sacrificed, so nothing can be done")
        del victim

    def test_doom_grasp_2(self) -> None:
        """The "if you do" clause is satisfied by attempting to sacrifice
        something with a Soul Stone or something with Two Lives (Rook or
        Justice Juggernaut). In these cases, the Soul Stone will fall off and
        Rook or Justice Juggernaut will get a crumbling rune, then "if you
        do" is satisfied."""
        # Two Lives is the Whitestar Order's (step 13); the Soul Stone half
        # is pinned here.
        engine, game, match = pb(first=2)
        at_max(engine, match, 2, "garth_torken")
        mine = put(match, 2, "neo_plexus")
        stone = put(match, 2, "soul_stone")
        stone.attached = [mine.id]
        victim = put(match, 1, "argonaut")
        cast(engine, game, match, "doom_grasp", f"1:{victim.ref}")
        self.assertIsNotNone(match.player(2).instance(mine.id))
        self.assertIsNone(match.player(2).instance(stone.id))
        self.assertIsNone(match.player(1).instance(victim.id))

    def test_death_and_decay_1(self) -> None:
        """Giving -3/-3 to an X/3 unit or hero will cause it to die (because
        it has 0 HP) even if it had armor."""
        engine, game, match = pb(first=2)
        at_max(engine, match, 2, "orpal_gloor")
        armored = put(match, 1, "thieving_imp", patrol="squad_leader")
        armored.armor = 1
        survivor = put(match, 1, "argonaut")
        cast(engine, game, match, "death_and_decay")
        self.assertIsNone(match.player(1).instance(armored.id))
        self.assertIsNotNone(match.player(1).instance(survivor.id))
        self.assertEqual(match.player(1).base_hp, 17)

    def test_soul_stone_1(self) -> None:
        """When the attached unit "would die," it doesn't actually die so
        things that trigger on "dies" such as drawing a card in the
        technician slot don't happen."""
        engine, game, match = pb(first=2)
        plexus = put(match, 2, "neo_plexus", patrol="technician", damage=1)
        hero_in_play(match, 2)
        cast(engine, game, match, "soul_stone")
        stone = next(card for card in match.player(2).play if card.slug == "soul_stone")
        self.assertEqual(stone.attached, [plexus.id])
        self.assertEqual(engine.unit_stats(plexus, match), (3, 3))
        before = len(match.player(2).hand)
        board.destroy(engine, match, [(2, plexus.ref)], board.StepResult())
        self.assertIsNotNone(match.player(2).instance(plexus.id))
        self.assertEqual(plexus.damage, 0)
        self.assertIsNone(match.player(2).instance(stone.id))
        self.assertEqual(len(match.player(2).hand), before, "the technician draws nothing")

    def test_soul_stone_2(self) -> None:
        """If you Soul Stone something with Two Lives such as Justice
        Juggernaut or Garus Rook, then the first time it would die, it gets
        a crumbling rune from the Two Lives ability instead. The second time
        it would die, Soul Stone's ability triggers (effectively giving it a
        third life)"""
        # Two Lives is step 13's; today the Soul Stone saves once, and the
        # next death is a death.
        engine, game, match = pb()
        plexus = put(match, 1, "neo_plexus")
        stone = put(match, 1, "soul_stone")
        stone.attached = [plexus.id]
        board.destroy(engine, match, [(1, plexus.ref)], board.StepResult())
        self.assertIsNotNone(match.player(1).instance(plexus.id))
        board.destroy(engine, match, [(1, plexus.ref)], board.StepResult())
        self.assertIsNone(match.player(1).instance(plexus.id))

    def test_shadow_blade_1(self) -> None:
        """If you destroy an Illusion because you targeted it with Shadow
        Blade, its controller discards a card."""
        # Illusions are the Whitestar Order's (step 13): pinned here is the
        # discard where Shadow Blade kills.
        engine, game, match = pb(first=2)
        at_max(engine, match, 2, "vandy_anadrose")
        guard = put(match, 1, "neo_plexus", patrol="squad_leader")
        hand(match, 1, "argonaut", "plasmodium")
        cast(engine, game, match, "shadow_blade")
        self.assertIsNone(match.player(1).instance(guard.id))
        self.assertEqual(len(match.player(1).hand), 1)


class EveryCardRulingIsPinnedTests(unittest.TestCase):
    """The ratchet: every ruling on a card of the basic set has a test
    named for it, whose docstring is the ruling's own words."""

    def _collect(self) -> dict:
        import test_codex_card_rulings as module

        found = {}
        for name in dir(module):
            case = getattr(module, name)
            if isinstance(case, type) and issubclass(case, unittest.TestCase):
                for method in dir(case):
                    if method.startswith("test_"):
                        found[method] = getattr(case, method)
        return found

    def _rulings(self) -> dict:
        return {
            slug: rulings.rulings_for(slug)
            for slug in sorted(BASIC_SET) if rulings.rulings_for(slug)
        }

    def test_the_count_is_pinned(self) -> None:
        total = sum(len(found) for found in self._rulings().values())
        self.assertEqual(
            total, CARD_RULINGS,
            f"the basic set's cards carry {total} rulings, not {CARD_RULINGS}: "
            "a re-import changed them, and each needs its test",
        )

    def test_every_ruling_has_a_test(self) -> None:
        found = self._collect()
        for slug, listed in self._rulings().items():
            for number in range(1, len(listed) + 1):
                self.assertIn(f"test_{slug}_{number}", found)

    def test_each_test_says_the_ruling_it_pins(self) -> None:
        found = self._collect()
        for slug, listed in self._rulings().items():
            for number, ruling in enumerate(listed, start=1):
                with self.subTest(card=slug, ruling=number):
                    doc = _collapse(found[f"test_{slug}_{number}"].__doc__ or "")
                    self.assertTrue(doc, "the ruling is the test's docstring")
                    text = _collapse(ruling.text)
                    for sentence in _sentences(doc):
                        self.assertIn(sentence, text)



class EveryRedAndGreenRulingIsPinnedTests(EveryCardRulingIsPinnedTests):
    """Step 11's ratchet: the same three checks over every red and green
    card, hero and token."""

    def _rulings(self) -> dict:
        return {
            slug: rulings.rulings_for(slug)
            for slug in sorted(RED | GREEN) if rulings.rulings_for(slug)
        }

    def test_the_count_is_pinned(self) -> None:
        total = sum(len(found) for found in self._rulings().values())
        self.assertEqual(
            total, RED_GREEN_RULINGS,
            f"red's and green's cards carry {total} rulings, not {RED_GREEN_RULINGS}: "
            "a re-import changed them, and each needs its test",
        )

class EveryPurpleAndBlackRulingIsPinnedTests(EveryCardRulingIsPinnedTests):
    """Step 12's ratchet: the same three checks over every purple and
    black card, hero and token whose text is played -- every one once
    `UNIMPLEMENTED` is empty."""

    def _rulings(self) -> dict:
        return {
            slug: rulings.rulings_for(slug)
            for slug in sorted((PURPLE | BLACK) - effects.UNIMPLEMENTED)
            if rulings.rulings_for(slug)
        }

    def test_the_count_is_pinned(self) -> None:
        total = sum(len(rulings.rulings_for(slug)) for slug in PURPLE | BLACK)
        self.assertEqual(
            total, PURPLE_BLACK_RULINGS,
            f"purple's and black's cards carry {total} rulings, not {PURPLE_BLACK_RULINGS}: "
            "a re-import changed them, and each needs its test",
        )


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _sentences(text: str) -> list[str]:
    found = [part.strip(' ."') for part in re.split(r"(?<=[.!?])\s+", text)]
    return [part for part in found if len(part) > 20]


if __name__ == "__main__":
    unittest.main()

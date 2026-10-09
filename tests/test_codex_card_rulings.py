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

from codex import rulings
from codex.effects import BASIC_SET
from codex.flow import board, driver
from codex.prompts import Action, PromptKind, pending_prompt

from codex_positions import TROQ, begin, built, hand, hero, hero_in_play, new_game, put

#: How many rulings the basic set's cards carry at the pinned import
#: (`SOURCE_SHA` in `scripts/import_codex_cards.py`).
CARD_RULINGS = 28


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


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _sentences(text: str) -> list[str]:
    found = [part.strip(' ."') for part in re.split(r"(?<=[.!?])\s+", text)]
    return [part for part in found if len(part) > 20]


if __name__ == "__main__":
    unittest.main()

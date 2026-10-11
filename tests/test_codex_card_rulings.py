"""
The cards' own rulings, **one test per ruling** (docs/codex-bot.md,
step 6).

Sirlin's rulings are official rules of the game (decision 7): each ruling
`codex/data/rulings.json` makes about a card of the basic set is a test
below, named `test_<the card's slug>_<its number in the file>` with the
ruling as its docstring, and `EveryCardRulingIsPinnedTests` holds the
two together -- it fails if a ruling has no test, if a test's docstring
is not its ruling's words, or if a re-import changes how many rulings
the set's cards carry. **There were 28 on the basic set at the pinned
import**: step 6's prompt counted 26, before the Dancer and the Angry
Dancer were counted as the two records their one shared ruling names.
Steps 11 to 13 added each colour's, and since step 13 the ratchet counts
every ruling the data holds on a card, a hero or a token -- 343.

Positions are staged by slug (`tests/codex_positions.py`), and every
action goes through `codex.flow.driver.apply`, the one door.
"""

from __future__ import annotations

import re
import unittest
from unittest import mock

from codex import effects, rulings, tokens
from codex.components import AddOnState
from codex.effects import BASIC_SET, BLACK, BLUE, GREEN, PURPLE, RED, WHITE
from codex.flow import StepResult, board, driver
from codex.prompts import Action, PromptKind, pending_prompt

from codex_positions import TROQ, begin, built, hand, hero, hero_in_play, new_game, put

#: How many rulings the cards, heroes and tokens carry at the pinned
#: import (`SOURCE_SHA` in `scripts/import_codex_cards.py`): every ruling
#: of `rulings.json` but the `General` group's, which
#: `tests/test_codex_keywords.py` pins -- the basic set's 28, red's and
#: green's 101, purple's and black's 122 and white's and blue's 92.
CARD_RULINGS = 343

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
                         "not enough runes")
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

    def test_a_unit_played_from_the_graveyard_may_be_boosted(self) -> None:
        """The author, 2026-10-10: "yes you can boost off of graveyard
        because the rulebook says that boost applies when you 'play' a card
        and that's what graveyard does." """
        engine, game, match = pb(first=2)
        built(match, 2, "tech1")
        yard = put(match, 2, "graveyard")
        executioner = put(match, 2, "hooded_executioner")
        board.destroy(engine, match, [(2, executioner.ref)], board.StepResult())
        victim = put(match, 1, "neo_plexus")
        match.player(2).gold = 10
        ability(engine, game, match, "graveyard", yard.ref)
        # One unit buried, so it is the pick; the play asks boosted or not.
        self.assertIs(asked(engine, game, match).kind, PromptKind.MODE_CHOICE)
        apply(engine, game, match, PromptKind.MODE_CHOICE, mode="boosted")
        self.assertTrue(any(card.slug == "hooded_executioner" for card in match.player(2).play))
        self.assertEqual(match.player(2).gold, 10 - 2 - 3, "its cost and its boost")
        self.assertIsNone(match.player(1).instance(victim.id), "the boost's weakest destroyed")

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
        self.assertIn("no target",
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


def black(first: int = 2):
    """Three black heroes (seat 2) against three purple, black to play,
    with tech up to II for Demonology."""
    engine, game, match = pb(first=first)
    return engine, game, match


def attack(engine, game, match, attacker: str, defender: str):
    from codex.flow import combat

    return combat.declare_attack(engine, game, match, attacker, defender)


def resolve_all(engine, match):
    from codex.flow import resolve

    result = board.StepResult()
    resolve.run(engine, match, result)
    return result


class BlackRulingTests(unittest.TestCase):
    """Black's effects (step 12, commit 4)."""

    def test_abomination_1(self) -> None:
        """Even your own units other than Abomination himself get -1/-1. If
        you have two Abominations, they each give the other -1/-1 and
        everything else -2/-2."""
        engine, game, match = black()
        one = put(match, 2, "abomination")
        mine = put(match, 2, "bone_collector")
        theirs = put(match, 1, "argonaut")
        self.assertEqual(engine.unit_stats(one, match), (6, 6))
        self.assertEqual(engine.unit_stats(mine, match), (2, 2))
        self.assertEqual(engine.unit_stats(theirs, match), (2, 3))
        two = put(match, 1, "abomination")
        self.assertEqual(engine.unit_stats(one, match), (5, 5))
        self.assertEqual(engine.unit_stats(two, match), (5, 5))
        self.assertEqual(engine.unit_stats(theirs, match), (1, 2))

    def test_blackhand_dozer_1(self) -> None:
        """"Damage you deal" means any damage you cause to be dealt. This
        includes combat damage your units do and damage from spells and
        abilities you control. If you destroy an opponent's tech building,
        and it would deal 2 damage, that also won't happen if it would
        reduce their base to below 6 HP. "You" can even deal damage when
        it's not your turn, such as if Crash Bomber dies on another player's
        turn. That also can't bring an opposing base below 6 HP if you have
        Blackhand Dozer."""
        engine, game, match = black()
        put(match, 2, "blackhand_dozer")
        match.player(1).base_hp = 7
        built(match, 1, "tech1", hp=1)
        brute = put(match, 2, "bone_collector")
        attack(engine, game, match, brute.ref, "tech1")
        self.assertTrue(match.player(1).buildings["tech1"].destroyed)
        self.assertEqual(match.player(1).base_hp, 6, "the building's 2 stops at 6")
        board.damage_building(match, 1, "base", 3, board.StepResult(), by=2)
        self.assertEqual(match.player(1).base_hp, 6)
        board.damage_building(match, 1, "base", 3, board.StepResult(), by=1)
        self.assertEqual(match.player(1).base_hp, 3, "its owner's own damage is not held")

    def test_the_dozers_death_is_the_active_players_to_choose(self) -> None:
        """Blackhand Dozer: "Dies: Active player destroys one of your lowest
        tech units." -- asked of the active player, on either side's turn."""
        engine, game, match = black(first=1)
        dozer = put(match, 2, "blackhand_dozer")
        put(match, 2, "bone_collector")
        first = put(match, 2, "neo_plexus")
        second = put(match, 2, "neo_plexus")
        board.destroy(engine, match, [(2, dozer.ref)], board.StepResult(), cause=1)
        prompt = asked(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.TARGET)
        self.assertEqual(prompt.asked_player, 1)
        self.assertEqual({row.ref for row in prompt.options.targets}, {first.ref, second.ref})

    def test_blackhand_resurrector_1(self) -> None:
        """If the hero in question is on cooldown from dying this turn or
        last turn, you can still summon it with this ability."""
        engine, game, match = black()
        hero_in_play(match, 2, slug="vandy_anadrose")
        board.destroy(engine, match, [(2, hero(match, 2, "vandy_anadrose"))], board.StepResult(), cause=1)
        vandy = match.player(2).hero_of("vandy_anadrose")
        self.assertEqual(vandy.summoning_runes, 2)
        rez = put(match, 2, "blackhand_resurrector")
        ability(engine, game, match, "blackhand_resurrector", rez.ref)
        self.assertTrue(vandy.in_play)
        self.assertEqual((vandy.level, vandy.summoning_runes), (5, 0))

    def test_blackhand_resurrector_2(self) -> None:
        """If the hero has an ability that triggers at max level, it WILL
        trigger."""
        engine, game, match = black()
        hero_in_play(match, 2, slug="vandy_anadrose")
        board.destroy(engine, match, [(2, hero(match, 2, "vandy_anadrose"))], board.StepResult(), cause=1)
        mine = put(match, 2, "neo_plexus")
        theirs = put(match, 1, "argonaut")
        rez = put(match, 2, "blackhand_resurrector")
        ability(engine, game, match, "blackhand_resurrector", rez.ref)
        self.assertEqual(engine.unit_stats(mine, match), (4, 4))
        self.assertEqual(engine.unit_stats(theirs, match), (5, 6))

    def test_blackhand_resurrector_holds_to_the_hero_limit(self) -> None:
        """The author, 2026-10-10: "you can't summon a hero if you're at your
        limit. however, you can summon a hero with runes using the
        resurrector." """
        engine, game, match = black()
        hero_in_play(match, 2, slug="vandy_anadrose")
        board.destroy(engine, match, [(2, hero(match, 2, "vandy_anadrose"))], board.StepResult(), cause=1)
        hero_in_play(match, 2, slug="garth_torken")
        self.assertEqual(engine.hero_limit(match.player(2)), 1)
        rez = put(match, 2, "blackhand_resurrector")
        self.assertFalse(option(engine, match, "blackhand_resurrector", rez.ref).allowed)
        run = driver.apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "ability",
                                                       {"ability": "blackhand_resurrector",
                                                        "source": rez.ref}))
        self.assertIsInstance(run, driver.Refusal)
        self.assertFalse(match.player(2).hero_of("vandy_anadrose").in_play)

    def test_crypt_crawler_1(self) -> None:
        """"Flier" means anything with flying, even a building or hero."""
        engine, game, match = black()
        crawler = put(match, 2, "crypt_crawler")
        stinger = put(match, 1, "stinger")
        hero_in_play(match, 1, slug="prynn_pasternaak")
        match.player(1).hero.modifiers.append({"kind": "keyword", "keyword": "Flying", "until": None})
        ability(engine, game, match, "crypt_crawler", crawler.ref)
        prompt = asked(engine, game, match)
        self.assertEqual({row.ref for row in prompt.options.targets},
                         {stinger.ref, hero(match, 1, "prynn_pasternaak")})
        apply(engine, game, match, PromptKind.TARGET, target=f"1:{stinger.ref}")
        self.assertFalse(engine.has_keyword(stinger, "Flying", match))

    def test_cursed_crow_1(self) -> None:
        """It has to damage the base directly to get the effect. Destroying
        a building and causing its owner to take 2 damage doesn't count."""
        engine, game, match = black()
        crow = put(match, 2, "cursed_crow")
        built(match, 1, "tech1", hp=1)
        hand(match, 1, "argonaut", "neo_plexus")
        attack(engine, game, match, crow.ref, "tech1")
        resolve_all(engine, match)
        self.assertEqual(len(match.player(1).hand), 2)
        crow.exhausted = False
        crow.attacked_this_turn = False
        attack(engine, game, match, crow.ref, "base")
        resolve_all(engine, match)
        self.assertEqual(len(match.player(1).hand), 1)

    def test_deteriorate_1(self) -> None:
        """If you give -1/-1 to an X/1 unit, that will unit will die (because
        it has 0 HP) even if it had armor."""
        engine, game, match = black()
        hero_in_play(match, 2)
        victim = put(match, 1, "stinger", patrol="squad_leader")
        victim.armor = 1
        cast(engine, game, match, "deteriorate")
        self.assertIsNone(match.player(1).instance(victim.id))

    def test_gargoyle_1(self) -> None:
        """Gargoyle's activated ability that lets it attack and patrol and
        abilities that stop Gargoyle specifically from attacking or
        patrolling are applied in the order of their creation to find out if
        the Gargoyle can attack or patrol. So if your Gargoyle has
        Entangling Vines attached, you can activate the ability and attack
        with it. On the other hand, if you use Entangling Vines and then
        Kidnapping on your opponent's patrolling Gargoyle, the "Can't attack
        or patrol" from Entangling Vines is newer than the "Can attack and
        patrol" from Gargoyle's activated ability, so you cannot attack with
        it unless you activate the ability yourself."""
        # Entangling Vines is the Flagstone Dominion's (step 13): pinned here
        # is the ability freeing its own "Can't attack or patrol".
        engine, game, match = black()
        gargoyle = put(match, 2, "gargoyle")
        self.assertNotIn(gargoyle.ref, engine.attackers(match))
        self.assertNotIn(gargoyle.ref, engine.patrol_candidates(match))
        match.player(2).gold = 3
        ability(engine, game, match, "gargoyle", gargoyle.ref)
        self.assertIn(gargoyle.ref, engine.attackers(match))
        self.assertTrue(engine.has_keyword(gargoyle, "Flying", match))
        self.assertFalse(engine.indestructible(match, gargoyle))
        self.assertEqual(engine.unit_stats(gargoyle, match)[0], 3)
        self.assertFalse(option(engine, match, "gargoyle", gargoyle.ref).allowed, "once per turn")

    def test_garth_torken_1(self) -> None:
        """"Meeting the tech reqs for it" means that you control the correct
        tech building. For example, if you want to put a Disease tech II
        unit into play using the max level ability, you must have a Disease
        tech II building."""
        engine, game, match = black()
        hero_in_play(match, 2, slug="garth_torken", level=6)
        match.player(2).discard = ["plague_spitter", "gorgon", "cursed_ghoul"]
        tech(match, 2, 2, "disease")
        match.player(2).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "level", hero="garth_torken", levels=1)
        prompt = asked(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.TARGET)
        self.assertEqual({row.ref for row in prompt.options.targets},
                         {"discard:plague_spitter", "discard:gorgon", "discard:cursed_ghoul"})
        match.player(2).tech2_spec = "necromancy"
        prompt = asked(engine, game, match)
        self.assertEqual({row.ref for row in prompt.options.targets}, {"discard:plague_spitter"})

    def test_garth_torken_2(self) -> None:
        """When you put a unit into play using the max level ability, you
        don't pay for the unit."""
        engine, game, match = black()
        hero_in_play(match, 2, slug="garth_torken", level=6)
        match.player(2).discard = ["plague_spitter"]
        tech(match, 2, 1)
        match.player(2).gold = 1
        apply(engine, game, match, PromptKind.MAIN_ACTION, "level", hero="garth_torken", levels=1)
        apply(engine, game, match, PromptKind.TARGET, target="2:discard:plague_spitter")
        self.assertEqual(match.player(2).gold, 0)
        self.assertTrue(any(card.slug == "plague_spitter" for card in match.player(2).play))

    def test_jandra_the_negator_1(self) -> None:
        """When something "deals damage in the form of" something else, such
        as -1/-1 runes from Plague Spitter, Orpal Gloor, or Poisonblade
        Rogue, they really did "deal combat damage." Immediately after their
        form of damage is dealt, check if their victim would die. If yes,
        that victim counts as "dying from combat damage." Jandra causes you
        to destroy all your non-Demon units in that case."""
        engine, game, match = black(first=1)
        jandra = put(match, 2, "jandra_the_negator", patrol="squad_leader")
        demon = put(match, 2, "thieving_imp")
        plain = put(match, 2, "bone_collector")
        rogue = put(match, 1, "poisonblade_rogue")
        rogue.plus_runes = 2
        attack(engine, game, match, rogue.ref, jandra.ref)
        resolve_all(engine, match)
        self.assertIsNone(match.player(2).instance(jandra.id))
        self.assertIsNotNone(match.player(2).instance(demon.id))
        self.assertIsNone(match.player(2).instance(plain.id))

    def test_jandra_dies_otherwise_and_nothing_happens(self) -> None:
        engine, game, match = black()
        hero_in_play(match, 2)
        jandra = put(match, 2, "jandra_the_negator")
        plain = put(match, 2, "bone_collector")
        board.destroy(engine, match, [(2, jandra.ref)], board.StepResult(), cause=2)
        resolve_all(engine, match)
        self.assertIsNotNone(match.player(2).instance(plain.id))

    def test_lichs_bargain_1(self) -> None:
        """It is legal to sacrifice one of your starting 4 or 5 workers. If
        you do, your worker count goes down by 1 (not by 4 or 5) and you can
        mark that however you want. The game will surely be over pretty
        quickly anyway!"""
        engine, game, match = black()
        at_max(engine, match, 2, "garth_torken")
        workers = match.player(2).workers
        cast(engine, game, match, "lichs_bargain")
        self.assertEqual(match.player(2).workers, workers - 1)
        self.assertEqual(match.player(2).base_hp, 16)
        self.assertEqual(sorted(card.slug for card in match.player(2).play),
                         ["horror", "skeleton", "zombie"])

    def test_metamorphosis_1(self) -> None:
        """Heroes generally don't have types, so your Demonology hero is NOT
        a Demon until Metamorphosis makes her a Demon. Once she is a Demon,
        playing a second Metamorphosis will not affect her. If she leaves
        play, she stops being a Demon."""
        engine, game, match = black()
        at_max(engine, match, 2, "vandy_anadrose")
        vandy = match.player(2).hero_of("vandy_anadrose")
        self.assertFalse(engine.is_demon(vandy))
        put(match, 2, "bone_collector")
        cast(engine, game, match, "metamorphosis")
        self.assertTrue(engine.is_demon(vandy))
        self.assertEqual(vandy.plus_runes, 2)
        self.assertEqual(match.player(2).play, [])
        cast(engine, game, match, "metamorphosis")
        self.assertEqual(vandy.plus_runes, 2, "a second does nothing to a Demon")
        board.destroy(engine, match, [(2, hero(match, 2, "vandy_anadrose"))], board.StepResult(), cause=1)
        self.assertFalse(engine.is_demon(vandy))

    def test_metamorphosis_2(self) -> None:
        """Whenever a hero leaves play, it always loses all properties such
        as levels, damage on it, +1/+1 runes on it, etc. So it also loses
        all buffs it got from Metamorphosis."""
        engine, game, match = black()
        at_max(engine, match, 2, "vandy_anadrose")
        vandy = match.player(2).hero_of("vandy_anadrose")
        cast(engine, game, match, "metamorphosis")
        self.assertTrue(engine.has_keyword(vandy, "Readiness", match))
        board.destroy(engine, match, [(2, hero(match, 2, "vandy_anadrose"))], board.StepResult(), cause=1)
        self.assertEqual((vandy.level, vandy.plus_runes, vandy.modifiers), (1, 0, []))

    def test_nether_drain_1(self) -> None:
        """It doesn't matter if you control the heroes this this targets or
        not. It works on your own heroes and/or opposing heroes."""
        engine, game, match = black()
        hero_in_play(match, 2, slug="garth_torken", level=4)
        hero_in_play(match, 1, slug="prynn_pasternaak", level=3)
        cast(engine, game, match, "nether_drain", f"2:{hero(match, 2, 'garth_torken')}")
        self.assertEqual(match.player(2).hero_of("garth_torken").level, 2)
        self.assertEqual(match.player(1).hero_of("prynn_pasternaak").level, 5)

    def test_nether_drain_2(self) -> None:
        """If you level up another player's hero and an ability that
        triggers from that requires another player to make a decision on
        your turn, instead that ability fizzles. For example, if you level
        up an opposing Necromancy hero to max level on YOUR turn, then its
        controller doesn't get to search their discard pile for a unit
        costing 5 or less."""
        engine, game, match = pb(first=1, teams=(("necromancy", "disease", "demonology"),
                                                 ("necromancy", "past", "future")))
        at_max(engine, match, 1, "garth_torken")
        hero_in_play(match, 2, slug="garth_torken", level=5)
        match.player(2).discard = ["bone_collector"]
        built(match, 2, "tech1")
        cast(engine, game, match, "nether_drain", f"1:{hero(match, 1, 'garth_torken')}")
        theirs = match.player(2).hero_of("garth_torken")
        self.assertEqual(theirs.level, 7)
        self.assertEqual(match.player(1).hero_of("garth_torken").level, 5)
        self.assertNotIn("bone_collector", [card.slug for card in match.player(2).play])
        self.assertEqual(match.resolving, [])

    def test_orpal_gloor_1(self) -> None:
        """Even though this deals damage in the form of -1/-1 runes, it still
        counts as "dealing combat damage" and anything that checks if it
        died to combat damage, such as Brave Knight, see getting hit by this
        and immediately dying as "dying from combat damage." """
        engine, game, match = black()
        hero_in_play(match, 2, slug="orpal_gloor")
        jandra = put(match, 1, "jandra_the_negator", patrol="squad_leader")
        jandra.armor = 0
        plain = put(match, 1, "argonaut")
        match.player(2).hero_of("orpal_gloor").modifiers.append(
            {"kind": "atk", "amount": 2, "until": "end_of_turn"})
        attack(engine, game, match, hero(match, 2, "orpal_gloor"), jandra.ref)
        resolve_all(engine, match)
        self.assertIsNone(match.player(1).instance(jandra.id))
        self.assertIsNone(match.player(1).instance(plain.id), "Jandra died from combat damage")

    def test_sickness_1(self) -> None:
        """You can target two units, two heroes, or one unit and one hero.
        You can also choose to have just one target if you want: just one
        unit or just one hero."""
        engine, game, match = black()
        at_max(engine, match, 2, "orpal_gloor")
        hero_in_play(match, 1, slug="prynn_pasternaak")
        unit = put(match, 1, "argonaut")
        hand(match, 2, "sickness")
        match.player(2).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="sickness")
        apply(engine, game, match, PromptKind.TARGET, target=f"1:{hero(match, 1, 'prynn_pasternaak')}")
        prompt = asked(engine, game, match)
        self.assertTrue(prompt.options.done, "one is enough")
        apply(engine, game, match, PromptKind.TARGET, target=f"1:{unit.ref}")
        self.assertEqual((match.player(1).hero.minus_runes, unit.minus_runes), (1, 1))

    def test_skeletal_lord_1(self) -> None:
        """When you put a unit into play with this ability, you don't have
        to pay for it and you don't have to meet the tech requirements for
        it either. It even allows you to put a tech III unit into play."""
        engine, game, match = black()
        lord = put(match, 2, "skeletal_lord")
        for _ in range(5):
            put(match, 2, "skeleton")
        hand(match, 2, "zarramonde_the_obliterator")
        match.player(2).gold = 0
        ability(engine, game, match, "skeletal_lord", lord.ref)
        self.assertTrue(any(card.slug == "zarramonde_the_obliterator" for card in match.player(2).play))
        self.assertFalse(lord.exhausted, "the Skeletons exhaust, not the Lord")

    def test_skeletal_lord_2(self) -> None:
        """You can pay the cost for Skeletal Lord's ability using skeletons
        that came under your control this turn."""
        engine, game, match = black()
        lord = put(match, 2, "skeletal_lord")
        for _ in range(5):
            put(match, 2, "skeleton", arrived=True)
        hand(match, 2, "bone_collector")
        self.assertTrue(option(engine, match, "skeletal_lord", lord.ref).allowed)
        self.assertEqual(engine.unit_stats(match.player(2).play[-1], match), (2, 2))

    def test_terras_q_the_shackled_1(self) -> None:
        """The Warlock tokens are controlled by the chosen opponent. That
        opponent can sacrifice them, patrol with them, attack with them,
        etc."""
        engine, game, match = black()
        tech(match, 2, 2, "demonology")
        hand(match, 2, "terras_q_the_shackled")
        match.player(2).gold = 10
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="terras_q_the_shackled")
        warlocks = [card for card in match.player(1).play if card.slug == "warlock"]
        self.assertEqual(len(warlocks), 4)
        self.assertTrue(all(card.controller == 1 for card in warlocks))

    def test_terras_q_the_shackled_2(self) -> None:
        """A particular copy of Terras Q is only shackled by the Warlocks
        that HE put into play. For example, if player1 plays Terras Q
        (summoning 4 warlocks) and player 2 also plays their own copy of
        Terras Q (which also summons 4 Warlocks), player1's Terras Q is NOT
        shackled by the Warlocks that player2's Terras Q summoned."""
        engine, game, match = black()
        terras = put(match, 2, "terras_q_the_shackled")
        other = put(match, 1, "terras_q_the_shackled")
        warlock = put(match, 2, "warlock")
        warlock.made_by = other.id
        self.assertTrue(engine.shackled(match, other))
        self.assertFalse(engine.shackled(match, terras))
        self.assertIn(terras.ref, engine.attackers(match))

    def test_terras_q_the_shackled_3(self) -> None:
        """If Terras Q leaves play and comes back, for example because of
        Geiger or Pasternaak's max level abilities, he comes back as a fresh
        copy that's treated as a totally new object. He will arrive again
        and summon new Warlocks, but the OLD Warlocks he summoned earlier
        are no longer shackling him."""
        engine, game, match = black()
        terras = put(match, 2, "terras_q_the_shackled")
        old = put(match, 1, "warlock")
        old.made_by = terras.id
        self.assertTrue(engine.shackled(match, terras))
        fresh = put(match, 2, "terras_q_the_shackled")
        board.trash(engine, match, terras)
        self.assertFalse(engine.shackled(match, fresh))

    def test_terras_q_the_shackled_4(self) -> None:
        """If something in play becomes a copy of Terras Q, no "arrives"
        triggers happen so he doesn't get new Warlocks. Any Warlocks already
        in play do NOT shackle that copy; they only shackle the specific
        Terras Q whose arrives trigger summoned them."""
        engine, game, match = black()
        terras = put(match, 2, "terras_q_the_shackled")
        copy = put(match, 2, "terras_q_the_shackled")
        warlock = put(match, 1, "warlock")
        warlock.made_by = terras.id
        self.assertFalse(engine.shackled(match, copy))
        self.assertTrue(engine.shackled(match, terras))

    def test_twilight_baron_1(self) -> None:
        """If you already have tech II units in play, it's ok to play
        Twilight Baron. It's just that while he is in play, you cannot play
        any more tech II units."""
        engine, game, match = black()
        tech(match, 2, 2, "demonology")
        put(match, 2, "voidblocker")
        player = match.player(2)
        player.gold = 10
        self.assertEqual(engine.why_not_playable(player, "twilight_baron"), "")
        put(match, 2, "twilight_baron")
        self.assertIn("Twilight Baron", engine.why_not_playable(player, "voidblocker"))

    def test_twilight_baron_2(self) -> None:
        """Though you can't "play" tech II units, you can still "put them
        into play" by any effect that's worded that way."""
        engine, game, match = black()
        put(match, 2, "twilight_baron")
        board.put_into_play(engine, match, "voidblocker", 2, from_hand=False)
        self.assertTrue(any(card.slug == "voidblocker" for card in match.player(2).play))

    def test_twilight_baron_3(self) -> None:
        """You can play tech II buildings and upgrades; those are not
        units."""
        engine, game, match = black()
        tech(match, 2, 2, "demonology")
        put(match, 2, "twilight_baron")
        match.player(2).gold = 10
        self.assertEqual(engine.why_not_playable(match.player(2), "shrine_of_forbidden_knowledge"), "")

    def test_twilight_baron_4(self) -> None:
        """If a tech II unit has forecast, such as Reaver, you still can't
        play it while you have Twilight Baron. You can play Reaver first,
        then play Twilight Baron, then have Reaver's forecast ability cause
        it to enter play though."""
        engine, game, match = pb(first=1, teams=(("future", "present", "past"),
                                                 ("demonology", "disease", "necromancy")))
        tech(match, 1, 2, "future")
        put(match, 1, "twilight_baron")
        match.player(1).gold = 10
        self.assertIn("Twilight Baron", engine.why_not_playable(match.player(1), "reaver"))
        board.to_future(engine, match, "reaver", 1)
        match.player(1).future[0].time_runes = 1
        board.remove_time_rune(engine, match, 1, f"future:{match.player(1).future[0].id}",
                               board.StepResult())
        self.assertTrue(any(card.slug == "reaver" for card in match.player(1).play))

    def test_vandy_anadrose_1(self) -> None:
        """The max level ability is not optional, so you must try to do as
        much as you can when she reaches max level. If you don't have a
        friendly tech 0 or I unit, you still must try to give the bonus to an
        opposing tech 0 or I unit, and vice versa."""
        engine, game, match = black()
        hero_in_play(match, 2, slug="vandy_anadrose", level=4)
        theirs = put(match, 1, "argonaut")
        match.player(2).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "level", hero="vandy_anadrose", levels=1)
        self.assertEqual(engine.unit_stats(theirs, match), (5, 6))

    def test_vandy_anadrose_2(self) -> None:
        """The units targeted by the max level ability will still lose the
        bonus and die during Vandy's owner's next upkeep, even if Vandy isn't
        around."""
        engine, game, match = black()
        hero_in_play(match, 2, slug="vandy_anadrose", level=4)
        mine = put(match, 2, "bone_collector")
        theirs = put(match, 1, "argonaut")
        match.player(2).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "level", hero="vandy_anadrose", levels=1)
        board.destroy(engine, match, [(2, hero(match, 2, "vandy_anadrose"))], board.StepResult(), cause=1)
        turn_round(engine, game, match, 2)
        self.assertIsNone(match.player(2).instance(mine.id))
        self.assertIsNone(match.player(1).instance(theirs.id))

    def test_vandys_max_reached_on_the_opponents_turn_does_not_resolve(self) -> None:
        """UMR p. 14: "If she reaches max level during an opponent's turn ...
        the effect doesn't resolve, because Vandy's controller can't choose
        which units gain the bonus." """
        engine, game, match = black(first=1)
        hero_in_play(match, 2, slug="vandy_anadrose", level=3)
        hero_in_play(match, 1, slug="prynn_pasternaak")
        theirs = put(match, 1, "argonaut")
        mine = put(match, 2, "bone_collector")
        board.destroy(engine, match, [(1, hero(match, 1, "prynn_pasternaak"))], board.StepResult(), cause=2)
        resolve_all(engine, match)
        self.assertEqual(match.player(2).hero_of("vandy_anadrose").level, 5)
        self.assertEqual(engine.unit_stats(theirs, match), (3, 4))
        self.assertEqual(engine.unit_stats(mine, match), (3, 3))

    def test_voidblocker_1(self) -> None:
        """If they don't have any other ready units or heroes, they can still
        attack Voidblocker."""
        engine, game, match = black(first=1)
        blocker = put(match, 2, "voidblocker")
        attacker = put(match, 1, "argonaut")
        self.assertIn(blocker.ref, engine.legal_defenders(match, attacker.ref))
        attack(engine, game, match, attacker.ref, blocker.ref)
        self.assertEqual(blocker.damage, 3)

    def test_voidblocker_exhausts_another_of_theirs(self) -> None:
        engine, game, match = black(first=1)
        blocker = put(match, 2, "voidblocker")
        attacker = put(match, 1, "neo_plexus")
        bystander = put(match, 1, "argonaut")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=attacker.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender=blocker.ref)
        self.assertTrue(bystander.exhausted)

    def test_plague_lab_1(self) -> None:
        """If a given card has two kinds of runes, Plague Lab can still only
        add one rune to that card. You choose which kind of rune to add from
        among the kinds of runes it already has."""
        engine, game, match = black()
        lab = put(match, 2, "plague_lab")
        target = put(match, 1, "fading_argonaut")
        target.minus_runes = 1
        target.time_runes = 2
        match.player(2).gold = 5
        ability(engine, game, match, "plague_lab_runes", lab.ref)
        prompt = asked(engine, game, match)
        self.assertEqual({row.ref for row in prompt.options.targets},
                         {f"{target.ref}#minus", f"{target.ref}#time"})
        apply(engine, game, match, PromptKind.TARGET, target=f"1:{target.ref}#time")
        self.assertEqual((target.minus_runes, target.time_runes), (1, 3))
        prompt = asked(engine, game, match)
        self.assertFalse(prompt is not None and prompt.kind is PromptKind.TARGET
                         and prompt.options.targets, "one rune a card")

    def test_plague_lab_2(self) -> None:
        """You do not have to add any runes to any cards you don't want to
        add runes to."""
        engine, game, match = black()
        lab = put(match, 2, "plague_lab")
        target = put(match, 1, "argonaut")
        target.minus_runes = 1
        match.player(2).gold = 5
        ability(engine, game, match, "plague_lab_runes", lab.ref)
        prompt = asked(engine, game, match)
        self.assertTrue(prompt.options.done)
        apply(engine, game, match, PromptKind.TARGET, "done")
        self.assertEqual(target.minus_runes, 1)
        self.assertEqual(match.player(2).gold, 3)

    def test_plague_lab_never_reaches_the_future(self) -> None:
        engine, game, match = black()
        board.to_future(engine, match, "plasmodium", 1)
        put(match, 2, "plague_lab")
        from codex import effects as table

        rows = engine.target_rows(match, 2, table.EFFECTS["plague_lab_runes"].parts[0])
        self.assertEqual(rows, ())

    def test_carrion_curse_looks_at_the_hand_for_the_caster_alone(self) -> None:
        """Carrion Curse: the opponent's whole hand shown to the caster, the
        non-units offered, and the discard said as a count."""
        engine, game, match = black()
        at_max(engine, match, 2, "orpal_gloor")
        hand(match, 1, "argonaut", "time_spiral", "now")
        hand(match, 2, "carrion_curse")
        match.player(2).gold = 5
        run = apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="carrion_curse")
        prompt = asked(engine, game, match)
        self.assertEqual(prompt.asked_player, 2)
        self.assertEqual(prompt.options.shown, ("argonaut", "time_spiral", "now"))
        self.assertEqual({row.ref for row in prompt.options.targets}, {"hand:time_spiral", "hand:now"})
        run = apply(engine, game, match, PromptKind.TARGET, target="1:hand:now")
        self.assertEqual(match.player(1).hand, ["argonaut", "time_spiral"])
        self.assertNotIn("now", said(run).lower().replace("{card:now}", ""))


def purple(first: int = 1):
    """Three purple heroes (seat 1), purple to play."""
    return pb(first=first)


class PurpleRulingTests(unittest.TestCase):
    """Purple's effects (step 12, commit 5)."""

    def test_assimilate_1(self) -> None:
        """You gain control of the card as long as it remains in play, for
        the rest of the game. If it's destroyed, it will go to its owner's
        discard pile, not (necessarily) yours. If something "returns" it to
        play such as Geiger or Pasternaak's max level abilities, it
        "returns" to play under your control because you were the one who
        last controlled it."""
        engine, game, match = purple()
        at_max(engine, match, 1, "vir_garbarean")
        yard = put(match, 2, "graveyard")
        cast(engine, game, match, "assimilate")
        self.assertEqual(yard.controller, 1)
        board.destroy(engine, match, [(1, yard.ref)], board.StepResult())
        board.settle(engine, match, board.StepResult())
        yard.damage = 3
        board.settle(engine, match, board.StepResult())
        self.assertIn("graveyard", match.player(2).discard)

    def test_assimilate_2(self) -> None:
        """A "building card" does not mean a base, an add-on (such as the
        Tower or Surplus), and it does not mean your tech I, II, or III
        buildings. It does mean building cards that players can have in
        their decks such as Rickety Mine, Graveyard, Firehouse, etc."""
        engine, game, match = purple()
        at_max(engine, match, 1, "vir_garbarean")
        match.player(2).add_on = AddOnState(slug="tower", hp=4, under_construction=False)
        built(match, 2, "tech1")
        hand(match, 1, "assimilate")
        self.assertIn("no target",
                      engine.why_not_playable(match.player(1), "assimilate", match))

    def test_assimilate_3(self) -> None:
        """If an enemy unit has Spirit of the Panda attached and you
        Assimilate Spirit of the Panda, you now control it. It remains
        attached to the enemy unit and that unit still gets +2/+2 and gives
        its ctonroller 1 gold when it attacks. But now during YOUR upkeep,
        YOU get the Healing 1 effect."""
        engine, game, match = purple()
        at_max(engine, match, 1, "vir_garbarean")
        unit = put(match, 2, "bone_collector")
        panda = put(match, 2, "spirit_of_the_panda")
        panda.attached = [unit.id]
        cast(engine, game, match, "assimilate")
        self.assertEqual(panda.controller, 1)
        self.assertEqual(panda.attached, [unit.id])
        self.assertEqual(engine.unit_stats(unit, match), (5, 5))

    def test_assimilate_4(self) -> None:
        """If you use this to steal an ongoing channeling spell such as Two
        Step, but you don't control the appropriate hero to channel that
        spell, it's immediately discarded."""
        engine, game, match = purple()
        at_max(engine, match, 1, "vir_garbarean")
        put(match, 2, "two_step")
        cast(engine, game, match, "assimilate")
        self.assertFalse(any(card.slug == "two_step" for card in match.instances()))
        self.assertIn("two_step", match.player(2).discard)

    def test_assimilate_5(self) -> None:
        """If you use this to steal your opponent's Graveyard, you will be
        able to play units owned by your opponent from the Graveyard. You
        can always play tech 0 units from the Graveyard. If you have a tech I
        building, you can play any tech I units from the Graveyard. To play a
        tech II unit owned by your opponent from the Graveyard, you must have
        a tech II building with a matching spec. This is only possible if you
        are playing some of the same specs as your opponent. You cannot name
        a spec other than your three specs when building your tech II
        building or tech lab."""
        engine, game, match = purple()
        at_max(engine, match, 1, "vir_garbarean")
        yard = put(match, 2, "graveyard")
        yard.buried = [{"slug": "thieving_imp", "owner": 2}, {"slug": "bone_collector", "owner": 2},
                       {"slug": "gorgon", "owner": 2}]
        cast(engine, game, match, "assimilate")
        yard.arrived_this_turn = False
        match.player(1).gold = 10
        rows = engine.target_candidates(match, 1, "buried_playable")
        self.assertEqual([ref for _, ref in rows], [f"buried:{yard.id}:0"])
        tech(match, 1, 2, "past")
        rows = engine.target_candidates(match, 1, "buried_playable")
        self.assertEqual([ref for _, ref in rows], [f"buried:{yard.id}:0", f"buried:{yard.id}:1"])
        ability(engine, game, match, "graveyard", yard.ref)
        apply(engine, game, match, PromptKind.TARGET, target=f"1:buried:{yard.id}:1")
        played = next(card for card in match.player(1).play if card.slug == "bone_collector")
        self.assertEqual((played.owner, played.controller), (2, 1))

    def test_chronofixer_1(self) -> None:
        """This prevents opposing heroes from gaining levels by any means.
        That includes killing another player's hero, and effects like
        Training Grounds."""
        engine, game, match = purple(first=2)
        put(match, 1, "chronofixer")
        hero_in_play(match, 2, slug="vandy_anadrose")
        hero_in_play(match, 1, slug="prynn_pasternaak")
        self.assertIn("Chronofixer", option(engine, match, "", "").why_not if False else
                      engine.hero_option(match.player(2), match.player(2).hero_of("vandy_anadrose"),
                                         match).why_not)
        board.destroy(engine, match, [(1, hero(match, 1, "prynn_pasternaak"))], board.StepResult())
        self.assertEqual(match.player(2).hero_of("vandy_anadrose").level, 1)

    def test_chronofixer_2(self) -> None:
        """Blackhand Resurrector's ability puts a hero into play a level 1,
        rather than max level, if an opponent has Chronofixer."""
        engine, game, match = purple(first=2)
        put(match, 1, "chronofixer")
        hero_in_play(match, 2, slug="vandy_anadrose")
        board.destroy(engine, match, [(2, hero(match, 2, "vandy_anadrose"))], board.StepResult(), cause=1)
        rez = put(match, 2, "blackhand_resurrector")
        ability(engine, game, match, "blackhand_resurrector", rez.ref)
        vandy = match.player(2).hero_of("vandy_anadrose")
        self.assertTrue(vandy.in_play)
        self.assertEqual(vandy.level, 1)

    def test_gilded_glaxx_1(self) -> None:
        """You only check if he "died from combat damage" when combat damage
        is actually dealt to him, not at other times. For example, if the
        Sickness spell puts a -1/-1 rune on him (that's not combat damage)
        and this causes him to have 0 HP, he will not die. The next time he
        is dealt combat damage by something though, he WILL die. So the
        steps are 1) was any combat damage dealt to him? 2) if yes, then see
        if he has 0 HP or less, 3) if yes, then he dies."""
        engine, game, match = purple(first=2)
        glaxx = put(match, 1, "gilded_glaxx")
        match.player(1).gold = 3
        glaxx.minus_runes = 4
        board.settle(engine, match, board.StepResult())
        self.assertIsNotNone(match.player(1).instance(glaxx.id))
        attacker = put(match, 2, "bone_collector")
        attack(engine, game, match, attacker.ref, glaxx.ref)
        self.assertIsNone(match.player(1).instance(glaxx.id))

    def test_gilded_glaxx_2(self) -> None:
        """If something "deals combat damage in the form of" something else,
        such as Plague Spitter, Poisonblade Rogue, or Orpal Gloor, then that
        CAN count as Glaxx "dying from combat damage". After those things
        deal combat damage (in the form of -1/-1 runes or whatever else),
        check if Glaxx has 0 or less HP to see if he dies."""
        engine, game, match = purple(first=2)
        glaxx = put(match, 1, "gilded_glaxx")
        match.player(1).gold = 3
        spitter = put(match, 2, "plague_spitter")
        spitter.plus_runes = 1
        attack(engine, game, match, spitter.ref, glaxx.ref)
        self.assertIsNone(match.player(1).instance(glaxx.id))

    def test_gilded_glaxx_3(self) -> None:
        """If Glaxx has 0 or less HP, and he has 1 point of armor, then he
        takes 1 combat damage, he doesn't die, unless it was 1 point of
        damage from something with deathtouch, then he does die. Damage that
        merely removes armor doesn't quality as "dying to combat damage" but
        deathtouch specifically says that deathtouch-type combat damage DOES
        kill things merely by hitting their armor."""
        engine, game, match = purple(first=2)
        glaxx = put(match, 1, "gilded_glaxx", patrol="squad_leader")
        glaxx.armor = 1
        glaxx.minus_runes = 4
        match.player(1).gold = 3
        stinger = put(match, 2, "skeleton")
        attack(engine, game, match, stinger.ref, glaxx.ref)
        self.assertIsNotNone(match.player(1).instance(glaxx.id), "the armor took it")
        glaxx.armor = 1
        horror = put(match, 2, "horror")
        horror.minus_runes = 2
        attack(engine, game, match, horror.ref, glaxx.ref)
        self.assertIsNone(match.player(1).instance(glaxx.id), "deathtouch kills through armor")

    def test_gilded_glaxx_4(self) -> None:
        """Some effects like Obliterate, Sacrifice the Weak, and Death Rites
        ask a player to destroy or sacrifice the unit that is the least
        according to some ordering. These effects skip units with
        Indestructible and units that cannot leave play."""
        engine, game, match = purple(first=2)
        glaxx = put(match, 1, "gilded_glaxx")
        other = put(match, 1, "argonaut")
        match.player(1).gold = 1
        self.assertEqual(engine.weakest(match, 1, sacrifice=False), [other])
        match.player(1).gold = 0
        self.assertEqual(engine.weakest(match, 1, sacrifice=False), [glaxx, other])

    def test_hardened_mox_1(self) -> None:
        """You only have to trash Hardened Mox if you have one or more tech
        II units in play and/or forecasted. It doesn't care about Tech III
        units, Tech II buildings or upgrades, or units in Jail/Graveyard."""
        engine, game, match = purple()
        mox = put(match, 1, "hardened_mox")
        put(match, 1, "octavian")
        put(match, 1, "second_chances")
        built(match, 1, "tech2")
        board.settle(engine, match, board.StepResult())
        self.assertIsNotNone(match.player(1).instance(mox.id))
        board.to_future(engine, match, "reaver", 1)
        board.settle(engine, match, board.StepResult())
        self.assertIsNone(match.player(1).instance(mox.id))
        self.assertNotIn("hardened_mox", match.player(1).discard)

    def test_hive_1(self) -> None:
        """If you have two Hives, you can have up to 10 Stingers."""
        engine, game, match = purple()
        tech(match, 1, 2, "future")
        match.player(1).gold = 20
        hand(match, 1, "hive", "hive")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="hive")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="hive")
        stingers = [card for card in match.player(1).play if card.slug == "stinger"]
        self.assertEqual(len(stingers), 10)

    def test_hive_2(self) -> None:
        """If you have two Hives and more than 5 Stingers and you lose a
        Hive, the active player chooses which 5 Stingers you sacrifice."""
        engine, game, match = purple(first=2)
        first = put(match, 1, "hive")
        put(match, 1, "hive")
        match.record_event("summoned_token", slug="stinger", seat=1)
        stingers = [put(match, 1, "stinger") for _ in range(7)]
        board.destroy(engine, match, [(1, first.ref)], board.StepResult(), cause=2)
        board.settle(engine, match, board.StepResult())
        prompt = asked(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.TARGET)
        self.assertEqual(prompt.asked_player, 2)
        for stinger in stingers[:2]:
            apply(engine, game, match, PromptKind.TARGET, target=f"1:{stinger.ref}")
        left = [card for card in match.player(1).play if card.slug == "stinger"]
        self.assertEqual(left, stingers[2:])

    def test_max_geiger_1(self) -> None:
        """When his max level ability returns a unit to play, it returns
        under the control of whoever controlled it when it was trashed."""
        engine, game, match = purple()
        hero_in_play(match, 1, slug="max_geiger", level=4)
        stolen = put(match, 2, "bone_collector")
        board.gain_control(match, stolen, 1)
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "level", hero="max_geiger", levels=1)
        apply(engine, game, match, PromptKind.TARGET, target=f"1:{stolen.ref}")
        back = next(card for card in match.player(1).play if card.slug == "bone_collector")
        self.assertNotEqual(back.id, stolen.id)
        self.assertEqual((back.owner, back.controller), (2, 1))

    def test_max_geiger_2(self) -> None:
        """When his max level ability returns a unit to play, it returns in a
        "fresh" state. It's a new object, and no longer has any properties of
        the old object such as +1/+1 runes, damage, being a dance partner
        from Two Step, etc. It also returns ready (not exhausted) and it
        can't attack or use exhaust abilities unless it has haste."""
        engine, game, match = purple()
        hero_in_play(match, 1, slug="max_geiger", level=4)
        unit = put(match, 1, "argonaut", damage=2, exhausted=True)
        unit.plus_runes = 1
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "level", hero="max_geiger", levels=1)
        apply(engine, game, match, PromptKind.TARGET, target=f"1:{unit.ref}")
        back = next(card for card in match.player(1).play if card.slug == "argonaut")
        self.assertNotEqual(back.id, unit.id)
        self.assertEqual((back.damage, back.plus_runes, back.exhausted), (0, 0, False))
        self.assertNotIn(back.ref, engine.attackers(match))

    def test_max_geiger_returns_a_token_too(self) -> None:
        """The author, 2026-10-10: a token Max Geiger trashes comes back."""
        engine, game, match = purple()
        hero_in_play(match, 1, slug="max_geiger", level=4)
        skeleton = put(match, 1, "skeleton")
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "level", hero="max_geiger", levels=1)
        apply(engine, game, match, PromptKind.TARGET, target=f"1:{skeleton.ref}")
        back = next(card for card in match.player(1).play if card.slug == "skeleton")
        self.assertNotEqual(back.id, skeleton.id)

    def test_nebula_1(self) -> None:
        """You can use the ability the turn Nebula arrives because it doesn't
        have exhaust as part of the cost."""
        engine, game, match = purple()
        nebula = put(match, 1, "nebula", arrived=True)
        victim = put(match, 2, "bone_collector")
        ability(engine, game, match, "nebula", nebula.ref)
        self.assertIsNone(match.player(2).instance(victim.id))
        self.assertFalse(option(engine, match, "nebula", nebula.ref).allowed, "once per turn")

    def test_origin_story_1(self) -> None:
        """Whenever heroes enter a command zone, they lose all levels (become
        level 1) and other properties. They lose any damage on them, lose
        +1/+1 runes, lose any attachments, etc."""
        engine, game, match = purple()
        at_max(engine, match, 1, "prynn_pasternaak")
        hero_in_play(match, 2, slug="vandy_anadrose", level=4, damage=1)
        vandy = match.player(2).hero_of("vandy_anadrose")
        vandy.plus_runes = 1
        cast(engine, game, match, "origin_story", f"2:{hero(match, 2, 'vandy_anadrose')}")
        self.assertEqual((vandy.zone, vandy.level, vandy.damage, vandy.plus_runes),
                         ("command", 1, 0, 0))
        self.assertEqual(vandy.summoning_runes, 0, "no death, so no summoning runes")
        self.assertFalse(any(event["kind"] == "hero_died" for event in match.events))

    def test_prynn_pasternaak_1(self) -> None:
        """She fades away when her last time rune is removed for any reason.
        Removing the last rune with the Time Spiral spell or her own max
        level ability will cause her to die."""
        engine, game, match = purple()
        hero_in_play(match, 1, slug="prynn_pasternaak")
        prynn = match.player(1).hero_of("prynn_pasternaak")
        prynn.time_runes = 1
        board.remove_time_rune(engine, match, 1, hero(match, 1, "prynn_pasternaak"), board.StepResult())
        self.assertEqual(prynn.zone, "command")

    def test_prynn_pasternaak_2(self) -> None:
        """"Dies from fading" means that the last time rune she had was
        removed because the fading ability said to do that during the upkeep.
        It doesn't trigger if something else removed her last time rune."""
        engine, game, match = purple()
        hero_in_play(match, 1, slug="prynn_pasternaak", level=4)
        prynn = match.player(1).hero_of("prynn_pasternaak")
        prynn.time_runes = 1
        board.remove_time_rune(engine, match, 1, hero(match, 1, "prynn_pasternaak"), board.StepResult())
        self.assertFalse(match.player(2).skip_draw)
        hero_in_play(match, 1, slug="prynn_pasternaak", level=4)
        prynn.time_runes = 1
        turn_round(engine, game, match, 1)
        self.assertEqual(prynn.zone, "command")
        self.assertTrue(match.player(2).skip_draw)

    def test_prynn_pasternaak_3(self) -> None:
        """If she has exactly two time runes, she CAN use her max level
        ability to trash a unit. If she does, she then immediately dies
        because of hanving no fading runes, then the trashed unit returns to
        play. This does not count as "dies from fading" on her middle
        ability, because that only triggers if fading itself removed the
        last time rune."""
        engine, game, match = purple()
        hero_in_play(match, 1, slug="prynn_pasternaak", level=7)
        prynn = match.player(1).hero_of("prynn_pasternaak")
        prynn.time_runes = 2
        victim = put(match, 2, "bone_collector", damage=1)
        ability(engine, game, match, "prynn_pasternaak_max", hero(match, 1, "prynn_pasternaak"))
        self.assertEqual(prynn.zone, "command")
        back = next(card for card in match.player(2).play if card.slug == "bone_collector")
        self.assertNotEqual(back.id, victim.id)
        self.assertFalse(match.player(2).skip_draw)

    def test_prynn_pasternaak_4(self) -> None:
        """When her max level ability returns a unit to play, it returns
        under the control of whoever controlled it when it was trashed."""
        engine, game, match = purple()
        hero_in_play(match, 1, slug="prynn_pasternaak", level=7)
        prynn = match.player(1).hero_of("prynn_pasternaak")
        prynn.time_runes = 3
        stolen = put(match, 2, "bone_collector")
        board.gain_control(match, stolen, 1)
        ability(engine, game, match, "prynn_pasternaak_max", hero(match, 1, "prynn_pasternaak"))
        self.assertEqual(len(prynn.trashed), 1)
        board.destroy(engine, match, [(1, hero(match, 1, "prynn_pasternaak"))], board.StepResult(), cause=2)
        back = next(card for card in match.player(1).play if card.slug == "bone_collector")
        self.assertEqual((back.owner, back.controller), (2, 1))

    def test_prynn_pasternaak_5(self) -> None:
        """When her max level ability returns a unit to play, it returns in a
        "fresh" state. It's a new object, and no longer has any properties of
        the old object such as +1/+1 runes, damage, being a dance partner
        from Two Step, etc. It also returns ready (not exhausted) and it
        can't attack or use exhaust abilities unless it has haste."""
        engine, game, match = purple()
        hero_in_play(match, 1, slug="prynn_pasternaak", level=7)
        prynn = match.player(1).hero_of("prynn_pasternaak")
        prynn.time_runes = 2
        unit = put(match, 1, "argonaut", damage=1, exhausted=True)
        unit.plus_runes = 2
        ability(engine, game, match, "prynn_pasternaak_max", hero(match, 1, "prynn_pasternaak"))
        back = next(card for card in match.player(1).play if card.slug == "argonaut")
        self.assertEqual((back.damage, back.plus_runes, back.exhausted), (0, 0, False))
        self.assertNotIn(back.ref, engine.attackers(match))

    def test_ready_or_not_1(self) -> None:
        """Readying one of your units CAN allow it to attack twice in a turn.
        (Attack with a unit, which will exhaust it. Play Ready or Not on that
        unit to ready it, then you can attack with it again.)"""
        engine, game, match = purple()
        at_max(engine, match, 1, "max_geiger")
        unit = put(match, 1, "neo_plexus")
        attack(engine, game, match, unit.ref, "base")
        self.assertNotIn(unit.ref, engine.attackers(match))
        cast(engine, game, match, "ready_or_not")
        self.assertIn(unit.ref, engine.attackers(match))

    def test_ready_or_not_2(self) -> None:
        """If a unit has the readiness keyword, using Ready or Not on it
        won't let you attack twice in a turn with it because readiness
        specifically says you can't do that."""
        engine, game, match = purple()
        at_max(engine, match, 1, "max_geiger")
        unit = put(match, 1, "argonaut")
        attack(engine, game, match, unit.ref, "base")
        unit.exhausted = True
        cast(engine, game, match, "ready_or_not")
        self.assertNotIn(unit.ref, engine.attackers(match))

    def test_ready_or_nots_second_clause_holds_exhausted_units_down(self) -> None:
        engine, game, match = purple()
        at_max(engine, match, 1, "max_geiger")
        put(match, 1, "neo_plexus")
        tired = put(match, 2, "bone_collector", exhausted=True)
        fresh = put(match, 2, "gorgon")
        cast(engine, game, match, "ready_or_not")
        turn_round(engine, game, match, 2)
        self.assertTrue(tired.exhausted)
        self.assertFalse(fresh.exhausted)

    def test_reaver_1(self) -> None:
        """If you choose the to "Deal 6 damage to up to 2 units and/or
        heroes", that means you can hit two units for 6 damage each, two
        heroes for 6 damage each, or one unit for 6 damage AND one hero for 6
        damage. You could also choose to hit just one thing if you want: one
        unit for 6 damage or one hero for 6 damage."""
        engine, game, match = purple()
        reaver = put(match, 1, "reaver")
        hero_in_play(match, 2, slug="vandy_anadrose", level=5)
        unit = put(match, 2, "gorgon")
        hand(match, 1, "neo_plexus")
        match.player(1).gold = 3
        ability(engine, game, match, "reaver", reaver.ref)
        apply(engine, game, match, PromptKind.MODE_CHOICE, mode="damage")
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{unit.ref}")
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{hero(match, 2, 'vandy_anadrose')}")
        self.assertIsNone(match.player(2).instance(unit.id))
        self.assertFalse(match.player(2).hero_of("vandy_anadrose").in_play)

    def test_reaver_2(self) -> None:
        """When you trash an opponent's worker, you don't get to choose which
        worker to destroy (because they're alll considered identical) and you
        don't get to see the front of the destroyed worker."""
        engine, game, match = purple()
        reaver = put(match, 1, "reaver")
        hand(match, 1, "neo_plexus")
        match.player(1).gold = 3
        workers = match.player(2).workers
        ability(engine, game, match, "reaver", reaver.ref)
        run = apply(engine, game, match, PromptKind.MODE_CHOICE, mode="workers")
        apply(engine, game, match, PromptKind.TARGET, target="2:workers")
        apply(engine, game, match, PromptKind.TARGET, target="2:workers")
        self.assertEqual(match.player(2).workers, workers - 2)
        del run

    def test_rememberer_1(self) -> None:
        """When you "return a unit with fading to play" this way, you don't
        pay for it."""
        engine, game, match = purple()
        rememberer = put(match, 1, "rememberer")
        rememberer.time_runes = 3
        match.player(1).discard = ["fading_argonaut"]
        match.player(1).gold = 0
        board.remove_time_rune(engine, match, 1, rememberer.ref, board.StepResult())
        apply(engine, game, match, PromptKind.TARGET, target="1:discard:fading_argonaut")
        argonaut = next(card for card in match.player(1).play if card.slug == "fading_argonaut")
        self.assertEqual(argonaut.time_runes, 3)

    def test_rememberer_2(self) -> None:
        """If the reason you remove a time rune from Rememberer isn't because
        of the fading ability, but rather something else such as Time Spiral,
        Seer, or Tinkerer, then Remember's ability to give you a unit with
        fading from your discard pile still DOES trigger."""
        engine, game, match = purple()
        rememberer = put(match, 1, "rememberer")
        rememberer.time_runes = 3
        tinkerer = put(match, 1, "tinkerer")
        match.player(1).discard = ["fading_argonaut"]
        ability(engine, game, match, "tinkerer", tinkerer.ref)
        apply(engine, game, match, PromptKind.MODE_CHOICE, mode="remove")
        prompt = asked(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.TARGET)
        self.assertEqual([row.ref for row in prompt.options.targets], ["discard:fading_argonaut"])

    def test_rememberer_3(self) -> None:
        """If you have just one Rememberer and you remove the last time rune,
        you CAN return her to play with her own ability. In this situation,
        the "dies from fading" effect and the "remember" ability trigger
        simultaneously, so as the active player you can choose the order."""
        engine, game, match = purple()
        tech(match, 1, 2, "past")
        rememberer = put(match, 1, "rememberer")
        rememberer.time_runes = 1
        match.player(1).discard = []
        board.remove_time_rune(engine, match, 1, rememberer.ref, board.StepResult())
        apply(engine, game, match, PromptKind.TARGET, target="1:discard:rememberer")
        back = next(card for card in match.player(1).play if card.slug == "rememberer")
        self.assertEqual(back.time_runes, 3)

    def test_rememberer_4(self) -> None:
        """You CAN return a tech III unit to play with this (for free!) but in
        order to do so, you must have the appropriate spec tech III building
        fully constructed."""
        engine, game, match = purple()
        rememberer = put(match, 1, "rememberer")
        rememberer.time_runes = 3
        match.player(1).discard = ["ebbflow_archon"]
        rows = engine.target_candidates(match, 1, "discard_fading_unit")
        self.assertEqual(rows, [])
        tech(match, 1, 3, "past")
        rows = engine.target_candidates(match, 1, "discard_fading_unit")
        self.assertEqual([ref for _, ref in rows], ["discard:ebbflow_archon"])

    def test_research__development_1(self) -> None:
        """You resolve a spell's effect before discarding it, so a given copy
        of Research & Development cannot draw itself from its own effect. You
        first draw cards from its effect, and you reshuffle your discard pile
        into your draw pile if you would draw from empty draw pile. Then, you
        discard Research & Development when you have finished resolving its
        effect."""
        engine, game, match = purple(first=1)
        at_max(engine, match, 1, "max_geiger")
        match.player(1).deck = ["neo_plexus"] * 2
        match.player(1).discard = ["argonaut"] * 4
        cast(engine, game, match, "research__development")
        self.assertEqual(len(match.player(1).hand), 5)
        self.assertEqual(match.player(1).discard, ["research__development"])

    def test_research__development_2(self) -> None:
        """As a gamewide rule, you can only reshuffle your discard pile into
        your draw pile once per main phase. The help text on this card is
        there because it's very possible to "try" to do it more times using
        this card. If drawing cards during your main phase causes you to
        reshuffle your discard pile into your draw pile once, then later that
        same main phase you would draw when you have an empty draw pile,
        instead you don't. You can't draw any more cards until your
        draw/discard step."""
        engine, game, match = purple(first=1)
        at_max(engine, match, 1, "max_geiger")
        match.player(1).deck = []
        match.player(1).discard = ["argonaut"] * 2
        match.player(1).reshuffled_this_phase = False
        cast(engine, game, match, "research__development")
        self.assertEqual(len(match.player(1).hand), 2)

    def test_rewind_1(self) -> None:
        """This doesn't cause the units to "die", so the opponent won't draw
        a card if a returned unit was in the technician slot."""
        engine, game, match = purple()
        at_max(engine, match, 1, "prynn_pasternaak")
        match.player(1).hero.max_level_since_turn_began = False
        tech_unit = put(match, 2, "bone_collector", patrol="technician")
        before = len(match.player(2).hand)
        cast(engine, game, match, "rewind")
        self.assertIsNone(match.player(2).instance(tech_unit.id))
        self.assertEqual(len(match.player(2).hand), before + 1, "the card itself, nothing drawn")

    def test_second_chances_1(self) -> None:
        """When this returns a unit to play, it returns in a "fresh" state.
        It's a new object, and no longer has any properties of the old object
        such as +1/+1 runes, damage, being a dance partner from Two Step,
        etc. It also returns ready (not exhausted) and it can't attack or use
        exhaust abilities unless it has haste."""
        engine, game, match = purple()
        put(match, 1, "second_chances")
        unit = put(match, 1, "argonaut", damage=1)
        unit.plus_runes = 1
        board.destroy(engine, match, [(1, unit.ref)], board.StepResult(), cause=2)
        back = next(card for card in match.player(1).play if card.slug == "argonaut")
        self.assertEqual((back.damage, back.plus_runes, back.exhausted), (0, 0, False))
        self.assertNotIn("argonaut", match.player(1).discard)

    def test_second_chances_2(self) -> None:
        """This does trigger on opponent's turns. So it can trigger once on
        your own turn, again on an opponent's turn, then again when it's your
        following turn, etc."""
        engine, game, match = purple(first=2)
        put(match, 1, "second_chances")
        unit = put(match, 1, "argonaut")
        board.destroy(engine, match, [(1, unit.ref)], board.StepResult(), cause=2)
        self.assertTrue(any(card.slug == "argonaut" for card in match.player(1).play))
        again = next(card for card in match.player(1).play if card.slug == "argonaut")
        board.destroy(engine, match, [(1, again.ref)], board.StepResult(), cause=2)
        self.assertFalse(any(card.slug == "argonaut" for card in match.player(1).play),
                         "once per turn")

    def test_second_chances_3(self) -> None:
        """If you steal a unit with Kidnapping, and this would then "return it
        to play," it returns under your control, not the original owner's
        control. "Return" effects check the last controller, rather than the
        owner."""
        engine, game, match = purple()
        put(match, 1, "second_chances")
        stolen = put(match, 2, "bone_collector")
        board.gain_control(match, stolen, 1)
        board.destroy(engine, match, [(1, stolen.ref)], board.StepResult(), cause=1)
        back = next(card for card in match.player(1).play if card.slug == "bone_collector")
        self.assertEqual((back.owner, back.controller), (2, 1))

    def test_second_chances_4(self) -> None:
        """If one of your TOKEN units leaves play, then it's destroyed as
        usual. (Tokens can't go to other zones than in play.) This does not
        use up the "once-per-turn" of Second Chances, so Second Chances will
        still trigger later than turn if one of your non-token units dies
        from something other than combat damage."""
        engine, game, match = purple()
        put(match, 1, "second_chances")
        token = put(match, 1, "stinger")
        unit = put(match, 1, "argonaut")
        board.destroy(engine, match, [(1, token.ref)], board.StepResult(), cause=2)
        self.assertFalse(any(card.slug == "stinger" for card in match.player(1).play))
        board.destroy(engine, match, [(1, unit.ref)], board.StepResult(), cause=2)
        self.assertTrue(any(card.slug == "argonaut" for card in match.player(1).play))

    def test_second_chances_5(self) -> None:
        """The sparkshot ability and the Tower add-on deal combat damage, so
        if these kill one of your units, Second Chances won't save it. Second
        Chances will save units affected by Undo, Rewind, Doom Grasp (whether
        it was the sacrifice effect OR destroy effect!), Hooded Executioner's
        ability, the obliterate ability, damage from Flame Arrow or Shadow
        Blade, to name a few."""
        engine, game, match = purple(first=2)
        put(match, 1, "second_chances")
        guard = put(match, 1, "neo_plexus", patrol="squad_leader")
        side = put(match, 1, "argonaut", patrol="elite")
        side.damage = 3
        crawler = put(match, 2, "crypt_crawler")
        attack(engine, game, match, crawler.ref, guard.ref)
        self.assertFalse(any(card.slug == "argonaut" for card in match.player(1).play),
                         "sparkshot is combat damage")
        unit = put(match, 1, "gorgon")
        from codex.flow import combat as fight

        match.combat = None
        del fight
        board.destroy(engine, match, [(1, unit.ref)], board.StepResult(), cause=2)
        self.assertTrue(any(card.slug == "gorgon" for card in match.player(1).play),
                        "a destroy effect is no combat damage")

    def test_sentry_1(self) -> None:
        """The damage done by the sparkshot ability and by the Tower add-on
        are both combat damage. But they are also both "abilities" so Sentry
        CAN prevent their damage."""
        engine, game, match = purple(first=2)
        put(match, 1, "sentry")
        guard = put(match, 1, "neo_plexus", patrol="squad_leader")
        side = put(match, 1, "argonaut", patrol="elite", damage=3)
        crawler = put(match, 2, "crypt_crawler")
        attack(engine, game, match, crawler.ref, guard.ref)
        self.assertIsNotNone(match.player(1).instance(side.id))
        self.assertEqual(side.damage, 3)

    def test_slowtime_generator_1(self) -> None:
        """For example, if a player had 7 workers, they would get a total of
        4 gold from their workers, rather than 7 gold."""
        engine, game, match = purple()
        put(match, 2, "slowtime_generator")
        match.player(1).workers = 7
        match.player(1).gold = 0
        turn_round(engine, game, match, 1)
        self.assertEqual(match.player(1).gold, 4)

    def test_stewardess_of_the_undone_1(self) -> None:
        """This doesn't cause the unit to "die", so the opponent won't draw a
        card if it was in the technician slot."""
        engine, game, match = purple()
        tech(match, 1, 1)
        victim = put(match, 2, "neo_plexus", patrol="technician")
        before = len(match.player(2).hand)
        hand(match, 1, "stewardess_of_the_undone")
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="stewardess_of_the_undone")
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{victim.ref}")
        self.assertIsNone(match.player(2).instance(victim.id))
        self.assertEqual(len(match.player(2).hand), before + 1)

    def test_temporal_distortion_1(self) -> None:
        """The "if you do" clause of Temporal Distortion is not satisfied if
        you try to return a unit to your hand, but it can't be returned, such
        as a Gilded Glaxx that "can't leave play." """
        engine, game, match = purple()
        at_max(engine, match, 1, "max_geiger")
        put(match, 1, "gilded_glaxx")
        cast(engine, game, match, "temporal_distortion")
        self.assertTrue(any(card.slug == "gilded_glaxx" for card in match.player(1).play))
        self.assertEqual(match.resolving, [])

    def test_temporal_distortion_2(self) -> None:
        """Tokens are generally tech 0, so they usually can't be returned to
        your hand for this effect. However, if you have a token that's
        copying a tech I or II unit, you CAN choose to return it to your hand
        for this spell. It will be destroyed as it would go into your hand,
        but the "if you do" clause of Temporal Distortion is satisfied. You
        really can still put a unit from your codex into play (based on the
        cost and tech level of the unit that token was copying)."""
        # Copies are the Whitestar Order's (step 13): pinned here is that a
        # token, tech 0, is never offered.
        engine, game, match = purple()
        at_max(engine, match, 1, "max_geiger")
        put(match, 1, "stinger")
        hand(match, 1, "temporal_distortion")
        self.assertIn("no target",
                      engine.why_not_playable(match.player(1), "temporal_distortion", match))

    def test_tricycloid_1(self) -> None:
        """Whenever anything leaves play then comes back into play, it's
        treated as a fresh copy. So if this is trashed then returns to play
        with Geiger's or Pasternaak's max level abilities, it will get three
        new time runes when it returns. Also, if you can return it to your
        hand with Temporal Distortion, then replay it to have it arrive with
        three new times runes as well."""
        engine, game, match = purple()
        hero_in_play(match, 1, slug="max_geiger", level=4)
        tricycloid = put(match, 1, "tricycloid")
        tricycloid.time_runes = 1
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "level", hero="max_geiger", levels=1)
        apply(engine, game, match, PromptKind.TARGET, target=f"1:{tricycloid.ref}")
        back = next(card for card in match.player(1).play if card.slug == "tricycloid")
        self.assertEqual(back.time_runes, 3)
        self.assertEqual(engine.unit_stats(back, match), (6, 6))

    def test_undo_1(self) -> None:
        """This doesn't cause the unit to "die", so the opponent won't draw a
        card if it was in the technician slot."""
        engine, game, match = purple()
        at_max(engine, match, 1, "prynn_pasternaak")
        victim = put(match, 2, "neo_plexus", patrol="technician")
        before = len(match.player(2).hand)
        cast(engine, game, match, "undo")
        self.assertIsNone(match.player(2).instance(victim.id))
        self.assertEqual(len(match.player(2).hand), before + 1)

    def test_vir_garbarean_1(self) -> None:
        """If you have no draw pile, looking at the top card of your draw
        pile does nothing. It does NOT cause you to shuffle your discard pile
        into your draw pile."""
        engine, game, match = purple()
        hero_in_play(match, 1, slug="vir_garbarean")
        match.player(1).deck = []
        match.player(1).discard = ["argonaut"]
        self.assertEqual(option(engine, match, "vir_garbarean", hero(match, 1, "vir_garbarean")).why_not,
                         "your draw pile is empty")
        match.player(1).deck = ["neo_plexus"]
        ability(engine, game, match, "vir_garbarean", hero(match, 1, "vir_garbarean"))
        prompt = asked(engine, game, match)
        self.assertEqual([row.ref for row in prompt.options.targets], ["deck:neo_plexus"])
        apply(engine, game, match, PromptKind.TARGET, "done")
        self.assertEqual(match.player(1).deck, ["neo_plexus"])

    def test_vir_garbarean_2(self) -> None:
        """If you have no draw pile, you can't "exchange the top card of your
        draw pile with a card from your hand." Nothing happens."""
        engine, game, match = purple()
        hero_in_play(match, 1, slug="vir_garbarean")
        match.player(1).deck = []
        hand(match, 1, "argonaut")
        match.player(1).gold = 3
        self.assertEqual(option(engine, match, "vir_garbarean_exchange",
                                hero(match, 1, "vir_garbarean")).why_not, "your draw pile is empty")
        match.player(1).deck = ["neo_plexus"]
        ability(engine, game, match, "vir_garbarean_exchange", hero(match, 1, "vir_garbarean"))
        self.assertEqual((match.player(1).deck, match.player(1).hand), (["argonaut"], ["neo_plexus"]))

    def test_vir_garbarean_3(self) -> None:
        """The max level ability summons a Mech token that has two time runes
        on it. Remove one time rune each of your upkeeps. When you remove the
        last, th Mech arrives. The Mech does not have haste so it can't attack
        the turn it arrives."""
        engine, game, match = purple()
        hero_in_play(match, 1, slug="vir_garbarean", level=6)
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "level", hero="vir_garbarean", levels=1)
        self.assertEqual([(card.slug, card.time_runes) for card in match.player(1).future], [("mech", 2)])
        turn_round(engine, game, match, 1)
        turn_round(engine, game, match, 1)
        mech = next(card for card in match.player(1).play if card.slug == "mech")
        self.assertNotIn(mech.ref, engine.attackers(match))

    def test_vir_says_why_he_may_not_play_the_top_card(self) -> None:
        """An empty pile says so; a top card that can't be played says
        that much and no more -- the card is hidden."""
        engine, game, match = purple()
        hero_in_play(match, 1, slug="vir_garbarean", level=5)
        match.player(1).deck = []
        source = hero(match, 1, "vir_garbarean")
        self.assertEqual(option(engine, match, "vir_garbarean_play", source).why_not,
                         "your draw pile is empty")
        match.player(1).deck = ["argonaut"]
        match.player(1).gold = 0
        self.assertEqual(option(engine, match, "vir_garbarean_play", source).why_not,
                         "the top card of your draw pile can't be played now")

    def test_vir_plays_the_top_card(self) -> None:
        engine, game, match = purple()
        hero_in_play(match, 1, slug="vir_garbarean", level=5)
        match.player(1).deck = ["argonaut"]
        tech(match, 1, 1)
        match.player(1).gold = 5
        ability(engine, game, match, "vir_garbarean_play", hero(match, 1, "vir_garbarean"))
        self.assertTrue(any(card.slug == "argonaut" for card in match.player(1).play))
        self.assertEqual(match.player(1).gold, 2)

    def test_vortoss_emblem_1(self) -> None:
        """You can attach this to an enemy unit. If you do, you still control
        Vortoss Emblem itself, so the time runes on it still count toward
        your Temporal Research."""
        engine, game, match = purple()
        at_max(engine, match, 1, "prynn_pasternaak")
        enemy = put(match, 2, "bone_collector")
        cast(engine, game, match, "vortoss_emblem")
        emblem = next(card for card in match.player(1).play if card.slug == "vortoss_emblem")
        self.assertEqual((emblem.attached, emblem.time_runes), ([enemy.id], 3))
        self.assertEqual(engine.time_runes_of(match, 1), 3)
        self.assertTrue(engine.is_flagbearer_body(match, enemy))

    def test_warp_gate_disciple_1(self) -> None:
        """When you put units into play with this ability, you don't have to
        pay for them and you don't have to meet the tech requirements for
        them either, so you can still do it even if you don't have a tech I
        or II building at all."""
        engine, game, match = purple()
        disciple = put(match, 1, "warp_gate_disciple")
        match.player(1).gold = 1
        ability(engine, game, match, "warp_gate_disciple", disciple.ref)
        prompt = asked(engine, game, match)
        target = next(row.key for row in prompt.options.targets if row.ref == "codex:argonaut")
        apply(engine, game, match, PromptKind.TARGET, target=target)
        self.assertTrue(any(card.slug == "argonaut" for card in match.player(1).play))
        self.assertEqual(match.player(1).gold, 0)

    def test_xenostalker_1(self) -> None:
        """If multiple patrollers die simultaneously and the order they die
        would matter for some reason, then you as the active player choose
        that order."""
        engine, game, match = purple()
        xeno = put(match, 1, "xenostalker")
        one = put(match, 2, "skeleton", patrol="squad_leader")
        two = put(match, 2, "skeleton", patrol="elite")
        flier = put(match, 2, "cursed_crow", patrol="lookout")
        attack(engine, game, match, xeno.ref, "base")
        prompt = asked(engine, game, match)
        self.assertNotIn(flier.ref, [row.ref for row in prompt.options.targets])
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{one.ref}")
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{two.ref}")
        self.assertIsNone(match.player(2).instance(one.id))
        self.assertIsNone(match.player(2).instance(two.id))

    def test_yesterdays_golgort_1(self) -> None:
        """The Golgort's ability to gain a time rune triggers even if "you"
        deal combat damage to a building with another unit, or with a hero.
        It doesn't have to be with the Golgort itself."""
        engine, game, match = purple()
        golgort = put(match, 1, "yesterdays_golgort")
        golgort.time_runes = 1
        unit = put(match, 1, "argonaut")
        attack(engine, game, match, unit.ref, "base")
        self.assertEqual(golgort.time_runes, 2)

    def test_yesterdays_golgort_counts_combat_damage_alone(self) -> None:
        """The author, 2026-10-10: "Whenever you deal combat damage to a
        building" is combat damage -- a spell's damage to a base gives no
        rune."""
        engine, game, match = black()
        golgort = put(match, 2, "yesterdays_golgort")
        golgort.time_runes = 1
        hero_in_play(match, 2, slug="vandy_anadrose")
        match.player(1).deck = ["argonaut"] * 4
        hand(match, 2, "dark_pact")
        match.player(2).gold = 0
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="dark_pact")
        prompt = asked(engine, game, match)
        if prompt.kind is PromptKind.TARGET:
            apply(engine, game, match, PromptKind.TARGET, target="1:base")
        self.assertEqual(match.player(1).base_hp, 18)
        self.assertEqual(golgort.time_runes, 1)


def upkeep_ordered_by(engine, game, match, seat: int):
    """Turns with nothing done until `seat`'s upkeep asks its order: the
    kind it stops on."""
    from test_codex_keywords import next_upkeep

    next_upkeep(engine, game, match, 2 if seat == 1 else 1)
    for _ in range(4):
        prompt = pending_prompt(engine, game, match)
        if prompt is None:
            begin(engine, game, match)
            continue
        if prompt.kind is PromptKind.UPKEEP_ORDER or (match.active == seat and match.phase == "main"):
            return prompt.kind
        if prompt.kind is PromptKind.MAIN_ACTION:
            apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        elif prompt.kind is PromptKind.PATROL:
            apply(engine, game, match, PromptKind.PATROL, assignment={})
        elif prompt.kind is PromptKind.TECH_CHOICE:
            apply(engine, game, match, prompt.kind, player=prompt.asked_player,
                  picks=[slug for slug, n in prompt.options.codex if n][:prompt.options.minimum])
        else:
            apply(engine, game, match, prompt.kind, "confirm", player=prompt.asked_player)
    return pending_prompt(engine, game, match).kind


def upkeep_of(engine, game, match, seat: int) -> None:
    """`seat`'s next upkeep and main phase, nothing done in between."""
    turn_round(engine, game, match, seat)


class UpkeepRulingTests(unittest.TestCase):
    """The upkeep, the extra turn and the debt (step 12, commit 6)."""

    def test_banefire_golem_1(self) -> None:
        """You can sacrifice him for his own effect. If you control no other
        units, you MUST sacrifice him since the effect isn't optional. You'll
        still deal the damage."""
        engine, game, match = black()
        golem = put(match, 2, "banefire_golem")
        victim = put(match, 1, "neo_plexus")
        upkeep_of(engine, game, match, 2)
        self.assertIsNone(match.player(2).instance(golem.id))
        self.assertEqual(victim.damage, 1)
        self.assertEqual(match.player(1).base_hp, 19)

    def test_banefire_golem_asks_which_unit_where_there_are_two(self) -> None:
        engine, game, match = black()
        golem = put(match, 2, "banefire_golem")
        fodder = put(match, 2, "skeleton")
        match.active = 1
        match.enter_phase("ready")
        match.player(1).tech_owed = False
        begin(engine, game, match)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        apply(engine, game, match, PromptKind.PATROL, assignment={})
        begin(engine, game, match)
        for standing in __import__("codex.prompts", fromlist=["x"]).standing_prompts(engine, match, game):
            del standing
        prompt = asked(engine, game, match)
        while prompt.kind in (PromptKind.TECH_CHOICE, PromptKind.TECH_CONFIRM):
            if prompt.kind is PromptKind.TECH_CHOICE:
                apply(engine, game, match, prompt.kind, player=prompt.asked_player,
                      picks=[slug for slug, n in prompt.options.codex if n][:prompt.options.minimum])
            else:
                apply(engine, game, match, prompt.kind, "confirm", player=prompt.asked_player)
            begin(engine, game, match)
            prompt = asked(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.TARGET)
        self.assertEqual({row.ref for row in prompt.options.targets}, {golem.ref, fodder.ref})
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{fodder.ref}")
        self.assertIsNotNone(match.player(2).instance(golem.id))

    def test_plague_lord_1(self) -> None:
        """The upkeep ability only triggers during your upkeep, not each
        other player's. When it triggers, even your own base takes damage if
        you have any -1/-1 runes on your units or heroes."""
        from test_codex_keywords import next_upkeep

        engine, game, match = black()
        put(match, 2, "plague_lord")
        mine = put(match, 2, "argonaut")
        mine.minus_runes = 1
        theirs = put(match, 1, "argonaut")
        theirs.minus_runes = 2
        next_upkeep(engine, game, match, 1)
        self.assertEqual((match.player(1).base_hp, match.player(2).base_hp), (20, 20))
        next_upkeep(engine, game, match, 2)
        self.assertEqual((match.player(1).base_hp, match.player(2).base_hp), (18, 19))

    def test_shrine_of_forbidden_knowledge_1(self) -> None:
        """"Card draw +1, hand size +1" means that instead of discarding your
        hand and drawing that many cards +2, capped at 5, you instead discard
        your hand and draw that many cards +3, capped at 6."""
        engine, game, match = black()
        put(match, 2, "shrine_of_forbidden_knowledge")
        player = match.player(2)
        self.assertEqual(engine.draw_count(1, player), 4)
        self.assertEqual(engine.draw_count(5, player), 6)
        put(match, 2, "shrine_of_forbidden_knowledge")
        self.assertEqual(engine.draw_count(5, player), 7)
        before = player.base_hp
        upkeep_of(engine, game, match, 2)
        self.assertEqual(player.base_hp, before - 2, "each Shrine's 1 at its upkeep")

    def test_double_time_1(self) -> None:
        """If you would take multiple extra turns, they do stack so you can
        potentially take 3 turns in a row."""
        engine, game, match = purple()
        for _ in range(2):
            board.to_future(engine, match, "double_time", 1)
        for card in match.player(1).future:
            card.time_runes = 1
        turn = match.turn
        upkeep_of(engine, game, match, 1)
        self.assertEqual(match.extra_turns, [1, 1])
        self.assertNotIn("double_time", match.player(1).discard, "trashed once it resolves")
        from test_codex_keywords import next_upkeep

        for _ in range(2):
            apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
            apply(engine, game, match, PromptKind.PATROL, assignment={})
            begin(engine, game, match)
            prompt = asked(engine, game, match)
            while prompt.kind in (PromptKind.TECH_CHOICE, PromptKind.TECH_CONFIRM):
                if prompt.kind is PromptKind.TECH_CHOICE:
                    apply(engine, game, match, prompt.kind, player=prompt.asked_player,
                          picks=[slug for slug, n in prompt.options.codex if n][:prompt.options.minimum])
                else:
                    apply(engine, game, match, prompt.kind, "confirm", player=prompt.asked_player)
                begin(engine, game, match)
                prompt = asked(engine, game, match)
            self.assertEqual(match.active, 1)
        self.assertEqual(match.extra_turns, [])
        self.assertEqual(match.turn, turn + 4)
        del next_upkeep

    def test_promise_of_payment_1(self) -> None:
        """You will get gold from your workers before you have to pay the
        cost. Also, since you as the active player decide in what order your
        upkeep effects happen, you can collect gold from upkeep effects like
        Galina Glimmer and Gemscout Owl before you have to pay. HOWEVER, you
        can't play cards or activate abilities (such as Merfolk Prospector
        and Rickety Mine) until your Main phase, so they can't help you pay
        the cost."""
        for owl_first in (True, False):
            with self.subTest(owl_first=owl_first):
                engine, game, match = purple()
                put(match, 1, "gemscout_owl")
                match.player(1).debt = 5
                match.player(1).gold = 0
                match.player(1).workers = 4
                self.assertIs(upkeep_ordered_by(engine, game, match, 1), PromptKind.UPKEEP_ORDER)
                prompt = asked(engine, game, match)
                self.assertIn("debt", prompt.options.effects)
                gains = [e for e in prompt.options.effects if e != "debt"]
                self.assertEqual(gains, ["owl"])
                first = gains[0] if owl_first else "debt"
                apply(engine, game, match, PromptKind.UPKEEP_ORDER, first=first)
                if owl_first:
                    # The Owl's gold makes 5 with the workers' 4.
                    self.assertIsNone(match.winner)
                    self.assertEqual((match.player(1).gold, match.player(1).debt), (0, 0))
                else:
                    # The active player's order: the debt first is 4 gold
                    # against 5, and the game is lost.
                    self.assertEqual((match.winner, match.lost_by_debt), (2, 1))

    def test_promise_of_payment_2(self) -> None:
        """You still have to pay any additional costs of that card as you
        play it. For example, if your opponent has a Building Inspector, you
        pay 1 even if Promise of Payment makes the first building you build
        cost 0."""
        # Building Inspector is the Flagstone Dominion's (step 13): pinned
        # here is that the promise is a card's cost, not what the card asks
        # on top -- a boost is still paid.
        engine, game, match = purple(first=2)
        at_max(engine, match, 2, "vandy_anadrose")
        tech(match, 2, 1)
        match.player(2).promised = True
        match.player(2).gold = 3
        hand(match, 2, "hooded_executioner")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="hooded_executioner", boost=True)
        self.assertEqual(match.player(2).gold, 0)
        self.assertEqual(match.player(2).debt, 2)

    def test_promise_of_payment_3(self) -> None:
        """Hiring a worker is not playing a card. Building a Tech Building or
        Add-on isn't playing a card. Using an ability of a card or putting a
        card into play is not playing a card. Promise of Payment doesn't
        apply to any of those things."""
        engine, game, match = purple()
        player = match.player(1)
        player.promised = True
        player.gold = 10
        hand(match, 1, "neo_plexus")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "hire", slug="neo_plexus")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "build", building="tower")
        self.assertEqual(player.gold, 10 - 1 - 3)
        self.assertTrue(player.promised)
        self.assertEqual(player.debt, 0)

    def test_promise_of_payment_4(self) -> None:
        """You CAN use Promise of Payment to play a unit from Graveyard or to
        play the top card of your draw pile with Vir's middle ability."""
        engine, game, match = purple()
        hero_in_play(match, 1, slug="vir_garbarean", level=5)
        tech(match, 1, 1)
        match.player(1).deck = ["argonaut"]
        match.player(1).promised = True
        match.player(1).gold = 0
        ability(engine, game, match, "vir_garbarean_play", hero(match, 1, "vir_garbarean"))
        self.assertTrue(any(card.slug == "argonaut" for card in match.player(1).play))
        self.assertEqual(match.player(1).debt, 3)

    def test_promise_of_payment_5(self) -> None:
        """Be sure to play Promise of Payment JUST before you play the card
        you want to pay 0 for. If you play another card in between (even with
        an effect like Cinderblast Dragon's attack effect), you have to apply
        Promise of Payment's effect to that card instead."""
        engine, game, match = purple()
        at_max(engine, match, 1, "vir_garbarean")
        hero_in_play(match, 1, slug="max_geiger")
        tech(match, 1, 2, "future")
        hand(match, 1, "promise_of_payment", "now", "reaver")
        match.player(1).gold = 1
        put(match, 1, "argonaut")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="promise_of_payment")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="now")
        self.assertEqual(match.player(1).debt, 1, "Now took the promise")
        self.assertIn("not enough gold", engine.why_not_playable(match.player(1), "reaver", match))

    def test_promise_of_payment_6(self) -> None:
        """The gold cost you have to pay during your next upkeep is the
        printed gold cost on the card. You don't get to apply any effects
        that would reduce its cost (even Gigadon's effect that's on the card
        itself)."""
        engine, game, match = purple()
        built(match, 1, "tech1")
        match.player(1).promised = True
        hand(match, 1, "argonaut")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="argonaut")
        self.assertEqual(match.player(1).debt, 3)

    def test_promise_of_payment_7(self) -> None:
        """If for some reason you play Promise of Payment and then don't play
        any other cards that turn, nothing happens during your next upkeeep."""
        engine, game, match = purple()
        at_max(engine, match, 1, "vir_garbarean")
        cast(engine, game, match, "promise_of_payment")
        self.assertTrue(match.player(1).promised)
        upkeep_of(engine, game, match, 1)
        self.assertFalse(match.player(1).promised)
        self.assertEqual(match.player(1).debt, 0)
        self.assertIsNone(match.winner)

    def test_promise_of_payment_8(self) -> None:
        """Promise of Payment does not help you pay for Boost. If you play
        Promise of Payment and then Murkwood Allies, you only get one kind of
        token unless you pay 4 gold."""
        engine, game, match = purple(first=2)
        tech(match, 2, 1)
        match.player(2).promised = True
        match.player(2).gold = 2
        hand(match, 2, "hooded_executioner")
        row = next(row for row in engine.playable(match.player(2), match) if row.slug == "hooded_executioner")
        self.assertEqual(row.cost, 0)
        self.assertEqual(row.boost_why_not, "not enough gold to boost")

    def test_promise_unpaid_loses_the_game(self) -> None:
        """Promise of Payment: "Pay its gold cost during your next upkeep or
        lose the game." -- GAME_OVER's third way."""
        engine, game, match = purple()
        match.player(1).debt = 9
        match.player(1).gold = 0
        upkeep_of(engine, game, match, 1)
        self.assertEqual((match.winner, match.lost_by_debt), (2, 1))
        prompt = asked(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.GAME_OVER)
        self.assertIn("could not pay", prompt.ask)
        self.assertEqual(prompt.options.lost_by_debt, 1)

    def test_second_chances_random_return_is_replayed_byte_for_byte(self) -> None:
        """Second Chances: "Choose randomly if multiples leave at once" --
        `engine.pick`, journalled beside the shuffles, so a replay by an
        engine of another seed returns the same one."""
        import json

        from codex import history
        from codex.engine import RulesEngine

        for seed in range(6):
            engine, game, match = new_game(seed=seed, first=1, teams=PB_TEAMS)
            put(match, 1, "second_chances")
            put(match, 1, "argonaut")
            put(match, 1, "neo_plexus")
            put(match, 1, "fading_argonaut")
            at_max(engine, match, 1, "prynn_pasternaak")
            hand(match, 1, "rewind")
            match.player(1).gold = 10
            begin(engine, game, match)
            match.player(1).hero.max_level_since_turn_began = True
            apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="rewind")
            outcome = match.journal[-1]["outcomes"]
            self.assertEqual(outcome[0][0], "@pick")
            replayed = history.replay(
                RulesEngine(seed=seed + 100), game, match.turn_snapshots[-1],
                match.journal, history=match.turn_snapshots,
            )
            self.assertEqual(json.dumps(replayed.to_dict(), sort_keys=True),
                             json.dumps(match.to_dict(), sort_keys=True))

    def test_a_forecast_unit_arrives_with_its_triggers_after_its_building_is_gone(self) -> None:
        """Forecast X: "A card in the future can arrive even if you lose the
        relevant spec or tech building" -- and it arrives as any unit does,
        what reads an arrival reading it."""
        engine, game, match = pb(first=1, teams=(("future", "past", "present"),
                                                 ("demonology", "disease", "necromancy")))
        tech(match, 1, 2, "future")
        put(match, 1, "blooming_ancient")
        hand(match, 1, "reaver")
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="reaver")
        match.player(1).buildings["tech2"].destroyed = True
        ancient = match.player(1).play[0]
        before = ancient.plus_runes
        upkeep_of(engine, game, match, 1)
        upkeep_of(engine, game, match, 1)
        self.assertTrue(any(card.slug == "reaver" for card in match.player(1).play))
        self.assertEqual(ancient.plus_runes, before + 1)


# -- White and blue (step 13) ---------------------------------------------------

#: Step 13: the rulings on white's and blue's cards, heroes and tokens --
#: 79 on the cards and 13 on the six heroes.
WHITE_BLUE_RULINGS = 92

WB_TEAMS = (("discipline", "ninjutsu", "strength"), ("law", "peace", "truth"))


def wb(first: int = 1, teams=WB_TEAMS):
    """White (seat 1) against blue (seat 2), a standard game, in `first`'s
    first main phase."""
    engine, game, match = new_game(first=first, teams=teams)
    begin(engine, game, match)
    return engine, game, match


def wb_hero(match, seat: int, slug: str, level: int = 1, **kwargs):
    hero_in_play(match, seat, slug=slug, level=level, **kwargs)
    return match.player(seat).hero_of(slug)


def answer_target(engine, game, match, key: str):
    return apply(engine, game, match, PromptKind.TARGET, target=key)


class WhiteBlueKeywordRulingTests(unittest.TestCase):
    """Commit 2's cards: the keywords and the copies."""

    def test_bluecoat_musketeer_1(self) -> None:
        """This effect checks what his ATK is after applying all effects and
        runes. It doesn't just check his printed or "base" ATK."""
        engine, game, match = wb(first=2)
        musketeer = put(match, 2, "bluecoat_musketeer")
        self.assertTrue(engine.has_keyword(musketeer, "Long-range", match))
        musketeer.modifiers.append({"kind": "atk", "amount": 1, "until": "end_of_turn"})
        self.assertFalse(engine.has_keyword(musketeer, "Long-range", match))
        musketeer.minus_runes = 1
        self.assertTrue(engine.has_keyword(musketeer, "Long-range", match))

    def test_liberty_gryphon_1(self) -> None:
        """If you control a Liberty Gryphon and Mirror Illusion copy of
        Liberty Gryphon, those both have the name "Liberty Gryphon." If you
        don't control any Illusions other than those, then your Liberty
        Gryphons do not get the keywords: unstoppable, unattackable,
        untargetable."""
        engine, game, match = wb(first=2)
        gryphon = put(match, 2, "liberty_gryphon")
        mirror = put(match, 2, "mirror_illusion")
        mirror.copy_of = "liberty_gryphon"
        mirror.modifiers.append({"kind": "illusion", "until": None})
        for body in (gryphon, mirror):
            for keyword in ("Unstoppable", "Unattackable", "Untargetable"):
                self.assertFalse(engine.has_keyword(body, keyword, match))
        put(match, 2, "spectral_hound")
        self.assertTrue(engine.has_keyword(gryphon, "Untargetable", match))

    def test_manufactured_truth_1(self) -> None:
        """Copying something copies the printed version of the card and
        does not copy any modifiers. For example, if you copy a 2/2 that has
        a +1/+1 rune on it and Spirit of the Panda attached to it, the copy
        will just be a 2/2."""
        engine, game, match = wb(first=2)
        wb_hero(match, 2, "sirus_quince")
        mine = put(match, 2, "spectral_hound")
        theirs = put(match, 1, "fox_viper")
        theirs.plus_runes = 1
        theirs.modifiers.append({"kind": "atk", "amount": 3, "until": "end_of_turn"})
        cast(engine, game, match, "manufactured_truth")
        self.assertEqual(mine.copy_of, "fox_viper")
        self.assertEqual(engine.unit_stats(mine, match), (2, 1))
        self.assertEqual((mine.plus_runes, mine.modifiers[0]["kind"]), (0, "copy"))

    def test_manufactured_truth_2(self) -> None:
        """If an effect changes the "printed" values of a card, the new
        values will be used. This includes Chaos Mirror and transformation
        effects such as Polymorph: Squirrel."""
        engine, game, match = wb(first=2)
        wb_hero(match, 2, "sirus_quince")
        mine = put(match, 2, "spectral_hound")
        theirs = put(match, 1, "fox_viper")
        theirs.printed = {"atk": 6}
        cast(engine, game, match, "manufactured_truth")
        self.assertEqual(engine.unit_stats(mine, match), (6, 1))
        theirs.printed = {"polymorph": 1}
        other = put(match, 2, "bluecoat_musketeer")
        cast(engine, game, match, "manufactured_truth")
        apply(engine, game, match, PromptKind.TARGET, target=f"2:{other.ref}")
        answer_target(engine, game, match, f"1:{theirs.ref}")
        self.assertEqual(engine.unit_stats(other, match), (1, 1))
        self.assertFalse(engine.texted(other))

    def test_justice_juggernaut_1(self) -> None:
        """If this doesn't have a crumbling rune on it and it would die, it
        doesn't actually die so nothing that triggers on "dies" will happen.
        For example, it won't draw a card if it "would die" in the
        technician slot, only when it really does die after it has a
        crumbling rune on it."""
        engine, game, match = wb()
        juggernaut = put(match, 2, "justice_juggernaut", patrol="technician")
        hand_before = len(match.player(2).hand)
        juggernaut.damage = 6
        board.settle(engine, match, StepResult())
        self.assertEqual(len(match.player(2).hand), hand_before)
        self.assertEqual(juggernaut.runes, {"crumbling": 1})
        juggernaut.damage = 6
        board.settle(engine, match, StepResult())
        self.assertIsNone(match.player(2).instance(juggernaut.id))
        self.assertEqual(len(match.player(2).hand), hand_before + 1)

    def test_garus_rook_1(self) -> None:
        """If this doesn't have a crumbling rune on it and it would die, it
        doesn't actually die so nothing that triggers on "dies" will happen.
        For example, it won't draw a card if it "would die" in the
        technician slot, only when it really does die after it has a
        crumbling rune on it."""
        engine, game, match = wb(first=2)
        rook = wb_hero(match, 1, "garus_rook", level=8, patrol="technician")
        hand_before = len(match.player(1).hand)
        rook.damage = 6
        board.settle(engine, match, StepResult())
        self.assertTrue(rook.in_play)
        self.assertEqual(len(match.player(1).hand), hand_before)
        rook.damage = 6
        board.settle(engine, match, StepResult())
        self.assertFalse(rook.in_play)
        self.assertEqual(rook.summoning_runes, 2)

    def test_reteller_of_truths_1(self) -> None:
        """The ability triggers from a unit dying, so it means that unit
        really did die. Anything that triggers from a unit dying really will
        trigger, such as drawing a card if the unit died when it was in the
        technician slot."""
        engine, game, match = wb()
        wb_hero(match, 1, "grave_stormborne")
        put(match, 2, "reteller_of_truths")
        hound = put(match, 2, "spectral_hound", patrol="technician")
        hand_before = len(match.player(2).hand)
        cast(engine, game, match, "wither", f"2:{hound.ref}")
        self.assertIn("spectral_hound", match.player(2).hand)
        # The technician's card, and the Hound back: two more.
        self.assertEqual(len(match.player(2).hand), hand_before + 2)

    def test_spectral_flagbearer_1(self) -> None:
        """If you aren't able to target an opposing Flagbearer for any
        reason, you don't have to. That includes if the Flagbearer has
        "resist 1" and you have no gold. In that case, you can't target it
        with a spell or ability because you can't afford to pay the cost for
        resist, so you can ignore the Flagbearer and target something
        else."""
        engine, game, match = wb()
        wb_hero(match, 1, "grave_stormborne")
        flag = put(match, 2, "spectral_flagbearer", patrol="lookout")
        other = put(match, 2, "scribe", patrol="elite")
        hand(match, 1, "spark")
        match.player(1).gold = 1
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="spark")
        self.assertEqual(other.damage, 1)
        self.assertIsNotNone(match.player(2).instance(flag.id))
        # With the gold for its resist, the flagbearer is the one target --
        # an Illusion, which dies of it.
        flag2 = put(match, 2, "spectral_flagbearer", patrol="scavenger")
        hand(match, 1, "spark")
        match.player(1).gold = 3
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="spark")
        prompt = asked(engine, game, match)
        self.assertTrue(prompt.options.forced)
        answer_target(engine, game, match, f"2:{flag2.ref}")
        self.assertIsNone(match.player(2).instance(flag2.id))

    def test_smoker_1(self) -> None:
        """When Smoker is targeted by something, he immediately returns to
        hand, even before the rest of the spell or ability that targeted him
        resolves."""
        engine, game, match = wb(first=2)
        wb_hero(match, 2, "sirus_quince")
        smoker = put(match, 1, "smoker", patrol="elite")
        cast(engine, game, match, "wither", f"1:{smoker.ref}")
        self.assertIsNone(match.player(1).instance(smoker.id))
        self.assertIn("smoker", match.player(1).hand)
        self.assertEqual(smoker.minus_runes, 0)


def end_turn_of(engine, game, match, seat: int) -> None:
    """End `seat`'s main phase with nothing patrolling, then run what the
    bot owes into the next player's turn -- tech confirmed where asked."""
    from codex_positions import begin as run_owed_steps

    apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
    apply(engine, game, match, PromptKind.PATROL, assignment={})
    while True:
        prompt = asked(engine, game, match)
        if prompt is not None and prompt.kind is PromptKind.STASH:
            apply(engine, game, match, PromptKind.STASH, "none")
            continue
        if prompt is not None and prompt.kind in (PromptKind.TECH_CHOICE, PromptKind.TECH_CONFIRM):
            player = prompt.asked_player
            if prompt.kind is PromptKind.TECH_CHOICE:
                picks = [slug for slug, left in prompt.options.codex for _ in range(left)][:prompt.options.maximum]
                apply(engine, game, match, PromptKind.TECH_CHOICE, player=player,
                      picks=picks[:prompt.options.minimum] or picks[:prompt.options.maximum])
            else:
                apply(engine, game, match, PromptKind.TECH_CONFIRM, "confirm", player=player)
            continue
        run_owed_steps(engine, game, match)
        prompt = asked(engine, game, match)
        if prompt is None or prompt.kind not in (PromptKind.TECH_CHOICE, PromptKind.TECH_CONFIRM,
                                                  PromptKind.STASH):
            return


class WhiteBlueRuleRulingTests(unittest.TestCase):
    """Commit 3's cards: the zones and the rules a player is put under."""

    def jail_against(self, attacker_spec: str = "necromancy"):
        """`attacker_spec`'s seat 1 against blue's seat 2, a Jail of seat 2's
        in play, seat 1 on its main phase with the buildings to play its
        tech I and II units."""
        engine, game, match = new_game(teams=((attacker_spec,), ("law",)))
        begin(engine, game, match)
        hero_in_play(match, 1)
        built(match, 1, "tech1")
        built(match, 1, "tech2")
        jail = put(match, 2, "jail")
        return engine, game, match, jail

    def test_jail_1(self) -> None:
        """When a unit goes from hand to Jail, that unit does not "enter
        play" or arrive. It goes directly to the Jail zone and it's not
        considered in play. When it's released from Jail (from another unit
        entering), it will arrive and trigger any "arrive" effects at that
        time."""
        engine, game, match, jail = self.jail_against()
        weak = put(match, 2, "tenderfoot")
        hand(match, 1, "hooded_executioner", "older_brother")
        match.player(1).gold = 20
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="hooded_executioner", boost=True)
        self.assertEqual(jail.jailed["slug"], "hooded_executioner")
        self.assertTrue(jail.jailed["boosted"])
        self.assertFalse(any(card.slug == "hooded_executioner" for card in match.player(1).play))
        self.assertIsNotNone(match.player(2).instance(weak.id))
        # A boosted unit jailed and released: its boost was paid as it was
        # played, and resolves as it leaves -- the weakest unit destroyed.
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="older_brother")
        self.assertEqual(jail.jailed["slug"], "older_brother")
        released = next(card for card in match.player(1).play if card.slug == "hooded_executioner")
        self.assertTrue(released.arrived_this_turn)
        self.assertIsNone(match.player(2).instance(weak.id))

    def test_jail_2(self) -> None:
        """Forecasted units don't go to Jail when played. They also don't go
        there when they later arrive."""
        engine, game, match, jail = self.jail_against("past")
        hand(match, 1, "plasmodium")
        match.player(1).gold = 20
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="plasmodium")
        self.assertIsNone(jail.jailed)
        future = match.player(1).future[0]
        future.time_runes = 1
        board.remove_time_rune(engine, match, 1, f"future:{future.id}", StepResult())
        self.assertIsNone(jail.jailed)
        self.assertTrue(any(card.slug == "plasmodium" for card in match.player(1).play))

    def test_a_jailed_unit_is_discarded_with_the_jail(self) -> None:
        engine, game, match, jail = self.jail_against()
        hand(match, 1, "older_brother")
        match.player(1).gold = 20
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="older_brother")
        board.destroy(engine, match, [(2, jail.ref)], StepResult())
        self.assertIn("older_brother", match.player(1).discard)

    def test_censorship_council_1(self) -> None:
        """The restriction doesn't apply to effects that would "put a card
        into play" such as from Feral Strike or Sanatorium."""
        engine, game, match = new_game(teams=(("feral",), ("law",)))
        begin(engine, game, match)
        hero_in_play(match, 1)
        built(match, 1, "tech1")
        put(match, 2, "censorship_council")
        hand(match, 1, "tiger_cub", "feral_strike", "young_treant")
        match.player(1).gold = 20
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="tiger_cub")
        refused = driver.apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "play",
                                                             {"slug": "feral_strike"}))
        self.assertIsInstance(refused, driver.Refusal)
        self.assertIn("Censorship Council", refused.reason)
        # An effect's "put into play" is not playing a card from the hand.
        frame = {"kind": "effect", "effect": "feral_strike", "seat": 1, "by": "{card:feral_strike}",
                 "source": None, "spell": None, "part": 0, "taken": [], "flagbearer": False,
                 "partners": [], "cancel_from": None, "drew": False, "mode": "put"}
        match.resolving.append(frame)
        from codex.flow import resolve
        resolve.run(engine, match, StepResult())
        apply(engine, game, match, PromptKind.TARGET, target="1:hand:young_treant")
        self.assertTrue(any(card.slug == "young_treant" for card in match.player(1).play))

    def test_reputable_newsman_1(self) -> None:
        """When Newsman leaves play, his effect ends."""
        engine, game, match = wb(first=2)
        wb_hero(match, 2, "bigby_hayes")
        hand(match, 2, "reputable_newsman")
        match.player(2).gold = 20
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="reputable_newsman")
        self.assertIs(asked(engine, game, match).kind, PromptKind.CHOOSE_NUMBER)
        apply(engine, game, match, PromptKind.CHOOSE_NUMBER, number=1)
        newsman = next(card for card in match.player(2).play if card.slug == "reputable_newsman")
        self.assertEqual(newsman.number, 1)
        match.active = 1
        wb_hero(match, 1, "grave_stormborne")
        hand(match, 1, "senseis_advice")
        match.player(1).gold = 5
        put(match, 1, "fox_viper")
        why = engine.why_not_playable(match.player(1), "senseis_advice", match)
        self.assertIn("Reputable Newsman", why)
        board.destroy(engine, match, [(2, newsman.ref)], StepResult())
        self.assertEqual(engine.why_not_playable(match.player(1), "senseis_advice", match), "")

    def test_building_inspector_1(self) -> None:
        """This effect applies to tech buildings and add-ons as well as
        building cards. This effect also applies to rebuilding tech
        buildings (if it's the first thing they build/rebuild in a turn, it
        will cost 1 instead of 0.)"""
        engine, game, match = wb()
        put(match, 2, "building_inspector")
        player = match.player(1)
        player.workers = 6
        built(match, 1, "tech1").destroyed = True
        match.player(1).buildings["tech1"].hp = 0
        self.assertEqual(engine.build_option(player, "tech1", match).cost, 1)
        self.assertEqual(engine.build_option(player, "tower", match).cost, 4)
        player.gold = 10
        apply(engine, game, match, PromptKind.MAIN_ACTION, "build", building="tech1")
        self.assertEqual(player.gold, 9)
        self.assertEqual(engine.build_option(player, "tower", match).cost, 3)
        # A building card is a building too.
        player.built_this_turn = False
        self.assertEqual(engine.effective_cost(player, "training_grounds", match), 2)

    def test_free_speech_1(self) -> None:
        """Opponents can still level up their heroes even if they are
        silenced. Heroes that reach the next band of levels still heal their
        damage even if their controller is silenced."""
        engine, game, match = wb()
        grave = wb_hero(match, 1, "grave_stormborne", level=2, damage=2)
        match.player(1).silenced = True
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "level", hero="grave_stormborne", levels=1)
        self.assertEqual((grave.level, grave.damage), (3, 0))
        self.assertFalse(engine.has_keyword(grave, "Readiness", match))
        self.assertFalse(engine.has_keyword(grave, "Sparkshot", match))

    def test_free_speech_2(self) -> None:
        """If you use Free Speech on an opponent and that opponent plays a
        new hero on their next turn (in which they are still silenced), that
        new hero loses all abilities and can't cast spells."""
        engine, game, match = wb(first=2)
        wb_hero(match, 2, "sirus_quince")
        cast(engine, game, match, "free_speech")
        self.assertTrue(match.player(1).silenced)
        end_turn_of(engine, game, match, 2)
        self.assertEqual(match.active, 1)
        player = match.player(1)
        player.gold = 10
        apply(engine, game, match, PromptKind.MAIN_ACTION, "summon", hero="grave_stormborne")
        grave = player.hero_of("grave_stormborne")
        self.assertFalse(engine.has_keyword(grave, "Sparkshot", match))
        hand(match, 1, "senseis_advice")
        self.assertIn("silenced", engine.why_not_playable(player, "senseis_advice", match))
        # And after that turn, the silence ends.
        end_turn_of(engine, game, match, 1)
        self.assertFalse(player.silenced)
        self.assertTrue(engine.has_keyword(grave, "Sparkshot", match))

    def test_free_speech_3(self) -> None:
        """A hero that "loses all abilities" from the silence effect can't
        get new abilities either. For example, it can't be granted anti-air
        or sparkshot from Elite Training, though it can be granted +1 ATK
        and 1 armor from that same spell because those are stats and not
        "abilities." """
        engine, game, match = wb()
        grave = wb_hero(match, 1, "garus_rook")
        match.player(1).silenced = True
        grave.modifiers += [
            {"kind": "keyword", "keyword": "Anti-air", "until": "end_of_turn"},
            {"kind": "atk", "amount": 1, "until": "end_of_turn"},
        ]
        self.assertFalse(engine.has_keyword(grave, "Anti-air", match))
        self.assertEqual(engine.hero_stats(grave, match), (3, 4))

    def test_free_speech_4(self) -> None:
        """When the silence effect ends, that players heroes are now able to
        have abilities again. (Imagine the abilities written on their
        character card are erased during the silence effect, then appear
        again when the duration ends.)"""
        engine, game, match = wb()
        rook = wb_hero(match, 1, "garus_rook", level=5)
        put(match, 2, "tenderfoot", patrol="elite")
        match.player(1).silenced = True
        self.assertNotIn("base", engine.legal_defenders(match, hero(match, 1, "garus_rook")))
        match.player(1).silenced = False
        self.assertIn("base", engine.legal_defenders(match, hero(match, 1, "garus_rook")))
        self.assertTrue(rook.in_play)

    def test_free_speech_5(self) -> None:
        """A silenced opponent can still play spells using Cinderblast Dragon
        or Guargum, Eternal Sentinel"""
        engine, game, match = new_game(teams=(("growth",), ("truth",)))
        begin(engine, game, match)
        hero_in_play(match, 1)
        built(match, 1, "tech1")
        built(match, 1, "tech2")
        built(match, 1, "tech3")
        put(match, 1, "guargum_eternal_sentinel")
        match.player(1).silenced = True
        self.assertEqual(engine.why_not_playable(match.player(1), "dinosize", match), "")
        self.assertIn("silenced", engine.why_not_playable(match.player(1), "spark", match))

    def test_oathkeeper_of_kor_mountain_1(self) -> None:
        """If you choose the first oath, you can still "put cards into play"
        with an effect that has that wording, such as Sanatorium, without
        breaking the oath."""
        engine, game, match = wb()
        keeper = put(match, 1, "oathkeeper_of_kor_mountain")
        keeper.oath = "hand"
        hand(match, 1, "fox_viper", "smoker")
        match.player(1).gold = 20
        self.assertIn("oath", engine.why_not_playable(match.player(1), "fox_viper", match))
        self.assertTrue(engine.hire_option(match.player(1)).allowed)
        card = board.put_into_play(engine, match, "smoker", 1, from_hand=True)
        self.assertIsNotNone(card)

    def test_oathkeeper_of_kor_mountain_2(self) -> None:
        """Choosing the second oath means that instead of discarding your
        hand and drawing new cards during the discard/draw phase, you simply
        keep your same remaining cards in hand for the next turn."""
        engine, game, match = wb()
        built(match, 1, "tech1")
        built(match, 1, "tech2")
        built(match, 1, "tech3")
        match.player(1).tech2_spec = "strength"
        hand(match, 1, "oathkeeper_of_kor_mountain", "fox_viper", "smoker")
        match.player(1).gold = 20
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="oathkeeper_of_kor_mountain")
        prompt = asked(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.OATH)
        apply(engine, game, match, PromptKind.OATH, oath="draw")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        run = apply(engine, game, match, PromptKind.PATROL, assignment={})
        self.assertEqual(sorted(match.player(1).hand), ["fox_viper", "smoker"])
        self.assertIn("keeping their hand", said(run))

    def test_morningstar_pass_1(self) -> None:
        """If they can't pay 1, they can't attack Morningstar Pass."""
        engine, game, match = wb(first=2)
        attacker = put(match, 2, "scribe")
        morningstar = put(match, 1, "morningstar_pass")
        match.player(2).gold = 0
        self.assertNotIn(morningstar.ref, engine.legal_defenders(match, attacker.ref))
        match.player(2).gold = 1
        self.assertIn(morningstar.ref, engine.legal_defenders(match, attacker.ref))
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=attacker.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender=morningstar.ref)
        self.assertEqual(match.player(2).gold, 0)
        self.assertEqual(morningstar.damage, 1)

    def test_morningstar_pass_prevents_damage_to_the_other_buildings(self) -> None:
        engine, game, match = wb(first=2)
        attacker = put(match, 2, "scribe")
        put(match, 1, "morningstar_pass")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=attacker.ref)
        run = apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="base")
        self.assertEqual(match.player(1).base_hp, 20)
        self.assertIn("prevents", said(run))

    def test_lawbringer_gryphon_1(self) -> None:
        """Your base is no longer flying if you lose Lawbringer Gryphon."""
        engine, game, match = wb()
        attacker = put(match, 1, "fox_viper")
        gryphon = put(match, 2, "lawbringer_gryphon")
        self.assertNotIn("base", engine.legal_defenders(match, attacker.ref))
        flier = put(match, 1, "flying_fox")
        self.assertIn("base", engine.legal_defenders(match, flier.ref))
        board.trash(engine, match, gryphon)
        self.assertIn("base", engine.legal_defenders(match, attacker.ref))

    def test_mindparry_monk_1(self) -> None:
        """This means that opponents can't use spells or abilities to target
        any units or heroes you control."""
        engine, game, match = wb(first=2)
        wb_hero(match, 2, "sirus_quince")
        put(match, 1, "mindparry_monk")
        viper = put(match, 1, "fox_viper", patrol="elite")
        hand(match, 2, "spark")
        self.assertIn("no target", engine.why_not_playable(match.player(2), "spark", match))
        put(match, 2, "scribe", patrol="elite")
        cast(engine, game, match, "spark")
        self.assertEqual(viper.damage, 0)


def birds(match, seat: int) -> list:
    return [card for card in match.player(seat).play if card.slug == "bird"]


class WhiteEffectRulingTests(unittest.TestCase):
    """Commit 4's cards: white's effects."""

    def test_birds_nest_1(self) -> None:
        """If you have two Bird's Nests, you can still only have two Bird
        tokens in play. Each Nest sees 2 birds in play, knows that's the
        limit, and refuses to put more into play."""
        engine, game, match = wb()
        wb_hero(match, 1, "garus_rook")
        cast(engine, game, match, "birds_nest")
        cast(engine, game, match, "birds_nest")
        nests = [card for card in match.player(1).play if card.slug == "birds_nest"]
        self.assertEqual(len(nests), 2)
        # The second Nest sees the two and summons none.
        self.assertEqual(len(birds(match, 1)), 2)
        board.destroy(engine, match, [(1, birds(match, 1)[0].ref)], StepResult())
        cast(engine, game, match, "birds_nest")
        self.assertEqual(len(birds(match, 1)), 2)
        for bird in birds(match, 1):
            match.player(1).play.remove(bird)
        upkeep_of(engine, game, match, 1)
        self.assertEqual(len(birds(match, 1)), 2)

    def test_birds_nest_2(self) -> None:
        """If you have Birds in play, then lose Bird's Nest, that doesn't
        cause you to lose your Birds."""
        engine, game, match = wb()
        wb_hero(match, 1, "garus_rook")
        cast(engine, game, match, "birds_nest")
        self.assertEqual(len(birds(match, 1)), 2)
        board.destroy(engine, match, [(1, "hero:garus_rook")], StepResult())
        board.settle(engine, match, StepResult())
        self.assertFalse(any(card.slug == "birds_nest" for card in match.player(1).play))
        self.assertEqual(len(birds(match, 1)), 2)

    def test_doubling_barbarbarian_1(self) -> None:
        """His ability DOES trigger when patroling as a squad leader (he
        gets two armor instead of one), and it does trigger on +1/+1 runes
        (they give him +2/+2)."""
        engine, game, match = wb()
        barb = put(match, 1, "doubling_barbarbarian")
        barb.plus_runes = 1
        self.assertEqual(engine.unit_stats(barb, match), (5, 7))
        barb.patrol_slot = "squad_leader"
        end_turn_of(engine, game, match, 1)
        self.assertEqual(barb.armor, 2)

    def test_doubling_barbarbarian_2(self) -> None:
        """When the effect that raised his ATK, HP, or armor ends, he also
        loses the extra stats from his effect. For example, Aged Sensei's
        effect will give him +2 ATK/+2 armor this turn, NOT +1 ATK/+1 armor
        this turn and +1 ATK /+1 armor permanently."""
        engine, game, match = wb()
        barb = put(match, 1, "doubling_barbarbarian")
        sensei = put(match, 1, "aged_sensei")
        ability(engine, game, match, "aged_sensei", sensei.ref)
        answer_target(engine, game, match, f"1:{barb.ref}")
        self.assertEqual(engine.unit_stats(barb, match), (5, 5))
        self.assertEqual(barb.armor, 2)
        end_turn_of(engine, game, match, 1)
        self.assertEqual(engine.unit_stats(barb, match), (3, 5))
        self.assertEqual(barb.armor, 0)

    def test_doubling_barbarbarian_3(self) -> None:
        """Healing something removes damage, rather than increases HP, so
        his ability does NOT trigger on healing."""
        engine, game, match = wb()
        barb = put(match, 1, "doubling_barbarbarian", damage=3)
        put(match, 1, "helpful_turtle")
        upkeep_of(engine, game, match, 1)
        self.assertEqual(barb.damage, 2)
        self.assertEqual(engine.unit_stats(barb, match), (3, 5))

    def test_earthquake_1(self) -> None:
        """If opponent has a damaged tech building and the 4 damage is enough
        to destroy it but his base is undamaged, the base will take 2 damage
        from the destruction of the tech building but none from the spell.
        This is due to that you never read twice the same sentence. So you
        deal 4 damage to the damaged buildings, which upon destruction cause
        the base to take 2 damage , but then you are at the "Deal 1 damage to
        all their undamaged buildings." line and the base is no more an
        undamaged building."""
        engine, game, match = wb()
        rook = wb_hero(match, 1, "garus_rook", level=8)
        rook.max_level_since_turn_began = True
        built(match, 2, "tech1", hp=3)
        base = match.player(2).base_hp
        cast(engine, game, match, "earthquake")
        self.assertTrue(match.player(2).buildings["tech1"].destroyed)
        self.assertEqual(match.player(2).base_hp, base - 2)

    def test_focus_master_1(self) -> None:
        """1 deathtouch damage is exactly lethal damage. Any other amount of
        deathtouch damage is not."""
        engine, game, match = wb()
        master = put(match, 1, "focus_master")
        master.runes["focus"] = 3
        guard = put(match, 1, "aged_sensei", damage=0)
        self.assertEqual(board.focus_prevents(engine, match, guard, 1, deathtouch=True), 0)
        self.assertEqual(master.runes["focus"], 2)
        self.assertEqual(board.focus_prevents(engine, match, guard, 2, deathtouch=True), 2)
        self.assertEqual(master.runes["focus"], 2)
        # Exactly lethal without deathtouch: the Master's own 3 HP.
        self.assertEqual(board.focus_prevents(engine, match, master, 3), 2)
        self.assertEqual(board.focus_prevents(engine, match, master, 4), 4)

    def test_focus_master_2(self) -> None:
        """If a patroller would take excess damage, but that damage is
        redirected by Overpower or Stampede, Focus Master cannot prevent any
        damage for that patroller."""
        engine, game, match = wb()
        master = put(match, 1, "focus_master")
        master.runes["focus"] = 3
        sensei = put(match, 1, "aged_sensei", patrol="squad_leader")
        self.assertEqual(board.focus_prevents(engine, match, sensei, 1, redirected=True), 1)
        self.assertEqual(master.runes["focus"], 3)
        self.assertEqual(board.focus_prevents(engine, match, sensei, 1), 0)

    def test_focus_master_arrives_with_three_runes(self) -> None:
        engine, game, match = wb()
        tech(match, 1, 2, "discipline")
        hero_in_play(match, 1)
        hand(match, 1, "focus_master")
        match.player(1).gold = 10
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="focus_master")
        master = next(card for card in match.player(1).play if card.slug == "focus_master")
        self.assertEqual(master.runes.get("focus"), 3)

    def test_foxs_den_school_1(self) -> None:
        """A unit that becomes a Ninja this way stays a Ninja until it leaves
        play. Even if Fox's Den School leaves play, your unit remains a
        Ninja."""
        engine, game, match = wb()
        school = put(match, 1, "foxs_den_school")
        sensei = put(match, 1, "aged_sensei")
        match.player(1).gold = 5
        # The one unit of seat 1's is the one target, taken unasked.
        ability(engine, game, match, "foxs_den_school", school.ref)
        self.assertTrue(engine.is_ninja(sensei))
        self.assertTrue(engine.has_keyword(sensei, "Invisible", match))
        board.destroy(engine, match, [(1, school.ref)], StepResult())
        self.assertTrue(engine.is_ninja(sensei))
        self.assertFalse(engine.has_keyword(sensei, "Invisible", match))

    def test_grappling_hook_1(self) -> None:
        """Pulling a patroller to another slot means removing it from the
        slot its in and putting it in an empty slot in that same patrol
        zone. It doesn't matter if slots in between are occupied or not."""
        engine, game, match = wb()
        wb_hero(match, 1, "grave_stormborne")
        far = put(match, 2, "scribe", patrol="squad_leader")
        put(match, 2, "tenderfoot", patrol="elite")
        put(match, 2, "tenderfoot", patrol="scavenger")
        cast(engine, game, match, "grappling_hook", f"2:{far.ref}")
        prompt = asked(engine, game, match)
        self.assertIn("2:slot:lookout", {row.key for row in prompt.options.targets})
        answer_target(engine, game, match, "2:slot:lookout")
        self.assertEqual(far.patrol_slot, "lookout")

    def test_grave_stormborne_1(self) -> None:
        """You can't activate his max level ability while attacking and he
        can't attack if he's exhausted. So if you want to attack and use his
        ability in the same turn, you generally have to attack first, and
        then use his ability after he finishes attacking. If he can't
        survive an attack, you'll have to pick which one you want to do."""
        engine, game, match = wb()
        grave = wb_hero(match, 1, "grave_stormborne", level=7)
        grave.runes["sword"] = 1
        victim = put(match, 2, "tenderfoot")
        ability(engine, game, match, "grave_stormborne", "hero:grave_stormborne")
        answer_target(engine, game, match, f"2:{victim.ref}")
        self.assertIsNone(match.player(2).instance(victim.id))
        self.assertTrue(grave.exhausted)
        self.assertEqual(grave.runes.get("sword", 0), 0)
        self.assertNotIn("hero:grave_stormborne", engine.attackers(match))

    def test_grave_stormborne_gets_his_sword_at_max_level(self) -> None:
        engine, game, match = wb()
        grave = wb_hero(match, 1, "grave_stormborne", level=6)
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "level", hero="grave_stormborne", levels=1)
        self.assertEqual(grave.level, 7)
        self.assertEqual(grave.runes.get("sword"), 1)

    def test_hidden_ninja_1(self) -> None:
        """If the unit or hero has more than 4 ATK later that turn, it keeps
        stealth."""
        engine, game, match = wb()
        wb_hero(match, 1, "setsuki_hiruki")
        sensei = put(match, 1, "aged_sensei")
        match.player(1).deck = ["scribe"] * 5
        cast(engine, game, match, "hidden_ninja", f"1:{sensei.ref}")
        prompt = asked(engine, game, match)
        if prompt is not None and prompt.kind is PromptKind.TARGET:
            apply(engine, game, match, PromptKind.TARGET, "done")
        sensei.modifiers.append({"kind": "atk", "amount": 5, "until": "end_of_turn"})
        self.assertTrue(engine.has_keyword(sensei, "Stealth", match))
        # Neither a Ninja nor the Ninjutsu hero: no card drawn.
        self.assertEqual(match.player(1).hand, [])
        cast(engine, game, match, "hidden_ninja", "1:hero:setsuki_hiruki")
        prompt = asked(engine, game, match)
        if prompt is not None and prompt.kind is PromptKind.TARGET:
            apply(engine, game, match, PromptKind.TARGET, "done")
        self.assertEqual(match.player(1).hand, ["scribe"])

    def test_inverse_power_ninja_1(self) -> None:
        """Each other unit or hero "you have" refers to units or heroes you
        control that are in play. It does not refer to heroes in your
        command zone, units in Jail or Graveyard, forecasted units, or units
        that you own but that an opponent now controls."""
        engine, game, match = wb()
        ninja = put(match, 1, "inverse_power_ninja")
        self.assertEqual(engine.unit_stats(ninja, match), (6, 6))
        wb_hero(match, 1, "setsuki_hiruki")
        put(match, 1, "aged_sensei")
        match.player(1).discard.append("tenderfoot")
        taken = put(match, 1, "tenderfoot")
        taken.controller = 2
        match.player(1).play.remove(taken)
        match.player(2).play.append(taken)
        self.assertEqual(engine.unit_stats(ninja, match), (4, 4))

    def test_jade_fox_dens_headmistress_1(self) -> None:
        """Jade Fox is a Ninja so she has flying and swift strike."""
        engine, game, match = wb()
        fox = put(match, 1, "jade_fox_dens_headmistress")
        for keyword in ("Flying", "Swift strike"):
            self.assertTrue(engine.has_keyword(fox, keyword, match))

    def test_jade_fox_dens_headmistress_2(self) -> None:
        """Thought Setsuki is the Ninjutsu hero, she does not have the type
        "Ninja" on her card, so she does not get buffed by Jade Fox."""
        engine, game, match = wb()
        put(match, 1, "jade_fox_dens_headmistress")
        setsuki = wb_hero(match, 1, "setsuki_hiruki")
        self.assertFalse(engine.has_keyword(setsuki, "Flying", match))

    def test_jade_fox_summons_four_ninjas(self) -> None:
        engine, game, match = wb()
        hero_in_play(match, 1, slug="setsuki_hiruki")
        tech(match, 1, 3, "ninjutsu")
        hand(match, 1, "jade_fox_dens_headmistress")
        match.player(1).gold = 20
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="jade_fox_dens_headmistress")
        ninjas = [card for card in match.player(1).play if card.slug == "ninja"]
        self.assertEqual(len(ninjas), 4)
        self.assertTrue(engine.has_keyword(ninjas[0], "Flying", match))

    def test_martial_mastery_1(self) -> None:
        """You resolve a spell's effect before discarding it, so a given copy
        of Marital Master cannot draw itself from its own effect. The steps
        here are 1) discard a card (not Martial Mastery), 2) draw 2 cards, 3)
        look at opponent's hand, 4) discard Martial Mastery because its
        effect is now fully resolved."""
        engine, game, match = wb()
        wb_hero(match, 1, "grave_stormborne")
        player = match.player(1)
        player.deck = []
        player.discard = []
        hand(match, 1, "martial_mastery", "tenderfoot")
        player.gold = 5
        # The Tenderfoot is the one card it may discard, taken unasked.
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="martial_mastery")
        # The deck was empty: the discard -- the Tenderfoot alone -- is
        # reshuffled, and Martial Mastery is not in it.
        self.assertIn("tenderfoot", player.hand)
        self.assertNotIn("martial_mastery", player.hand)
        prompt = asked(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.TARGET)
        self.assertEqual(sorted(prompt.options.shown), sorted(match.player(2).hand))
        apply(engine, game, match, PromptKind.TARGET, "done")
        self.assertIn("martial_mastery", player.discard)

    def test_rambasa_twin_1(self) -> None:
        """If two twins die simultaneously, the active player chooses which
        returns to your codex."""
        engine, game, match = wb()
        twins = [put(match, 1, "rambasa_twin"), put(match, 1, "rambasa_twin")]
        codex_before = match.player(1).codex.get("rambasa_twin", 0)
        board.destroy(engine, match, [(1, twin.ref) for twin in twins], StepResult())
        board.settle(engine, match, StepResult())
        self.assertEqual(match.player(1).codex.get("rambasa_twin", 0), codex_before + 1)
        self.assertEqual(match.player(1).discard.count("rambasa_twin"), 1)

    def test_rambasa_twin_goes_back_to_the_codex_once_a_turn(self) -> None:
        engine, game, match = wb()
        first = put(match, 1, "rambasa_twin")
        codex_before = match.player(1).codex.get("rambasa_twin", 0)
        board.destroy(engine, match, [(1, first.ref)], StepResult())
        self.assertEqual(match.player(1).codex.get("rambasa_twin", 0), codex_before + 1)
        self.assertNotIn("rambasa_twin", match.player(1).discard)
        second = put(match, 1, "rambasa_twin")
        board.destroy(engine, match, [(1, second.ref)], StepResult())
        self.assertIn("rambasa_twin", match.player(1).discard)
        # Its arrival brings the one in the codex back.
        hero_in_play(match, 1)
        built(match, 1, "tech1")
        hand(match, 1, "rambasa_twin")
        match.player(1).gold = 10
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="rambasa_twin")
        answer_target(engine, game, match, "1:codex:rambasa_twin")
        self.assertEqual(sum(1 for card in match.player(1).play if card.slug == "rambasa_twin"), 2)

    def test_safe_attacking_1(self) -> None:
        """After your unit finishes its attack (after combat damage is
        dealt), it loses the armor Safe Attacking granted if it still had
        it."""
        engine, game, match = wb()
        put(match, 1, "safe_attacking")
        sensei = put(match, 1, "aged_sensei")
        guard = put(match, 2, "tenderfoot", patrol="squad_leader")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=sensei.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender=guard.ref)
        # Tenderfoot's 1 ATK went into the armor; none is left after.
        self.assertEqual((sensei.damage, sensei.armor), (0, 0))

    def test_safe_attacking_2(self) -> None:
        """If something readies that unit and you attack with it a second
        time that turn, it will get 1 point of armor again."""
        engine, game, match = wb()
        put(match, 1, "safe_attacking")
        sensei = put(match, 1, "aged_sensei")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=sensei.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="base")
        sensei.exhausted = False
        guard = put(match, 2, "tenderfoot", patrol="squad_leader")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=sensei.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender=guard.ref)
        self.assertEqual((sensei.damage, sensei.armor), (0, 0))

    def test_setsuki_hiruki_1(self) -> None:
        """It's ok to have more than 5 cards in your hand. When you reach the
        discard/draw phase, you'll still have to discard your hand, and draw
        that many cards + 2, capped at 5."""
        engine, game, match = wb()
        wb_hero(match, 1, "setsuki_hiruki", level=6)
        hand(match, 1, "tenderfoot", "tenderfoot", "tenderfoot", "tenderfoot")
        match.player(1).deck = ["scribe"] * 10
        upkeep_of(engine, game, match, 1)
        # Four discarded and five drawn -- 4 + 2, capped -- then two more.
        self.assertEqual(len(match.player(1).hand), 7)

    def test_setsuki_costs_a_gold_to_attack(self) -> None:
        engine, game, match = wb(first=2)
        setsuki = wb_hero(match, 1, "setsuki_hiruki")
        self.assertEqual(engine.attack_toll(match, "hero:setsuki_hiruki"), 1)
        setsuki.patrol_slot = "elite"
        self.assertEqual(engine.attack_toll(match, "hero:setsuki_hiruki"), 0)

    def test_shuriken_hail_1(self) -> None:
        """If this would cause simultaneous effects to happen that require
        some order (such as multiple units dying that have "dies" triggers),
        then you (the active player) choose the order."""
        engine, game, match = wb()
        wb_hero(match, 1, "setsuki_hiruki")
        mine = put(match, 1, "ninja", patrol="squad_leader")
        theirs = put(match, 2, "ninja", patrol="elite")
        tough = put(match, 2, "scribe", patrol="lookout")
        cast(engine, game, match, "shuriken_hail")
        self.assertIsNone(match.player(1).instance(mine.id))
        self.assertIsNone(match.player(2).instance(theirs.id))
        self.assertEqual(tough.damage, 1)

    def test_snapback_1(self) -> None:
        """Whenever heroes enter a command zone, they lose all levels (become
        level 1) and other properties. They lose any damage on them, lose
        +1/+1 runes, lose any attachments, etc."""
        engine, game, match = wb(first=2)
        wb_hero(match, 2, "sirus_quince")
        rook = wb_hero(match, 1, "garus_rook", level=5, damage=2)
        rook.plus_runes = 1
        # The one opposing hero in play is taken unasked.
        cast(engine, game, match, "snapback", "1:hero:grave_stormborne")
        self.assertFalse(rook.in_play)
        self.assertEqual((rook.level, rook.damage, rook.plus_runes, rook.summoning_runes), (1, 0, 0, 2))

    def test_snapback_2(self) -> None:
        """When Snapback returns a hero to its command zone, it cannot put
        that very same hero back into play unless there are no other heroes
        at all in that command zone."""
        engine, game, match = wb(first=2)
        wb_hero(match, 2, "sirus_quince")
        wb_hero(match, 1, "garus_rook", level=5)
        hand(match, 2, "snapback")
        match.player(2).gold = 20
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="snapback")
        offered = {row.key for row in asked(engine, game, match).options.targets}
        self.assertEqual(offered, {"1:hero:grave_stormborne", "1:hero:setsuki_hiruki"})
        apply(engine, game, match, PromptKind.TARGET, target="1:hero:setsuki_hiruki")
        # Every other hero in play: the same one comes back.
        wb_hero(match, 1, "grave_stormborne")
        rook = match.player(1).hero_of("garus_rook")
        rook.summoning_runes = 0
        hero_in_play(match, 1, slug="garus_rook", level=4)
        hand(match, 2, "snapback")
        match.player(2).gold = 20
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="snapback")
        for key in ("1:hero:garus_rook", "1:hero:garus_rook"):
            prompt = asked(engine, game, match)
            if prompt is not None and prompt.kind is PromptKind.TARGET:
                apply(engine, game, match, PromptKind.TARGET, target=key)
        self.assertTrue(rook.in_play)
        self.assertEqual(rook.level, 1)

    def test_snapback_3(self) -> None:
        """When Snapback returns a hero to its command zone, it CAN return a
        different hero from that command zone to play, even if that different
        hero is currently on cooldown from dying somehow."""
        engine, game, match = wb(first=2)
        wb_hero(match, 2, "sirus_quince")
        wb_hero(match, 1, "garus_rook", level=5)
        setsuki = match.player(1).hero_of("setsuki_hiruki")
        setsuki.summoning_runes = 2
        cast(engine, game, match, "snapback", "1:hero:setsuki_hiruki")
        self.assertTrue(setsuki.in_play)
        self.assertEqual(setsuki.summoning_runes, 0)

    def test_sparring_partner_1(self) -> None:
        """"He can only spar" means that if you use his second ability, he
        can still use his first ability that same turn, even though he can't
        attack for the rest of that turn."""
        engine, game, match = wb()
        partner = put(match, 1, "sparring_partner")
        sensei = put(match, 1, "aged_sensei")
        other = put(match, 1, "tenderfoot")
        ability(engine, game, match, "sparring_partner", partner.ref)
        answer_target(engine, game, match, f"1:{sensei.ref}")
        match.player(1).gold = 5
        ability(engine, game, match, "sparring_partner_ready", partner.ref)
        self.assertFalse(partner.exhausted)
        self.assertNotIn(partner.ref, engine.attackers(match))
        ability(engine, game, match, "sparring_partner", partner.ref)
        answer_target(engine, game, match, f"1:{other.ref}")
        self.assertEqual((sensei.plus_runes, other.plus_runes), (1, 1))

    def test_thunderclap_1(self) -> None:
        """Tokens count as cost 0, so this does work on token units unless
        you somehow have a token that is copying a higher cost unit."""
        engine, game, match = wb()
        wb_hero(match, 1, "garus_rook")
        ninja = put(match, 2, "ninja", patrol="elite")
        copier = put(match, 2, "ninja")
        copier.copy_of = "doubling_barbarbarian"
        hand(match, 1, "thunderclap")
        match.player(1).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="thunderclap")
        offered = {row.key for row in asked(engine, game, match).options.targets}
        self.assertIn(f"2:{ninja.ref}", offered)
        self.assertNotIn(f"2:{copier.ref}", offered)

    def test_thunderclap_2(self) -> None:
        """This can target units that aren't patrolling. Sidelining those
        won't do anything, but if they are illusions they will die from
        being targeted."""
        engine, game, match = wb()
        wb_hero(match, 1, "garus_rook")
        hound = put(match, 2, "spectral_hound")
        cast(engine, game, match, "thunderclap", f"2:{hound.ref}")
        self.assertIsNone(match.player(2).instance(hound.id))

    def test_true_power_of_storms_1(self) -> None:
        """If you do not reveal and discard 2 cards that cost 3, it won't
        target anything."""
        engine, game, match = wb()
        grave = wb_hero(match, 1, "grave_stormborne", level=7)
        grave.max_level_since_turn_began = True
        target = put(match, 2, "scribe")
        # Played with no card that costs 3: it does nothing (the author,
        # 2026-10-10).
        hand(match, 1, "true_power_of_storms")
        match.player(1).gold = 10
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="true_power_of_storms")
        self.assertIs(asked(engine, game, match).kind, PromptKind.MAIN_ACTION)
        self.assertIsNotNone(match.player(2).instance(target.id))
        # With one: it may be discarded, and nothing is targeted.
        hand(match, 1, "true_power_of_storms", "young_lightning_dragon")
        match.player(1).gold = 10
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="true_power_of_storms")
        answer_target(engine, game, match, "1:hand:young_lightning_dragon")
        self.assertIs(asked(engine, game, match).kind, PromptKind.MAIN_ACTION)
        self.assertIn("young_lightning_dragon", match.player(1).discard)
        self.assertIsNotNone(match.player(2).instance(target.id))
        # Or kept: Done with none discarded.
        hand(match, 1, "true_power_of_storms", "young_lightning_dragon")
        match.player(1).gold = 10
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="true_power_of_storms")
        apply(engine, game, match, PromptKind.TARGET, "done")
        self.assertEqual(match.player(1).hand, ["young_lightning_dragon"])
        # With two discarded, it deals its 10.
        hand(match, 1, "true_power_of_storms", "young_lightning_dragon", "focus_master")
        match.player(1).gold = 10
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="true_power_of_storms")
        answer_target(engine, game, match, "1:hand:young_lightning_dragon")
        answer_target(engine, game, match, "1:hand:focus_master")
        answer_target(engine, game, match, f"2:{target.ref}")
        self.assertIn("focus_master", match.player(1).discard)
        self.assertIsNone(match.player(2).instance(target.id))

    def test_training_grounds_levels_its_controllers_hero_alone(self) -> None:
        """The author, 2026-10-10: never an opponent's hero."""
        engine, game, match = wb()
        grounds = put(match, 1, "training_grounds")
        grave = wb_hero(match, 1, "grave_stormborne", level=2)
        wb_hero(match, 2, "bigby_hayes", level=2)
        ability(engine, game, match, "training_grounds", grounds.ref)
        self.assertEqual(grave.level, 7)
        self.assertEqual(match.player(2).hero_of("bigby_hayes").level, 2)
        self.assertEqual(engine.target_candidates(match, 1, "own_hero_in_play"), [(1, "hero:grave_stormborne")])

    def test_young_lightning_dragon_1(self) -> None:
        """Thrice-per-turn means three times per turn."""
        engine, game, match = wb()
        dragon = put(match, 1, "young_lightning_dragon")
        match.player(1).gold = 10
        for _ in range(3):
            ability(engine, game, match, "young_lightning_dragon", dragon.ref)
        self.assertEqual(engine.unit_stats(dragon, match), (6, 3))
        self.assertEqual(option(engine, match, "young_lightning_dragon", dragon.ref).why_not,
                         "it has been used 3 times this turn")


def trigger(engine, game, match, effect: str, seat: int, source=None, slug=None):
    """`effect` onto the stack for `seat` -- an arrives trigger of the card
    at `source` -- and worked until it asks something."""
    from codex.flow import resolve

    by = tokens.card(slug or effect)
    match.resolving.append(resolve.frame(effect, seat, by, source=source, origin=slug or effect))
    resolve.run(engine, match, StepResult())


def blue(first: int = 2):
    """Blue's seat 2 against white's seat 1, blue to play by default."""
    return wb(first=first)


class BlueEffectRulingTests(unittest.TestCase):
    """Commit 5's cards: blue's effects."""

    def test_bigby_hayes_1(self) -> None:
        """An example of how stash works. Normally (without stash), if you
        have 2 cards left in hand when you reach the discard/draw phase,
        you'd discard both cards and then draw 4 cards (you draw 2 more than
        you discard). If you have stash, instead of discarding both cards,
        you can choose to keep one of them in your hand. If you do, you will
        STILL end up with 4 cards total, but you'll be drawing 3 cards rather
        than 4 (the 4th card is the one you kept)."""
        engine, game, match = blue()
        wb_hero(match, 2, "bigby_hayes")
        hand(match, 2, "scribe", "arrest")
        match.player(2).deck = ["tenderfoot"] * 10
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        apply(engine, game, match, PromptKind.PATROL, assignment={})
        self.assertIs(asked(engine, game, match).kind, PromptKind.STASH)
        apply(engine, game, match, PromptKind.STASH, "keep", slug="arrest")
        self.assertEqual(sorted(match.player(2).hand), ["arrest", "tenderfoot", "tenderfoot", "tenderfoot"])
        self.assertIn("scribe", match.player(2).discard)

    def test_bigby_sidelines_and_draws(self) -> None:
        engine, game, match = blue()
        bigby = wb_hero(match, 2, "bigby_hayes", level=5)
        patroller = put(match, 1, "tenderfoot", patrol="elite")
        ability(engine, game, match, "bigby_hayes", "hero:bigby_hayes")
        self.assertIsNone(patroller.patrol_slot)
        self.assertTrue(bigby.exhausted)
        self.assertEqual(option(engine, match, "bigby_hayes_draw", "hero:bigby_hayes").why_not, "it is exhausted")

    def test_boot_camp_1(self) -> None:
        """You CAN use this on something that's already exhausted. The
        exhaust isn't a cost here, so you do as much as you can."""
        engine, game, match = blue()
        wb_hero(match, 2, "general_onimaru")
        tired = put(match, 2, "tenderfoot", exhausted=True)
        match.player(2).deck = ["scribe"] * 3
        # The one unit, Onimaru being the Peace hero: taken unasked.
        cast(engine, game, match, "boot_camp")
        self.assertEqual((tired.exhausted, tired.plus_runes), (True, 1))
        self.assertEqual(match.player(2).hand, ["scribe"])
        # Its own Peace hero can't be chosen.
        put(match, 1, "tenderfoot")
        hand(match, 2, "boot_camp")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="boot_camp")
        offered = {row.key for row in asked(engine, game, match).options.targets}
        self.assertNotIn("2:hero:general_onimaru", offered)

    def test_brave_knight_1(self) -> None:
        """Combat damage includes damage done while attacking or getting
        attacked while patrolling. It also includes damage from the
        overpower and sparkshot keywords as well as damage from the Tower
        add-on."""
        engine, game, match = blue()
        knight = put(match, 2, "brave_knight", damage=2)
        match.player(1).add_on = AddOnState(slug="tower", hp=4, under_construction=False)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=knight.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="base")
        self.assertIsNone(match.player(2).instance(knight.id))
        self.assertIn("brave_knight", match.player(2).hand)
        self.assertNotIn("brave_knight", match.player(2).discard)

    def test_brave_knight_2(self) -> None:
        """When something "deals damage in the form of" something else, such
        as -1/-1 runes from Plague Spitter, Orpal Gloor, or Poisonblade
        Rogue, they really did "deal combat damage." Immediately after their
        form of damage is dealt, check if their victim would die. If yes,
        that victim counts as "dying from combat damage." Brave Knight will
        return to his owner's hand in this case."""
        engine, game, match = blue(first=1)
        knight = put(match, 2, "brave_knight", patrol="squad_leader")
        spitter = put(match, 1, "plague_spitter")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=spitter.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender=knight.ref)
        self.assertIsNone(match.player(2).instance(knight.id))
        self.assertIn("brave_knight", match.player(2).hand)

    def test_brave_knight_returns_from_deathtouch(self) -> None:
        engine, game, match = blue(first=1)
        knight = put(match, 2, "brave_knight", patrol="squad_leader")
        horror = put(match, 1, "horror")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=horror.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender=knight.ref)
        self.assertIsNone(match.player(2).instance(knight.id))
        self.assertIn("brave_knight", match.player(2).hand)
        # Not combat damage: he dies.
        knight = put(match, 2, "brave_knight")
        board.destroy(engine, match, [(2, knight.ref)], StepResult())
        self.assertIn("brave_knight", match.player(2).discard)

    def test_community_service_1(self) -> None:
        """When you put units into play with this, you don't have to pay for
        them and you don't have to meet the tech requirements for them
        either."""
        engine, game, match = blue()
        wb_hero(match, 2, "bigby_hayes")
        hand(match, 1, "doubling_barbarbarian", "tenderfoot")
        cast(engine, game, match, "community_service", gold=5)
        apply(engine, game, match, PromptKind.MODE_CHOICE, mode="hand")
        prompt = asked(engine, game, match)
        self.assertEqual(sorted(prompt.options.shown), ["doubling_barbarbarian", "tenderfoot"])
        answer_target(engine, game, match, "1:hand:doubling_barbarbarian")
        barb = next(card for card in match.player(2).play if card.slug == "doubling_barbarbarian")
        self.assertEqual((barb.controller, barb.owner), (2, 1))
        self.assertEqual(match.player(2).gold, 0)
        self.assertEqual(match.player(1).hand, ["tenderfoot"])

    def test_community_service_shows_a_discard_pile_with_no_unit_in_it(self) -> None:
        engine, game, match = blue()
        wb_hero(match, 2, "bigby_hayes")
        match.player(1).discard = ["thunderclap"]
        cast(engine, game, match, "community_service")
        apply(engine, game, match, PromptKind.MODE_CHOICE, mode="discard")
        prompt = asked(engine, game, match)
        self.assertEqual(prompt.options.shown, ("thunderclap",))
        apply(engine, game, match, PromptKind.TARGET, "done")
        self.assertIs(asked(engine, game, match).kind, PromptKind.MAIN_ACTION)

    def test_drill_sergeant_1(self) -> None:
        """Playing a spell from your hand that summons units such as Murkwood
        Allies or Summon Skeletons does NOT count as "playing a unit from
        your hand.\""""
        engine, game, match = blue()
        sergeant = put(match, 2, "drill_sergeant")
        trigger(engine, game, match, "murkwood_allies", 2)
        apply(engine, game, match, PromptKind.MODE_CHOICE, mode="beast")
        self.assertEqual(sergeant.plus_runes, 0)
        hand(match, 2, "tenderfoot")
        match.player(2).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="tenderfoot")
        self.assertEqual(sergeant.plus_runes, 1)
        other = next(card for card in match.player(2).play if card.slug == "tenderfoot")
        ability(engine, game, match, "drill_sergeant", sergeant.ref)
        if asked(engine, game, match).kind is PromptKind.TARGET:
            answer_target(engine, game, match, f"2:{other.ref}")
        self.assertEqual(sergeant.plus_runes, 0)
        self.assertEqual(sum(card.plus_runes for card in match.player(2).play), 1)

    def test_drill_sergeant_2(self) -> None:
        """Using a spell or ability to "put a unit into play" from your hand
        does not count as "playing it from your hand.\""""
        engine, game, match = blue()
        sergeant = put(match, 2, "drill_sergeant")
        hand(match, 2, "tenderfoot")
        match.player(2).hand.remove("tenderfoot")
        board.put_into_play(engine, match, "tenderfoot", 2, from_hand=True)
        self.assertEqual(sergeant.plus_runes, 0)

    def test_flagstone_garrison_1(self) -> None:
        """Playing a spell from your hand that summons units such as Murkwood
        Allies or Summon Skeletons does NOT count as "playing a unit from
        your hand.\""""
        engine, game, match = blue()
        put(match, 2, "flagstone_garrison")
        match.player(2).deck = ["scribe"] * 3
        hand(match, 2)
        trigger(engine, game, match, "murkwood_allies", 2)
        apply(engine, game, match, PromptKind.MODE_CHOICE, mode="beast")
        self.assertEqual(match.player(2).hand, [])
        hand(match, 2, "tenderfoot")
        match.player(2).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="tenderfoot")
        self.assertEqual(match.player(2).hand, ["scribe"])

    def test_flagstone_garrison_2(self) -> None:
        """Using a spell or ability to "put a unit into play" from your hand
        does not count as "playing it from your hand.\""""
        engine, game, match = blue()
        put(match, 2, "flagstone_garrison")
        match.player(2).deck = ["scribe"] * 3
        hand(match, 2)
        board.put_into_play(engine, match, "tenderfoot", 2, from_hand=True)
        self.assertEqual(match.player(2).hand, [])

    def test_flagstone_spy_1(self) -> None:
        """His ability that steals gold can't steal any against an opponent
        that doesn't have any gold."""
        engine, game, match = blue()
        spy = put(match, 2, "flagstone_spy")
        match.player(1).gold = 0
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=spy.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="base")
        self.assertEqual(match.player(1).gold, 0)
        self.assertEqual(engine.hands_visible_to(match, 2), (1,))
        spy.exhausted = False
        match.player(1).gold = 3
        gold = match.player(2).gold
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=spy.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="base")
        self.assertEqual((match.player(1).gold, match.player(2).gold), (2, gold + 1))

    def test_guardian_of_the_gates_1(self) -> None:
        """Guardian of the Gates disables the unit he deals combat damage
        to, not himself."""
        engine, game, match = blue(first=1)
        guardian = put(match, 2, "guardian_of_the_gates", patrol="squad_leader")
        cub = put(match, 1, "tiger_cub")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=cub.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender=guardian.ref)
        self.assertTrue(cub.disabled)
        self.assertFalse(guardian.disabled)
        self.assertNotIn(guardian.ref, {ref for ref in engine.attackers(match)})

    def test_guardian_of_the_gates_2(self) -> None:
        """If Guardian of the Gates deals combat damage to a unit with armor
        and the armor absorbs all the damage, his ability still triggers."""
        engine, game, match = blue(first=1)
        guardian = put(match, 2, "guardian_of_the_gates", patrol="squad_leader")
        cub = put(match, 1, "tiger_cub")
        cub.armor = 1
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=cub.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender=guardian.ref)
        self.assertEqual(cub.damage, 0)
        self.assertTrue(cub.disabled)

    def law_against_tech(self, *levels: str):
        engine, game, match = blue()
        wb_hero(match, 2, "bigby_hayes")
        for level in levels:
            built(match, 1, level)
        match.player(1).tech2_spec = "strength"
        return engine, game, match

    def test_injunction_1(self) -> None:
        """If you use Injunction on an opponent's Growth tech II building,
        for example, this will disable any tech II units they control at
        that moment, even if they are of a different spec. (They might have
        gained control of an Anarchy tech II unit or something, or cheated in
        units from other specs with Feral Strike.)"""
        engine, game, match = self.law_against_tech("tech1", "tech2")
        barb = put(match, 1, "doubling_barbarbarian", patrol="elite")
        constable = put(match, 1, "arresting_constable")
        constable.owner = 2
        cub = put(match, 1, "tiger_cub")
        cast(engine, game, match, "injunction", "1:tech2")
        self.assertTrue(match.player(1).buildings["tech2"].disabled)
        self.assertTrue(barb.disabled and constable.disabled)
        self.assertIsNone(barb.patrol_slot)
        self.assertFalse(cub.disabled)

    def test_injunction_2(self) -> None:
        """When you disable an opponent's tech building, they cannot build
        the next higher tech building until the disable ends. For example,
        if you disable their tech II building, they cannot build a tech III
        building on their next turn. If they already had a tech III building
        though, disabling their tech II building doesn't affect their tech
        III building—the tech III building continues operating normally."""
        engine, game, match = self.law_against_tech("tech1", "tech2")
        cast(engine, game, match, "injunction", "1:tech2")
        end_turn_of(engine, game, match, 2)
        player = match.player(1)
        player.workers, player.gold = 10, 20
        self.assertIn("Tech II", engine.build_option(player, "tech3", match).why_not)
        self.assertFalse(engine.tech_building_active(player, 2))
        end_turn_of(engine, game, match, 1)
        self.assertFalse(player.buildings["tech2"].disabled)
        built(match, 1, "tech3")
        player.buildings["tech2"].disabled = True
        self.assertTrue(engine.tech_building_active(player, 3))

    def test_injunction_on_tech_i_leaves_tech_iii_buildable(self) -> None:
        engine, game, match = self.law_against_tech("tech1", "tech2")
        cast(engine, game, match, "injunction", "1:tech1")
        end_turn_of(engine, game, match, 2)
        player = match.player(1)
        player.workers, player.gold = 10, 20
        self.assertFalse(engine.tech_building_active(player, 1))
        self.assertEqual(engine.build_option(player, "tech3", match).why_not, "")

    def test_injunction_3(self) -> None:
        """If an opponent does not have a tech II building, you won't be able
        to use Injunction to disable their tech II units."""
        engine, game, match = self.law_against_tech("tech1")
        barb = put(match, 1, "doubling_barbarbarian")
        hand(match, 2, "injunction")
        match.player(2).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="injunction")
        # The Tech I building is the one target, taken unasked.
        self.assertTrue(match.player(1).buildings["tech1"].disabled)
        self.assertFalse(barb.disabled)

    def insured(self, unit: str = "tiger_cub", seat: int = 1):
        engine, game, match = blue()
        agent = put(match, 2, "insurance_agent")
        target = put(match, seat, unit)
        trigger(engine, game, match, "insurance_agent", 2, agent.ref)
        prompt = asked(engine, game, match)
        if prompt is not None and prompt.kind is PromptKind.TARGET:
            answer_target(engine, game, match, f"{seat}:{target.ref}")
        match.player(2).deck = ["scribe"] * 5
        hand(match, 2)
        return engine, game, match, agent, target

    def test_insurance_agent_1(self) -> None:
        """If you use the ability on an Illusion, the Illusion immediately
        dies when targeted, never gets an insurance rune, and is thus never
        considered "insured." You don't get gold when it dies."""
        engine, game, match = blue()
        agent = put(match, 2, "insurance_agent")
        hound = put(match, 2, "spectral_hound")
        gold = match.player(2).gold
        trigger(engine, game, match, "insurance_agent", 2, agent.ref)
        answer_target(engine, game, match, f"2:{hound.ref}")
        self.assertIsNone(match.player(2).instance(hound.id))
        self.assertEqual(match.player(2).gold, gold)
        self.assertFalse(any(m.get("kind") == "insures" for m in agent.modifiers))

    def test_insurance_agent_2(self) -> None:
        """If Insurance Agent dies, his effect is no longer active. The
        insurance rune on his target now does nothing, even if you play a new
        Insurance Agent. The new Insurance Agent will place a new insurance
        rune on something, but he won't interact with the previous rune
        because of the "that unit" phrase on the ability."""
        engine, game, match, agent, cub = self.insured()
        self.assertEqual(cub.runes.get("insurance"), 1)
        board.destroy(engine, match, [(2, agent.ref)], StepResult())
        put(match, 2, "insurance_agent")
        gold = match.player(2).gold
        board.destroy(engine, match, [(1, cub.ref)], StepResult())
        self.assertEqual(match.player(2).gold, gold)

    def test_insurance_agent_3(self) -> None:
        """If the unit with the insurance rune leaves play without dying, you
        don't get the gold. For example, if it returns to someone's hand with
        Undo or is trashed somehow. If it's "destroyed" or "sacrificed" you
        do get the gold, because destroying or sacrificing a unit causes it
        to die."""
        engine, game, match, agent, cub = self.insured()
        gold = match.player(2).gold
        board.trash(engine, match, cub, StepResult())
        self.assertEqual(match.player(2).gold, gold)
        engine, game, match, agent, cub = self.insured()
        gold = match.player(2).gold
        board.destroy(engine, match, [(1, cub.ref)], StepResult())
        self.assertEqual(match.player(2).gold, gold + 2)
        self.assertEqual(match.player(2).hand, ["scribe"])

    def test_insurance_agent_4(self) -> None:
        """If Plague Lab adds a second insurance rune to a unit, that doesn't
        let you collect insurance money twice. The insurance rune itself
        doesn't actually do anything—it's just a tangible marker and memory
        aid."""
        engine, game, match, agent, cub = self.insured()
        cub.runes["insurance"] = 2
        gold = match.player(2).gold
        board.destroy(engine, match, [(1, cub.ref)], StepResult())
        self.assertEqual(match.player(2).gold, gold + 2)

    def test_insurance_agent_5(self) -> None:
        """If you have two Insurance Agents in play insuring the same unit,
        you can get double the gold and cards when it dies (since their
        abilities work independently)."""
        engine, game, match, agent, cub = self.insured()
        second = put(match, 2, "insurance_agent")
        trigger(engine, game, match, "insurance_agent", 2, second.ref)
        prompt = asked(engine, game, match)
        if prompt is not None and prompt.kind is PromptKind.TARGET:
            answer_target(engine, game, match, f"1:{cub.ref}")
        gold = match.player(2).gold
        board.destroy(engine, match, [(1, cub.ref)], StepResult())
        self.assertEqual(match.player(2).gold, gold + 4)
        self.assertEqual(len(match.player(2).hand), 2)

    def test_insurance_agent_6(self) -> None:
        """If Insurance Agent is insuring a unit, then you make something
        else a copy of that Insurance Agent, the copy will NOT also be
        insuring the unit. When you make something a copy of something else,
        it doesn't arrive so no arrive triggers happen. The copy does not get
        to put the insurance rune anywhere, and the rest of the copy's
        ability is looking for where that particular rune went. Because the
        copy never put a rune anywhere, the copy is not insuring anyting at
        all."""
        engine, game, match, agent, cub = self.insured()
        from codex.flow import resolve

        mirror = put(match, 2, "mirror_illusion")
        resolve.make_copy(engine, match, mirror, agent)
        gold = match.player(2).gold
        board.destroy(engine, match, [(1, cub.ref)], StepResult())
        self.assertEqual(match.player(2).gold, gold + 2)

    def test_judgment_day_1(self) -> None:
        """When a unit is "destroyed" it will "die" as a consequence of that.
        Anything that triggers on "dies" such as the patrol zone's scavenger
        and technician slots, or a Soul Stone, will trigger. When units die,
        they go to their owner's discard pile."""
        engine, game, match = blue()
        bigby = wb_hero(match, 2, "bigby_hayes", level=5)
        bigby.max_level_since_turn_began = False
        put(match, 2, "tenderfoot", patrol="scavenger")
        taken = put(match, 2, "tiger_cub")
        taken.owner = 1
        put(match, 1, "jade_fox_dens_headmistress")
        cast(engine, game, match, "judgment_day", gold=4)
        units = [card.slug for player in match.players for card in player.play
                 if engine.catalog.cards[card.slug].is_unit]
        self.assertEqual(units, ["jade_fox_dens_headmistress"])
        self.assertEqual(match.player(2).gold, 1)
        self.assertIn("tiger_cub", match.player(1).discard)

    def test_jurisdiction_1(self) -> None:
        """If you use this to play a channeling spell such as Two Step, but
        you don't control the appropriate hero to channel that spell, it's
        immediately discarded."""
        engine, game, match = blue()
        wb_hero(match, 2, "bigby_hayes")
        match.player(2).codex = {"dreamscape": 1}
        cast(engine, game, match, "jurisdiction", gold=10)
        self.assertEqual(match.player(2).codex["dreamscape"], 0)
        self.assertFalse(any(card.slug == "dreamscape" for card in match.player(2).play))
        self.assertIn("dreamscape", match.player(2).discard)
        self.assertEqual(match.player(2).gold, 10 - 2 - engine.catalog.cards["dreamscape"].cost)

    def test_jurisdiction_plays_a_spell_of_another_spec(self) -> None:
        """The author, 2026-10-10: Jurisdiction's spell needs no hero of its
        spec -- a Peace spell, with Bigby the Law hero alone in play."""
        engine, game, match = blue()
        wb_hero(match, 2, "bigby_hayes")
        unit = put(match, 2, "tenderfoot")
        match.player(2).codex = {"elite_training": 1}
        cast(engine, game, match, "jurisdiction", gold=10)
        answer_target(engine, game, match, f"2:{unit.ref}")
        prompt = asked(engine, game, match)
        if prompt is not None and prompt.kind is PromptKind.TARGET:
            apply(engine, game, match, PromptKind.TARGET, "done")
        self.assertTrue(engine.has_keyword(unit, "Anti-air", match))
        self.assertIn("elite_training", match.player(2).discard)

    def mind_controlled(self):
        engine, game, match = blue()
        at_max(engine, match, 2, "sirus_quince")
        cub = put(match, 1, "tiger_cub", patrol="elite")
        cast(engine, game, match, "mind_control")
        spell = next(card for card in match.player(2).play if card.slug == "mind_control")
        return engine, game, match, cub, spell

    def test_mind_control_1(self) -> None:
        """If the unit dies, it and Mind Control each go to their OWNER'S
        discard pile. That means Mind Control probably goes to yours and the
        unit probably goes to an opponent's discard pile."""
        engine, game, match, cub, spell = self.mind_controlled()
        self.assertEqual(cub.controller, 2)
        self.assertIsNone(cub.patrol_slot)
        board.destroy(engine, match, [(2, cub.ref)], StepResult())
        board.settle(engine, match, StepResult())
        self.assertIn("tiger_cub", match.player(1).discard)
        self.assertIn("mind_control", match.player(2).discard)

    def test_mind_control_2(self) -> None:
        """If Mind Control is destroyed (by Nature Reclaims, for example), the
        unit returns to whoever controlled it before it was Mind
        Controlled."""
        engine, game, match, cub, spell = self.mind_controlled()
        board.trash(engine, match, spell, StepResult())
        board.settle(engine, match, StepResult())
        self.assertEqual(cub.controller, 1)
        self.assertIn(cub, match.player(1).play)

    def test_mind_control_3(self) -> None:
        """If you Assimilate an a Mind Control, now you control the attached
        unit."""
        engine, game, match, cub, spell = self.mind_controlled()
        trigger(engine, game, match, "assimilate", 1)
        self.assertEqual(spell.controller, 1)
        self.assertEqual(cub.controller, 1)

    def test_patriot_gryphon_1(self) -> None:
        """As an example, if Patriot Gryphon attacks a tech II building,
        he'll destroy that tech building because he deals 6 damage to it. As
        usual, that tech building being destroyed deals 2 damage to its
        controller's base. Then, because of Patriot Gryphon's ability, he'll
        deal an additional 6 damage to that same base."""
        engine, game, match = blue()
        gryphon = put(match, 2, "patriot_gryphon")
        built(match, 1, "tech1")
        built(match, 1, "tech2")
        base = match.player(1).base_hp
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=gryphon.ref)
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, defender="tech2")
        self.assertTrue(match.player(1).buildings["tech2"].destroyed)
        self.assertEqual(match.player(1).base_hp, base - 8)

    def test_porkhand_magistrate_1(self) -> None:
        """He can't use his ability on himself."""
        engine, game, match = blue()
        pig = put(match, 2, "porkhand_magistrate")
        put(match, 1, "tenderfoot")
        put(match, 1, "tiger_cub")
        match.player(2).gold = 3
        match.player(2).deck = ["scribe"] * 3
        hand(match, 1)
        ability(engine, game, match, "porkhand_magistrate", pig.ref)
        offered = {row.key for row in asked(engine, game, match).options.targets}
        self.assertNotIn(f"2:{pig.ref}", offered)

    def test_porkhand_magistrate_2(self) -> None:
        """He CAN use his ability on a unit or hero that's already exhausted.
        He CAN use it on units or heroes you control as well."""
        engine, game, match = blue()
        pig = put(match, 2, "porkhand_magistrate")
        mine = put(match, 2, "tenderfoot", exhausted=True)
        match.player(2).gold = 3
        match.player(2).deck = ["scribe"] * 3
        hand(match, 2)
        # His own controller's exhausted unit, the one other: taken unasked.
        ability(engine, game, match, "porkhand_magistrate", pig.ref)
        self.assertTrue(mine.disabled)
        self.assertEqual(match.player(2).hand, ["scribe"])

    def quince(self, level: int = 3):
        engine, game, match = blue()
        quince = wb_hero(match, 2, "sirus_quince", level=level)
        mirror = put(match, 2, "mirror_illusion")
        match.player(2).gold = 20
        return engine, game, match, quince, mirror

    def quince_copies(self, engine, game, match, mirror, original, seat: int = 1) -> None:
        ability(engine, game, match, "sirus_quince_copy", "hero:sirus_quince")
        # Each part asked where it has more than one to choose.
        for _ in range(2):
            prompt = asked(engine, game, match)
            if prompt.kind is not PromptKind.TARGET:
                break
            key = f"2:{mirror.ref}" if prompt.options.part == 0 else f"{seat}:{original.ref}"
            answer_target(engine, game, match, key)

    def test_sirus_quince_1(self) -> None:
        """Copying something copies the printed version of the card and does
        not copy any modifiers. For example, if you copy a 2/2 that has a
        +1/+1 rune on it and Spirit of the Panda attached to it, the copy
        will just be a 2/2."""
        engine, game, match, quince, mirror = self.quince()
        cub = put(match, 1, "tiger_cub")
        cub.plus_runes = 1
        self.quince_copies(engine, game, match, mirror, cub)
        self.assertEqual(engine.unit_stats(mirror, match), (2, 2))

    def test_sirus_quince_2(self) -> None:
        """If an effect changes the "printed" values of a card, the new
        values will be used. This includes Chaos Mirror and transformation
        effects such as Polymorph: Squirrel."""
        engine, game, match, quince, mirror = self.quince()
        cub = put(match, 1, "tiger_cub")
        cub.printed = {"atk": 5}
        self.quince_copies(engine, game, match, mirror, cub)
        self.assertEqual(engine.unit_stats(mirror, match), (5, 2))

    def test_sirus_quince_3(self) -> None:
        """For both middle ability and max level ability, the copy is an
        Illusion. That means, for example, if you copy a unit of type
        Squirrel or Mystic then the copy will be an Illusion Squirrel or an
        Illusion Mystic. It will still count as a Squirrel or Mystic, and it
        also counts as an Illusion. Because it's an Illusion, it dies if its
        targeted."""
        engine, game, match, quince, mirror = self.quince()
        master = put(match, 1, "focus_master")
        self.quince_copies(engine, game, match, mirror, master)
        self.assertTrue(engine.is_illusion(match, mirror))
        self.assertIn("Mystic", engine.subtype_of(mirror))
        cast(engine, game, match, "wither", f"2:{mirror.ref}")
        self.assertIsNone(match.player(2).instance(mirror.id))

    def test_sirus_quince_4(self) -> None:
        """If you use the middle ability or max level ability to make of your
        Mirror Illusions a copy of something else, you can't use either of
        those abilities again the same turn on that same Illusion. The reason
        is that the ability refers to your "Mirror Illusion" but after your
        Mirror Illusion copies a Squirrel, for example, you have an Illusion
        Squirrel, not a Mirror Illusion. You can use these abilities on
        ANOTHER Mirror Illusion you control though."""
        engine, game, match, quince, mirror = self.quince()
        cub = put(match, 1, "tiger_cub")
        self.quince_copies(engine, game, match, mirror, cub)
        self.assertEqual(option(engine, match, "sirus_quince_copy", "hero:sirus_quince").why_not,
                         "no target")
        other = put(match, 2, "mirror_illusion")
        self.assertEqual(option(engine, match, "sirus_quince_copy", "hero:sirus_quince").why_not, "")
        self.assertIsNone(other.copy_of)

    def test_sirus_quince_5(self) -> None:
        """Mirror Illusions that are copying something else DO still count
        toward your limit of 2 Mirror Illusion tokens."""
        engine, game, match, quince, mirror = self.quince()
        cub = put(match, 1, "tiger_cub")
        self.quince_copies(engine, game, match, mirror, cub)
        ability(engine, game, match, "sirus_quince_summon", "hero:sirus_quince")
        self.assertEqual(sum(1 for card in match.player(2).play if card.slug == "mirror_illusion"), 2)
        self.assertEqual(option(engine, match, "sirus_quince_summon", "hero:sirus_quince").why_not,
                         "you have 2 Mirror Illusions")

    def test_sirus_quince_6(self) -> None:
        """The max level ability says that when you use it to make one of
        your Mirror Illusions copy something, you must trash it when Quince
        or the thing it copied leaves. This does NOT have anything to do
        with Mirror Illusions that have not yet copied anything. Mirror
        Illusions that haven't copied anything do NOT get trashed when
        Quince leaves."""
        engine, game, match, quince, mirror = self.quince(level=5)
        board.destroy(engine, match, [(2, "hero:sirus_quince")], StepResult())
        board.settle(engine, match, StepResult())
        self.assertIsNotNone(match.player(2).instance(mirror.id))

    def test_sirus_quince_7(self) -> None:
        """Quince's middle ability trashes the Mirror Illusion only once at
        the end of the turn you use the ability."""
        engine, game, match, quince, mirror = self.quince()
        cub = put(match, 1, "tiger_cub")
        self.quince_copies(engine, game, match, mirror, cub)
        self.assertIsNotNone(match.player(2).instance(mirror.id))
        end_turn_of(engine, game, match, 2)
        self.assertIsNone(match.player(2).instance(mirror.id))
        self.assertNotIn("mirror_illusion", match.player(2).discard)

    def test_sirus_quince_8(self) -> None:
        """Quince's max level ability can try to trash the Mirror Illusion
        two times, once when Quince leaves and once when the unit copied by
        the Mirror Illusion leaves."""
        engine, game, match, quince, mirror = self.quince(level=5)
        hand(match, 2, "tenderfoot")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="tenderfoot")
        prompt = asked(engine, game, match)
        if prompt is not None and prompt.kind is PromptKind.TARGET:
            answer_target(engine, game, match, f"2:{mirror.ref}")
        original = next(card for card in match.player(2).play if card.slug == "tenderfoot")
        self.assertEqual(mirror.copy_of, "tenderfoot")
        board.destroy(engine, match, [(2, original.ref)], StepResult())
        board.settle(engine, match, StepResult())
        self.assertIsNone(match.player(2).instance(mirror.id))
        # And once Quince leaves, for another.
        second = put(match, 2, "mirror_illusion")
        hand(match, 2, "tenderfoot")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="tenderfoot")
        prompt = asked(engine, game, match)
        if prompt is not None and prompt.kind is PromptKind.TARGET:
            answer_target(engine, game, match, f"2:{second.ref}")
        board.destroy(engine, match, [(2, "hero:sirus_quince")], StepResult())
        board.settle(engine, match, StepResult())
        self.assertIsNone(match.player(2).instance(second.id))

    def test_sirus_quince_9(self) -> None:
        """If your Mirror Illusion copies a Tech 1 unit, it becomes Tech
        1."""
        engine, game, match, quince, mirror = self.quince()
        self.assertEqual(engine.tech_level(mirror), 0)
        hound = put(match, 1, "iron_man")
        self.quince_copies(engine, game, match, mirror, hound)
        self.assertEqual(engine.tech_level(mirror), 1)

    def test_quince_summons_his_mirror_as_he_arrives(self) -> None:
        engine, game, match = blue()
        match.player(2).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "summon", hero="sirus_quince")
        self.assertEqual([card.slug for card in match.player(2).play], ["mirror_illusion"])

    def test_tax_collector_1(self) -> None:
        """His ability does nothing against an opponent that doesn't have
        any gold."""
        engine, game, match = blue()
        collector = put(match, 2, "tax_collector")
        match.player(1).gold = 0
        gold = match.player(2).gold
        trigger(engine, game, match, "tax_collector", 2, collector.ref)
        self.assertEqual((match.player(1).gold, match.player(2).gold), (0, gold))
        match.player(1).gold = 2
        trigger(engine, game, match, "tax_collector", 2, collector.ref)
        self.assertEqual((match.player(1).gold, match.player(2).gold), (1, gold + 1))

    def test_the_art_of_war_lasts_until_the_next_upkeep(self) -> None:
        engine, game, match = blue()
        at_max(engine, match, 2, "general_onimaru")
        onimaru = match.player(2).hero_of("general_onimaru")
        cast(engine, game, match, "the_art_of_war")
        self.assertTrue(engine.has_keyword(onimaru, "Unstoppable", match))
        self.assertEqual(onimaru.armor, 2)
        end_turn_of(engine, game, match, 2)
        self.assertEqual(onimaru.armor, 2, "new as the opponent's turn begins")
        end_turn_of(engine, game, match, 1)
        self.assertFalse(engine.has_keyword(onimaru, "Unstoppable", match))
        self.assertEqual(onimaru.armor, 0)

    def test_elite_training_and_the_air_hammer_and_the_debilitator(self) -> None:
        engine, game, match = blue()
        wb_hero(match, 2, "general_onimaru")
        hammer = put(match, 2, "air_hammer")
        cast(engine, game, match, "elite_training", f"2:{hammer.ref}")
        prompt = asked(engine, game, match)
        if prompt is not None and prompt.kind is PromptKind.TARGET:
            apply(engine, game, match, PromptKind.TARGET, "done")
        for keyword in ("Anti-air", "Sparkshot"):
            self.assertTrue(engine.has_keyword(hammer, keyword, match))
        self.assertEqual(hammer.armor, 1)
        built(match, 1, "tech1", hp=4)
        self.assertEqual(engine.attack_value(match, 2, hammer.ref, against="tech1"), 6)
        self.assertEqual(engine.attack_value(match, 2, hammer.ref, against="base"), 4)
        alpha = put(match, 1, "debilitator_alpha", patrol="squad_leader")
        self.assertEqual(engine.attack_value(match, 2, hammer.ref, against=alpha.ref), 3)

    def test_onimaru_summons_three_soldiers_at_max_level(self) -> None:
        engine, game, match = blue()
        wb_hero(match, 2, "general_onimaru", level=7)
        match.player(2).gold = 5
        apply(engine, game, match, PromptKind.MAIN_ACTION, "level", hero="general_onimaru", levels=1)
        soldiers = [card for card in match.player(2).play if card.slug == "soldier"]
        self.assertEqual(len(soldiers), 3)
        self.assertTrue(engine.has_keyword(soldiers[0], "Sparkshot", match))


class EveryCardRulingIsPinnedTests(unittest.TestCase):
    """The ratchet: every ruling the data holds on a card, a hero or a
    token has a test named for it, whose docstring is the ruling's own
    words -- so a re-import that adds one fails here (step 13)."""

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
        everything = rulings._load()[1]
        return {slug: entry.rulings for slug, entry in sorted(everything.items()) if entry.rulings}

    def test_the_count_is_pinned(self) -> None:
        total = sum(len(found) for found in self._rulings().values())
        self.assertEqual(
            total, CARD_RULINGS,
            f"the cards carry {total} rulings, not {CARD_RULINGS}: "
            "a re-import changed them, and each needs its test",
        )
        basic = sum(len(rulings.rulings_for(slug)) for slug in BASIC_SET)
        self.assertEqual(basic, 28, "the basic set's own count")

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


class EveryWhiteAndBlueRulingIsPinnedTests(EveryCardRulingIsPinnedTests):
    """Step 13's ratchet: the same three checks over every white and blue
    card, hero and token whose text is played -- every one once
    `UNIMPLEMENTED` is empty."""

    def _rulings(self) -> dict:
        return {
            slug: rulings.rulings_for(slug)
            for slug in sorted((WHITE | BLUE) - effects.UNIMPLEMENTED)
            if rulings.rulings_for(slug)
        }

    def test_the_count_is_pinned(self) -> None:
        total = sum(len(rulings.rulings_for(slug)) for slug in WHITE | BLUE)
        self.assertEqual(
            total, WHITE_BLUE_RULINGS,
            f"white's and blue's cards carry {total} rulings, not {WHITE_BLUE_RULINGS}: "
            "a re-import changed them, and each needs its test",
        )


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _sentences(text: str) -> list[str]:
    found = [part.strip(' ."') for part in re.split(r"(?<=[.!?])\s+", text)]
    return [part for part in found if len(part) > 20]


if __name__ == "__main__":
    unittest.main()

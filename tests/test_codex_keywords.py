"""
The combat keywords, **one test per ruling** (docs/codex-bot.md, step 5).

Sirlin's rulings are official rules of the game (decision 7): each one
the `General` group makes about a keyword this step implements is a test
below, named `test_<the ruling's keyword slug>_<its number in the file>`
with the ruling as its docstring, and `EveryRulingIsPinnedTests` holds
the two together -- it fails if a ruling has no test, if a test's
docstring is not its ruling's words, or if a re-import changes how many
rulings a keyword has.

Positions are staged by slug (`tests/codex_positions.py`), since Codex's
cards are fixed data. Two keywords of the set are printed on no card
the basic game plays -- swift strike, which Blademaster *grants* (step 6),
and stealth, which Sneaky Pig's arrives effect gives (step 6) -- so a
test that needs one gives a card the keyword for its own length
(`printed`), which is exactly what the table those steps will write does.
"""

from __future__ import annotations

import re
import unittest
from contextlib import contextmanager
from unittest import mock

from codex import keywords, rulings
from codex.components import AddOnState, CardInstance, hero_ref, is_hero_ref
from codex.flow import StepResult, actions, board, combat, driver, turn
from codex.game import RuleRefusal
from codex.prompts import Action, PromptKind, pending_prompt
from codex_positions import TROQ, begin, built, hero_in_play, new_game, put

#: The keywords step 5 implements, and how many `General` rulings each
#: carried at the pinned import (`SOURCE_SHA` in
#: `scripts/import_codex_cards.py`). A re-import that adds one fails
#: loudly, as step 6's card rulings will.
STEP_5_KEYWORDS = {
    "Anti-air": 7,
    "Flying": 4,
    "Stealth": 3,
    "Invisible": 4,
    "Unstoppable": 1,
    "Tower": 8,
    "Swift strike": 2,
    "Sparkshot": 6,
    "Overpower": 6,
    "Obliterate X": 2,
    "Readiness": 3,
    "Resist X": 2,
    "Frenzy X": 2,
    "Healing X": 1,
    "Haste": 2,
    #: A detector is what the tower is; the database rules on it nowhere.
    "Detector": 0,
    #: The standard game's add-on, step 10's (UMR p. 9).
    "Heroes' Hall": 2,
    "Tech Lab": 2,
}

#: The keywords red and green bring (step 11), and how many `General`
#: rulings each carried at the pinned import.
STEP_11_KEYWORDS = {
    "Deathtouch": 2,
    "Long-range": 2,
    "Ephemeral": 1,
    "Untargetable": 1,
    "Boost X": 3,
    "Channelling": 1,
    "Limit: X": 4,
}

#: The keywords purple and black bring (step 12), and how many `General`
#: rulings each carried at the pinned import.
STEP_12_KEYWORDS = {
    "Fading X": 3,
    "Forecast X": 3,
    "Indestructible": 4,
}

#: The keywords white and blue bring (step 13), and the two the General
#: group rules on that no step pinned before -- arrival fatigue and the
#: flagbearer -- with how many rulings each carried at the pinned import.
#: With them the tables cover the whole General group
#: (`test_the_tables_cover_the_general_group`).
STEP_13_KEYWORDS = {
    "Illusion": 3,
    "Stash": 1,
    "Arrival Fatigue": 2,
    "Flagbearer": 4,
}

ALL_KEYWORDS = {**STEP_5_KEYWORDS, **STEP_11_KEYWORDS, **STEP_12_KEYWORDS, **STEP_13_KEYWORDS}


@contextmanager
def printed(**pairs):
    """
    Give cards keywords for the length of a test -- `printed(iron_man=(("Swift
    strike", None),))`. The keyword table is read off the card texts, and
    nothing in the basic set prints swift strike or stealth, so a ruling
    about one is pinned by giving a card the keyword the way step 6's
    grants will.
    """
    table = keywords.keyword_table()
    with mock.patch.dict(table, dict(pairs)):
        yield


def fresh(seed: int = 7, teams=(("bashing",), ("finesse",))):
    """A game of Bashing against Finesse -- or `teams` -- standing in
    seat 1's main phase."""
    engine, game, match = new_game(seed=seed, teams=teams)
    begin(engine, game, match)
    return engine, game, match


def tower(match, seat: int, *, detected=None, finished: bool = True) -> AddOnState:
    """A tower in `seat`'s add-on slot (UMR p. 9)."""
    add_on = AddOnState(
        slug="tower", hp=4, under_construction=not finished, detected=detected,
    )
    match.player(seat).add_on = add_on
    return add_on


def said(result) -> str:
    return " ".join(result.narration)


class KeywordCase(unittest.TestCase):
    """What every ruling's test shares."""

    def attack(self, engine, game, match, attacker: str, defender: str):
        return combat.declare_attack(engine, game, match, attacker, defender)

    def damage(self, match, seat: int, ref: str) -> int:
        body = match.player(seat).hero_by_ref(ref) if is_hero_ref(ref) else match.player(seat).instance(
            int(ref.split(":", 1)[1]),
        )
        return body.damage


# -- Flying and anti-air (UMR p. 16) ------------------------------------------


class FlyingTests(KeywordCase):
    def test_flying_1(self) -> None:
        """Ground forces without anti-air can only shoot straight. They
        can never hit fliers, ever. Flying forces can shoot both straight
        and down. Anti-air forces can shoot both straight and up. This is
        never a handicap because even though they CAN hit patrolling
        fliers, they aren't forced to. As a patroller, you only stop an
        attacker if it's on the *same* level as you."""
        engine, game, match = fresh()
        ground = put(match, 1, "iron_man").ref
        flier = put(match, 1, "eggship").ref
        antiair = put(match, 1, "leaping_lizard").ref
        sprite = put(match, 2, "cloud_sprite", patrol="squad_leader").ref
        brother = put(match, 2, "older_brother").ref
        # A ground attacker can neither attack the flier nor be stopped by it.
        self.assertFalse(engine.may_be_attacked(match, ground, sprite))
        self.assertNotIn(sprite, engine.legal_defenders(match, ground))
        self.assertIn(brother, engine.legal_defenders(match, ground))
        # The flier is stopped by the flying patroller, and may take it.
        self.assertEqual(engine.legal_defenders(match, flier), (sprite,))
        # Anti-air may shoot up, and is not forced to.
        self.assertTrue(engine.may_be_attacked(match, antiair, sprite))
        self.assertIn(sprite, engine.legal_defenders(match, antiair))
        self.assertIn("base", engine.legal_defenders(match, antiair))

    def test_flying_2(self) -> None:
        """Fliers can ignore patrollers that don't have flying. In other
        words, they can attack something else instead if you want."""
        engine, game, match = fresh()
        flier = put(match, 1, "eggship").ref
        guard = put(match, 2, "older_brother", patrol="squad_leader").ref
        defenders = engine.legal_defenders(match, flier)
        self.assertIn("base", defenders)
        self.assertIn(guard, defenders, "it may take the patroller if it prefers")
        rows = dict(engine.defender_rows(match, flier))
        self.assertEqual(rows["base"], "it flies over the patrol zone")
        # The squad leader it takes is where it flies to, not over.
        self.assertEqual(rows[guard], "squad leader")

    def test_flying_3(self) -> None:
        """Fliers cannot ignore flying patrollers. The usual rules of the
        patrol zone apply, meaning if you want to attack with a flier at
        all, that flier CAN attack patrolling fliers so it must do that
        rather than attack other things such as non-patrollers or tech
        buildings."""
        engine, game, match = fresh()
        flier = put(match, 1, "eggship").ref
        sprite = put(match, 2, "cloud_sprite", patrol="elite").ref
        built(match, 2, "tech1")
        self.assertEqual(engine.legal_defenders(match, flier), (sprite,))

    def test_flying_4(self) -> None:
        """When a flier attacks another flier or gets attacked by another
        flier, they both deal combat damage to each other as usual. When a
        flier attacks a ground unit or hero without anti-air, the flier
        deals its combat damage to the ground thing and the ground thing
        does NOT deal any combat damage to the flier."""
        engine, game, match = fresh()
        flier = put(match, 1, "eggship").ref
        sprite = put(match, 2, "cloud_sprite").ref
        self.assertEqual(engine.damage_back(match, flier, sprite), 3)
        ground = put(match, 2, "regularsized_rhinoceros").ref
        self.assertEqual(engine.damage_back(match, flier, ground), 0)
        self.attack(engine, game, match, flier, ground)
        self.assertEqual(self.damage(match, 1, flier), 0)
        self.assertEqual(self.damage(match, 2, ground), 4)


class AntiAirTests(KeywordCase):
    def test_antiair_1(self) -> None:
        """You don't have to attack patrolling fliers with your anti-air
        attacker. You can ignore them and attack something else if you
        want."""
        engine, game, match = fresh()
        lizard = put(match, 1, "leaping_lizard").ref
        sprite = put(match, 2, "cloud_sprite", patrol="squad_leader").ref
        defenders = engine.legal_defenders(match, lizard)
        self.assertIn(sprite, defenders)
        self.assertIn("base", defenders)

    def test_antiair_2(self) -> None:
        """When one of your ground forces WITH anti-air gets attacked by a
        flier, each deals combat damage to the other. If your ground unit
        or hero doesn't have anti-air though, the flier will deal its
        combat damage "for free" to your ground unit or hero, and you
        won't get to hit back."""
        engine, game, match = fresh()
        flier = put(match, 1, "eggship").ref
        lizard = put(match, 2, "leaping_lizard").ref
        self.assertEqual(engine.damage_back(match, flier, lizard), 3)
        self.attack(engine, game, match, flier, lizard)
        self.assertEqual(self.damage(match, 2, lizard), 4)
        self.assertEqual(match.player(1).play, [], "4/3 takes the lizard's 3 and dies")

    def test_antiair_3(self) -> None:
        """When something "flies over" your patroller with anti-air, that
        means it used FLYING in particular to ignore your patroller. For
        example, if an attacker has stealth and flying and you don't have
        a detector, then the attacker doesn't even need to use flying to
        ignore your patroller. Stealth allows it to ignore your patroller
        so no "fly over" happened there and your anti-air patroller will
        not hit the attacker."""
        engine, game, match = fresh()
        with printed(eggship=(("Flying", None), ("Stealth", None))):
            flier = put(match, 1, "eggship").ref
            put(match, 2, "leaping_lizard", patrol="squad_leader")
            self.assertEqual(engine.ignores_patrollers(match, flier), "stealth")
            self.assertEqual(engine.flown_over(match, flier, "base"), ())
            self.attack(engine, game, match, flier, "base")
            self.assertEqual(self.damage(match, 1, flier), 0)
            self.assertEqual(match.player(2).base_hp, 16)

    def test_antiair_4(self) -> None:
        """If you have multiple patrollers with anti-air, they all deal
        combat damage to a flier that flies over all of them. But if that
        same flier were to attack just your squad leader, your two OTHER
        patrollers wouldn't deal combat damage to it because it did not
        "fly over" them. Or if that same flier attacked one of those two
        patrollers, the squad leader would deal combat damage to it (and
        the anti-air patroller it attacked would), but the third anti-air
        patroller would not."""
        def staged():
            engine, game, match = fresh()
            flier = put(match, 1, "eggship").ref
            leader = put(match, 2, "leaping_lizard", patrol="squad_leader").ref
            second = put(match, 2, "leaping_lizard", patrol="elite").ref
            third = put(match, 2, "leaping_lizard", patrol="scavenger").ref
            built(match, 2, "tech2")
            return engine, game, match, flier, leader, second, third

        engine, _, match, flier, leader, second, third = staged()
        self.assertEqual(
            set(engine.flown_over(match, flier, "tech2")), {leader, second, third},
        )
        engine, _, match, flier, leader, second, third = staged()
        self.assertEqual(engine.flown_over(match, flier, leader), ())
        engine, _, match, flier, leader, second, third = staged()
        self.assertEqual(engine.flown_over(match, flier, second), (leader,))

    def test_antiair_5(self) -> None:
        """All combat damage (except swift strike) is dealt
        simultaneously, and anti-air is not an exception. Anti-air combat
        damage is dealt at the same time as everything else, unless it has
        swift strike, in which case it's dealt before combat damage that
        doesn't have swift strike."""
        engine, game, match = fresh()
        flier = put(match, 1, "eggship").ref
        put(match, 2, "leaping_lizard", patrol="squad_leader")
        self.attack(engine, game, match, flier, "base")
        # The flier dies to the anti-air patroller it flew over, and its
        # own damage still reached the base.
        self.assertEqual(match.player(1).play, [])
        self.assertEqual(match.player(2).base_hp, 16)

    def test_antiair_6(self) -> None:
        """A unit or hero that has both flying and anti-air does not
        benefit from anti-air. In other words, anti-air doesn't allow your
        fliers to ignore patrollers with flying."""
        engine, game, match = fresh()
        with printed(eggship=(("Flying", None), ("Anti-air", None))):
            flier = put(match, 1, "eggship").ref
            sprite = put(match, 2, "cloud_sprite", patrol="elite").ref
            self.assertEqual(engine.legal_defenders(match, flier), (sprite,))

    def test_antiair_7(self) -> None:
        """Anti-air does not stack. Having two instances of anti-air is
        the same as having just one."""
        self.assertNotIn("Anti-air", keywords.STACKING)
        with printed(leaping_lizard=(("Anti-air", None), ("Anti-air", None))):
            card = CardInstance(1, "leaping_lizard", 1, 1)
            self.assertEqual(keywords.keyword_x(card, "Anti-air"), 1)


# -- Stealth, invisible, unstoppable and the tower (UMR p. 9, 17, 18) --------


class StealthTests(KeywordCase):
    def test_stealth_1(self) -> None:
        """"Sneaking past" means you can ignore patrollers when attacking
        and attack anything you want. You can also attack the patrollers
        if you prefer."""
        engine, game, match = fresh()
        with printed(iron_man=(("Stealth", None),)):
            sneak = put(match, 1, "iron_man").ref
            guard = put(match, 2, "older_brother", patrol="squad_leader").ref
            defenders = engine.legal_defenders(match, sneak)
            self.assertIn("base", defenders)
            self.assertIn(guard, defenders)
            self.assertEqual(
                dict(engine.defender_rows(match, sneak))["base"],
                "it sneaks past the patrol zone",
            )

    def test_stealth_2(self) -> None:
        """When something with stealth attacks an enemy unit or hero, that
        enemy unit or hero DOES deal its combat damage back as usual."""
        engine, game, match = fresh()
        with printed(iron_man=(("Stealth", None),)):
            sneak = put(match, 1, "iron_man").ref
            brother = put(match, 2, "older_brother").ref
            self.attack(engine, game, match, sneak, brother)
            self.assertEqual(self.damage(match, 1, sneak), 2)

    def test_stealth_3(self) -> None:
        """If an opponent has the Tower add-on and their tower has already
        used its once-per-turn detect on something, then you attack with
        something that has stealth, the Tower will not deal its damage to
        your stealth thing."""
        engine, game, match = fresh()
        with printed(iron_man=(("Stealth", None),)):
            sneak = put(match, 1, "iron_man").ref
            tower(match, 2, detected="unit:99")
            self.assertFalse(engine.tower_sees(match, sneak))
            self.attack(engine, game, match, sneak, "base")
            self.assertEqual(self.damage(match, 1, sneak), 0)


class InvisibleTests(KeywordCase):
    def test_invisible_1(self) -> None:
        """"Sneaking past" means you can ignore patrollers when attacking
        and attack anything you want. You can also attack the patrollers
        if you prefer."""
        engine, game, match = fresh()
        sneak = put(match, 2, "backstabber").ref
        guard = put(match, 1, "older_brother", patrol="squad_leader").ref
        match.active = 2
        defenders = engine.legal_defenders(match, sneak)
        self.assertIn("base", defenders)
        self.assertIn(guard, defenders)

    def test_invisible_2(self) -> None:
        """When something invisible attacks an enemy unit or hero, that
        enemy unit or hero DOES deal its combat damage back as usual."""
        engine, game, match = fresh()
        sneak = put(match, 1, "backstabber").ref
        brother = put(match, 2, "older_brother", patrol="squad_leader").ref
        self.attack(engine, game, match, sneak, brother)
        self.assertEqual(self.damage(match, 1, sneak), 2)

    def test_invisible_3(self) -> None:
        """If an opponent has the Tower add-on and their tower has already
        used its once-per-turn detect on something, then you attack with
        something invisible, the Tower will not deal its damage to your
        invisible thing. It would if it's once-per-turn detect hadn't been
        used, but it can only damage things it can see."""
        engine, game, match = fresh()
        sneak = put(match, 1, "backstabber").ref
        spent = tower(match, 2, detected="unit:99")
        self.assertFalse(engine.tower_sees(match, sneak))
        self.attack(engine, game, match, sneak, "base")
        self.assertEqual(self.damage(match, 1, sneak), 0)
        # Unspent, the same tower would have seen it.
        spent.detected = None
        self.assertTrue(engine.tower_sees(match, sneak))

    def test_invisible_4(self) -> None:
        """You can [target] your own invisible things whether you have a
        detector or not."""
        engine, game, match = fresh()
        mine = put(match, 1, "backstabber").ref
        # Nothing of your own is ever hidden from you: the engine's
        # reading is asked of the opponent alone (`may_be_attacked`), and
        # your own cards are in every list of your own things. What a
        # target may be is step 6's.
        self.assertEqual(engine.hidden(match, 1, mine), "invisible")
        self.assertIn(mine, engine._things_in_play(match, 1))
        self.assertIn(mine, engine.patrol_candidates(match))


class UnstoppableTests(KeywordCase):
    def test_unstoppable_1(self) -> None:
        """Having a detector (or a Tower add-on) doesn't help against the
        unstoppable keywords. Even then, unstoppable attackers can ignore
        patrollers."""
        engine, game, match = fresh()
        dancer = put(match, 1, "angry_dancer").ref
        put(match, 2, "older_brother", patrol="squad_leader")
        tower(match, 2)
        self.assertEqual(engine.ignores_patrollers(match, dancer), "unstoppable")
        self.assertIn("base", engine.legal_defenders(match, dancer))
        self.assertEqual(
            dict(engine.defender_rows(match, dancer))["base"], "it is unstoppable",
        )


class TowerTests(KeywordCase):
    def test_tower_1(self) -> None:
        """The damage dealt by the tower is considered combat damage (so
        if it kills a Brave Knight that counts as "dying from combat
        damage"). It also means that the damage is dealt simultaneously
        with other combat damage."""
        engine, game, match = fresh()
        tower(match, 2)
        messenger = put(match, 1, "timely_messenger").ref  # 1/1
        self.attack(engine, game, match, messenger, "base")
        # It died to the tower's damage, which landed at the same time as
        # its own, so the base still took it.
        self.assertEqual(match.player(1).play, [])
        self.assertIn("timely_messenger", match.player(1).discard)
        self.assertEqual(match.player(2).base_hp, 19)

    def test_tower_2(self) -> None:
        """If the attacker has swift strike, the tower still deals combat
        damage simultaneously as the swift strike. If the attacker has
        flying, the tower still hits it as if it had anti-air."""
        engine, game, match = fresh()
        tower(match, 2)
        with printed(tenderfoot=(("Swift strike", None),)):
            swift = put(match, 1, "tenderfoot").ref
            self.attack(engine, game, match, swift, "base")
            self.assertEqual(self.damage(match, 1, swift), 1)
        engine, game, match = fresh()
        tower(match, 2)
        flier = put(match, 1, "eggship").ref
        self.attack(engine, game, match, flier, "base")
        self.assertEqual(self.damage(match, 1, flier), 1)

    def test_tower_3(self) -> None:
        """The tower deals 1 damage to attackers who are attacking
        ANYTHING controlled by the player (or team in 2v2) with the tower.
        It doesn't just trigger when they attack the tower itself."""
        engine, game, match = fresh()
        tower(match, 2)
        iron = put(match, 1, "iron_man").ref
        brother = put(match, 2, "older_brother").ref
        self.attack(engine, game, match, iron, brother)
        self.assertEqual(self.damage(match, 1, iron), 2 + 1)

    def test_tower_4(self) -> None:
        """On an opponent's turn, your tower uses its detect ability the
        first time it can. For example, if the opponent attacks you with a
        stealth 1/1, the tower will automatically reveal it, and that
        attacker can't ignore your patrollers. If the opponent then
        attacks with an 8/8 stealth unit, the tower won't detect it
        because it already used its ability once that turn."""
        engine, game, match = fresh()
        standing = tower(match, 2)
        with printed(iron_man=(("Stealth", None),),
                     regularsized_rhinoceros=(("Stealth", None),)):
            first = put(match, 1, "iron_man").ref
            second = put(match, 1, "regularsized_rhinoceros").ref
            guard = put(match, 2, "tenderfoot", patrol="squad_leader").ref
            self.assertEqual(engine.ignores_patrollers(match, first), "")
            self.assertEqual(engine.legal_defenders(match, first), (guard,))
            self.attack(engine, game, match, first, guard)
            self.assertEqual(standing.detected, first)
            self.assertEqual(engine.ignores_patrollers(match, second), "stealth")
            self.assertIn("base", engine.legal_defenders(match, second))

    def test_tower_5(self) -> None:
        """If an attacker has stealth or invisible AND another evasion
        ability such as unstoppable, the tower will still use its
        once-per-turn detect so that it can deal 1 damage to the attacker.
        This won't prevent the attacker from using evasion abilities such
        as unstoppable though, so it can still ignore patrollers when it
        attacks."""
        engine, game, match = fresh()
        standing = tower(match, 2)
        with printed(iron_man=(("Stealth", None), ("Unstoppable", None))):
            sneak = put(match, 1, "iron_man").ref
            put(match, 2, "older_brother", patrol="squad_leader")
            self.assertEqual(engine.ignores_patrollers(match, sneak), "unstoppable")
            self.assertTrue(engine.tower_detects(match, sneak))
            self.attack(engine, game, match, sneak, "base")
            self.assertEqual(standing.detected, sneak)
            self.assertEqual(self.damage(match, 1, sneak), 1)
            self.assertEqual(match.player(2).base_hp, 17)

    def test_tower_6(self) -> None:
        """If the tower already used its detect ability on an opponent's
        turn, then that opponent attacks with a stealth/invisible unit or
        hero, the tower won't hit that attacker. It won't even hit the
        attacker if it attacks the tower itself."""
        engine, game, match = fresh()
        tower(match, 2, detected="unit:99")
        sneak = put(match, 1, "backstabber").ref
        self.attack(engine, game, match, sneak, "add_on")
        self.assertEqual(self.damage(match, 1, sneak), 0)
        self.assertEqual(match.player(2).add_on.hp, 1, "the tower took the 3 itself")

    def test_tower_7(self) -> None:
        """When you reveal a stealth/invisible thing with your tower, that
        thing stays revealed the rest of the turn. It is legal for you to
        cast multiple spells that target that revealed thing later that
        turn."""
        engine, game, match = fresh()
        standing = tower(match, 2)
        sneak = put(match, 1, "backstabber").ref
        other = put(match, 1, "iron_man").ref
        self.attack(engine, game, match, sneak, "base")
        self.assertEqual(standing.detected, sneak)
        self.assertTrue(engine.detected_by(match, 2, sneak))
        # It is still detected after another attack, and the detection is
        # new again when a turn begins.
        self.attack(engine, game, match, other, "base")
        self.assertEqual(standing.detected, sneak)
        match.active = 2
        match.enter_phase("ready")
        match.player(2).tech_owed = False
        turn.begin_turn(engine, game, match)
        self.assertIsNone(standing.detected)

    def test_tower_8(self) -> None:
        """In free-for-all, the tower will only hit an attacker that is
        attacking things you control. It won't hit an attacker that is
        attacking things controlled by one of your opponents."""
        engine, game, match = fresh()
        mine = tower(match, 1)
        theirs = tower(match, 2)
        iron = put(match, 1, "iron_man").ref
        self.attack(engine, game, match, iron, "base")
        # Only the defending player's tower shoots: a two-player game is
        # every attack the rule covers.
        self.assertEqual(self.damage(match, 1, iron), 1)
        self.assertEqual((mine.hp, theirs.hp), (4, 4))


# -- Swift strike (UMR p. 18) --------------------------------------------------


class SwiftStrikeTests(KeywordCase):
    def test_swift_strike_1(self) -> None:
        """Combat damage is dealt simultaneously if the attacker and the
        thing it's attacking both have swift strike."""
        engine, game, match = fresh()
        with printed(iron_man=(("Swift strike", None),),
                     regularsized_rhinoceros=(("Swift strike", None),)):
            iron = put(match, 1, "iron_man").ref
            rhino = put(match, 2, "regularsized_rhinoceros", damage=4).ref
            self.attack(engine, game, match, iron, rhino)
            self.assertEqual(match.player(1).play, [], "both deal their damage")
            self.assertEqual(match.player(2).play, [])

    def test_swift_strike_2(self) -> None:
        """If swift strike damage kills a unit or hero in combat that does
        not have swift strike, the non-swift strike unit or hero dies
        before it gets a chance to deal combat damage."""
        engine, game, match = fresh()
        with printed(iron_man=(("Swift strike", None),)):
            iron = put(match, 1, "iron_man").ref
            brother = put(match, 2, "older_brother").ref
            result = self.attack(engine, game, match, iron, brother)
            self.assertEqual(self.damage(match, 1, iron), 0)
            self.assertIn("before it strikes back", said(result))


# -- Sparkshot (UMR p. 18) -----------------------------------------------------


class SparkshotTests(KeywordCase):
    def staged(self, seed: int = 7):
        engine, game, match = fresh(seed)
        ocelot = put(match, 1, "revolver_ocelot").ref
        return engine, game, match, ocelot

    def test_sparkshot_1(self) -> None:
        """Sparkshot can only hit something 1 slot over from the thing
        you're attacking (an adjacent slot). It can't hit something two
        slots away even if it's the closest patroller (that is no longer
        ADJACENT to the thing you're attacking)."""
        engine, game, match, ocelot = self.staged()
        leader = put(match, 2, "tenderfoot", patrol="squad_leader").ref
        far = put(match, 2, "older_brother", patrol="scavenger").ref
        self.assertEqual(engine.sparkshot_candidates(match, ocelot, leader), ())
        beside = put(match, 2, "iron_man", patrol="elite").ref
        self.assertEqual(engine.sparkshot_candidates(match, ocelot, leader), (beside,))

    def test_sparkshot_2(self) -> None:
        """This counts as combat damage (it can kill Gilded Glaxx for
        example) and it counts as an ability (so something that has
        sparkshot cannot get +2/+2 from Midori's middle ability)."""
        engine, game, match, ocelot = self.staged()
        leader = put(match, 2, "older_brother", patrol="squad_leader").ref
        beside = put(match, 2, "tenderfoot", patrol="elite", damage=1).ref
        self.attack(engine, game, match, ocelot, leader)
        self.assertIsNone(match.player(2).instance(int(beside.split(":")[1])),
                          "sparkshot's damage destroys, as combat damage does")

    def test_sparkshot_3(self) -> None:
        """Sparkshot damage is dealt simultaneously with all other combat
        damage."""
        engine, game, match, ocelot = self.staged()
        leader = put(match, 2, "regularsized_rhinoceros", patrol="squad_leader").ref
        beside = put(match, 2, "tenderfoot", patrol="elite").ref
        self.attack(engine, game, match, ocelot, leader)
        # The ocelot died to the squad leader's 5, and its sparkshot still
        # landed.
        self.assertEqual(match.player(1).play, [])
        self.assertEqual(self.damage(match, 2, beside), 1)

    def test_sparkshot_4(self) -> None:
        """Sparkshot CAN hit a flier even if the attacker with sparkshot
        doesn't have anti-air."""
        engine, game, match, ocelot = self.staged()
        leader = put(match, 2, "older_brother", patrol="squad_leader").ref
        sprite = put(match, 2, "cloud_sprite", patrol="elite").ref
        self.assertEqual(engine.sparkshot_candidates(match, ocelot, leader), (sprite,))
        self.attack(engine, game, match, ocelot, leader)
        self.assertEqual(self.damage(match, 2, sprite), 1)

    def test_sparkshot_5(self) -> None:
        """Sparkshot doesn't [target]."""
        engine, game, match, ocelot = self.staged()
        leader = put(match, 2, "older_brother", patrol="squad_leader").ref
        # The neighbour is hit with no resist paid, whatever it would
        # cost to target it.
        beside = put(match, 2, "brick_thief", patrol="elite").ref
        self.assertEqual(engine.resist_cost(match, 2, beside), 1)
        self.assertEqual(engine.sparkshot_candidates(match, ocelot, leader), (beside,))
        gold = match.player(1).gold
        self.attack(engine, game, match, ocelot, leader)
        self.assertIn("brick_thief", match.player(2).discard,
                      "the 2/1 neighbour took sparkshot's damage and died")
        self.assertEqual(match.player(1).gold, gold)

    def test_sparkshot_6(self) -> None:
        """Sparkshot does stack. A unit with 2 instances of sparkshot will
        get to deal 2 damage to an adjacent patroller or 1 damage to each
        of 2 adjacent patrollers."""
        self.assertIn("Sparkshot", keywords.STACKING)
        twice = {"revolver_ocelot": (("Sparkshot", None), ("Sparkshot", None))}
        with printed(**twice):
            # Both to one neighbour.
            engine, game, match, ocelot = self.staged()
            left = put(match, 2, "iron_man", patrol="elite").ref
            middle = put(match, 2, "tenderfoot", patrol="scavenger").ref
            right = put(match, 2, "iron_man", patrol="technician").ref
            self.assertEqual(engine.sparkshot_count(match, ocelot), 2)
            self.attack(engine, game, match, ocelot, middle)
            asked = pending_prompt(engine, game, match)
            self.assertIs(asked.kind, PromptKind.SPARKSHOT_TARGET)
            self.assertEqual(asked.options.left, 2)
            combat.choose_sparkshot(engine, game, match, left)
            asked = pending_prompt(engine, game, match)
            self.assertIs(asked.kind, PromptKind.SPARKSHOT_TARGET)
            self.assertEqual((asked.options.left, asked.options.placed), (1, (left,)))
            combat.choose_sparkshot(engine, game, match, left)
            self.assertEqual((self.damage(match, 2, left), self.damage(match, 2, right)), (2, 0))
            # One to each.
            engine, game, match, ocelot = self.staged()
            left = put(match, 2, "iron_man", patrol="elite").ref
            middle = put(match, 2, "tenderfoot", patrol="scavenger").ref
            right = put(match, 2, "iron_man", patrol="technician").ref
            self.attack(engine, game, match, ocelot, middle)
            combat.choose_sparkshot(engine, game, match, left)
            combat.choose_sparkshot(engine, game, match, right)
            self.assertEqual((self.damage(match, 2, left), self.damage(match, 2, right)), (1, 1))
            # With one neighbour, both go to it unasked.
            engine, game, match, ocelot = self.staged()
            leader = put(match, 2, "regularsized_rhinoceros", patrol="squad_leader").ref
            beside = put(match, 2, "iron_man", patrol="elite").ref
            self.attack(engine, game, match, ocelot, leader)
            self.assertEqual(self.damage(match, 2, beside), 2)


# -- Overpower (UMR p. 17) -----------------------------------------------------


class OverpowerTests(KeywordCase):
    def staged(self):
        engine, game, match = fresh()
        reaper = put(match, 1, "harvest_reaper").ref  # 6/5
        return engine, game, match, reaper

    def test_overpower_1(self) -> None:
        """The excess combat damage from the first target can go to only
        one additional target. It can't cascade beyond that to hit even
        more targets."""
        engine, game, match, reaper = self.staged()
        leader = put(match, 2, "tenderfoot", patrol="squad_leader").ref
        second = put(match, 2, "tenderfoot", patrol="elite").ref
        loose = put(match, 2, "tenderfoot").ref
        built(match, 2, "tech1")
        result = self.attack(engine, game, match, reaper, leader)
        self.assertEqual(said(result).count("Overpower carries"), 1)
        self.assertIsNone(match.player(2).instance(int(second.split(":")[1])),
                          "the excess went to the other patroller")
        self.assertEqual(self.damage(match, 2, loose), 0, "and no cascade past it")
        self.assertEqual(match.player(2).buildings["tech1"].hp, 5)

    def test_overpower_2(self) -> None:
        """The "excess" combat damage is the damage beyond the remaining
        HP of the thing you attacked. It doesn't matter if the thing
        actually dies or not, the damage beyond its HP is still counted as
        "excess"."""
        engine, game, match, reaper = self.staged()
        leader = put(match, 2, "iron_man", patrol="squad_leader", damage=1).ref
        # 3/4 with a damage: three HP left, so three of the six carry over.
        self.assertEqual(engine.overpower_excess(match, reaper, leader), 3)

    def test_overpower_2_with_armor(self) -> None:
        """A patroller's armor is part of what destroys it, and the excess
        is what is left after that (the author, 2026-10-08: "if the
        overpowering attacker destroys a patroller with armor, the excess
        damage goes to anything else it could attack")."""
        engine, game, match, reaper = self.staged()
        leader = put(match, 2, "tenderfoot", patrol="squad_leader")
        leader.armor = 1
        beside = put(match, 2, "regularsized_rhinoceros", patrol="elite").ref
        # 1/2 behind armor 1 takes three of the six; three carry over.
        self.assertEqual(engine.overpower_excess(match, reaper, leader.ref), 3)
        self.attack(engine, game, match, reaper, leader.ref)
        self.assertIn("tenderfoot", match.player(2).discard, "the squad leader is destroyed")
        self.assertEqual(self.damage(match, 2, beside), 3)

    def test_overpower_3(self) -> None:
        """When determining what an overpower attacker "could have
        attacked" you still obey all the normal rules of attacking. If
        there are any patrollers other than the one actually attacked that
        would have been possible for the overpower attacker to attack, the
        excess combat damage has to go to one of them rather than say, a
        tech building. If there aren't any other patrollers that the
        overpower unit or hero could have attacked, then the excess damage
        can go to anything with HP that's controlled by the player (or
        team in 2v2) whose patroller was attacked."""
        engine, game, match, reaper = self.staged()
        leader = put(match, 2, "tenderfoot", patrol="squad_leader").ref
        beside = put(match, 2, "older_brother", patrol="elite").ref
        built(match, 2, "tech1")
        self.assertEqual(engine.overpower_candidates(match, reaper, leader), (beside,))
        # A flier it could not have attacked is no candidate, and with no
        # other patroller left the excess may go to anything of theirs.
        match.player(2).instance(int(beside.split(":")[1])).patrol_slot = None
        sprite = put(match, 2, "cloud_sprite", patrol="elite").ref
        candidates = engine.overpower_candidates(match, reaper, leader)
        self.assertNotIn(sprite, candidates)
        self.assertIn("tech1", candidates)
        self.assertIn("base", candidates)

    def test_overpower_4(self) -> None:
        """Overpower does nothing when you attack a non-patroller. It also
        does nothing on defense (when your overpower unit or hero gets
        attacked)."""
        engine, game, match, reaper = self.staged()
        loose = put(match, 2, "tenderfoot").ref
        self.assertEqual(engine.overpower_excess(match, reaper, loose), 0)
        self.assertEqual(engine.overpower_candidates(match, reaper, loose), ())
        # On defence: the attacker's own side is asked, never the
        # defender's keyword.
        match.active = 2
        iron = put(match, 2, "iron_man").ref
        self.assertEqual(engine.overpower_excess(match, iron, reaper), 0)

    def test_overpower_5(self) -> None:
        """Overpower damage still counts as combat damage (it can kill
        Gilded Glaxx for example) and it counts as an ability (so
        something that has overpower cannot get +2/+2 from Midori's middle
        ability)."""
        engine, game, match, reaper = self.staged()
        leader = put(match, 2, "tenderfoot", patrol="squad_leader").ref
        beside = put(match, 2, "older_brother", patrol="elite").ref
        self.attack(engine, game, match, reaper, leader)
        self.assertEqual(match.player(2).play, [], "the excess destroyed the other")
        self.assertIn("older_brother", match.player(2).discard)

    def test_overpower_6(self) -> None:
        """Overpower does not stack. Having two instances of overpower is
        the same as having just one."""
        self.assertNotIn("Overpower", keywords.STACKING)
        with printed(harvest_reaper=(("Overpower", None), ("Overpower", None))):
            card = CardInstance(1, "harvest_reaper", 1, 1)
            self.assertEqual(keywords.keyword_x(card, "Overpower"), 1)


# -- Obliterate (UMR p. 17) ----------------------------------------------------


class ObliterateTests(KeywordCase):
    def test_obliterate_x_1(self) -> None:
        """Obliterate never targets. Having resist or being untargetable
        doesn't help against obliterate."""
        engine, game, match = fresh()
        duck = put(match, 1, "trojan_duck").ref
        thief = put(match, 2, "brick_thief").ref
        self.assertEqual(engine.resist_cost(match, 2, thief), 1)
        self.assertEqual(engine.obliterate_candidates(match), (thief,))
        gold = match.player(1).gold
        self.attack(engine, game, match, duck, "base")
        self.assertEqual(match.player(2).play, [])
        self.assertEqual(match.player(1).gold, gold, "nothing is paid to obliterate")

    def test_obliterate_x_2(self) -> None:
        """If there are any units that are indestructible or that can't
        leave play, ignore them when looking for the lowest tech unit. If
        such a thing would be their "lowest tech unit" then instead
        destroy their next lowest."""
        engine, game, match = fresh()
        duck = put(match, 1, "trojan_duck").ref
        low = put(match, 2, "tenderfoot").ref
        high = put(match, 2, "backstabber").ref
        # Nothing in the basic set is indestructible, so the rule reads as
        # the lowest tech units and nothing else; invisibility is no
        # shelter either, since obliterate does not target.
        self.assertEqual(engine.obliterate_candidates(match), (low,))
        self.attack(engine, game, match, duck, "base")
        self.assertEqual(
            [card.slug for card in match.player(2).play], [],
            "obliterate 2 took the tech 0 unit and then the invisible one",
        )
        self.assertIn("backstabber", match.player(2).discard)


# -- Readiness, haste, frenzy, healing and resist (UMR p. 16-18) --------------


class ReadinessTests(KeywordCase):
    def test_readiness_1(self) -> None:
        """Readiness doesn't let you ignore any other attacking rules. You
        still can't attack with something that's exhausted, and you still
        can't attack with it the turn it comes under your control (unless
        it also has haste.)"""
        engine, game, match = fresh()
        hero_in_play(match, 1, level=8)
        hero = match.player(1).hero
        self.assertTrue(engine.has_keyword(hero, "Readiness"))
        self.assertIn(TROQ, engine.attackers(match))
        hero.exhausted = True
        self.assertNotIn(TROQ, engine.attackers(match))
        hero.exhausted = False
        hero.arrived_this_turn = True
        self.assertNotIn(TROQ, engine.attackers(match))

    def test_readiness_2(self) -> None:
        """If you attack with something that has readiness, it won't
        exhaust. You CAN exhaust it to pay for the cost of a spell or
        ability (or as an effect from a spell or ability), even though you
        can't attack with it again that turn."""
        engine, game, match = fresh()
        hero_in_play(match, 1, level=8)
        self.attack(engine, game, match, TROQ, "base")
        hero = match.player(1).hero
        self.assertFalse(hero.exhausted)
        self.assertTrue(hero.attacked_this_turn)

    def test_readiness_3(self) -> None:
        """Things with readiness can only attack once per turn, even if an
        effect would normally let them attack again. When cards leave play
        and then come back (for example, from Geiger or Pasternaak's max
        level abilities), they count as new objects though."""
        engine, game, match = fresh()
        hero_in_play(match, 1, level=8)
        self.attack(engine, game, match, TROQ, "base")
        self.assertNotIn(TROQ, engine.attackers(match))
        with self.assertRaises(Exception):
            self.attack(engine, game, match, TROQ, "base")
        # Killed and summoned again, it is a new object: nothing of the
        # turn clings to it.
        hero = match.player(1).hero
        hero.zone, hero.summoning_runes = "command", 0
        hero.attacked_this_turn = False
        match.player(1).gold = 5
        actions.summon_hero(engine, game, match)
        self.assertFalse(hero.attacked_this_turn)


class HasteTests(KeywordCase):
    def test_haste_1(self) -> None:
        """Haste allows things that came under your control this turn use
        exhaust abilities, which means abilities that have exhaust as part
        of the cost. Haste also allows units and heroes to attack that
        came under your control this turn."""
        engine, game, match = fresh()
        hasty = put(match, 1, "timely_messenger", arrived=True).ref
        slow = put(match, 1, "older_brother", arrived=True).ref
        self.assertEqual(engine.attackers(match), (hasty,))
        self.attack(engine, game, match, hasty, "base")
        self.assertEqual(match.player(2).base_hp, 19)

    def test_haste_2(self) -> None:
        """Things do NOT need haste to become exhausted as the result of
        an effect. For example, you can play a unit then immediately
        exhaust it with Boot Camp because the exhaust is an effect there,
        not a cost."""
        engine, game, match = fresh()
        card = put(match, 1, "timely_messenger", arrived=True, exhausted=True)
        # Being exhausted is not what haste answers: an exhausted card may
        # not attack, hasted or not. The effects that exhaust come in
        # step 6.
        self.assertTrue(engine.has_keyword(card, "Haste"))
        self.assertFalse(engine.may_attack_with(card))
        self.assertNotIn(card.ref, engine.patrol_candidates(match))


class FrenzyTests(KeywordCase):
    def test_frenzy_x_1(self) -> None:
        """It loses the extra ATK at the end of the turn."""
        engine, game, match = fresh()
        ninja = put(match, 1, "fruit_ninja").ref
        self.assertEqual(engine.attack_value(match, 1, ninja), 3)
        match.active = 2
        self.assertEqual(engine.attack_value(match, 1, ninja), 2)

    def test_frenzy_x_2(self) -> None:
        """This does stack, so if one of your units gets frenzy 1 twice,
        it gets +2 ATK on your turn."""
        self.assertIn("Frenzy", keywords.STACKING)
        with printed(fruit_ninja=(("Frenzy", 1), ("Frenzy", 1))):
            engine, game, match = fresh()
            ninja = put(match, 1, "fruit_ninja").ref
            self.assertEqual(engine.attack_value(match, 1, ninja), 4)


class HealingTests(KeywordCase):
    def test_healing_x_1(self) -> None:
        """Damage is always recorded on an object in the form of damage
        chits. Healing is able to remove those damage chits. Healing is
        not able to increase the maximum HP of something. Healing does not
        interact with -1/-1 runes, either."""
        engine, game, match = fresh()
        put(match, 1, "helpful_turtle")
        hurt = put(match, 1, "iron_man", damage=2)
        withered = put(match, 1, "older_brother")
        withered.minus_runes = 1
        hero_in_play(match, 1, damage=1)
        self.assertEqual(engine.healing(match.player(1)), 1)
        match.active = 2
        match.enter_phase("ready")
        match.player(2).tech_owed = False
        turn.begin_turn(engine, game, match)
        self.assertEqual(hurt.damage, 2, "it heals at its controller's upkeep")
        match.active = 1
        match.enter_phase("ready")
        turn.begin_turn(engine, game, match)
        self.assertEqual(hurt.damage, 1)
        self.assertEqual(match.player(1).hero.damage, 0)
        self.assertEqual(withered.minus_runes, 1, "a rune is not damage")
        self.assertEqual(engine.unit_stats(withered), (1, 1))


class ResistTests(KeywordCase):
    def test_resist_x_1(self) -> None:
        """This has nothing to do with attacking. Opponents don't have to
        pay to attack something with resist, they only have to pay to
        target it with spells or abilities."""
        engine, game, match = fresh()
        iron = put(match, 1, "iron_man").ref
        thief = put(match, 2, "brick_thief", patrol="squad_leader").ref
        self.assertEqual(engine.resist_cost(match, 2, thief), 1)
        match.player(1).gold = 0
        self.assertEqual(engine.legal_defenders(match, iron), (thief,))
        self.attack(engine, game, match, iron, thief)
        self.assertEqual(match.player(1).gold, 0)
        self.assertIn("brick_thief", match.player(2).discard)

    def test_resist_x_2(self) -> None:
        """This does stack, so if one of your units gets resist 1 twice,
        opponents must pay 2 gold to target it with spells or abilities."""
        self.assertIn("Resist", keywords.STACKING)
        engine, game, match = fresh()
        # Brick Thief's own resist 1, and the lookout slot's.
        thief = put(match, 2, "brick_thief", patrol="lookout").ref
        plain = put(match, 2, "tenderfoot", patrol="lookout")
        self.assertEqual(engine.resist_cost(match, 2, thief), 2)
        plain.patrol_slot = "elite"
        self.assertEqual(engine.resist_cost(match, 2, plain.ref), 0)


# -- The detection action, and the ratchet over the rulings -------------------


class DetectActionTests(KeywordCase):
    def test_the_tower_detects_on_its_owners_turn(self) -> None:
        """A tower's owner names one hidden card on their own turn, which
        is then visible for the rest of it (UMR p. 9)."""
        engine, game, match = fresh()
        standing = tower(match, 1)
        iron = put(match, 1, "iron_man").ref
        sneak = put(match, 2, "backstabber").ref
        self.assertFalse(engine.may_be_attacked(match, iron, sneak))
        option = engine.detect_option(match)
        self.assertTrue(option.allowed)
        self.assertEqual(option.candidates, (sneak,))
        actions.detect(engine, game, match, sneak)
        self.assertEqual(standing.detected, sneak)
        self.assertTrue(engine.may_be_attacked(match, iron, sneak))
        self.assertIn("has detected this turn", engine.detect_option(match).why_not)

    def test_without_a_tower_there_is_nothing_to_detect_with(self) -> None:
        engine, game, match = fresh()
        put(match, 2, "backstabber")
        option = engine.detect_option(match)
        self.assertFalse(option.tower)
        self.assertIn("no finished tower", option.why_not)


class AttackChoiceTests(KeywordCase):
    """The three questions an attack asks inside itself, each asked only
    where there is something to choose."""

    def test_obliterate_asks_on_a_tie_and_the_defender_is_chosen_again(self) -> None:
        engine, game, match = fresh()
        duck = put(match, 1, "trojan_duck").ref
        first = put(match, 2, "tenderfoot", patrol="squad_leader").ref
        second = put(match, 2, "older_brother").ref
        put(match, 2, "iron_man")
        result = self.attack(engine, game, match, duck, first)
        asked = pending_prompt(engine, game, match)
        self.assertIs(asked.kind, PromptKind.OBLITERATE_CHOICE)
        self.assertEqual(set(asked.options.units), {first, second})
        combat.choose_obliterate(engine, game, match, first)
        asked = pending_prompt(engine, game, match)
        self.assertIs(asked.kind, PromptKind.CHOOSE_DEFENDER,
                      "obliterate took the defender, so another is chosen")
        combat.declare_attack(engine, game, match, duck, "base")
        # Its attacks trigger, before the damage (step 6): 4 to a building,
        # either side's, so it is asked.
        asked = pending_prompt(engine, game, match)
        self.assertIs(asked.kind, PromptKind.TARGET)
        from codex.flow import resolve
        resolve.choose_target(engine, game, match, "2:base")
        self.assertEqual(match.player(2).base_hp, 20 - 4 - 8)
        self.assertIsNone(match.combat)

    def test_sparkshot_asks_only_between_two_neighbours(self) -> None:
        engine, game, match = fresh()
        ocelot = put(match, 1, "revolver_ocelot").ref
        left = put(match, 2, "tenderfoot", patrol="elite").ref
        middle = put(match, 2, "iron_man", patrol="scavenger").ref
        right = put(match, 2, "older_brother", patrol="technician").ref
        self.attack(engine, game, match, ocelot, middle)
        asked = pending_prompt(engine, game, match)
        self.assertIs(asked.kind, PromptKind.SPARKSHOT_TARGET)
        self.assertEqual(set(asked.options.patrollers), {left, right})
        combat.choose_sparkshot(engine, game, match, right)
        self.assertEqual(self.damage(match, 2, right), 1)
        self.assertEqual(self.damage(match, 2, left), 0)

    def test_overpower_asks_only_between_two_targets(self) -> None:
        engine, game, match = fresh()
        reaper = put(match, 1, "harvest_reaper").ref
        leader = put(match, 2, "tenderfoot", patrol="squad_leader").ref
        one = put(match, 2, "regularsized_rhinoceros", patrol="elite").ref
        two = put(match, 2, "iron_man", patrol="scavenger").ref
        self.attack(engine, game, match, reaper, leader)
        asked = pending_prompt(engine, game, match)
        self.assertIs(asked.kind, PromptKind.OVERPOWER_TARGET)
        self.assertEqual(asked.options.excess, 4)
        self.assertEqual(set(asked.options.targets), {one, two})
        combat.choose_overpower(engine, game, match, one)
        self.assertEqual(self.damage(match, 2, one), 4)

    def test_an_attack_that_has_begun_cannot_be_taken_back(self) -> None:
        engine, game, match = fresh()
        duck = put(match, 1, "trojan_duck").ref
        put(match, 2, "tenderfoot", patrol="squad_leader")
        put(match, 2, "older_brother")
        match.attacking = duck
        combat.declare_attack(engine, game, match, duck, "unit:2")
        with self.assertRaises(Exception):
            actions.cancel_attack(engine, game, match)


class HeroesHallTests(KeywordCase):
    """The heroes' hall (UMR p. 9) -- a standard game's add-on, whose
    rulings are the one reading of the hero limit (`RulesEngine.hero_limit`)."""

    RED = ("fire", "anarchy", "blood")
    GREEN = ("feral", "growth", "balance")

    def standard(self):
        engine, game, match = new_game(teams=(self.RED, self.GREEN))
        begin(engine, game, match)
        return engine, game, match

    def test_heroes_hall_1(self) -> None:
        """Heroes' Hall only does anything when you want to play a hero.
        You can determine how many heroes you can play like so: - If you
        have an active Tech 3 building, or you have an active Tech 2
        building and an active Heroes' Hall, you can play all 3 heroes. -
        If you have an active Tech 2 building or an active Heroes' Hall,
        you can play 2 heroes. - Otherwise, you can play only 1 hero."""
        engine, game, match = self.standard()
        player = match.player(1)
        self.assertEqual(engine.hero_limit(player), 1)
        hall = AddOnState(slug="heroes_hall", hp=4, under_construction=True)
        player.add_on = hall
        self.assertEqual(engine.hero_limit(player), 1, "a hall under construction is not active")
        hall.under_construction = False
        self.assertEqual(engine.hero_limit(player), 2)
        player.add_on = None
        built(match, 1, "tech1")
        tech2 = built(match, 1, "tech2")
        self.assertEqual(engine.hero_limit(player), 2)
        player.add_on = hall
        self.assertEqual(engine.hero_limit(player), 3)
        player.add_on = None
        built(match, 1, "tech3")
        self.assertEqual(engine.hero_limit(player), 3)
        tech2.destroyed = True
        self.assertEqual(engine.hero_limit(player), 3, "an active Tech 3 is enough")
        match.player(1).buildings["tech3"].destroyed = True
        self.assertEqual(engine.hero_limit(player), 1)

    def test_heroes_hall_2(self) -> None:
        """Losing Heroes' Hall won't cause any of your heroes to leave
        play."""
        engine, game, match = self.standard()
        player = match.player(1)
        player.add_on = AddOnState(slug="heroes_hall", hp=1, under_construction=False)
        hero_in_play(match, 1, slug="jaina_stormborne")
        hero_in_play(match, 1, slug="captain_zane")
        put(match, 2, "iron_man")
        board.damage_building(match, 1, "add_on", 1, StepResult())
        self.assertIsNone(player.add_on)
        board.settle(engine, match, StepResult())
        self.assertEqual(len(player.heroes_in_play), 2)
        self.assertEqual(engine.hero_limit(player), 1)
        option = engine.hero_option(player, player.hero_of("drakk_ramhorn"))
        self.assertIn("hero limit is 1", option.why_not)


class TechLabTests(KeywordCase):
    """The tech lab (UMR p. 9): a second spec's tech II and III cards."""

    RED = ("fire", "anarchy", "blood")
    GREEN = ("feral", "growth", "balance")

    def standard(self):
        engine, game, match = new_game(teams=(self.RED, self.GREEN))
        begin(engine, game, match)
        player = match.player(1)
        player.gold, player.workers = 20, 10
        return engine, game, match, player

    def build(self, engine, game, match, building, **arguments):
        return actions.construct(engine, game, match, building, **arguments)

    def test_tech_lab_1(self) -> None:
        """If you choose one spec for your Tech Lab, you can build another
        Tech Lab later and choose a different spec."""
        engine, game, match, player = self.standard()
        built(match, 1, "tech1")
        built(match, 1, "tech2")
        player.tech2_spec = "fire"
        self.build(engine, game, match, "tech_lab", spec="anarchy")
        player.add_on.under_construction = False
        self.assertEqual(engine.chosen_specs(player), ("fire", "anarchy"))
        board.damage_building(match, 1, "add_on", 4, StepResult())
        self.build(engine, game, match, "tech_lab", spec="blood")
        player.add_on.under_construction = False
        self.assertEqual(engine.chosen_specs(player), ("fire", "blood"))

    def test_tech_lab_2(self) -> None:
        """If you have a Tech Lab but have not built a Tech 2 building, you
        do not choose a spec for your Tech Lab. Later when you build your
        Tech 2 building, you will choose the spec for the Tech 2 building
        and for the Tech Lab."""
        engine, game, match, player = self.standard()
        self.assertEqual(engine.build_option(player, "tech_lab").specs, ())
        with self.assertRaises(RuleRefusal):
            self.build(engine, game, match, "tech_lab", spec="fire")
        self.build(engine, game, match, "tech_lab")
        self.assertIsNone(player.add_on.spec)
        player.add_on.under_construction = False
        built(match, 1, "tech1")
        option = engine.build_option(player, "tech2")
        self.assertEqual((option.specs, option.lab_specs), (self.RED, self.RED))
        with self.assertRaises(RuleRefusal):
            self.build(engine, game, match, "tech2", spec="fire", lab_spec="fire")
        self.build(engine, game, match, "tech2", spec="fire", lab_spec="blood")
        self.assertEqual((player.tech2_spec, player.add_on.spec), ("fire", "blood"))


# -- Red and green's keywords (step 11) -------------------------------------


class DeathtouchTests(KeywordCase):
    def test_deathtouch_1(self) -> None:
        """Anything that checks for "dying from combat damage" such as
        Brave Knight or Gilded Glaxx does "die from combat damage" if
        deathtouch hits it."""
        engine, game, match = fresh()
        basilisk = put(match, 1, "tiny_basilisk").ref
        guard = put(match, 2, "older_brother", patrol="squad_leader")
        guard.armor = 1
        result = self.attack(engine, game, match, basilisk, guard.ref)
        # The squad leader's armor took the 1, and it is destroyed by the
        # combat all the same -- a death in combat, its 2 back included.
        self.assertIsNone(match.player(2).instance(guard.id))
        self.assertIsNone(match.player(1).instance(int(basilisk.split(":")[1])))
        self.assertIn("armor takes 1", said(result))

    def test_deathtouch_2(self) -> None:
        """Deathtouch does not stack. Having two instances of deathtouch is
        the same as having just one."""
        self.assertNotIn("Deathtouch", keywords.STACKING)
        with printed(tiny_basilisk=(("Deathtouch", None), ("Deathtouch", None))):
            engine, game, match = fresh()
            basilisk = put(match, 1, "tiny_basilisk")
            self.assertEqual(engine.keyword_x(basilisk, "Deathtouch", match), 1)
            target = put(match, 2, "iron_man")
            self.assertEqual(engine.lethal_damage(match, 1, basilisk.ref, target), 1)

    def test_deathtouch_kills_nothing_that_is_a_building(self) -> None:
        """"This doesn't affect buildings" (UMR p. 16)."""
        engine, game, match = fresh()
        basilisk = put(match, 1, "tiny_basilisk").ref
        self.attack(engine, game, match, basilisk, "base")
        self.assertEqual(match.player(2).base_hp, 19)


class LongRangeTests(KeywordCase):
    def test_longrange_1(self) -> None:
        """Long-range does not prevent anti-air patrollers that the
        attacker flies over from dealing damage."""
        with printed(eggship=(("Flying", None), ("Long-range", None))):
            engine, game, match = fresh()
            ship = put(match, 1, "eggship").ref
            put(match, 2, "leaping_lizard", patrol="squad_leader")
            result = self.attack(engine, game, match, ship, "base")
            self.assertIn("with anti-air, deals", said(result))

    def test_longrange_2(self) -> None:
        """Long-range does not prevent towers from dealing damage."""
        engine, game, match = fresh()
        archer = put(match, 1, "doubleshot_archer").ref
        tower(match, 2)
        guard = put(match, 2, "iron_man").ref
        # The defender deals nothing back...
        self.assertEqual(engine.damage_back(match, archer, guard), 0)
        self.attack(engine, game, match, archer, guard)
        # ... and the tower still deals its 1.
        self.assertEqual(self.damage(match, 1, archer), 1)
        self.assertIsNone(engine.body(match, 2, guard))

    def test_a_defender_with_long_range_deals_back(self) -> None:
        engine, game, match = fresh()
        archer = put(match, 1, "doubleshot_archer").ref
        other = put(match, 2, "doubleshot_archer").ref
        self.assertEqual(engine.damage_back(match, archer, other), 4)


class EphemeralTests(KeywordCase):
    def test_ephemeral_1(self) -> None:
        """Ephemeral triggers at the end of each player's turn."""
        engine, game, match = fresh()
        mine = put(match, 1, "crashbarrow")
        theirs = put(match, 2, "shoddy_glider")
        result = StepResult()
        turn.end_of_turn(engine, match, result)
        self.assertIsNone(match.player(1).instance(mine.id))
        self.assertIsNone(match.player(2).instance(theirs.id))
        self.assertEqual(match.player(1).discard[-1], "crashbarrow")


class UntargetableTests(KeywordCase):
    def test_untargetable_1(self) -> None:
        """Something that's untargetable still CAN be attacked. It can even
        be affected by some spells and abilities, but NOT spells or
        abilities that use the [target] symbol."""
        engine, game, match = fresh()
        attacker = put(match, 1, "iron_man").ref
        ancient = put(match, 2, "moss_ancient").ref
        self.assertIn(ancient, engine.legal_defenders(match, attacker))
        from codex import effects

        spark = effects.EFFECTS["spark"].parts[0]
        put(match, 2, "older_brother", patrol="elite")
        match.player(2).instance(int(ancient.split(":")[1])).patrol_slot = "squad_leader"
        offered = {row.ref for row in engine.target_rows(match, 1, spark)}
        self.assertNotIn(ancient, offered, "Spark has the target symbol")
        self.assertTrue(offered, "the other patroller may still be chosen")
        # Its own controller may not target it either.
        self.assertNotIn(ancient, {row.ref for row in engine.target_rows(match, 2, spark)})


class BoostTests(KeywordCase):
    def test_boost_x_1(self) -> None:
        """If something has you "put a unit into play," that's different
        from "playing it" so you can't pay for or use a boost effect in that
        case. Likewise, if a unit with a boost enters play through any
        means other than playing it (such as being returned from Second
        Chances or Geiger or Pasternaak's max level abilities) then you
        can't use its boost."""
        engine, game, match = fresh(teams=(("anarchy",), ("growth",)))
        house = put(match, 1, "sanatorium")
        match.player(1).hand = ["marauder"]
        match.player(1).gold = 10
        workers = (match.player(1).workers, match.player(2).workers)
        driver.apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "ability",
                                                 {"ability": "sanatorium", "source": house.ref}))
        run = driver.apply(engine, game, match, Action(PromptKind.TARGET, "", {"target": "1:hand:marauder"}))
        self.assertNotIsInstance(run, driver.Refusal)
        self.assertEqual(match.player(1).gold, 9, "only the ability's gold")
        self.assertEqual((match.player(1).workers, match.player(2).workers), workers)

    def test_boost_x_2(self) -> None:
        """Using Graveyard, Jurisdiction, and Vir Garbarean you can "play" a
        card from a zone other than your hand. You can still use boost when
        playing a card this way."""
        engine, game, match = fresh(teams=(("feral",), ("anarchy",)))
        # Red and green play only from the hand: boosting is part of the
        # play itself, offered with its cost on the hand's row.
        hero_in_play(match, 1)
        match.player(1).hero.level = 5
        match.player(1).hero.max_level_since_turn_began = True
        match.player(1).hand = ["feral_strike"]
        match.player(1).gold = 8
        row = engine.playable(match.player(1), match)[0]
        self.assertEqual((row.cost, row.boost, row.boostable), (4, 4, True))
        driver.apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "play",
                                                 {"slug": "feral_strike", "boost": True}))
        self.assertEqual(match.player(1).gold, 0)
        self.assertIsNot(pending_prompt(engine, game, match).kind, PromptKind.MODE_CHOICE,
                         "boosted: both, nothing asked")

    def test_boost_x_3(self) -> None:
        """If an opponent has Jail and you play a unit with a boost, you CAN
        pay for and use the boost. You do that immediately as you play the
        unit from your hand, then the boost effect happens and your unit
        goes to Jail. When it leaves Jail and arrives in play, you do not
        have a chance to pay for or use the boost a second time."""
        engine, game, match = fresh(teams=(("anarchy",), ("growth",)))
        built(match, 1, "tech1")
        built(match, 1, "tech2")
        match.player(1).hand = ["marauder"]
        match.player(1).gold = 6
        workers = match.player(2).workers
        driver.apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "play",
                                                 {"slug": "marauder", "boost": True}))
        driver.apply(engine, game, match, Action(PromptKind.TARGET, "", {"target": "2:workers"}))
        self.assertEqual(match.player(2).workers, workers - 1)
        # Back to the hand and in again, unplayed: no second boost.
        marauder = next(card for card in match.player(1).play if card.slug == "marauder")
        board.leave_play(engine, match, marauder, "hand")
        match.player(1).hand.remove("marauder")
        board.put_into_play(engine, match, "marauder", 1, from_hand=True)
        self.assertEqual(match.resolving[-1].get("boosted"), None)


class ChannellingTests(KeywordCase):
    def test_channelling_1(self) -> None:
        """If at any moment you don't control the correct hero for a
        channeling spell, you sacrifice the channeling spell."""
        engine, game, match = fresh(teams=(("blood",), ("feral",)))
        drums = put(match, 1, "war_drums")
        match.active = 2
        ferns = put(match, 2, "behind_the_ferns")
        hero_in_play(match, 1)
        board.settle(engine, match, StepResult())
        self.assertIsNotNone(match.player(1).instance(drums.id))
        self.assertIsNone(match.player(2).instance(ferns.id), "no Feral hero in play")
        match.player(1).hero.zone = "command"
        board.settle(engine, match, StepResult())
        self.assertIsNone(match.player(1).instance(drums.id))
        self.assertIn("war_drums", match.player(1).discard)


class LimitTests(KeywordCase):
    """Harmony's Dancers are the one token of red, green and the basic set
    with a limit (docs/design/codex.md, "Red and green")."""

    def setUp(self) -> None:
        from test_codex_card_rulings import finesse
        self.engine, self.game, self.match = finesse()
        hero_in_play(self.match, 2)
        put(self.match, 2, "harmony")

    def spell(self) -> None:
        from test_codex_card_rulings import cast
        put(self.match, 1, "older_brother", patrol="elite")
        cast(self.engine, self.game, self.match, "spark")

    def dancers(self, seat: int = 2) -> list:
        return [card for card in self.match.player(seat).play
                if card.slug in ("dancer", "angry_dancer")]

    def test_limit_x_1(self) -> None:
        """Limit: X is a rule that applies to some kinds of tokens. It means
        "If summoning the number of tokens indicated by an ability would
        cause you to have X or more of that kind of token in play, instead
        only summon enough tokens to bring your number of copies of that
        token up to X.\" """
        put(self.match, 2, "dancer")
        put(self.match, 2, "angry_dancer")
        self.spell()
        self.assertEqual(len(self.dancers()), 3)
        self.match.player(2).gold = 20
        self.match.player(1).play[:] = [
            card for card in self.match.player(1).play if card.slug != "older_brother"
        ]
        self.spell()
        self.assertEqual(len(self.dancers()), 3, "three is Harmony's limit")

    def test_limit_x_2(self) -> None:
        """You might still end up having more than X of a token in play, for
        example if you steal them from your opponent."""
        for _ in range(3):
            put(self.match, 2, "dancer")
        stolen = put(self.match, 1, "dancer")
        board.gain_control(self.match, stolen, 2)
        self.assertEqual(len(self.dancers()), 4)
        self.spell()
        self.assertEqual(len(self.dancers()), 4, "none summoned past the limit, none lost")

    def test_limit_x_3(self) -> None:
        """When a card specifies that Limit: X applies to one way of creating
        tokens, that limit applies to all ways of creating that kind of
        token in the whole game."""
        # Harmony is the only way red, green and the basic set make a
        # Dancer, so the limit is counted where every Dancer comes from:
        # the Dancers in play, whatever summoned them.
        for _ in range(3):
            put(self.match, 2, "dancer")
        self.spell()
        self.assertEqual(len(self.dancers()), 3)

    def test_limit_x_4(self) -> None:
        """Limit: X on some kind of token applies to things that are that
        token before considering copy effects or Polymorph: Squirrel."""
        for _ in range(3):
            put(self.match, 2, "dancer")
        self.dancers()[0].printed = {"polymorph": 1}
        self.spell()
        self.assertEqual(len(self.dancers()), 3, "the Squirrel is still a Dancer")


class ConditionedKeywordTests(KeywordCase):
    """The keywords a red or green card has only while the position says
    so (docs/design/codex.md, "Red and green")."""

    def test_tiny_basilisk_is_unattackable_and_unstoppable_by_tech_0(self) -> None:
        engine, game, match = fresh()
        basilisk = put(match, 2, "tiny_basilisk").ref
        tenderfoot = put(match, 1, "tenderfoot").ref
        self.assertNotIn(basilisk, engine.legal_defenders(match, tenderfoot))
        match.active = 2
        put(match, 1, "older_brother", patrol="squad_leader")
        self.assertIn("base", engine.legal_defenders(match, basilisk))

    def test_predator_tiger_ignores_tech_0_patrollers_only(self) -> None:
        engine, game, match = fresh()
        tiger = put(match, 1, "predator_tiger").ref
        put(match, 2, "older_brother", patrol="squad_leader")
        self.assertIn("base", engine.legal_defenders(match, tiger))
        guard = put(match, 2, "huntress", patrol="elite").ref
        self.assertEqual(engine.legal_defenders(match, tiger), (guard,))

    def test_stalking_tiger_sneaks_to_a_unit_and_is_invisible_with_a_feral_hero(self) -> None:
        engine, game, match = fresh(teams=(("feral",), ("finesse",)))
        tiger = put(match, 1, "stalking_tiger")
        leader = put(match, 2, "older_brother", patrol="squad_leader").ref
        lying = put(match, 2, "tenderfoot").ref
        defenders = engine.legal_defenders(match, tiger.ref)
        self.assertIn(leader, defenders)
        self.assertIn(lying, defenders, "stealth while attacking a unit")
        self.assertNotIn("base", defenders)
        self.assertFalse(engine.has_keyword(tiger, "Invisible", match))
        hero_in_play(match, 1)
        self.assertTrue(engine.has_keyword(tiger, "Invisible", match))

    def test_cant_attack_and_cant_patrol(self) -> None:
        engine, game, match = fresh()
        treant = put(match, 1, "young_treant").ref
        owl = put(match, 1, "gemscout_owl")
        ram = put(match, 1, "makeshift_rambaster").ref
        self.assertTrue(engine.has_keyword(owl, "Flying", match))
        self.assertEqual(engine.attackers(match), (ram,))
        self.assertNotIn(ram, engine.patrol_candidates(match))
        self.assertIn(treant, engine.patrol_candidates(match))

    def test_bonus_when_attacking_buildings(self) -> None:
        engine, game, match = fresh()
        tank = put(match, 1, "steam_tank").ref
        self.attack(engine, game, match, tank, "base")
        self.assertEqual(match.player(2).base_hp, 13)
        unit = put(match, 2, "iron_man").ref
        self.assertEqual(engine.attack_value(match, 1, tank, against=unit), 3)

    def test_ironbark_treant_on_the_opponents_turn_while_patrolling(self) -> None:
        """He's a 3/2 on your turn. The -2 ATK / +2 armor only happens on
        opponents turns and only while he's in your patrol zone."""
        engine, game, match = fresh()
        treant = put(match, 2, "ironbark_treant", patrol="squad_leader")
        self.assertEqual(engine.unit_stats(treant, match), (1, 2))
        match.active = 2
        self.assertEqual(engine.unit_stats(treant, match), (3, 2))

    def test_rampaging_elephant_readies_the_first_time(self) -> None:
        engine, game, match = fresh()
        elephant = put(match, 1, "rampaging_elephant")
        self.attack(engine, game, match, elephant.ref, "base")
        self.assertFalse(elephant.exhausted)
        self.assertIn(elephant.ref, engine.attackers(match))
        self.attack(engine, game, match, elephant.ref, "base")
        self.assertTrue(elephant.exhausted)
        self.assertEqual(match.player(2).base_hp, 8)

    def test_wandering_mimic_copies_what_is_in_play_and_never_another_mimic(self) -> None:
        """If you have two Mimics that have flying because a THIRD unit
        has flying, but then that third unit dies, both your Mimics lose
        flying."""
        engine, game, match = fresh()
        first = put(match, 1, "wandering_mimic")
        second = put(match, 2, "wandering_mimic")
        ship = put(match, 2, "eggship")
        self.assertTrue(engine.has_keyword(first, "Flying", match))
        self.assertTrue(engine.has_keyword(second, "Flying", match))
        match.player(2).play.remove(ship)
        self.assertFalse(engine.has_keyword(first, "Flying", match))
        self.assertFalse(engine.has_keyword(second, "Flying", match))

    def test_midori_flies_on_his_own_turn_at_8(self) -> None:
        engine, game, match = fresh(teams=(("balance",), ("finesse",)))
        hero_in_play(match, 1, level=8)
        midori = match.player(1).hero
        self.assertTrue(engine.has_keyword(midori, "Flying", match))
        match.active = 2
        self.assertFalse(engine.has_keyword(midori, "Flying", match))

    def test_a_second_legendary_copy_is_destroyed(self) -> None:
        engine, game, match = fresh()
        first = put(match, 1, "galina_glimmer")
        second = put(match, 1, "galina_glimmer")
        theirs = put(match, 2, "galina_glimmer")
        board.settle(engine, match, StepResult())
        self.assertIsNotNone(match.player(1).instance(first.id))
        self.assertIsNone(match.player(1).instance(second.id))
        self.assertIsNotNone(match.player(2).instance(theirs.id))


# -- Purple and black's keywords (step 12) ----------------------------------------

PURPLE_BLACK = (("past", "present", "future"), ("demonology", "disease", "necromancy"))


def purple_black(seed: int = 7):
    """A standard game of three purple heroes (seat 1) against three
    black, standing in seat 1's main phase."""
    return fresh(seed=seed, teams=PURPLE_BLACK)


def apply_ok(engine, game, match, kind, choice="", **arguments):
    run = driver.apply(engine, game, match, Action(kind, choice, arguments))
    assert not isinstance(run, driver.Refusal), run
    return run


def next_upkeep(engine, game, match, seat: int) -> None:
    """Run turns -- nothing played, nothing patrolling -- until `seat`'s
    main phase opens again."""
    for _ in range(6):
        if match.active == seat and match.phase == "main" and not match.resolving:
            return
        prompt = pending_prompt(engine, game, match)
        if prompt is None:
            begin(engine, game, match)
            continue
        if prompt.kind is PromptKind.MAIN_ACTION:
            apply_ok(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        elif prompt.kind is PromptKind.PATROL:
            apply_ok(engine, game, match, PromptKind.PATROL, assignment={})
        elif prompt.kind is PromptKind.TECH_CHOICE:
            apply_ok(engine, game, match, PromptKind.TECH_CHOICE,
                     player=prompt.asked_player, picks=list(_picks(prompt.options)))
        elif prompt.kind is PromptKind.TECH_CONFIRM:
            apply_ok(engine, game, match, PromptKind.TECH_CONFIRM, "confirm",
                     player=prompt.asked_player)
        else:
            raise AssertionError(prompt.kind)
        begin(engine, game, match)
        for standing in __import__("codex.prompts", fromlist=["standing_prompts"]).standing_prompts(
            engine, match, game,
        ):
            if match.player(standing.asked_player).tech_choice is None:
                apply_ok(engine, game, match, PromptKind.TECH_CHOICE,
                         player=standing.asked_player, picks=list(_picks(standing.options)))
    raise AssertionError("the turn did not come round")


def _picks(options):
    picks = []
    for slug, count in options.codex:
        for _ in range(count):
            if len(picks) < options.minimum:
                picks.append(slug)
    return picks


class FadingTests(KeywordCase):
    def test_fading_x_1(self) -> None:
        """If you remove the last time rune for some other reason than the
        fading ability, such as from Time Spiral, Seer, or Tinkerer, you
        still must sacrifice the fading thing."""
        engine, game, match = purple_black()
        argonaut = put(match, 1, "fading_argonaut")
        argonaut.time_runes = 1
        match.player(1).hand = ["time_spiral"]
        match.player(1).gold = 5
        hero_in_play(match, 1)
        apply_ok(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="time_spiral")
        prompt = pending_prompt(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.MODE_CHOICE)
        apply_ok(engine, game, match, PromptKind.MODE_CHOICE, mode="remove")
        self.assertIsNone(match.player(1).instance(argonaut.id))
        self.assertIn("fading_argonaut", match.player(1).discard)

    def test_fading_x_2(self) -> None:
        """If you somehow have something with fading in play with 0 time
        runes (probably because you made a copy of something if fading),
        it won't die from fading anymore."""
        engine, game, match = purple_black()
        argonaut = put(match, 1, "fading_argonaut")
        self.assertEqual(argonaut.time_runes, 0)
        self.assertNotIn(f"fade:{argonaut.id}", engine.upkeep_effects(match.player(1)))
        next_upkeep(engine, game, match, 1)
        next_upkeep(engine, game, match, 2)
        next_upkeep(engine, game, match, 1)
        self.assertIsNotNone(match.player(1).instance(argonaut.id))

    def test_fading_x_3(self) -> None:
        """X is not a limit to the number of time runes you can have on
        that card. For example, you can play Shimmer Ray and discard 4
        cards so that it has 6 time runes; you're not limited to 2 total."""
        engine, game, match = purple_black()
        built(match, 1, "tech1")
        built(match, 1, "tech2")
        match.player(1).tech2_spec = "past"
        match.player(1).gold = 5
        match.player(1).hand = ["shimmer_ray", "neo_plexus", "neo_plexus", "neo_plexus", "neo_plexus"]
        apply_ok(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="shimmer_ray")
        ray = next(card for card in match.player(1).play if card.slug == "shimmer_ray")
        self.assertEqual(ray.time_runes, 2)
        for _ in range(4):
            apply_ok(engine, game, match, PromptKind.MAIN_ACTION, "ability",
                     ability="shimmer_ray", source=ray.ref)
        self.assertEqual(ray.time_runes, 6)
        self.assertEqual(match.player(1).hand, [])

    def test_fading_counts_down_at_its_controllers_upkeep(self) -> None:
        """Fading X (UMR p. 17): a rune off at each of its controller's
        upkeeps, sacrificed as the last goes."""
        engine, game, match = purple_black()
        built(match, 1, "tech1")
        match.player(1).gold = 5
        match.player(1).hand = ["fading_argonaut"]
        apply_ok(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="fading_argonaut")
        argonaut = match.player(1).play[-1]
        self.assertEqual(argonaut.time_runes, 3)
        next_upkeep(engine, game, match, 2)
        self.assertEqual(argonaut.time_runes, 3, "not at the opponent's upkeep")
        for left in (2, 1):
            next_upkeep(engine, game, match, 1)
            self.assertEqual(argonaut.time_runes, left)
            next_upkeep(engine, game, match, 2)
        next_upkeep(engine, game, match, 1)
        self.assertIsNone(match.player(1).instance(argonaut.id))


class ForecastTests(KeywordCase):
    def test_forecast_x_1(self) -> None:
        """When it would come into play from something other than
        forecast, instead it goes to the "future" zone and gets time
        runes."""
        engine, game, match = purple_black()
        result = StepResult()
        self.assertIsNone(board.put_into_play(engine, match, "plasmodium", 1, from_hand=False))
        future = match.player(1).future
        self.assertEqual([(card.slug, card.time_runes) for card in future], [("plasmodium", 3)])
        self.assertFalse(any(card.slug == "plasmodium" for card in match.player(1).play))
        del result

    def test_forecast_x_2(self) -> None:
        """To play a forecasted thing from your hand, you must meet the
        requirements to play it, like any card. You do NOT need to meet
        any requirements when it later arrives / resolves. For example,
        playing a forecasted Future tech II unit requires a Future tech II
        building, then the forecasted unit goes to the future, and if your
        Future tech II building is destroyed before the time runes are all
        removed, that's fine, the Future tech II unit will still arrive
        when the last time rune is removed."""
        engine, game, match = purple_black()
        player = match.player(1)
        player.gold = 10
        player.hand = ["reaver"]
        self.assertIn("Tech II", engine.why_not_playable(player, "reaver"))
        built(match, 1, "tech1")
        tech2 = built(match, 1, "tech2")
        player.tech2_spec = "future"
        apply_ok(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="reaver")
        self.assertEqual([card.slug for card in player.future], ["reaver"])
        self.assertEqual(player.gold, 10 - 3)
        tech2.destroyed = True
        next_upkeep(engine, game, match, 2)
        next_upkeep(engine, game, match, 1)
        self.assertEqual(player.future[0].time_runes, 1)
        next_upkeep(engine, game, match, 2)
        next_upkeep(engine, game, match, 1)
        self.assertEqual(player.future, [])
        reaver = next(card for card in player.play if card.slug == "reaver")
        self.assertTrue(reaver.arrived_this_turn, "it arrives with arrival fatigue")

    def test_forecast_x_3(self) -> None:
        """Forecasted units do not go to Jail."""
        # Jail is the Flagstone Dominion's (step 13): what this pins today
        # is the ground the ruling stands on -- a card in the future is not
        # in play, so nothing in play reaches it.
        engine, game, match = purple_black()
        board.to_future(engine, match, "plasmodium", 2)
        card = match.player(2).future[0]
        self.assertIsNone(engine.body(match, 2, f"future:{card.id}"))
        self.assertNotIn(card, list(match.instances()))
        self.assertFalse(engine.legal_defenders(match, put(match, 1, "neo_plexus").ref).count(
            f"future:{card.id}"))

    def test_a_forecast_unit_arrives_with_its_trigger(self) -> None:
        """Forecast X (UMR p. 17): "Forecast cards resolve arrival effects
        and have arrival fatigue on the turn they arrive from the future" --
        Plasmodium's haste lets it attack at once."""
        engine, game, match = purple_black()
        player = match.player(1)
        player.gold = 5
        player.hand = ["plasmodium"]
        apply_ok(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="plasmodium")
        self.assertEqual(player.future[0].time_runes, 3)
        for _ in range(3):
            next_upkeep(engine, game, match, 2)
            next_upkeep(engine, game, match, 1)
        plasmodium = next(card for card in player.play if card.slug == "plasmodium")
        self.assertIn(plasmodium.ref, engine.attackers(match))


class IndestructibleTests(KeywordCase):
    def test_indestructible_1(self) -> None:
        """If an indestructible thing has 0 HP because of having -1/-1
        runes, it will remain exhausted forever. If it gets any damage or
        attachments in this state, immediately remove the damage and/or
        attachments."""
        engine, game, match = purple_black()
        mox = put(match, 1, "hardened_mox")
        mox.minus_runes = 1
        result = StepResult()
        board.settle(engine, match, result)
        self.assertIsNotNone(match.player(1).instance(mox.id))
        self.assertTrue(mox.exhausted)
        mox.damage = 2
        board.settle(engine, match, result)
        self.assertEqual(mox.damage, 0)
        next_upkeep(engine, game, match, 2)
        next_upkeep(engine, game, match, 1)
        self.assertTrue(mox.exhausted, "it never readies at 0 HP")

    def test_indestructible_2(self) -> None:
        """Attachments are cards that attach to a unit or hero, like
        "Spirit of the Panda" or "Entangling Vines". Runes and other
        ongoing spells or effects are not attachments."""
        engine, game, match = purple_black()
        immortal = put(match, 2, "immortal")
        immortal.plus_runes = 1
        panda = put(match, 1, "spirit_of_the_panda")
        panda.attached = [immortal.id]
        board.destroy(engine, match, [(2, immortal.ref)], StepResult())
        self.assertIsNotNone(match.player(2).instance(immortal.id))
        self.assertIsNone(match.player(1).instance(panda.id))
        self.assertIn("spirit_of_the_panda", match.player(1).discard)
        self.assertEqual(immortal.plus_runes, 1, "a rune is not an attachment")

    def test_indestructible_3(self) -> None:
        """Even if it has -1/-1 runes that were from something that "dealt
        combat damage in the form of -1/-1 runes," you still don't remove
        them when the indestructible thing would die."""
        engine, game, match = purple_black()
        immortal = put(match, 2, "immortal", damage=4)
        immortal.minus_runes = 1
        board.settle(engine, match, StepResult())
        self.assertIsNotNone(match.player(2).instance(immortal.id))
        self.assertEqual((immortal.damage, immortal.minus_runes), (0, 1))
        self.assertTrue(immortal.exhausted)

    def test_indestructible_4(self) -> None:
        """Some effects like Obliterate, Sacrifice the Weak, and Death Rites
        ask a player to destroy or sacrifice the unit that is the least
        according to some ordering. These effects skip units with
        Indestructible and units that cannot leave play."""
        engine, game, match = purple_black()
        put(match, 2, "hardened_mox")
        plexus = put(match, 2, "neo_plexus")
        self.assertEqual(engine.obliterate_candidates(match), (plexus.ref,))

    def test_an_indestructible_unit_cant_be_sacrificed(self) -> None:
        engine, game, match = purple_black()
        mox = put(match, 1, "hardened_mox")
        self.assertFalse(engine.may_sacrifice(match, mox))
        board.sacrifice(engine, match, mox)
        self.assertIsNotNone(match.player(1).instance(mox.id))


class PurpleBlackStaticKeywordTests(KeywordCase):
    def test_pestering_haunt_is_unstoppable_cant_patrol_and_has_1_atk(self) -> None:
        engine, game, match = purple_black()
        haunt = put(match, 1, "pestering_haunt")
        guard = put(match, 2, "neo_plexus", patrol="squad_leader")
        self.assertIn("base", engine.legal_defenders(match, haunt.ref))
        self.assertNotIn(haunt.ref, engine.patrol_candidates(match))
        haunt.plus_runes = 3
        self.assertEqual(engine.unit_stats(haunt, match)[0], 1)
        self.assertEqual(engine.attack_value(match, 1, haunt.ref), 1)
        del guard

    def test_wight_is_unstoppable_and_deathtouch_against_heroes(self) -> None:
        engine, game, match = purple_black()
        match.active = 2
        wight = put(match, 2, "wight")
        put(match, 1, "argonaut", patrol="squad_leader")
        hero_in_play(match, 1, level=1)
        hero = hero_ref("prynn_pasternaak")
        defenders = engine.legal_defenders(match, wight.ref)
        self.assertIn(hero, defenders)
        self.assertNotIn("base", defenders)
        match.player(1).hero.level = 7
        self.attack(engine, game, match, wight.ref, hero)
        self.assertFalse(match.player(1).hero.in_play, "4 damage on a 3/5 hero, and deathtouch")

    def test_cursed_ghoul_ignores_patrolling_units_with_runes(self) -> None:
        engine, game, match = purple_black()
        match.active = 2
        ghoul = put(match, 2, "cursed_ghoul")
        leader = put(match, 1, "argonaut", patrol="squad_leader")
        self.assertEqual(engine.legal_defenders(match, ghoul.ref), (leader.ref,))
        leader.minus_runes = 1
        self.assertIn("base", engine.legal_defenders(match, ghoul.ref))

    def test_shrines_demons_are_unstoppable_by_units(self) -> None:
        engine, game, match = purple_black()
        match.active = 2
        put(match, 2, "shrine_of_forbidden_knowledge")
        baron = put(match, 2, "twilight_baron")
        put(match, 1, "argonaut", patrol="squad_leader")
        self.assertIn("base", engine.legal_defenders(match, baron.ref))
        hero_in_play(match, 1, patrol="squad_leader")
        match.player(1).play[-1].patrol_slot = None
        self.assertEqual(engine.legal_defenders(match, baron.ref), (hero_ref("prynn_pasternaak"),))

    def test_nullcraft_is_not_the_target_of_buff_or_debuff_spells(self) -> None:
        """Nullcraft: "Can't be the {target} of Buff or Debuff spells." """
        engine, game, match = purple_black()
        craft = put(match, 2, "nullcraft")
        plain = put(match, 2, "neo_plexus")
        from codex import effects

        wither = effects.EFFECTS["wither"].parts[0]
        rows = {row.ref for row in engine.target_rows(match, 1, wither, frame={"spell": "spark"})}
        self.assertIn(craft.ref, rows, "Spark is a Burn spell, neither Buff nor Debuff")
        rows = {row.ref for row in engine.target_rows(match, 1, wither, frame={"spell": "deteriorate"})}
        self.assertNotIn(craft.ref, rows)
        self.assertIn(plain.ref, rows)

    def test_battle_suits_and_lord_of_shadows(self) -> None:
        engine, game, match = purple_black()
        put(match, 1, "battle_suits")
        argonaut = put(match, 1, "argonaut")
        plexus = put(match, 1, "neo_plexus")
        self.assertEqual(engine.unit_stats(argonaut, match)[0], 4)
        self.assertEqual(engine.unit_stats(plexus, match)[0], 3)
        lord = put(match, 2, "lord_of_shadows")
        imp = put(match, 2, "thieving_imp")
        self.assertTrue(engine.has_keyword(lord, "Invisible", match))
        self.assertTrue(engine.has_keyword(imp, "Invisible", match))
        self.assertFalse(engine.has_keyword(argonaut, "Invisible", match))


# -- White and blue (step 13) ------------------------------------------------


def white_blue(seed: int = 7, first: int = 1,
               teams=(("discipline", "ninjutsu", "strength"), ("law", "peace", "truth"))):
    """White (seat 1) against blue (seat 2), a standard game, standing in
    `first`'s main phase."""
    engine, game, match = new_game(seed=seed, first=first, teams=teams)
    begin(engine, game, match)
    return engine, game, match


def cast_now(engine, game, match, slug, *targets, gold: int = 20):
    """`slug` from the active player's hand, each target answered as it is
    asked; the run of the last answer."""
    seat = match.active
    match.player(seat).hand = [slug]
    match.player(seat).gold = gold
    run = apply_ok(engine, game, match, PromptKind.MAIN_ACTION, "play", slug=slug)
    for target in targets:
        prompt = pending_prompt(engine, game, match)
        assert prompt.kind is PromptKind.TARGET, prompt
        run = apply_ok(engine, game, match, PromptKind.TARGET, target=target)
    return run


class IllusionTests(KeywordCase):
    def test_illusion_1(self) -> None:
        """Illusions die immediately if they are targeted by a spell or
        ability. At the moment they are targeted, they die (and go to their
        owner's discard pile). That means if an effect would target an
        illusion and deal 3 damage to it, or target it and put a rune on
        it, the illusion is already dead and gone before the effect
        happens. It never actually takes the 3 damage or gets the rune in
        those examples."""
        engine, game, match = fresh()
        hero_in_play(match, 1)
        hound = put(match, 2, "spectral_hound", patrol="elite")
        run = cast_now(engine, game, match, "wither", f"2:{hound.ref}")
        self.assertIsNone(match.player(2).instance(hound.id))
        self.assertIn("spectral_hound", match.player(2).discard)
        self.assertIn("is an Illusion: targeted by", " ".join(run.result.narration))
        self.assertNotIn("-1/-1 rune", " ".join(run.result.narration))

    def test_illusion_2(self) -> None:
        """Attacking an Illusion does not automatically kill it. Illusions
        only immediately die if they are targeted by a spell or ability."""
        engine, game, match = fresh()
        brother = put(match, 1, "older_brother")
        hound = put(match, 2, "spectral_hound", patrol="squad_leader")
        hound.armor = 0
        self.attack(engine, game, match, brother.ref, hound.ref)
        self.assertIsNotNone(match.player(2).instance(hound.id))
        self.assertEqual(hound.damage, 2)

    def test_illusion_3(self) -> None:
        """"Illusion" is a subtype that a unit can have, it's not an
        ability. That means Spectral Hound, for example, does not have any
        abilities if Midori's middle ability checks for things "with no
        abilities"."""
        engine, game, match = fresh(teams=(("balance",), ("truth",)))
        hero_in_play(match, 1, level=5)
        hound = put(match, 1, "spectral_hound")
        self.assertEqual(engine.unit_stats(hound, match), (4, 4))
        self.assertTrue(engine.is_illusion(match, hound))

    def test_dreamscape_makes_every_low_tech_unit_an_illusion(self) -> None:
        engine, game, match = white_blue(first=2)
        hero_in_play(match, 2, slug="sirus_quince")
        brother = put(match, 1, "older_brother", patrol="elite")
        put(match, 2, "dreamscape")
        self.assertTrue(engine.is_illusion(match, brother))
        cast_now(engine, game, match, "spark")
        self.assertIsNone(match.player(1).instance(brother.id))

    def test_macciatus_keeps_his_illusions_alive_and_grows_them(self) -> None:
        engine, game, match = new_game(first=2, teams=(("bashing",), ("truth",)))
        begin(engine, game, match)
        hero_in_play(match, 2)
        put(match, 2, "macciatus_the_whisperer")
        hound = put(match, 2, "spectral_hound")
        self.assertEqual(engine.unit_stats(hound, match), (4, 4))
        cast_now(engine, game, match, "wither", f"2:{hound.ref}")
        self.assertIsNotNone(match.player(2).instance(hound.id))
        self.assertEqual(hound.minus_runes, 1)

    def test_hallucination_makes_two_units_illusions_this_turn(self) -> None:
        engine, game, match = white_blue(first=2)
        hero_in_play(match, 2, slug="sirus_quince")
        brother = put(match, 1, "older_brother")
        tender = put(match, 1, "tenderfoot")
        cast_now(engine, game, match, "hallucination", f"1:{brother.ref}", f"1:{tender.ref}")
        self.assertTrue(engine.is_illusion(match, brother) and engine.is_illusion(match, tender))
        cast_now(engine, game, match, "wither", f"1:{brother.ref}")
        self.assertIsNone(match.player(1).instance(brother.id))

    def test_reteller_returns_the_first_two_illusions_each_turn(self) -> None:
        engine, game, match = fresh(teams=(("bashing",), ("truth",)))
        hero_in_play(match, 1)
        put(match, 2, "reteller_of_truths")
        hounds = [put(match, 2, "spectral_hound", patrol=slot)
                  for slot in ("squad_leader", "elite", "scavenger")]
        for hound in hounds:
            cast_now(engine, game, match, "wither", f"2:{hound.ref}")
        self.assertEqual(match.player(2).hand.count("spectral_hound"), 2)
        self.assertEqual(match.player(2).discard.count("spectral_hound"), 1)

    def test_smoker_goes_home_when_targeted(self) -> None:
        engine, game, match = white_blue(first=2)
        hero_in_play(match, 2, slug="sirus_quince")
        smoker = put(match, 1, "smoker", patrol="elite")
        cast_now(engine, game, match, "spark")
        self.assertIsNone(match.player(1).instance(smoker.id))
        self.assertIn("smoker", match.player(1).hand)
        self.assertEqual(smoker.damage, 0)


class StashTests(KeywordCase):
    def test_stash_1(self) -> None:
        """An example of how stash works. Normally (without stash), if you
        have 2 cards left in hand when you reach the discard/draw phase,
        you'd discard both cards and then draw 4 cards (you draw 2 more
        than you discard). If you have stash, instead of discarding both
        cards, you can choose to keep one of them in your hand. If you do,
        you will STILL end up with 4 cards total, but you'll be drawing 3
        cards rather than 4 (the 4th card is the one you kept)."""
        engine, game, match = fresh(teams=(("law",), ("growth",)))
        hero_in_play(match, 1)
        match.player(1).hand = ["arrest", "jail"]
        apply_ok(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        apply_ok(engine, game, match, PromptKind.PATROL, assignment={})
        prompt = pending_prompt(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.STASH)
        self.assertEqual(prompt.options.hand, ("arrest", "jail"))
        deck = len(match.player(1).deck)
        run = apply_ok(engine, game, match, PromptKind.STASH, "keep", slug="jail")
        player = match.player(1)
        self.assertEqual(len(player.hand), 4)
        self.assertIn("jail", player.hand)
        self.assertEqual(player.discard[-1], "arrest")
        self.assertEqual(deck - len(player.deck), 3)
        line = " ".join(run.result.narration)
        self.assertIn("keeps a card, discards 1 and draws 3", line)
        self.assertNotIn("Jail", line)

    def test_no_stash_draws_as_ever(self) -> None:
        engine, game, match = fresh(teams=(("law",), ("growth",)))
        hero_in_play(match, 1)
        match.player(1).hand = ["arrest", "jail"]
        apply_ok(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        apply_ok(engine, game, match, PromptKind.PATROL, assignment={})
        apply_ok(engine, game, match, PromptKind.STASH, "none")
        self.assertEqual(match.player(1).discard[-2:], ["arrest", "jail"])
        self.assertEqual(len(match.player(1).hand), 4)


class ArrivalFatigueTests(KeywordCase):
    def test_arrival_fatigue_1(self) -> None:
        """Simplified, it means if the card is not under your control since
        the very beginning of your turn, it has arrival fatigue."""
        engine, game, match = fresh()
        mine = put(match, 1, "iron_man")
        taken = put(match, 2, "older_brother")
        board.gain_control(match, taken, 1)
        attackers = engine.attackers(match)
        self.assertIn(mine.ref, attackers)
        self.assertNotIn(taken.ref, attackers)

    def test_arrival_fatigue_2(self) -> None:
        """Arrival fatigue is tied to the card itself, so if a Sirus
        Quince's Mirror Illusion has been under your control since the
        beginning of your turn and it copies something, even if the copied
        card has arrival fatigue, the Mirror Illusion doesn't. The opposite
        is also true, if you summon a Mirror Illusion and copy something
        doesn't have arrival fatigue with Sirus Quince's midband, the
        Mirror Illusion still has arrival fatigue."""
        engine, game, match = white_blue(first=2)
        hero_in_play(match, 2, slug="sirus_quince")
        mirror = put(match, 2, "mirror_illusion")
        new = put(match, 1, "tenderfoot", arrived=True)
        fresh_mirror = put(match, 2, "mirror_illusion", arrived=True)
        old = put(match, 1, "older_brother")
        cast_now(engine, game, match, "manufactured_truth")
        apply_ok(engine, game, match, PromptKind.TARGET, target=f"2:{mirror.ref}")
        apply_ok(engine, game, match, PromptKind.TARGET, target=f"1:{new.ref}")
        cast_now(engine, game, match, "manufactured_truth")
        apply_ok(engine, game, match, PromptKind.TARGET, target=f"2:{fresh_mirror.ref}")
        apply_ok(engine, game, match, PromptKind.TARGET, target=f"1:{old.ref}")
        self.assertEqual((mirror.copy_of, fresh_mirror.copy_of), ("tenderfoot", "older_brother"))
        attackers = engine.attackers(match)
        self.assertIn(mirror.ref, attackers)
        self.assertNotIn(fresh_mirror.ref, attackers)


class FlagbearerTests(KeywordCase):
    def test_flagbearer_1(self) -> None:
        """Only spells and abilities that use the [target] symbol interact
        with a flagbearer. For example, Manufactured Truth does NOT have
        the [target] symbol, so it can copy a unit other than a flagbearer
        even if the opponent has a flagbearer."""
        engine, game, match = white_blue(first=2)
        hero_in_play(match, 2, slug="sirus_quince")
        mine = put(match, 2, "bluecoat_musketeer")
        put(match, 1, "morningstar_flagbearer")
        other = put(match, 1, "tenderfoot")
        cast_now(engine, game, match, "manufactured_truth")
        prompt = pending_prompt(engine, game, match)
        self.assertFalse(prompt.options.forced)
        apply_ok(engine, game, match, PromptKind.TARGET, target=f"1:{other.ref}")
        self.assertEqual(mine.copy_of, "tenderfoot")

    def test_flagbearer_2(self) -> None:
        """This has nothing to do with attacking. The flagbearer effect only
        interacts with spells and abilities that use the [target] symbol,
        not with declaring attacks. You don't have to attack a flagbearer
        before you attack other things."""
        engine, game, match = white_blue(first=2)
        attacker = put(match, 2, "bluecoat_musketeer")
        put(match, 1, "morningstar_flagbearer")
        self.assertIn("base", engine.legal_defenders(match, attacker.ref))

    def test_flagbearer_3(self) -> None:
        """If you cannot target a flagbearer for some reason, then you don't
        have to and you can ignore it. For example, if a flagbearer has
        resist 1 (which requires you to pay 1 gold to target it) and you
        have 0 gold, you don't have to target it. Or in other words, if you
        have a spell that costs 4 and that targets, and you have exactly 4
        gold, you CAN ignore a flagbearer with resist 1 because it's
        impossible for you to pay the resist cost in this case, and thus
        impossible to target the flagbearer."""
        engine, game, match = white_blue(first=2)
        hero_in_play(match, 2, slug="sirus_quince")
        flag = put(match, 1, "morningstar_flagbearer", patrol="lookout")
        other = put(match, 1, "tenderfoot", patrol="elite")
        match.player(2).hand = ["spark"]
        match.player(2).gold = 1
        apply_ok(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="spark")
        self.assertEqual(other.damage, 1)
        self.assertEqual(flag.damage, 0)

    def test_flagbearer_4(self) -> None:
        """If a spell can target multiple things, such as Ember Sparks, and
        it can target a flagbearer, it only needs to target that flagbearer
        once. For example, you might split Ember Sparks to do 1 damage to a
        Frog, 1 damage to a Skeleton, and 1 damage to a Flagbearer. That's
        legal and still obeys the flagbearer's effect."""
        engine, game, match = fresh(teams=(("fire",), ("discipline",)))
        hero_in_play(match, 1)
        flag = put(match, 2, "morningstar_flagbearer", patrol="squad_leader")
        first = put(match, 2, "tenderfoot", patrol="elite")
        second = put(match, 2, "older_brother", patrol="scavenger")
        match.player(1).hand = ["ember_sparks"]
        match.player(1).gold = 5
        # The flagbearer is the only first pick the rule allows, so it is
        # taken unasked; after it, anything.
        apply_ok(engine, game, match, PromptKind.MAIN_ACTION, "play", slug="ember_sparks")
        prompt = pending_prompt(engine, game, match)
        self.assertEqual(prompt.options.picked, (f"2:{flag.ref}",))
        self.assertFalse(prompt.options.forced)
        apply_ok(engine, game, match, PromptKind.TARGET, target=f"2:{first.ref}")
        apply_ok(engine, game, match, PromptKind.TARGET, target=f"2:{second.ref}")
        self.assertEqual((flag.damage, first.damage, second.damage), (1, 1, 1))


class WhiteBlueKeywordTests(KeywordCase):
    def test_two_lives_heals_once_then_dies(self) -> None:
        engine, game, match = white_blue(first=2)
        juggernaut = put(match, 2, "justice_juggernaut", patrol=None)
        juggernaut.damage = 6
        result = StepResult()
        board.settle(engine, match, result)
        self.assertIsNotNone(match.player(2).instance(juggernaut.id))
        self.assertEqual((juggernaut.damage, juggernaut.runes.get("crumbling")), (0, 1))
        juggernaut.damage = 6
        board.settle(engine, match, result)
        self.assertIsNone(match.player(2).instance(juggernaut.id))
        self.assertIn("justice_juggernaut", match.player(2).discard)

    def test_two_lives_sacrificed_takes_the_rune(self) -> None:
        engine, game, match = white_blue(first=2)
        juggernaut = put(match, 2, "justice_juggernaut")
        board.sacrifice(engine, match, juggernaut, StepResult())
        self.assertIsNotNone(match.player(2).instance(juggernaut.id))
        self.assertEqual(juggernaut.runes.get("crumbling"), 1)

    def test_garus_rook_has_two_lives_at_eight(self) -> None:
        engine, game, match = white_blue()
        hero_in_play(match, 1, slug="garus_rook", level=8)
        rook = match.player(1).hero_of("garus_rook")
        rook.damage = 6
        board.settle(engine, match, StepResult())
        self.assertTrue(rook.in_play)
        self.assertEqual(rook.runes, {"crumbling": 1})

    def test_rook_is_unstoppable_by_a_lone_patroller(self) -> None:
        engine, game, match = white_blue()
        hero_in_play(match, 1, slug="garus_rook", level=5)
        put(match, 2, "tenderfoot", patrol="elite")
        self.assertIn("base", engine.legal_defenders(match, hero_ref("garus_rook")))
        put(match, 2, "older_brother", patrol="scavenger")
        self.assertNotIn("base", engine.legal_defenders(match, hero_ref("garus_rook")))

    def test_bluecoat_is_long_range_at_exactly_one_atk(self) -> None:
        engine, game, match = white_blue(first=2)
        musketeer = put(match, 2, "bluecoat_musketeer")
        self.assertTrue(engine.has_keyword(musketeer, "Long-range", match))
        musketeer.plus_runes = 1
        self.assertFalse(engine.has_keyword(musketeer, "Long-range", match))

    def test_colossus_reaches_the_base_past_patrollers(self) -> None:
        engine, game, match = white_blue()
        colossus = put(match, 1, "colossus")
        put(match, 2, "tenderfoot", patrol="squad_leader")
        defenders = engine.legal_defenders(match, colossus.ref)
        self.assertIn("base", defenders)
        self.assertNotIn("tech1", defenders)

    def test_traffic_director_reaches_every_building(self) -> None:
        engine, game, match = white_blue(first=2)
        director = put(match, 2, "traffic_director")
        put(match, 1, "tenderfoot", patrol="squad_leader")
        built(match, 1, "tech1")
        defenders = engine.legal_defenders(match, director.ref)
        self.assertIn("base", defenders)
        self.assertIn("tech1", defenders)

    def test_patriot_gryphon_ignores_small_units(self) -> None:
        engine, game, match = white_blue(first=2)
        gryphon = put(match, 2, "patriot_gryphon")
        put(match, 1, "bird", patrol="squad_leader")
        self.assertIn("base", engine.legal_defenders(match, gryphon.ref))
        put(match, 1, "flying_fox", patrol="elite")
        self.assertNotIn("base", engine.legal_defenders(match, gryphon.ref))

    def test_masked_raccoon_beside_a_ninja_and_a_cute_animal(self) -> None:
        engine, game, match = white_blue()
        raccoon = put(match, 1, "masked_raccoon")
        put(match, 2, "tenderfoot", patrol="squad_leader")
        self.assertNotIn("base", engine.legal_defenders(match, raccoon.ref))
        put(match, 1, "fox_viper")
        self.assertIn("base", engine.legal_defenders(match, raccoon.ref))
        match.active = 2
        hero_in_play(match, 2, slug="bigby_hayes")
        brother = put(match, 2, "older_brother")
        put(match, 1, "porcupine")
        self.assertNotIn(raccoon.ref, engine.legal_defenders(match, brother.ref))
        self.assertIn(raccoon.ref, engine.legal_defenders(match, hero_ref("bigby_hayes")))

    def test_liberty_gryphon_beside_another_illusion(self) -> None:
        engine, game, match = white_blue(first=2)
        gryphon = put(match, 2, "liberty_gryphon")
        self.assertFalse(engine.has_keyword(gryphon, "Untargetable", match))
        put(match, 2, "spectral_hound")
        for keyword in ("Unstoppable", "Unattackable", "Untargetable"):
            self.assertTrue(engine.has_keyword(gryphon, keyword, match))

    def test_eyes_of_the_chancellor_is_a_detector(self) -> None:
        engine, game, match = white_blue(first=2)
        spy = put(match, 1, "smoker")
        self.assertFalse(engine.detected_by(match, 2, spy.ref))
        put(match, 2, "eyes_of_the_chancellor")
        self.assertTrue(engine.detected_by(match, 2, spy.ref))

    def test_manufactured_truth_copies_the_printed_card_until_the_turn_ends(self) -> None:
        engine, game, match = white_blue(first=2)
        hero_in_play(match, 2, slug="sirus_quince")
        mine = put(match, 2, "bluecoat_musketeer")
        theirs = put(match, 1, "fox_primus")
        theirs.plus_runes = 1
        # One unit of theirs to copy, one of hers to copy it: nothing asked.
        cast_now(engine, game, match, "manufactured_truth")
        self.assertEqual(mine.copy_of, "fox_primus")
        self.assertEqual(engine.unit_stats(mine, match), (2, 2))
        self.assertTrue(engine.has_keyword(mine, "Anti-air", match))
        turn.begin_tech(engine, game, match)
        self.assertIsNone(mine.copy_of)
        self.assertEqual(engine.unit_stats(mine, match), (1, 2))


class EveryRulingIsPinnedTests(unittest.TestCase):
    """
    The ratchet: every `General` ruling on a keyword this step implements
    has a test named for it, and that test's docstring is the ruling's own
    words.
    """

    def _collect(self) -> dict:
        import test_codex_keywords as module

        found = {}
        for name in dir(module):
            case = getattr(module, name)
            if not (isinstance(case, type) and issubclass(case, unittest.TestCase)):
                continue
            for method in dir(case):
                if method.startswith("test_"):
                    found[method] = getattr(case, method)
        return found

    def test_the_tables_cover_the_general_group(self) -> None:
        """Step 13: every keyword the General group rules on is in one of
        the tables, so every ruling the data holds is pinned, and a
        re-import that adds a keyword fails here."""
        pinned = {rulings.keyword_slug(keyword) for keyword in ALL_KEYWORDS}
        general = {entry.slug for entry in rulings.keywords()}
        self.assertEqual(general - pinned, set())

    def test_every_ruling_has_a_test(self) -> None:
        found = self._collect()
        for keyword, count in ALL_KEYWORDS.items():
            slug = rulings.keyword_slug(keyword)
            with self.subTest(keyword=keyword):
                self.assertEqual(
                    len(rulings.keyword_rulings(keyword)), count,
                    f"{keyword} has a different number of rulings than this file pins",
                )
                for number in range(1, count + 1):
                    self.assertIn(f"test_{slug}_{number}", found)

    def test_each_test_says_the_ruling_it_pins(self) -> None:
        found = self._collect()
        for keyword, count in ALL_KEYWORDS.items():
            slug = rulings.keyword_slug(keyword)
            for number, ruling in enumerate(rulings.keyword_rulings(keyword), start=1):
                with self.subTest(keyword=keyword, ruling=number):
                    doc = _collapse(found[f"test_{slug}_{number}"].__doc__ or "")
                    self.assertTrue(doc, "the ruling is the test's docstring")
                    text = _collapse(ruling.text).replace("atatcker", "attacker")
                    # A docstring may leave out a sentence of a long
                    # ruling -- an example about a card of another spec --
                    # but every sentence it does carry is the ruling's.
                    for sentence in _sentences(doc):
                        self.assertIn(sentence, text)


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _sentences(text: str) -> list[str]:
    """The docstring's sentences, each of which has to be the ruling's."""
    found = [part.strip(' ."') for part in re.split(r"(?<=[.!?])\s+", text)]
    return [part for part in found if len(part) > 20]


if __name__ == "__main__":
    unittest.main()

"""
The free-for-all through the driver (docs/codex-multiplayer.md, step 2):
the variant on the record and the match, the deal and its Mercenaries,
the turn order, the ending on the most base HP and its playoff, debt and
concession -- each staged by slug and played through `driver.apply`.

The rules are Rulebook p. 14 (and p. 4, 5, 11, 19 where a test says so)
and the author's answers of 2026-10-14 to the worksheet's questions 15,
16 and 17; the UMR's reading of the playoff's current turn (question 13,
still open) is built.
"""

from __future__ import annotations

import unittest

from codex import tokens
from codex.cards import catalog
from codex.components import MatchState
from codex.engine import MERCENARY
from codex.flow import StepResult, driver
from codex.flow.turn import concede
from codex.game import CodexGame, GameStatus, RuleRefusal
from codex.prompts import Action, PromptKind, owed_step, pending_prompt

from codex_positions import begin, hero_in_play, new_game, put

THREE = (("bashing",), ("finesse",), ("bashing",))
FIVE = (("bashing",), ("finesse",), ("bashing",), ("finesse",), ("bashing",))


def free_for_all(teams=THREE, first=1, seed=7):
    """A free-for-all dealt and standing on the first player's main phase."""
    engine, game, match = new_game(seed=seed, first=first, teams=teams, variant="free_for_all")
    begin(engine, game, match)
    return engine, game, match


def apply(engine, game, match, action):
    run = driver.apply(engine, game, match, action)
    assert not isinstance(run, driver.Refusal), run
    return run


def said(run) -> str:
    lines = [line for group in run.groups for line in group.narration] + list(run.result.narration)
    return "\n".join(line for line in lines if line)


def lock(engine, game, match, assignment=None, lent=None) -> str:
    """The active player ends their main phase and locks `assignment`
    and `lent`; the turn runs on to the next main phase, the tech each
    player owes settled with no picks, as staging. What was said."""
    heard = [said(apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "end_main")))]
    arguments = {"assignment": assignment or {}}
    if lent is not None:
        arguments["lent"] = lent
    heard.append(said(apply(engine, game, match, Action(PromptKind.PATROL, arguments=arguments))))
    while match.winner is None:
        for player in match.players:
            player.tech_owed = False
        owed = owed_step(engine, game, match)
        if owed is None:
            break
        heard.append(said(driver.advance(engine, game, match, StepResult(next=owed))))
    return "\n".join(heard)


def end_turn(engine, game, match) -> str:
    """The active player ends their main phase, locks no patrollers, and
    the turn runs on to the next player's main phase. What was said."""
    return lock(engine, game, match)


def attack(engine, game, match, attacker, defender, against):
    """`attacker` (a ref) attacks `defender` of `against`, through the
    driver. What was said."""
    heard = [said(apply(engine, game, match, Action(
        PromptKind.MAIN_ACTION, "attack", {"attacker": attacker}))),
    ]
    heard.append(said(apply(engine, game, match, Action(
        PromptKind.CHOOSE_DEFENDER, arguments={"defender": defender, "against": against},
    ))))
    return "\n".join(heard)


def attack_base(engine, game, match, against: int) -> str:
    """The active player's Iron Man attacks `against`'s base."""
    return attack(engine, game, match, put(match, match.active, "iron_man").ref, "base", against)


class VariantTests(unittest.TestCase):
    """The variant is the record's and the match's (decision 2)."""

    def test_the_three_variants(self) -> None:
        from codex.game import VARIANTS

        self.assertEqual(VARIANTS, ("duel", "free_for_all", "two_headed_dragon"))

    def test_a_record_counts_its_seats_by_variant(self) -> None:
        game = CodexGame("g", 1)
        self.assertEqual(game.seat_count, 2)
        game.set_variant("free_for_all")
        self.assertEqual(game.seat_count, 5)
        self.assertEqual(len(game.seats), 5)
        self.assertEqual(len(CodexGame("g", 2, variant="free_for_all").seats), 5)

    def test_the_variant_is_saved_and_a_duel_writes_none(self) -> None:
        duel = CodexGame("g", 1)
        self.assertNotIn("variant", duel.to_dict())
        self.assertEqual(CodexGame.from_dict(duel.to_dict()).variant, "duel")
        game = CodexGame("g", 1)
        game.set_variant("free_for_all")
        game.take_seat(1, "a", "bashing")
        loaded = CodexGame.from_dict(game.to_dict())
        self.assertEqual(loaded.variant, "free_for_all")
        self.assertEqual(len(loaded.seats), 5)
        self.assertEqual(loaded.seat_user_id(1), 1)

    def test_the_variant_is_the_lobbys_until_start(self) -> None:
        engine, game, _ = new_game(teams=THREE, variant="free_for_all")
        game.status = GameStatus.LOBBY
        game.match_state = None
        game.start(engine)
        with self.assertRaises(RuleRefusal):
            game.set_variant("duel")

    def test_the_dragon_is_offered(self) -> None:
        """Multiplayer step 6 opened it: four seats in two teams."""
        game = CodexGame("g", 1)
        game.set_variant("two_headed_dragon")
        self.assertEqual((game.seat_count, game.teams()), (4, ((1, 2), (3, 4))))

    def test_changing_the_variant_keeps_who_fits(self) -> None:
        game = CodexGame("g", 1)
        game.set_variant("free_for_all")
        for user in (1, 2, 3):
            game.take_seat(user, f"p{user}", "bashing")
        game.set_variant("duel")
        self.assertEqual(game.seat_ids(), (1, 2))
        self.assertNotIn(3, game.player_specs)

    def test_a_free_for_all_starts_from_three_complete_seats(self) -> None:
        engine = new_game()[0]
        game = CodexGame("g", 1)
        game.set_variant("free_for_all")
        game.take_seat(1, "a", "bashing")
        game.take_seat(2, "b", "finesse")
        self.assertFalse(game.may_start())
        with self.assertRaises(RuleRefusal) as refused:
            game.start(engine)
        self.assertEqual(refused.exception.cite, "Rulebook p. 14")
        game.take_seat(3, "c", "bashing")
        self.assertTrue(game.may_start())
        game.start(engine)
        match = MatchState.from_dict(game.match_state)
        self.assertEqual([player.seat for player in match.players], [1, 2, 3])
        self.assertEqual(match.variant, "free_for_all")

    def test_the_default_view_follows_the_table(self) -> None:
        """The author, 2026-10-14: three or four players open side by side
        (two panels a row), five open stacked."""
        for count, layout in ((3, "side_by_side"), (4, "side_by_side"), (5, "stacked")):
            with self.subTest(players=count):
                engine = new_game()[0]
                game = CodexGame("g", 1)
                game.set_variant("free_for_all")
                for user in range(1, count + 1):
                    game.take_seat(user, f"p{user}", "bashing")
                game.start(engine)
                self.assertEqual(game.board_layout, layout)

    def test_leaving_closes_the_gap(self) -> None:
        """Turn order is seat order: the seats after a leaver move up."""
        game = CodexGame("g", 1)
        game.set_variant("free_for_all")
        for user, spec in ((1, "bashing"), (2, "finesse"), (3, "bashing")):
            game.take_seat(user, f"p{user}", spec)
        game.leave(2)
        self.assertEqual(game.seat_user_id(1), 1)
        self.assertEqual(game.seat_user_id(2), 3)
        self.assertIsNone(game.seat_user_id(3))
        self.assertEqual(game.player_specs, {1: ["bashing"], 2: ["bashing"]})

    def test_seats_are_taken_in_order(self) -> None:
        game = CodexGame("g", 1, test_game=True)
        game.set_variant("free_for_all")
        game.take_seat(1, "a", "bashing", seat=1)
        with self.assertRaises(RuleRefusal):
            game.take_seat(1, "a", "bashing", seat=3)

    def test_the_match_saves_its_variant_and_a_duel_writes_none(self) -> None:
        engine, _, duel = new_game()
        self.assertNotIn("variant", duel.to_dict())
        self.assertEqual(MatchState.from_dict(duel.to_dict()).variant, "duel")
        _, _, match = new_game(teams=THREE, variant="free_for_all")
        saved = match.to_dict()
        self.assertEqual(saved["variant"], "free_for_all")
        loaded = MatchState.from_dict(saved)
        loaded.validate(catalog())
        self.assertEqual(loaded.to_dict(), saved)


class DealTests(unittest.TestCase):
    """Rulebook p. 14: player 1 starts with 4 workers, the rest with 5;
    players 3, 4 and 5 get 1, 2 and 3 Mercenaries in their first upkeep."""

    def test_the_mercenaries_follow_turn_order_from_the_first(self) -> None:
        engine, game, match = new_game(teams=FIVE, first=4, variant="free_for_all")
        # Turn order 4, 5, 1, 2, 3: the third, fourth and fifth players are
        # seats 1, 2 and 3.
        owed = {player.seat: player.mercenaries_owed for player in match.players}
        self.assertEqual(owed, {4: 0, 5: 0, 1: 1, 2: 2, 3: 3})
        workers = {player.seat: player.workers for player in match.players}
        self.assertEqual(workers, {4: 4, 5: 5, 1: 5, 2: 5, 3: 5})

    def test_a_duel_owes_none(self) -> None:
        _, _, match = new_game()
        self.assertTrue(all(player.mercenaries_owed == 0 for player in match.players))
        self.assertNotIn("mercenaries_owed", match.to_dict()["players"][0])

    def test_a_mercenary_arrives_in_its_owners_first_upkeep(self) -> None:
        engine, game, match = free_for_all()
        third = match.player(3)
        self.assertEqual(third.mercenaries_owed, 1)
        self.assertFalse(any(card.slug == MERCENARY for card in third.play))
        end_turn(engine, game, match)
        self.assertFalse(any(card.slug == MERCENARY for card in third.play))
        heard = end_turn(engine, game, match)
        self.assertEqual(match.active, 3)
        mercenaries = [card for card in third.play if card.slug == MERCENARY]
        self.assertEqual(len(mercenaries), 1)
        self.assertEqual((mercenaries[0].owner, mercenaries[0].controller), (3, 3))
        self.assertIsNone(mercenaries[0].made_by)
        self.assertEqual(third.mercenaries_owed, 0)
        self.assertIn(f"{tokens.player(3)}'s {tokens.card(MERCENARY)} arrives.", heard)
        # "It doesn't have haste, so it can't attack on their first turn."
        prompt = pending_prompt(engine, game, match)
        self.assertNotIn(mercenaries[0].ref, prompt.options.attackers)
        for _ in range(3):
            end_turn(engine, game, match)
        prompt = pending_prompt(engine, game, match)
        self.assertIn(mercenaries[0].ref, prompt.options.attackers)

    def test_two_mercenaries_are_said_as_two(self) -> None:
        engine, game, match = free_for_all(teams=FIVE)
        for _ in range(3):
            end_turn(engine, game, match)
        self.assertEqual(match.active, 4)
        self.assertEqual(sum(1 for card in match.player(4).play if card.slug == MERCENARY), 2)


class TargetKeyTests(unittest.TestCase):
    def test_a_target_key_names_any_seat(self) -> None:
        from codex.engine import parse_target

        self.assertEqual(parse_target("5:unit:35"), (5, "unit:35"))
        for bad in ("0:base", "x:base", "3:"):
            with self.subTest(key=bad), self.assertRaises(ValueError):
                parse_target(bad)


class TurnOrderTests(unittest.TestCase):
    def test_the_turn_wraps_through_every_seat(self) -> None:
        engine, game, match = free_for_all(teams=FIVE, first=3)
        order = [match.active]
        for _ in range(5):
            end_turn(engine, game, match)
            order.append(match.active)
        self.assertEqual(order, [3, 4, 5, 1, 2, 3])


class EndingTests(unittest.TestCase):
    """Rulebook p. 14: the game ends when any base is destroyed, and the
    most base HP wins; a tie for the most plays off."""

    def test_a_sole_leader_wins_when_a_base_falls(self) -> None:
        engine, game, match = free_for_all()
        match.set_base(2, 1)
        match.set_base(3, 14)
        match.set_base(1, 12)
        heard = attack_base(engine, game, match, 2)
        self.assertEqual(match.winner, 3)
        self.assertIn(f"**{tokens.player(2)}'s base is destroyed.**", heard)
        self.assertIn(f"{tokens.player(3)} wins with 14 base HP!", heard)
        prompt = pending_prompt(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.GAME_OVER)
        self.assertEqual(
            prompt.ask,
            f"{tokens.player(3)} wins with 14 base HP: {tokens.player(2)}'s base is destroyed.",
        )
        self.assertEqual(prompt.options.winners, (3,))
        self.assertEqual(prompt.options.base_hp, ((1, 12), (2, 0), (3, 14)))
        self.assertEqual(prompt.options.to_dict()["winners"], [3])

    def test_a_duel_says_its_winner_as_before(self) -> None:
        engine, game, match = new_game()
        begin(engine, game, match)
        match.set_base(2, 1)
        attack_base(engine, game, match, 2)
        prompt = pending_prompt(engine, game, match)
        self.assertEqual(prompt.ask, f"{tokens.player(1)} wins!")
        self.assertEqual(prompt.options.winners, (1,))

    def tie(self, teams=THREE):
        """Seat 1 destroys seat 2's base with seats 1 and 3 tied at 14 --
        and a fourth seat, where there is one, at 13."""
        engine, game, match = free_for_all(teams=teams)
        if len(teams) > 3:
            match.set_base(4, 13)
        match.set_base(2, 1)
        match.set_base(1, 14)
        match.set_base(3, 14)
        heard = attack_base(engine, game, match, 2)
        return engine, game, match, heard

    def test_a_tie_fills_the_playoff_in_turn_order_from_the_next(self) -> None:
        engine, game, match, heard = self.tie()
        self.assertIsNone(match.winner)
        self.assertEqual(match.tied, [3, 1])
        self.assertEqual(match.playoff, [3, 1])
        self.assertIn(
            f"A tie at 14 base HP: {tokens.player(3)} and {tokens.player(1)} each take one more turn.",
            heard,
        )
        # The current turn runs to its end (question 13, the UMR's reading).
        self.assertIs(pending_prompt(engine, game, match).kind, PromptKind.MAIN_ACTION)
        self.assertEqual(match.active, 1)
        saved = match.to_dict()
        self.assertEqual((saved["playoff"], saved["tied"]), ([3, 1], [3, 1]))
        MatchState.from_dict(saved).validate(catalog())

    def test_the_tied_play_their_turns_and_the_tie_is_broken(self) -> None:
        engine, game, match, _ = self.tie()
        end_turn(engine, game, match)
        self.assertEqual(match.active, 3)  # seat 2 is not tied: skipped
        self.assertEqual(match.playoff, [1])
        match.set_base(1, 9)  # seat 3 hurts seat 1 on their extra turn
        end_turn(engine, game, match)
        self.assertEqual(match.active, 1)
        self.assertEqual(match.playoff, [])
        heard = end_turn(engine, game, match)
        self.assertEqual(match.winner, 3)
        self.assertIn(f"{tokens.player(3)} wins with 14 base HP: the tie is broken.", heard)
        self.assertEqual(
            pending_prompt(engine, game, match).ask,
            f"{tokens.player(3)} wins with 14 base HP: the tie is broken.",
        )

    def test_a_tie_still_held_plays_off_again(self) -> None:
        engine, game, match, _ = self.tie()
        for _ in range(3):
            heard = end_turn(engine, game, match)
        self.assertIsNone(match.winner)
        self.assertIn(
            f"Still tied at 14 base HP: {tokens.player(3)} and {tokens.player(1)} each take one more turn.",
            heard,
        )
        self.assertEqual(match.active, 3)
        self.assertEqual(match.playoff, [1])

    def test_a_tie_the_rest_of_the_turn_would_break_still_plays_off(self) -> None:
        """Question 15 (the author, 2026-10-14): the tied players are those
        tied when the base falls -- "at that moment" -- and a repair later
        in the same turn changes nothing about who is in the playoff."""
        engine, game, match, _ = self.tie()
        match.set_base(1, 17)  # as a repair would, later in seat 1's turn
        end_turn(engine, game, match)
        self.assertEqual(match.tied, [3, 1])
        self.assertEqual(match.active, 3)

    def test_a_third_player_never_wins_the_playoff(self) -> None:
        """Question 16 (the author, 2026-10-14): after the extra turns the
        comparison is among the tied alone, however they hurt each other."""
        engine, game, match, _ = self.tie(teams=(("bashing",), ("finesse",), ("bashing",), ("finesse",)))
        end_turn(engine, game, match)
        match.set_base(1, 5)
        end_turn(engine, game, match)
        match.set_base(3, 6)
        end_turn(engine, game, match)
        self.assertEqual(match.winner, 3)  # seat 4's 13 counts for nothing

    def test_a_base_destroyed_in_the_playoff_counts_only_if_tied(self) -> None:
        engine, game, match, _ = self.tie(teams=(("bashing",), ("finesse",), ("bashing",), ("finesse",)))
        end_turn(engine, game, match)
        self.assertEqual(match.active, 3)
        match.set_base(4, 1)
        attack_base(engine, game, match, 4)
        self.assertIsNone(match.winner)
        self.assertEqual(match.base_of(4), 0)
        match.set_base(1, 1)
        heard = attack_base(engine, game, match, 1)
        self.assertEqual(match.winner, 3)
        self.assertIn(f"{tokens.player(3)} wins with 14 base HP!", heard)

    def test_no_concession_in_a_free_for_all(self) -> None:
        """Decision 5 (the author, 2026-10-11): "no player elimination"."""
        engine, game, match = free_for_all()
        with self.assertRaises(RuleRefusal) as refused:
            concede(engine, game, match, 2)
        self.assertEqual(refused.exception.cite, "Rulebook p. 14")
        self.assertIsNone(match.winner)


class DebtTests(unittest.TestCase):
    """Question 17 (the author, 2026-10-14): in a free-for-all a debt
    unpaid is exactly a base destroyed -- the base to zero, and the
    comparison made then."""

    def owe(self, bases):
        engine, game, match = free_for_all()
        for seat, hp in bases.items():
            match.set_base(seat, hp)
        match.player(2).debt = 30
        end_turn(engine, game, match)
        return engine, game, match

    def test_a_debt_unpaid_with_a_sole_leader(self) -> None:
        engine, game, match = self.owe({1: 12, 2: 18, 3: 15})
        self.assertEqual(match.base_of(2), 0)
        self.assertEqual(match.winner, 3)
        self.assertIsNone(match.lost_by_debt)
        self.assertEqual(
            pending_prompt(engine, game, match).ask,
            f"{tokens.player(3)} wins with 15 base HP: {tokens.player(2)}'s base is destroyed.",
        )

    def test_a_debt_unpaid_with_a_tie(self) -> None:
        engine, game, match = self.owe({1: 15, 2: 18, 3: 15})
        self.assertIsNone(match.winner)
        self.assertEqual(match.tied, [3, 1])
        self.assertEqual(match.base_of(2), 0)


class TowerAndArmorTests(unittest.TestCase):
    """Rulebook p. 4, the General group's tower rulings and p. 19."""

    def tower(self, match, seat):
        from codex.components import AddOnState

        match.player(seat).add_on = AddOnState(slug="tower", hp=4, under_construction=False)

    def test_the_tower_detects_only_an_attacker_of_its_owner(self) -> None:
        """Rulebook p. 4: "the first one of those that attacks you" -- a
        stealth attacker of another player passes seat 2's tower by."""
        engine, game, match = free_for_all()
        self.tower(match, 2)
        sneak = put(match, 1, "chameleon")
        put(match, 3, "older_brother", patrol="squad_leader")
        apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "attack", {"attacker": sneak.ref}))
        apply(engine, game, match, Action(PromptKind.CHOOSE_DEFENDER, arguments={"defender": "base", "against": 3}))
        self.assertIsNone(match.player(2).add_on.detected)
        self.assertEqual(sneak.damage, 0)
        self.assertLess(match.base_of(3), 20, "it sneaked past seat 3's patroller")

    def test_the_tower_detects_and_damages_an_attacker_of_its_owner(self) -> None:
        engine, game, match = free_for_all()
        self.tower(match, 2)
        sneak = put(match, 1, "chameleon")
        apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "attack", {"attacker": sneak.ref}))
        apply(engine, game, match, Action(PromptKind.CHOOSE_DEFENDER, arguments={"defender": "base", "against": 2}))
        self.assertEqual(match.player(2).add_on.detected, sneak.ref)

    def test_the_towers_damage_falls_only_on_an_attacker_of_its_owner(self) -> None:
        """The free-for-all tower ruling: its damage is dealt only to an
        attacker of something its owner controls."""
        engine, game, match = free_for_all()
        self.tower(match, 2)
        attack_base(engine, game, match, 3)
        man = next(card for card in match.player(1).play if card.slug == "iron_man")
        self.assertEqual(man.damage, 0)
        attack_base(engine, game, match, 2)
        second = [card for card in match.player(1).play if card.slug == "iron_man"][1]
        self.assertEqual(second.damage, 1)

    def test_armor_refreshes_on_every_opponents_turn(self) -> None:
        """Rulebook p. 19 and the Ironbark Treant ruling: armor refreshes
        each turn -- the squad leader's 1 and the Treant's own 2 -- so a
        patroller's comes back on every opponent's turn, not its owner's."""
        engine, game, match = free_for_all()
        treant = put(match, 3, "ironbark_treant", patrol="squad_leader")
        end_turn(engine, game, match)
        self.assertEqual(match.active, 2)
        self.assertEqual(treant.armor, 3)
        treant.armor = 0
        end_turn(engine, game, match)
        self.assertEqual(match.active, 3)
        # Its owner's own ready phase takes it out of the patrol zone.
        self.assertIsNone(treant.patrol_slot)


class AttackTests(unittest.TestCase):
    """Rulebook p. 5: each opponent's patrol zone protects that opponent
    alone; the overpower ruling; Moment's Peace."""

    def test_each_opponents_zone_protects_them_alone(self) -> None:
        engine, game, match = free_for_all()
        leader = put(match, 2, "older_brother", patrol="squad_leader")
        put(match, 3, "older_brother")
        man = put(match, 1, "iron_man")
        apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "attack", {"attacker": man.ref}))
        options = pending_prompt(engine, game, match).options
        offered = set(zip(options.seats, options.defenders))
        self.assertEqual({ref for seat, ref in offered if seat == 2}, {leader.ref})
        self.assertIn((3, "base"), offered)
        self.assertEqual(options.to_dict()["seats"], list(options.seats))

    def test_overpower_stays_with_the_attacked_opponent(self) -> None:
        """The overpower ruling: the excess goes to something controlled by
        the player whose patroller was attacked."""
        engine, game, match = free_for_all()
        centaur = put(match, 1, "centaur")
        guard = put(match, 2, "older_brother", patrol="elite")
        put(match, 2, "older_brother")
        elsewhere = put(match, 3, "older_brother")
        apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "attack", {"attacker": centaur.ref}))
        apply(engine, game, match, Action(PromptKind.CHOOSE_DEFENDER, arguments={"defender": guard.ref, "against": 2}))
        prompt = pending_prompt(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.OVERPOWER_TARGET)
        self.assertNotIn(elsewhere.ref, prompt.options.targets)
        self.assertIn("base", prompt.options.targets)

    def test_moments_peace_shields_its_caster_alone(self) -> None:
        """Moment's Peace: "opposing units can't attack you" -- its
        caster's things leave the legal defenders and nothing else."""
        engine, game, match = free_for_all()
        match.player(2).peace = True
        man = put(match, 1, "iron_man")
        self.assertIn(man.ref, pending_prompt(engine, game, match).options.attackers)
        apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "attack", {"attacker": man.ref}))
        options = pending_prompt(engine, game, match).options
        self.assertEqual(set(options.seats), {3})
        refused = driver.apply(engine, game, match, Action(
            PromptKind.CHOOSE_DEFENDER, arguments={"defender": "base", "against": 2}))
        self.assertIsInstance(refused, driver.Refusal)

    def test_moments_peace_on_every_opponent_stops_the_units(self) -> None:
        engine, game, match = free_for_all()
        match.player(2).peace = match.player(3).peace = True
        man = put(match, 1, "iron_man")
        hero_in_play(match, 1)
        attackers = pending_prompt(engine, game, match).options.attackers
        self.assertNotIn(man.ref, attackers)
        self.assertIn("hero:troq_bashar", attackers, "heroes still may")


class OpponentCardTests(unittest.TestCase):
    """Decision 11: a plural is every opponent; "an opponent's" is the one
    the controller chooses, asked only where there are several; "that
    opponent" is the one the context names."""

    def table(self, teams=THREE, first=1):
        return free_for_all(teams=teams, first=first)

    def cast(self, engine, game, match, slug, gold=20):
        match.player(match.active).hand = [slug]
        match.player(match.active).gold = gold
        return apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "play", {"slug": slug}))

    def test_a_dead_heros_levels_may_go_to_a_third_players_hero(self) -> None:
        """Rulebook p. 11: one opposing hero levels, the active player
        choosing -- any hero of any opponent of the dead hero's controller."""
        engine, game, match = self.table(teams=(("bashing",), ("finesse",), ("fire",)))
        hero_in_play(match, 1)
        river_hp = engine.hero_stats(match.player(2).hero, match)[1]
        hero_in_play(match, 2, damage=river_hp - 1)
        hero_in_play(match, 3)
        apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "attack", {"attacker": "hero:troq_bashar"}))
        apply(engine, game, match, Action(
            PromptKind.CHOOSE_DEFENDER, arguments={"defender": "hero:river_montoya", "against": 2}))
        prompt = pending_prompt(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.LEVEL_GAIN)
        self.assertEqual(prompt.asked_player, 1)
        self.assertEqual(set(zip(prompt.options.seats, prompt.options.heroes)),
                         {(1, "hero:troq_bashar"), (3, "hero:jaina_stormborne")})
        apply(engine, game, match, Action(PromptKind.LEVEL_GAIN, arguments={"hero": "hero:jaina_stormborne", "seat": 3}))
        self.assertEqual(match.player(3).hero.level, 3)
        self.assertEqual(match.player(1).hero.level, 1)

    def test_a_hero_at_its_maximum_level_is_not_offered_the_levels(self) -> None:
        """A hero at its maximum can gain no more, so it is never offered a
        dead hero's levels (the author, 2026-10-15): with the third
        player's hero maxed, the attacker's own hero is the one that can
        take them, and takes them unasked."""
        engine, game, match = self.table(teams=(("bashing",), ("finesse",), ("fire",)))
        hero_in_play(match, 1)
        river_hp = engine.hero_stats(match.player(2).hero, match)[1]
        hero_in_play(match, 2, damage=river_hp - 1)
        hero_in_play(match, 3)
        jaina = match.player(3).hero
        jaina.level = engine.hero_card(jaina).max_level
        apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "attack", {"attacker": "hero:troq_bashar"}))
        apply(engine, game, match, Action(
            PromptKind.CHOOSE_DEFENDER, arguments={"defender": "hero:river_montoya", "against": 2}))
        self.assertIsNot(pending_prompt(engine, game, match).kind, PromptKind.LEVEL_GAIN)
        self.assertEqual(match.player(1).hero.level, 3)
        self.assertEqual(jaina.level, engine.hero_card(jaina).max_level)

    def test_discord_asks_which_opponent(self) -> None:
        engine, game, match = self.table(first=2)
        hero_in_play(match, 2)
        mine = put(match, 1, "older_brother")
        theirs = put(match, 3, "older_brother")
        self.cast(engine, game, match, "discord")
        prompt = pending_prompt(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.TARGET)
        self.assertEqual(prompt.ask, f"{tokens.player(2)}, {tokens.card('discord')}: choose an opponent.")
        self.assertEqual({row.key for row in prompt.options.targets}, {"1:base", "3:base"})
        run = apply(engine, game, match, Action(PromptKind.TARGET, arguments={"target": "3:base"}))
        self.assertIn(f"{tokens.player(2)} chooses {tokens.player(3)} for {tokens.card('discord')}.", said(run))
        self.assertEqual(engine.unit_stats(theirs, match), (0, 1))
        self.assertEqual(engine.unit_stats(mine, match), (2, 2))

    def test_reputable_newsman_binds_every_opponent(self) -> None:
        """"Opponents can't play spells or upgrades that cost that amount."
        -- a plural: every opponent."""
        engine, game, match = self.table()
        self.cast(engine, game, match, "reputable_newsman")
        self.assertIs(pending_prompt(engine, game, match).kind, PromptKind.CHOOSE_NUMBER)
        run = apply(engine, game, match, Action(PromptKind.CHOOSE_NUMBER, arguments={"number": 2}))
        self.assertIn("Opponents can't play spells or upgrades that cost 2", said(run))
        for seat in (2, 3):
            with self.subTest(seat=seat):
                match.player(seat).hand = ["discord"]
                hero_in_play(match, seat)
                match.player(seat).gold = 10
                match.active = seat
                rows = {row.slug: row for row in engine.playable(match.player(seat), match)}
                self.assertFalse(rows["discord"].allowed)

    def test_the_flagbearer_of_any_opponent_must_be_targeted(self) -> None:
        engine, game, match = self.table()
        hero_in_play(match, 1)
        flag = put(match, 3, "granfalloon_flagbearer")
        put(match, 2, "older_brother")
        brother = match.player(2).play[-1]
        self.cast(engine, game, match, "intimidate")
        # The one row left -- seat 3's flagbearer -- is taken unasked.
        self.assertEqual(engine.unit_stats(flag, match)[0], 0)
        self.assertEqual(engine.unit_stats(brother, match)[0], 2)

    def test_captured_bugblatter_on_an_opponents_turn_and_its_own(self) -> None:
        """"Whenever a unit dies on an opponent's turn, their base takes 1
        damage. Whenever a unit dies on your turn, deal 1 damage to an
        opponent's base." -- the active player's base, or the one chosen."""
        from codex.flow import board, resolve

        engine, game, match = self.table(first=2)
        put(match, 1, "captured_bugblatter")
        cub = put(match, 3, "older_brother")
        board.destroy(engine, match, [(3, cub.ref)], StepResult())
        resolve.run(engine, match, StepResult())
        self.assertEqual((match.base_of(2), match.base_of(3)), (19, 20))
        match.active = 1
        other = put(match, 3, "older_brother")
        board.destroy(engine, match, [(3, other.ref)], StepResult())
        resolve.run(engine, match, StepResult())
        prompt = pending_prompt(engine, game, match)
        self.assertEqual(prompt.asked_player, 1)
        self.assertEqual({row.key for row in prompt.options.targets}, {"2:base", "3:base"})
        apply(engine, game, match, Action(PromptKind.TARGET, arguments={"target": "3:base"}))
        self.assertEqual((match.base_of(2), match.base_of(3)), (19, 19))

    def test_carrion_curse_looks_at_the_chosen_opponents_hand_alone(self) -> None:
        engine, game, match = self.table(teams=(("bashing",), ("disease",), ("bashing",)), first=2)
        hero_in_play(match, 2)
        match.player(1).hand = ["wrecking_ball"]
        match.player(3).hand = ["intimidate", "older_brother"]
        self.cast(engine, game, match, "carrion_curse")
        prompt = pending_prompt(engine, game, match)
        self.assertEqual(prompt.options.shown, ())
        self.assertEqual({row.key for row in prompt.options.targets}, {"1:base", "3:base"})
        apply(engine, game, match, Action(PromptKind.TARGET, arguments={"target": "3:base"}))
        prompt = pending_prompt(engine, game, match)
        self.assertEqual(prompt.options.shown, ("intimidate", "older_brother"))
        self.assertEqual([row.key for row in prompt.options.targets], ["3:hand:intimidate"])

    def test_hooded_executioner_destroys_each_opponents_weakest(self) -> None:
        engine, game, match = self.table(teams=(("necromancy",), ("finesse",), ("bashing",)))
        from codex_positions import built

        built(match, 1, "tech1")
        weak2 = put(match, 2, "older_brother")
        strong2 = put(match, 2, "iron_man")
        weak3 = put(match, 3, "older_brother")
        match.player(1).hand = ["hooded_executioner"]
        match.player(1).gold = 20
        apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "play", {"slug": "hooded_executioner", "boost": True}))
        self.assertIsNone(match.instance(weak2.id))
        self.assertIsNone(match.instance(weak3.id))
        self.assertIsNotNone(match.instance(strong2.id))

    def test_a_duel_never_asks_for_its_one_opponent(self) -> None:
        engine, game, match = new_game(first=2)
        begin(engine, game, match)
        hero_in_play(match, 2)
        brother = put(match, 1, "older_brother")
        match.player(2).hand = ["discord"]
        match.player(2).gold = 5
        apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "play", {"slug": "discord"}))
        self.assertIs(pending_prompt(engine, game, match).kind, PromptKind.MAIN_ACTION)
        self.assertEqual(engine.unit_stats(brother, match), (0, 1))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

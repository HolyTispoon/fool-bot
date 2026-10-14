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


def end_turn(engine, game, match) -> str:
    """The active player ends their main phase, locks no patrollers, and
    the turn runs on to the next player's main phase -- the tech choice
    each player owes settled with no picks, as staging. What was said."""
    heard = [said(apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "end_main")))]
    heard.append(said(apply(engine, game, match, Action(PromptKind.PATROL, arguments={"assignment": {}}))))
    while match.winner is None:
        for player in match.players:
            player.tech_owed = False
        owed = owed_step(engine, game, match)
        if owed is None:
            break
        heard.append(said(driver.advance(engine, game, match, StepResult(next=owed))))
    return "\n".join(heard)


def attack_base(engine, game, match, against: int) -> str:
    """The active player's Iron Man attacks `against`'s base."""
    unit = put(match, match.active, "iron_man")
    heard = [said(apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "attack", {"attacker": unit.ref})))]
    heard.append(said(apply(engine, game, match, Action(
        PromptKind.CHOOSE_DEFENDER, arguments={"defender": "base", "against": against},
    ))))
    return "\n".join(heard)


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

    def test_the_dragon_is_not_offered_yet(self) -> None:
        with self.assertRaises(RuleRefusal):
            CodexGame("g", 1).set_variant("two_headed_dragon")

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
        self.assertEqual(prompt.ask, f"{tokens.player(1)} wins: the opposing base is destroyed.")
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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

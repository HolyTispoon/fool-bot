"""
The two-headed dragon through the driver (docs/codex-multiplayer.md,
step 5): the teams and the deal, the team's turn with two seats acting in
one main phase, the attack priorities over both patrol zones, and the
words "you" and "friendly" -- each staged by slug and played through
`driver.apply`.

The rules are Rulebook p. 13 (with p. 4, 5 and 11 where a test says so)
and the General group's overpower and tower rulings, Captured
Bugblatter's, Drakk Ramhorn's and Moment's Peace's.
"""

from __future__ import annotations

import unittest

from codex import history
from codex.components import MatchState
from codex.engine import DRAGON_BASE_HP, RulesEngine
from codex.flow import StepResult, driver
from codex.game import CodexGame, RuleRefusal
from codex.prompts import (
    Action, PendingPrompt, PromptKind, SeveralAsked, owed_step, pending, pending_all,
    pending_prompt, pending_prompts, standing_prompts,
)

from codex_positions import begin, built, hero_in_play, new_game, put

FOUR = (("bashing",), ("finesse",), ("bashing",), ("finesse",))
DRAGON = "two_headed_dragon"


def dragon(teams=FOUR, first=1, seed=7):
    """A dragon dealt and standing on the first team's turn."""
    return new_game(seed=seed, first=first, teams=teams, variant=DRAGON)


def settle(engine, game, match):
    """Run the steps the bot owes until somebody is asked something."""
    while True:
        owed = pending_all(engine, game, match)[0]
        if isinstance(owed, PendingPrompt):
            return match
        driver.advance(engine, game, match, StepResult(next=owed))


def started(teams=FOUR, first=1, seed=7):
    """A dragon dealt and standing on the first team's main phase."""
    engine, game, match = dragon(teams, first, seed)
    settle(engine, game, match)
    return engine, game, match


def act(engine, game, match, kind, choice="", **arguments):
    """One action through the driver, which must apply."""
    run = driver.apply(engine, game, match, Action(kind, choice, arguments))
    assert not isinstance(run, driver.Refusal), run.reason
    return run


def refused(engine, game, match, kind, choice="", **arguments) -> driver.Refusal:
    run = driver.apply(engine, game, match, Action(kind, choice, arguments))
    assert isinstance(run, driver.Refusal), "the action was applied"
    return run


def asked(engine, game, match):
    """Who is asked what, as `(kind, seat)` pairs."""
    return [(one.kind, one.asked_player) for one in pending_all(engine, game, match)
            if isinstance(one, PendingPrompt)]


def lock(engine, game, match, seat, assignment=None):
    act(engine, game, match, PromptKind.MAIN_ACTION, "end_main", player=seat)
    return act(engine, game, match, PromptKind.PATROL, player=seat, assignment=assignment or {})


def end_team_turn(engine, game, match):
    """Both teammates of the team on turn lock nothing, and the turn runs
    on to the next team's main phase (their tech, if any, settled)."""
    for seat in engine.turn_seats(match):
        lock(engine, game, match, seat)
    for _ in range(8):
        for player in match.players:
            if player.seat not in engine.turn_seats(match):
                player.tech_owed = False
        settle(engine, game, match)
        waiting = pending_all(engine, game, match)
        if all(one.kind is PromptKind.MAIN_ACTION for one in waiting):
            return
        for one in waiting:
            if one.kind is PromptKind.TECH_CONFIRM:
                act(engine, game, match, PromptKind.TECH_CONFIRM, "confirm", player=one.asked_player)
            elif one.kind is PromptKind.TECH_CHOICE:
                picks = [slug for slug, count in one.options.codex for _ in range(count)][:2]
                act(engine, game, match, PromptKind.TECH_CHOICE, player=one.asked_player, picks=picks)


class DealTests(unittest.TestCase):
    """The teams and the deal (Rulebook p. 13)."""

    def test_four_seats_in_two_teams_with_one_base_of_thirty_each(self) -> None:
        engine, game, match = dragon()
        self.assertEqual(match.dragons, [[1, 2], [3, 4]])
        self.assertEqual(engine.dragon_of(match, 2), (1, 2))
        self.assertEqual(engine.teammate(match, 3), 4)
        self.assertEqual(engine.opponents(match, 1), (3, 4))
        self.assertEqual([match.base_of(seat) for seat in (1, 2, 3, 4)], [DRAGON_BASE_HP] * 4)
        self.assertEqual(DRAGON_BASE_HP, 30)
        match.validate(engine.catalog)

    def test_the_first_team_starts_with_four_workers_each_and_the_other_five(self) -> None:
        """Rulebook p. 13: each player on the team that goes first starts
        with 4 workers, each on the other with 5."""
        for first in (1, 3):
            engine, game, match = dragon(first=first)
            going = engine.dragon_of(match, first)
            for player in match.players:
                self.assertEqual(player.workers, 4 if player.seat in going else 5)
            self.assertEqual(match.first, going[0])
            self.assertEqual(match.active, going[0])

    def test_the_first_team_is_drawn_when_not_given(self) -> None:
        engine = RulesEngine(seed=5)
        match = engine.new_match([["bashing"], ["finesse"], ["bashing"], ["finesse"]],
                                 variant=DRAGON)
        self.assertIn(match.first, (1, 3))

    def test_the_bases_are_one_reading(self) -> None:
        """A team's base is its head's `base_hp`; the second seat's is
        never read (decision 9)."""
        engine, game, match = dragon()
        match.set_base(2, 24)
        self.assertEqual(match.player(1).base_hp, 24)
        self.assertEqual(match.base_of(1), 24)
        self.assertEqual(match.base_of(2), 24)
        self.assertEqual(match.base_of(3), 30)

    def test_no_mercenary_is_owed_and_no_addition_is_listed(self) -> None:
        """Nothing of the free-for-all's three additions is on a dragon."""
        engine, game, match = dragon()
        self.assertTrue(all(player.mercenaries_owed == 0 for player in match.players))
        begin(engine, game, match)
        self.assertIsNone(engine.repair_option(match))
        self.assertEqual(engine.lending_zones(match), ())

    def test_the_dragons_are_saved_and_a_duel_saves_none(self) -> None:
        engine, game, match = dragon()
        saved = match.to_dict()
        self.assertEqual(saved["dragons"], [[1, 2], [3, 4]])
        self.assertEqual(MatchState.from_dict(saved).dragons, [[1, 2], [3, 4]])
        _, _, duel = new_game()
        for key in ("dragons", "solo"):
            self.assertNotIn(key, duel.to_dict())
        for player in duel.to_dict()["players"]:
            self.assertNotIn("locked", player)
            self.assertNotIn("locking", player)

    def test_a_dragon_needs_four_seats_in_two_teams(self) -> None:
        engine, game, match = dragon()
        match.dragons = [[1, 2], [3, 3]]
        with self.assertRaises(ValueError):
            match.validate(engine.catalog)
        _, _, duel = new_game()
        duel.dragons = [[1, 2]]
        with self.assertRaises(ValueError):
            duel.validate(engine.catalog)


class AddOnTests(unittest.TestCase):
    """A team never holds two of the same add-on (Rulebook p. 13)."""

    def test_the_build_options_refuse_the_teammates_add_on(self) -> None:
        from codex.components import AddOnState

        engine, game, match = dragon()
        begin(engine, game, match)
        match.player(2).add_on = AddOnState(slug="tower", hp=4, under_construction=True)
        mine = match.player(1)
        option = engine.build_option(mine, "tower", match)
        self.assertFalse(option.allowed)
        self.assertIn("teammate", option.why_not)
        self.assertTrue(engine.build_option(mine, "surplus", match).why_not != option.why_not)
        # The other team's add-on is nothing to do with it.
        match.player(3).add_on = AddOnState(slug="surplus", hp=4)
        self.assertNotIn("teammate", engine.build_option(mine, "surplus", match).why_not)


class SeeingTests(unittest.TestCase):
    """What a teammate may see: the hand, the codex and the tech choice,
    and nothing else (decision 13)."""

    def test_team_sees_names_the_teammate_in_a_dragon_and_nobody_in_a_duel(self) -> None:
        engine, game, match = dragon()
        self.assertEqual(engine.team_sees(match, 1), 2)
        self.assertEqual(engine.team_sees(match, 4), 3)
        _, _, duel = new_game()
        self.assertIsNone(engine.team_sees(duel, 1))

    def test_hands_visible_to_folds_it_in_beside_a_reveal(self) -> None:
        engine, game, match = dragon()
        self.assertEqual(engine.hands_visible_to(match, 1), (2,))
        put(match, 1, "eyes_of_the_chancellor")
        self.assertEqual(engine.hands_visible_to(match, 1), (2, 3, 4))

    def test_the_codex_and_the_tech_choice_are_shown_to_a_teammate_alone(self) -> None:
        engine, game, match = dragon()
        match.player(2).tech_choice = ["iron_man"]
        self.assertEqual(engine.tech_picks_of(match, 1, 2), ["iron_man"])
        self.assertEqual(engine.tech_picks_of(match, 2, 2), ["iron_man"])
        self.assertTrue(engine.codex_remaining(match, 2, viewer=1))
        self.assertTrue(engine.own_deck(match, 2, viewer=1).cards)
        for foe in (3, 4):
            with self.assertRaises(RuleRefusal) as refused:
                engine.tech_picks_of(match, 1, foe)
            self.assertEqual(refused.exception.cite, "Rulebook p. 13")
            with self.assertRaises(RuleRefusal):
                engine.codex_remaining(match, foe, viewer=1)
            with self.assertRaises(RuleRefusal):
                engine.own_deck(match, foe, viewer=1)
        # In a duel nobody sees the other's.
        _, _, duel = new_game()
        with self.assertRaises(RuleRefusal):
            engine.codex_remaining(duel, 2, viewer=1)


class TeamTurnTests(unittest.TestCase):
    """The team's turn: two seats acting in one main phase (decision 8)."""

    def test_the_turn_opens_on_both_teammates_main_phases(self) -> None:
        engine, game, match = dragon()
        settle(engine, game, match)
        self.assertEqual(engine.turn_seats(match), (1, 2))
        self.assertEqual(engine.acting_seats(match), (1, 2))
        self.assertEqual(asked(engine, game, match),
                         [(PromptKind.MAIN_ACTION, 1), (PromptKind.MAIN_ACTION, 2)])
        # Both collected their own gold in the team's upkeep.
        self.assertEqual([match.player(seat).gold for seat in (1, 2)], [4, 4])
        self.assertEqual([match.player(seat).gold for seat in (3, 4)], [0, 0])
        # One snapshot for the team's turn.
        self.assertEqual(history.latest_snapshot(match)["turn"], 1)

    def test_pending_prompt_raises_where_two_seats_are_asked(self) -> None:
        engine, game, match = started()
        with self.assertRaises(SeveralAsked):
            pending_prompt(engine, game, match)
        self.assertEqual([one.asked_player for one in pending_prompts(engine, game, match)], [1, 2])
        self.assertEqual(pending(engine, game, match, 2).asked_player, 2)
        self.assertIsNone(pending(engine, game, match, 3))
        self.assertEqual(pending(engine, game, match).asked_player, 1)

    def test_each_prompt_carries_its_own_seats_options(self) -> None:
        """Every reading is made on the asked seat's behalf: their hand,
        their gold."""
        engine, game, match = started()
        first, second = pending_prompts(engine, game, match)
        self.assertEqual({row.slug for row in first.options.hand}, set(match.player(1).hand))
        self.assertEqual({row.slug for row in second.options.hand}, set(match.player(2).hand))
        self.assertIn("4", first.ask)

    def test_a_teammate_hires_with_their_own_gold_and_the_journal_names_the_seat(self) -> None:
        engine, game, match = started()
        slug = match.player(2).hand[0]
        act(engine, game, match, PromptKind.MAIN_ACTION, "hire", slug=slug, player=2)
        self.assertEqual((match.player(1).workers, match.player(2).workers), (4, 5))
        self.assertEqual((match.player(1).gold, match.player(2).gold), (4, 3))
        entry = match.journal[-1]["action"]
        self.assertEqual(entry["arguments"]["player"], 2)
        # Between actions the team's head is active again.
        self.assertEqual(match.active, 1)
        self.assertEqual(asked(engine, game, match),
                         [(PromptKind.MAIN_ACTION, 1), (PromptKind.MAIN_ACTION, 2)])

    def test_an_action_naming_no_seat_is_the_active_seats(self) -> None:
        """An older journal names none: read as the active seat's, and
        journalled with it filled in."""
        engine, game, match = started()
        slug = match.player(1).hand[0]
        act(engine, game, match, PromptKind.MAIN_ACTION, "hire", slug=slug)
        self.assertEqual((match.player(1).workers, match.player(2).workers), (5, 4))
        self.assertEqual(match.journal[-1]["action"]["arguments"]["player"], 1)

    def test_a_duels_journal_names_no_seat(self) -> None:
        engine, game, match = new_game()
        begin(engine, game, match)
        act(engine, game, match, PromptKind.MAIN_ACTION, "hire", slug=match.player(1).hand[0])
        self.assertNotIn("player", match.journal[-1]["action"]["arguments"])

    def test_a_seat_cannot_answer_for_another_team(self) -> None:
        engine, game, match = started()
        run = refused(engine, game, match, PromptKind.MAIN_ACTION, "end_main", player=3)
        self.assertIn("moved on", run.reason)

    def test_the_other_teammate_waits_on_an_attack_under_way(self) -> None:
        """While one teammate's attack stands half-resolved the team's
        question is that one alone, and the other's click is refused with
        why (decision 8)."""
        engine, game, match = started()
        unit = put(match, 1, "iron_man")
        act(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=unit.ref, player=1)
        self.assertEqual(asked(engine, game, match), [(PromptKind.CHOOSE_DEFENDER, 1)])
        self.assertEqual(match.active, 1)
        run = refused(engine, game, match, PromptKind.MAIN_ACTION, "end_main", player=2)
        self.assertIn("{player:1}'s attack", run.reason)
        act(engine, game, match, PromptKind.CHOOSE_DEFENDER, "cancel", player=1)
        self.assertEqual(asked(engine, game, match),
                         [(PromptKind.MAIN_ACTION, 1), (PromptKind.MAIN_ACTION, 2)])

    def test_the_second_teammates_attack_runs_with_them_active(self) -> None:
        engine, game, match = started()
        unit = put(match, 2, "iron_man")
        act(engine, game, match, PromptKind.MAIN_ACTION, "attack", attacker=unit.ref, player=2)
        self.assertEqual(match.active, 2)
        self.assertEqual(asked(engine, game, match), [(PromptKind.CHOOSE_DEFENDER, 2)])
        act(engine, game, match, PromptKind.CHOOSE_DEFENDER, "cancel", player=2)
        self.assertEqual(match.active, 1)

    def test_a_lock_ends_that_seats_actions_and_the_second_ends_the_phase(self) -> None:
        engine, game, match = started()
        lock(engine, game, match, 1)
        self.assertTrue(match.player(1).locked)
        self.assertEqual(engine.turn_seats(match), (1, 2))
        self.assertEqual(engine.acting_seats(match), (2,))
        self.assertEqual(asked(engine, game, match), [(PromptKind.MAIN_ACTION, 2)])
        self.assertEqual(match.phase, "main")
        refused(engine, game, match, PromptKind.MAIN_ACTION, "hire", slug="x", player=1)
        # The second lock runs the draw and the tech phase for both.
        run = lock(engine, game, match, 2)
        self.assertEqual([step.name for step in run.steps], ["DRAW_PHASE", "BEGIN_TECH", "BEGIN_TURN"])
        said = " ".join(line for group in run.groups for line in group.narration) + " ".join(run.result.narration)
        self.assertIn("{player:1} discards 5 and draws 5", said)
        self.assertIn("{player:2} discards 5 and draws 5", said)
        self.assertEqual(said.count("**End of turn 1**"), 1)
        self.assertIn("{player:1} (Bashing) and {player:2} (Finesse)", said)

    def test_the_turn_passes_to_the_other_teams_head_and_both_owe_their_tech(self) -> None:
        engine, game, match = started()
        end_team_turn(engine, game, match)
        self.assertEqual(match.active, 3)
        self.assertEqual(match.turn, 2)
        self.assertEqual(engine.turn_seats(match), (3, 4))
        self.assertEqual(asked(engine, game, match),
                         [(PromptKind.MAIN_ACTION, 3), (PromptKind.MAIN_ACTION, 4)])

    def test_both_teammates_tech_choices_stand_through_the_other_teams_turn(self) -> None:
        engine, game, match = started()
        for seat in (1, 2):
            lock(engine, game, match, seat)
        settle(engine, game, match)
        standing = standing_prompts(engine, match, game)
        self.assertEqual([(one.kind, one.asked_player) for one in standing],
                         [(PromptKind.TECH_CHOICE, 1), (PromptKind.TECH_CHOICE, 2)])
        for one in standing:
            slugs = [slug for slug, count in one.options.codex for _ in range(count)][:2]
            act(engine, game, match, PromptKind.TECH_CHOICE, player=one.asked_player, picks=slugs)
        # Their turn: both confirmations stand, and the turn begins on both.
        for seat in (3, 4):
            lock(engine, game, match, seat)
        settle(engine, game, match)
        self.assertEqual(asked(engine, game, match),
                         [(PromptKind.TECH_CONFIRM, 1), (PromptKind.TECH_CONFIRM, 2)])
        self.assertEqual([(one.kind, one.asked_player) for one in standing_prompts(engine, match, game)],
                         [(PromptKind.TECH_CHOICE, 3), (PromptKind.TECH_CHOICE, 4)])
        act(engine, game, match, PromptKind.TECH_CONFIRM, "confirm", player=1)
        # The turn waits on the other confirmation.
        self.assertEqual(asked(engine, game, match), [(PromptKind.TECH_CONFIRM, 2)])
        self.assertIsInstance(pending_all(engine, game, match)[0], PendingPrompt)
        act(engine, game, match, PromptKind.TECH_CONFIRM, "confirm", player=2)
        settle(engine, game, match)
        self.assertEqual(asked(engine, game, match),
                         [(PromptKind.MAIN_ACTION, 1), (PromptKind.MAIN_ACTION, 2)])
        self.assertEqual([match.player(seat).teched is not None for seat in (1, 2)], [True, True])

    def test_the_turn_is_both_teammates_for_every_turns_reading(self) -> None:
        """Frenzy's ATK and the rest ask `turn_seats`, which a locked
        teammate stays in."""
        engine, game, match = started()
        lock(engine, game, match, 1)
        self.assertEqual(engine.turn_seats(match), (1, 2))
        self.assertEqual(engine.opponents(match, 1), (3, 4))

    def test_an_extra_turn_is_one_seats_alone(self) -> None:
        """Rulebook p. 13: "you means you" -- Double Time's extra turn is
        the caster's, and the teammate neither readies nor acts."""
        engine, game, match = started()
        match.extra_turns.append(2)
        put(match, 1, "iron_man", exhausted=True)
        mate = put(match, 1, "iron_man", exhausted=True)
        end_team_turn(engine, game, match)
        self.assertEqual(match.solo, 2)
        self.assertEqual(match.active, 2)
        self.assertEqual(engine.turn_seats(match), (2,))
        self.assertEqual(engine.acting_seats(match), (2,))
        self.assertEqual(asked(engine, game, match), [(PromptKind.MAIN_ACTION, 2)])
        self.assertTrue(match.player(1).instance(mate.id).exhausted)
        # It ends like any turn: the other team's head is next.
        lock(engine, game, match, 2)
        for player in match.players:
            player.tech_owed = False
        settle(engine, game, match)
        self.assertIsNone(match.solo)
        self.assertEqual(match.active, 3)
        self.assertEqual(engine.turn_seats(match), (3, 4))


class EndingTests(unittest.TestCase):
    """A destroyed base ends the game for the team; a concession and a
    debt are the team's too (Rulebook p. 13; questions 17 and 5)."""

    def test_a_destroyed_base_is_the_other_teams_win(self) -> None:
        from codex.flow import turn

        engine, game, match = started()
        result = StepResult()
        match.set_base(3, 1)
        turn.damage_base(match, 4, 5, result)
        self.assertEqual(match.base_of(3), 0)
        self.assertEqual(match.winner, 1)
        self.assertIn("{player:3} and {player:4}'s base is destroyed. {player:1} and {player:2} win!",
                      result.narration[0])
        over = pending(engine, game, match)
        self.assertIs(over.kind, PromptKind.GAME_OVER)
        self.assertEqual(over.options.winners, (1, 2))
        self.assertIn("{player:1} and {player:2} win", over.ask)

    def test_a_concession_is_the_conceding_teams(self) -> None:
        from codex.flow import turn

        engine, game, match = started()
        turn.concede(engine, game, match, 4)
        self.assertEqual((match.winner, match.conceded), (1, 3))
        over = pending(engine, game, match)
        self.assertEqual(over.options.winners, (1, 2))
        self.assertIn("{player:3}'s team conceded", over.ask)

    def test_a_teammate_who_cannot_pay_a_debt_loses_it_for_the_team(self) -> None:
        from codex.flow import turn

        engine, game, match = started()
        match.player(2).debt = 5
        match.player(2).gold = 0
        result = StepResult()
        turn._pay_debt(match, 2, result)
        self.assertEqual((match.winner, match.lost_by_debt), (3, 2))
        self.assertIn("{player:3} and {player:4} win!", result.narration[0])


class UndoTests(unittest.TestCase):
    """The undos work over the team turn's snapshot and journal
    (decision 15)."""

    def test_to_the_start_of_the_turn_takes_back_either_teammates_actions(self) -> None:
        engine, game, match = started()
        act(engine, game, match, PromptKind.MAIN_ACTION, "hire", slug=match.player(1).hand[0], player=1)
        act(engine, game, match, PromptKind.MAIN_ACTION, "hire", slug=match.player(2).hand[0], player=2)
        self.assertEqual((match.player(1).workers, match.player(2).workers), (5, 5))
        history.undo_to_turn_start(match)
        self.assertEqual((match.player(1).workers, match.player(2).workers), (4, 4))
        self.assertEqual(asked(engine, game, match),
                         [(PromptKind.MAIN_ACTION, 1), (PromptKind.MAIN_ACTION, 2)])

    def test_the_fine_undo_offers_every_point_of_the_team_turn(self) -> None:
        engine, game, match = started()
        act(engine, game, match, PromptKind.MAIN_ACTION, "hire", slug=match.player(1).hand[0], player=1)
        act(engine, game, match, PromptKind.MAIN_ACTION, "hire", slug=match.player(2).hand[0], player=2)
        points = history.undo_points(engine, game, match)
        self.assertEqual([point.choice for point in points], ["hire"])
        history.undo_to(engine, game, match, points[0].index)
        self.assertEqual((match.player(1).workers, match.player(2).workers), (5, 4))
        self.assertEqual(match.active, 1)

    def test_the_end_of_the_turn_is_taken_back_by_either_player_of_the_team(self) -> None:
        engine, game, match = started()
        for seat in (1, 2):
            lock(engine, game, match, seat)
        settle(engine, game, match)
        self.assertEqual(match.turn, 2)
        self.assertEqual(history.end_of_turn_owners(engine, game, match), (1, 2))
        said = history.undo_end_of_turn(engine, game, match)
        self.assertEqual(match.turn, 1)
        self.assertEqual(match.active, 1)
        self.assertEqual(said[-1], history.UNDONE_END)

    def test_the_take_back_closes_once_the_next_team_has_acted(self) -> None:
        engine, game, match = started()
        for seat in (1, 2):
            lock(engine, game, match, seat)
        settle(engine, game, match)
        act(engine, game, match, PromptKind.MAIN_ACTION, "hire", slug=match.player(4).hand[0], player=4)
        self.assertEqual(history.end_of_turn_owners(engine, game, match), ())

    def test_undo_to_the_turn_start_asks_both_teammates_tech_again(self) -> None:
        engine, game, match = started()
        for seat in (1, 2):
            lock(engine, game, match, seat)
        settle(engine, game, match)
        for one in standing_prompts(engine, match, game):
            slugs = [slug for slug, count in one.options.codex for _ in range(count)][:2]
            act(engine, game, match, PromptKind.TECH_CHOICE, player=one.asked_player, picks=slugs)
        for seat in (3, 4):
            lock(engine, game, match, seat)
        settle(engine, game, match)
        act(engine, game, match, PromptKind.TECH_CONFIRM, "confirm", player=1)
        act(engine, game, match, PromptKind.TECH_CONFIRM, "confirm", player=2)
        settle(engine, game, match)
        history.undo_to_turn_start(match)
        self.assertEqual(asked(engine, game, match),
                         [(PromptKind.TECH_CONFIRM, 1), (PromptKind.TECH_CONFIRM, 2)])


if __name__ == "__main__":
    unittest.main()

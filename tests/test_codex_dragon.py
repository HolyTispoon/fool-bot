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

from codex import effects, history
from codex.components import AddOnState, MatchState
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
        self.assertEqual(over.ask, "{player:1} and {player:2} win!")

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


def rows_of(engine, match, attacker):
    """The defenders an attacker has, as `(seat, ref)` pairs in the order
    the prompt lists them (its options)."""
    found = []
    for foe in engine.opponents(match, match.active):
        for ref, _ in engine.defender_rows(match, attacker, against=foe):
            found.append((foe, ref))
    return found


class AttackingTests(unittest.TestCase):
    """The attack priorities over both patrol zones (Rulebook p. 13)."""

    def setUp(self) -> None:
        self.engine, self.game, self.match = started()
        self.attacker = put(self.match, 1, "iron_man")

    def rows(self):
        return rows_of(self.engine, self.match, self.attacker.ref)

    def test_facing_two_squad_leaders_the_attacker_chooses_which(self) -> None:
        first = put(self.match, 3, "iron_man", patrol="squad_leader")
        second = put(self.match, 4, "iron_man", patrol="squad_leader")
        put(self.match, 3, "iron_man", patrol="elite")
        put(self.match, 4, "iron_man")
        self.assertEqual(self.rows(), [(3, first.ref), (4, second.ref)])

    def test_a_squad_leader_comes_before_the_partners_other_patrollers(self) -> None:
        leader = put(self.match, 3, "iron_man", patrol="squad_leader")
        put(self.match, 4, "iron_man", patrol="elite")
        self.assertEqual(self.rows(), [(3, leader.ref)])

    def test_then_any_patroller_of_either_zone(self) -> None:
        one = put(self.match, 3, "iron_man", patrol="elite")
        two = put(self.match, 4, "iron_man", patrol="lookout")
        put(self.match, 3, "iron_man")
        self.assertEqual(self.rows(), [(3, one.ref), (4, two.ref)])

    def test_a_players_buildings_are_safe_while_the_partners_patroller_could_be_hit(self) -> None:
        """Rulebook p. 13: a player with an empty patrol zone is protected
        by the partner's patroller."""
        guard = put(self.match, 4, "iron_man", patrol="elite")
        built(self.match, 3, "tech1")
        self.assertEqual(self.rows(), [(4, guard.ref)])

    def test_with_no_patrol_anything_with_hp_and_the_shared_base_once(self) -> None:
        hero_in_play(self.match, 3)
        unit = put(self.match, 4, "iron_man")
        built(self.match, 3, "tech1")
        rows = self.rows()
        self.assertEqual(sorted(ref for _, ref in rows if ref == "base"), ["base"])
        self.assertEqual(sum(1 for _, ref in rows if ref == "base"), 1)
        self.assertIn((4, unit.ref), rows)
        self.assertIn((3, "tech1"), rows)
        self.assertIn((3, "hero:" + self.match.player(3).heroes[0].slug), rows)

    def test_the_base_is_one_row_however_many_seats_defend(self) -> None:
        rows = self.rows()
        self.assertEqual([row for row in rows if row[1] == "base"], [(3, "base")])

    def test_the_prompt_lists_each_row_with_its_seat(self) -> None:
        guard = put(self.match, 4, "iron_man", patrol="squad_leader")
        act(self.engine, self.game, self.match, PromptKind.MAIN_ACTION, "attack",
            attacker=self.attacker.ref, player=1)
        (prompt,) = pending_prompts(self.engine, self.game, self.match)
        self.assertIs(prompt.kind, PromptKind.CHOOSE_DEFENDER)
        self.assertEqual(list(zip(prompt.options.seats, prompt.options.defenders)), [(4, guard.ref)])
        run = act(self.engine, self.game, self.match, PromptKind.CHOOSE_DEFENDER, player=1,
                  defender=guard.ref)
        self.assertIn("attacks", " ".join(run.result.narration))
        self.assertTrue(self.match.player(4).instance(guard.id).damage)

    def test_a_row_the_pool_does_not_offer_is_refused(self) -> None:
        put(self.match, 3, "iron_man", patrol="squad_leader")
        built(self.match, 4, "tech1")
        act(self.engine, self.game, self.match, PromptKind.MAIN_ACTION, "attack",
            attacker=self.attacker.ref, player=1)
        run = refused(self.engine, self.game, self.match, PromptKind.CHOOSE_DEFENDER,
                      player=1, defender="tech1", against=4)
        self.assertIn("squad leader", run.reason)

    def test_damage_to_the_shared_base_comes_off_it_once(self) -> None:
        act(self.engine, self.game, self.match, PromptKind.MAIN_ACTION, "attack",
            attacker=self.attacker.ref, player=1)
        act(self.engine, self.game, self.match, PromptKind.CHOOSE_DEFENDER, player=1,
            defender="base")
        self.assertEqual(self.match.base_of(3), 30 - 3)
        self.assertEqual(self.match.base_of(4), 27)
        self.assertEqual(self.match.winner, None)


def stealthy(card):
    """The card has stealth for the turn, as Sneaky Pig's grant gives it."""
    card.modifiers.append({"kind": "keyword", "keyword": "Stealth", "until": "end_of_turn"})
    return card


class TowerTests(unittest.TestCase):
    """The tower: a team has one (never two of the same add-on, Rulebook
    p. 13) and it detects and deals its damage for the whole team (the
    author, 2026-10-14)."""

    def setUp(self) -> None:
        self.engine, self.game, self.match = started()
        self.attacker = stealthy(put(self.match, 1, "iron_man"))
        self.match.player(4).add_on = AddOnState(slug="tower", hp=4, under_construction=False)

    def attack(self, defender, against):
        from codex.flow import combat

        return combat.declare_attack(self.engine, self.game, self.match, self.attacker.ref,
                                     defender, against=against)

    def said(self, result) -> str:
        return " ".join(result.narration)

    def test_the_teams_tower_detects_an_attack_on_either_players_card(self) -> None:
        for seat in (3, 4):
            engine, game, match = started()
            attacker = stealthy(put(match, 1, "iron_man"))
            match.player(4).add_on = AddOnState(slug="tower", hp=4, under_construction=False)
            victim = put(match, seat, "older_brother")
            from codex.flow import combat

            result = combat.declare_attack(engine, game, match, attacker.ref, victim.ref, against=seat)
            self.assertEqual(match.player(4).add_on.detected, attacker.ref, seat)
            self.assertIn("{player:4}'s tower detects", " ".join(result.narration))

    def test_an_attack_on_the_shared_base_is_detected_too(self) -> None:
        self.attack("base", 3)
        self.assertEqual(self.match.player(4).add_on.detected, self.attacker.ref)

    def test_the_damage_falls_on_an_attacker_of_anything_the_team_controls(self) -> None:
        mate = put(self.match, 3, "older_brother")
        said = self.said(self.attack(mate.ref, 3))
        self.assertEqual(said.count("tower deals 1"), 1)
        self.assertIn("{player:4}'s tower deals 1", said)

    def test_a_team_with_no_tower_is_detected_by_nobody(self) -> None:
        self.match.player(4).add_on = None
        mate = put(self.match, 3, "older_brother")
        self.assertNotIn("tower", self.said(self.attack(mate.ref, 3)))
        self.assertIsNone(self.engine.team_tower(self.match, 3))

    def test_the_tower_detects_on_its_owners_turn_for_the_teammate(self) -> None:
        engine, game, match = started()
        match.player(2).add_on = AddOnState(slug="tower", hp=4, under_construction=False)
        hidden = stealthy(put(match, 3, "iron_man"))
        option = engine.detect_option(match)             # seat 1, whose teammate built it
        self.assertTrue(option.allowed)
        self.assertIn(hidden.ref, option.candidates)
        act(engine, game, match, PromptKind.MAIN_ACTION, "detect", card=hidden.ref, player=1)
        self.assertEqual(match.player(2).add_on.detected, hidden.ref)

    def test_a_duels_one_tower_is_unchanged(self) -> None:
        from codex.flow import combat

        engine, game, match = new_game()
        begin(engine, game, match)
        match.player(2).add_on = AddOnState(slug="tower", hp=4, under_construction=False)
        attacker = put(match, 1, "iron_man")
        victim = put(match, 2, "older_brother")
        result = combat.declare_attack(engine, game, match, attacker.ref, victim.ref)
        self.assertEqual(" ".join(result.narration).count("tower deals"), 1)


class OverpowerTests(unittest.TestCase):
    def test_the_excess_may_go_to_the_attacked_teams_other_seat(self) -> None:
        """The overpower ruling: "controlled by the player (or team in
        2v2) whose patroller was attacked"."""
        engine, game, match = started()
        reaper = put(match, 1, "harvest_reaper")       # 6/5, overpower
        leader = put(match, 3, "tenderfoot", patrol="squad_leader")
        near = put(match, 3, "tenderfoot", patrol="elite")
        far = put(match, 4, "tenderfoot", patrol="elite")
        from codex.flow import combat

        combat.declare_attack(engine, game, match, reaper.ref, leader.ref, against=3)
        candidates = engine.overpower_team(match, reaper.ref, leader.ref)
        self.assertEqual(set(candidates), {near.ref, f"4:{far.ref}"})
        prompt = pending(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.OVERPOWER_TARGET)
        run = act(engine, game, match, PromptKind.OVERPOWER_TARGET, player=1, target=f"4:{far.ref}")
        self.assertIn("Overpower carries", " ".join(run.result.narration))
        self.assertIsNone(match.player(4).instance(far.id))
        self.assertIsNotNone(match.player(3).instance(near.id))

    def test_the_teams_other_patrollers_come_before_anything_else_of_theirs(self) -> None:
        """Sirlin's priority, read over the team: with a patroller left in
        either zone the excess goes to a patroller, not to a building."""
        engine, game, match = started()
        reaper = put(match, 1, "harvest_reaper")
        leader = put(match, 3, "tenderfoot", patrol="squad_leader")
        far = put(match, 4, "tenderfoot", patrol="elite")
        built(match, 3, "tech1")
        put(match, 4, "tenderfoot")
        match.against = 3        # the attack is declared against seat 3
        self.assertEqual(engine.overpower_team(match, reaper.ref, leader.ref), (f"4:{far.ref}",))
        match.player(4).instance(far.id).patrol_slot = None
        candidates = engine.overpower_team(match, reaper.ref, leader.ref)
        self.assertIn("tech1", candidates)
        self.assertIn("base", candidates)
        self.assertEqual(sum(1 for one in candidates if one.endswith("base")), 1)

    def test_a_duels_candidates_are_unchanged(self) -> None:
        engine, game, match = new_game()
        begin(engine, game, match)
        reaper = put(match, 1, "harvest_reaper")
        leader = put(match, 2, "tenderfoot", patrol="squad_leader")
        put(match, 2, "tenderfoot", patrol="elite")
        self.assertEqual(engine.overpower_team(match, reaper.ref, leader.ref),
                         engine.overpower_candidates(match, reaper.ref, leader.ref))


class PeaceTests(unittest.TestCase):
    def test_moments_peace_protects_its_casters_cards_and_the_shared_base(self) -> None:
        """Its ruling: the caster's cards and the shared base, not the
        teammate's cards."""
        engine, game, match = started()
        attacker = put(match, 1, "iron_man")
        mine = put(match, 3, "older_brother")
        mate = put(match, 4, "older_brother")
        match.player(4).peace = True
        rows = rows_of(engine, match, attacker.ref)
        self.assertIn((3, mine.ref), rows)
        self.assertNotIn((4, mate.ref), rows)
        self.assertFalse([row for row in rows if row[1] == "base"], "the shared base is at peace")
        match.player(4).peace = False
        self.assertTrue([row for row in rows_of(engine, match, attacker.ref) if row[1] == "base"])

    def test_a_unit_may_attack_while_any_opponent_is_not_at_peace(self) -> None:
        engine, game, match = started()
        attacker = put(match, 1, "iron_man")
        match.player(3).peace = True
        self.assertIn(attacker.ref, engine.attackers(match))
        match.player(4).peace = True
        self.assertNotIn(attacker.ref, engine.attackers(match))


class OneBaseTests(unittest.TestCase):
    def test_a_building_destroyed_deals_its_two_to_the_teams_base(self) -> None:
        from codex.flow import board

        engine, game, match = started()
        built(match, 4, "tech1", hp=1)
        board.damage_building(match, 4, "tech1", 1, StepResult())
        self.assertEqual(match.base_of(3), 28)
        self.assertEqual(match.base_of(4), 28)
        match.player(3).add_on = AddOnState(slug="tower", hp=1, under_construction=False)
        board.damage_building(match, 3, "add_on", 1, StepResult())
        self.assertEqual(match.base_of(4), 26)

    def test_captured_bugblatter_hits_the_one_base_and_asks_nothing(self) -> None:
        """Its ruling: "an opponent's base" is the team's one."""
        from codex.flow import board, resolve

        engine, game, match = started()
        put(match, 1, "captured_bugblatter")
        cub = put(match, 3, "older_brother")
        match.active = 3
        board.destroy(engine, match, [(3, cub.ref)], StepResult())
        resolve.run(engine, match, StepResult())
        self.assertEqual(match.base_of(3), 29, "on an opponent's turn, the active player's base")
        match.active = 1
        other = put(match, 4, "older_brother")
        board.destroy(engine, match, [(4, other.ref)], StepResult())
        resolve.run(engine, match, StepResult())
        self.assertEqual(match.base_of(3), 28)
        self.assertEqual(asked(engine, game, match)[0][0], PromptKind.MAIN_ACTION)

    def test_each_opposing_base_is_the_one_base_once(self) -> None:
        from codex.flow import resolve

        engine, game, match = started()
        resolve.push(match, resolve.frame("drakk_ramhorn", 1, "Drakk", origin="drakk_ramhorn"))
        resolve.run(engine, match, StepResult())
        self.assertEqual(match.base_of(3), 29)

    def test_targets_list_the_shared_base_once(self) -> None:
        engine, game, match = started()
        rows = engine.target_candidates(match, 1, "base")
        self.assertEqual(len([row for row in rows if row[1] == "base"]), 2, rows)
        self.assertEqual({engine.dragon_of(match, seat) for seat, _ in rows}, {(1, 2), (3, 4)})


class LevelTests(unittest.TestCase):
    def test_a_dead_heros_levels_go_to_either_of_the_other_teams_heroes(self) -> None:
        """Rulebook p. 11: any of the other team's, the active player
        choosing."""
        from codex.flow import board

        engine, game, match = started()
        hero_in_play(match, 1)
        hero_in_play(match, 3, level=1)
        hero_in_play(match, 4, level=1)
        board.destroy(engine, match, [(1, "hero:" + match.player(1).heroes[0].slug)], StepResult())
        from codex.flow import resolve

        resolve.run(engine, match, StepResult())
        prompt = pending(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.LEVEL_GAIN)
        self.assertEqual(sorted(set(prompt.options.seats)), [3, 4])


def targets_of(engine, match, seat, effect, part=0):
    """The keys a part of `effect` may choose for `seat`."""
    row = effects.EFFECTS[effect].parts[part]
    return {one.key for one in engine.target_rows(match, seat, row)}


class FriendlyTests(unittest.TestCase):
    """"Friendly" is the teammate's too; "your" is the controller's alone
    (Rulebook p. 13: "you means you"). The fourteen cards and bands that
    say "friendly" carry `Part.friendly`; the audit is text beside flag
    in `FRIENDLY_TEXT`."""

    #: Every card or band whose text says "friendly", and the effect part
    #: that carries the flag (None where it is read by an engine reading
    #: instead of a target filter).
    FRIENDLY_TEXT = {
        "aged_sensei": "aged_sensei",
        "bloom": "bloom",
        "eyes_of_the_chancellor": "eyes_of_the_chancellor",
        "focus_master": None,
        "forests_favor": "forests_favor",
        "fuzz_cuddles": None,
        "helpful_turtle": None,
        "savior_monk": None,
        "sparring_partner": "sparring_partner",
        "spirit_of_the_panda": None,
        "verdant_tree": None,
        "max_geiger": "max_geiger_max",
        "orpal_gloor": "orpal_gloor_max",
        "vandy_anadrose": "vandy_anadrose_max",
    }

    def test_the_audit_is_every_card_and_band_that_says_friendly(self) -> None:
        from codex.cards import catalog

        said = set()
        for slug, card in catalog().cards.items():
            if any("riendly" in line for line in card.text):
                said.add(slug)
        for slug, hero in catalog().heroes.items():
            if any("riendly" in line for band in hero.bands for line in band.text):
                said.add(slug)
        self.assertEqual(said, set(self.FRIENDLY_TEXT))
        self.assertEqual(len(said), 14)
        for slug, effect in self.FRIENDLY_TEXT.items():
            if effect is None:
                continue
            flagged = [part for part in effects.EFFECTS[effect].parts if part.friendly]
            self.assertTrue(flagged, f"{effect} says friendly but no part carries it")

    def test_no_part_flags_a_text_that_says_your(self) -> None:
        flagged = {key for key, effect in effects.EFFECTS.items()
                   if any(part.friendly for part in effect.parts)}
        self.assertEqual(flagged, {effect for effect in self.FRIENDLY_TEXT.values() if effect})

    def test_aged_sensei_buffs_a_teammates_unit_or_hero(self) -> None:
        engine, game, match = started()
        mate = put(match, 2, "iron_man")
        mine = put(match, 1, "iron_man")
        foe = put(match, 3, "iron_man")
        hero_in_play(match, 2)
        keys = targets_of(engine, match, 1, "aged_sensei")
        self.assertIn(f"2:{mate.ref}", keys)
        self.assertIn(f"1:{mine.ref}", keys)
        self.assertIn("2:hero:" + match.player(2).heroes[0].slug, keys)
        self.assertNotIn(f"3:{foe.ref}", keys)

    def test_elite_training_says_your_and_is_the_controllers_alone(self) -> None:
        engine, game, match = started()
        mate = put(match, 2, "iron_man")
        mine = put(match, 1, "iron_man")
        keys = targets_of(engine, match, 1, "elite_training")
        self.assertIn(f"1:{mine.ref}", keys)
        self.assertNotIn(f"2:{mate.ref}", keys)

    def test_bloom_and_the_other_runes_reach_a_teammates_unbloomed(self) -> None:
        engine, game, match = started()
        mate = put(match, 2, "iron_man")
        blooming = put(match, 2, "iron_man")
        blooming.plus_runes = 1
        for effect in ("bloom", "forests_favor", "sparring_partner"):
            keys = targets_of(engine, match, 1, effect)
            self.assertIn(f"2:{mate.ref}", keys, effect)
            self.assertNotIn(f"2:{blooming.ref}", keys, effect)

    def test_a_charge_says_your_and_stays_the_controllers(self) -> None:
        engine, game, match = started()
        mate = put(match, 2, "iron_man")
        mine = put(match, 1, "iron_man")
        keys = targets_of(engine, match, 1, "charge")
        self.assertEqual(keys, {f"1:{mine.ref}"})
        self.assertNotIn(f"2:{mate.ref}", keys)

    def test_eyes_of_the_chancellor_and_max_geiger_choose_a_friendly_unit(self) -> None:
        engine, game, match = started()
        mate = put(match, 2, "iron_man")
        for effect in ("eyes_of_the_chancellor", "max_geiger_max"):
            self.assertIn(f"2:{mate.ref}", targets_of(engine, match, 1, effect), effect)

    def test_vandys_friendly_unit_may_be_the_teammates_and_the_opposing_one_is_not(self) -> None:
        engine, game, match = started()
        mate = put(match, 2, "tenderfoot")
        foe = put(match, 3, "tenderfoot")
        friend = targets_of(engine, match, 1, "vandy_anadrose_max", 0)
        opposing = targets_of(engine, match, 1, "vandy_anadrose_max", 1)
        self.assertIn(f"2:{mate.ref}", friend)
        self.assertNotIn(f"3:{foe.ref}", friend)
        self.assertEqual(opposing, {f"3:{foe.ref}"})

    def test_orpal_gloors_friendly_is_relative_to_the_dead_unit(self) -> None:
        """"Two units friendly to the dead unit": the dead unit's
        controller's and that controller's teammate's -- not the
        controller of the effect's."""
        engine, game, match = started()
        part = effects.EFFECTS["orpal_gloor_max"].parts[0]
        dead_side = put(match, 3, "iron_man")
        mate_of_dead = put(match, 4, "iron_man")
        other = put(match, 1, "iron_man")
        rows = engine.target_rows(match, 1, part, frame={"against": 3, "taken": []})
        keys = {row.key for row in rows}
        self.assertEqual(keys, {f"3:{dead_side.ref}", f"4:{mate_of_dead.ref}"})
        self.assertNotIn(f"1:{other.ref}", keys)

    def test_focus_master_protects_the_teammates_units(self) -> None:
        from codex.flow import board

        engine, game, match = started()
        master = put(match, 2, "focus_master")
        master.runes[effects.FOCUS] = 1
        ward = put(match, 1, "iron_man")
        # Exactly lethal: its HP.
        hp = engine.body_stats(match, ward)[1]
        self.assertEqual(board.focus_prevents(engine, match, ward, hp), hp - 1)
        self.assertEqual(master.runes[effects.FOCUS], 0)

    def test_healing_reaches_the_teammates_units_and_heroes(self) -> None:
        """Fuzz Cuddles and the rest: "heal 2 damage from all friendly
        units and heroes", at their controller's upkeep."""
        from codex.flow import turn

        engine, game, match = started()
        put(match, 1, "fuzz_cuddles")
        mate = put(match, 2, "iron_man", damage=3)
        foe = put(match, 3, "iron_man", damage=3)
        hero_in_play(match, 2, damage=2)
        result = StepResult()
        turn._upkeep_effect(engine, match, 1, "healing", result)
        self.assertEqual(mate.damage, 1)
        self.assertEqual(foe.damage, 3)
        self.assertEqual(match.player(2).heroes[0].damage, 0)

    def test_a_teammates_healing_does_not_heal_for_you(self) -> None:
        from codex.flow import turn

        engine, game, match = started()
        put(match, 2, "fuzz_cuddles")
        mine = put(match, 1, "iron_man", damage=3)
        turn._upkeep_effect(engine, match, 1, "healing", StepResult())
        self.assertEqual(mine.damage, 3)

    def test_mythmakings_malus_is_an_opponents_legendary_units_alone(self) -> None:
        from codex.cards import catalog

        legend = next(slug for slug, card in catalog().cards.items()
                      if card.is_unit and "Legendary" in card.type and (card.atk or 0) >= 2)
        mythmaking = next(iter(effects.MYTHMAKING))
        engine, game, match = started()
        put(match, 1, mythmaking)
        mate = put(match, 2, legend)
        foe = put(match, 3, legend)
        base_mate = engine.catalog.cards[legend]
        self.assertEqual(engine.unit_stats(mate, match), (base_mate.atk, base_mate.hp))
        self.assertEqual(engine.unit_stats(foe, match), (base_mate.atk - 1, base_mate.hp - 1))


class YouMeansYouTests(unittest.TestCase):
    """Nobody spends a teammate's gold, uses a teammate's abilities or
    patrols in a teammate's zone (Rulebook p. 13): each is impossible by
    construction, and these hold it."""

    def test_nobody_spends_a_teammates_gold(self) -> None:
        engine, game, match = started()
        match.player(1).gold = 0
        match.player(2).gold = 9
        slug = match.player(1).hand[0]
        run = refused(engine, game, match, PromptKind.MAIN_ACTION, "hire", slug=slug, player=1)
        self.assertIn("gold", run.reason.lower())
        self.assertEqual(match.player(2).gold, 9)

    def test_nobody_uses_a_teammates_ability(self) -> None:
        engine, game, match = started()
        mate = put(match, 2, "aged_sensei")
        options = pending(engine, game, match, 1).options
        self.assertFalse([row for row in options.abilities if row.source == mate.ref])
        run = refused(engine, game, match, PromptKind.MAIN_ACTION, "ability",
                      ability="aged_sensei", source=mate.ref, player=1)
        self.assertTrue(run.reason)

    def test_nobody_patrols_in_a_teammates_zone(self) -> None:
        engine, game, match = started()
        card = put(match, 1, "iron_man")
        self.assertEqual(engine.lending_zones(match), ())
        act(engine, game, match, PromptKind.MAIN_ACTION, "end_main", player=1)
        run = refused(engine, game, match, PromptKind.PATROL, player=1, assignment={},
                      lent={"2": {"elite": card.ref}})
        self.assertIn("free-for-all", run.reason)

    def test_a_teammates_card_is_not_among_the_cards_you_can_patrol_with(self) -> None:
        engine, game, match = started()
        mate = put(match, 2, "iron_man")
        mine = put(match, 1, "iron_man")
        act(engine, game, match, PromptKind.MAIN_ACTION, "end_main", player=1)
        (prompt,) = [one for one in pending_prompts(engine, game, match) if one.asked_player == 1]
        self.assertIn(mine.ref, prompt.options.candidates)
        self.assertNotIn(mate.ref, prompt.options.candidates)
        run = refused(engine, game, match, PromptKind.PATROL, player=1,
                      assignment={"elite": mate.ref})
        self.assertIn("ready units", run.reason)


if __name__ == "__main__":
    unittest.main()

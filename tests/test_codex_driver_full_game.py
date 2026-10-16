"""
A whole game of Codex -- Bashing against Finesse -- played through
`codex.flow.driver` alone, from the deal to a destroyed base: no cog, no
view, no Discord (docs/codex-bot.md, step 2's deliverable).

It does what a frontend would: read `pending_prompt` and the standing
prompts, build a legal action off the prompt's options the way a view
builds its buttons, hand it to `driver.apply`, save, reload, and go
again; where the bot owes a step, run it as the service's resume will.
Both players are one policy, deliberately simple -- it hires when it
can until it has ten workers (beyond which a worker buys nothing in the
basic game) -- never with a spell, which it keeps for its hero -- builds
the next tech building when it can, summons the hero, plays the cheapest
playable card -- a unit before a spell of the same cost, and since step
6 the spells do what they say -- levels the hero, attacks with
everything that has a legal defender (the base where it may) and
patrols everything ready, and techs the lowest-tech units first. A question an effect asks takes the first
thing offered, which is the opponent's where there is one.

**Every position round-trips** through `to_dict`/`from_dict` and
`validate` before the next action is built, which is the restart
written as a loop.

Run it with `-v` and it prints the game's narration: the transcript the
author reads for its wording (the step's stop).
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from codex import tokens
from codex.components import PATROL_SLOTS, MatchState
from codex.engine import RulesEngine
from codex.flow import StepResult
from codex.flow import driver
from codex.formatting import plain_token
from codex.game import CodexGame
from codex.prompts import (
    Action,
    PromptKind,
    owed_step,
    pending_prompt,
    pending_prompts,
    standing_prompts,
)

#: Chosen so the game is decided well inside the bound; the test that
#: names it says so if a change to the rules moves the ending.
SEED = 20261008
#: A game this policy plays ends long before this many turns.
TURN_LIMIT = 60

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _tech_picks(engine: RulesEngine, options) -> list[str]:
    """The lowest-tech units first, then everything else."""
    def order(row):
        card = engine.catalog.cards[row[0]]
        return (0 if card.is_unit else 1, card.tech_level or 0, card.cost or 0)

    picks = []
    for slug, count in sorted(options.codex, key=order):
        for _ in range(count):
            if len(picks) < options.maximum:
                picks.append(slug)
    return picks


def choose(engine: RulesEngine, match: MatchState, prompt) -> Action:
    """The policy: one legal action, read off the prompt's options."""
    options = prompt.options
    kind = prompt.kind
    if kind is PromptKind.TECH_CHOICE:
        return Action(kind, arguments={"player": prompt.asked_player,
                                       "picks": _tech_picks(engine, options)})
    if kind is PromptKind.TECH_CONFIRM:
        return Action(kind, "confirm", {"player": prompt.asked_player})
    if kind is PromptKind.OBLITERATE_CHOICE:
        return Action(kind, arguments={"unit": options.units[0]})
    if kind is PromptKind.SPARKSHOT_TARGET:
        return Action(kind, arguments={"patroller": options.patrollers[0]})
    if kind is PromptKind.OVERPOWER_TARGET:
        return Action(kind, arguments={"target": options.targets[0]})
    if kind is PromptKind.CHOOSE_DEFENDER:
        at = options.defenders.index("base") if "base" in options.defenders else 0
        arguments = {"defender": options.defenders[at]}
        if len(set(options.seats)) > 1:
            # A table of several: whose (the multiplayer worksheet).
            arguments["against"] = options.seats[at]
        return Action(kind, arguments=arguments)
    if kind is PromptKind.TARGET:
        # "Up to" and "you may" (step 11): the first thing offered, until
        # the part has chosen as many as it must, then Done.
        if options.done and (options.picked or not options.targets):
            return Action(kind, "done")
        return Action(kind, arguments={"target": options.targets[0].key})
    if kind is PromptKind.DIVIDE_DAMAGE:
        return Action(kind, arguments={"target": options.split[0][0]})
    if kind is PromptKind.STASH:
        return Action(kind, "none")
    if kind is PromptKind.CHOOSE_NUMBER:
        return Action(kind, arguments={"number": 3})
    if kind is PromptKind.OATH:
        return Action(kind, arguments={"oath": "draw"})
    if kind is PromptKind.MODE_CHOICE:
        return Action(kind, arguments={"mode": options.modes[0][0]})
    if kind is PromptKind.APPEL_STOMP_TOP:
        return Action(kind, "discard")
    if kind is PromptKind.UPKEEP_ORDER:
        return Action(kind, arguments={"first": options.effects[0]})
    if kind is PromptKind.LEVEL_GAIN:
        arguments = {"hero": options.heroes[0]}
        if len(set(options.seats)) > 1:
            arguments["seat"] = options.seats[0]
        return Action(kind, arguments=arguments)
    if kind is PromptKind.PATROL:
        assignment = dict(zip(PATROL_SLOTS, options.candidates))
        return Action(kind, arguments={"assignment": assignment})
    # The main phase: the asked seat's, which in a dragon is either teammate's.
    player = match.player(prompt.asked_player)
    if options.hire.allowed and player.workers < 10:
        playable = {row.slug for row in options.playable if row.allowed}
        # A spell is kept for the hero to cast; anything else not
        # playable is what a worker is hired with.
        spare = ([slug for slug in player.hand if slug not in playable
                  and not engine.catalog.cards[slug].is_spell]
                 or [slug for slug in player.hand if slug not in playable] or player.hand)
        return Action(kind, "hire", {"slug": spare[-1]})
    for row in options.buildings:
        if row.building.startswith("tech") and row.allowed:
            arguments = {"building": row.building}
            # A standard game's Tech II -- and a tech lab -- chooses a
            # spec: the first offered, and the lab's a different one.
            if row.specs:
                arguments["spec"] = row.specs[0]
            if row.lab_specs:
                arguments["lab_spec"] = next(spec for spec in row.lab_specs if spec != row.specs[0])
            return Action(kind, "build", arguments)
    for hero in options.heroes:
        if hero.action == "summon" and hero.allowed:
            return Action(kind, "summon", {"hero": hero.slug})
    cards = sorted(
        (row for row in options.playable if row.allowed),
        key=lambda row: (row.cost, not engine.catalog.cards[row.slug].is_unit, row.slug),
    )
    if cards:
        return Action(kind, "play", {"slug": cards[0].slug})
    for hero in options.heroes:
        if hero.action == "level" and hero.allowed and hero.max_levels:
            return Action(kind, "level", {"levels": hero.max_levels, "hero": hero.slug})
    if options.attackers:
        return Action(kind, "attack", {"attacker": options.attackers[0]})
    return Action(kind, "end_main")


#: The standard game step 10's second game plays: three red heroes
#: against three green, each on its own colour's deck.
STANDARD_TEAMS = (["fire", "anarchy", "blood"], ["feral", "growth", "balance"])
STANDARD_SEED = 20261009
#: Step 12's third game: three purple heroes against three black.
PURPLE_BLACK_TEAMS = (["past", "present", "future"], ["demonology", "disease", "necromancy"])
PURPLE_BLACK_SEED = 20261010
#: Step 13's fourth game: three white heroes against three blue.
WHITE_BLUE_TEAMS = (["discipline", "ninjutsu", "strength"], ["law", "peace", "truth"])
WHITE_BLUE_SEED = 20261011


def numbered_seats(specs):
    """A multiplayer test's seats: (user id, name, spec) for each spec in
    seat order -- 101 "player1", 202 "player2", ... -- as the whole-game
    test and the golden seat them."""
    for number, spec in enumerate(specs, start=1):
        yield 100 * number + number, f"player{number}", spec


def answer(engine: RulesEngine, match: MatchState, prompt) -> Action:
    """The policy's answer to `prompt`, naming the seat asked in a dragon,
    where two teammates are asked at once (docs/design/codex.md,
    "Multiplayer"); a duel's and a free-for-all's name none."""
    action = choose(engine, match, prompt)
    if match.dragons:
        action = Action(action.kind, action.choice,
                        {**action.arguments, "player": prompt.asked_player})
    return action


def play(seed: int = SEED, *, say=None, teams=None, players=None, dragon=None,
         turn_limit: int = TURN_LIMIT, max_steps: int = 20000) -> tuple[RulesEngine, CodexGame, MatchState, list[str]]:
    """Play a whole game -- Bashing against Finesse, or a standard game
    of `teams` -- and return the engine, the record, the final match and
    the transcript in plain words. `players`, a spec per seat, plays a
    basic free-for-all of three to five (docs/codex-multiplayer.md,
    step 2), the policy playing every seat; `dragon`, four teams (one
    spec each in a basic game, three in a standard one), a two-headed
    dragon (step 5) in which the policy answers whichever seat is asked,
    the two teammates' questions in turn."""
    engine = RulesEngine(seed=seed)
    game = CodexGame("codex-full-game", 1, variant="two_headed_dragon" if dragon is not None else "duel")
    if dragon is not None:
        if len(dragon[0]) == 3:
            game.set_mode("standard")
        for user_id, name, team in numbered_seats(dragon):
            game.take_seat(user_id, name, list(team))
    elif players is not None:
        game.set_variant("free_for_all")
        for user_id, name, spec in numbered_seats(players):
            game.take_seat(user_id, name, spec)
    elif teams is None:
        game.take_seat(101, "basher", "bashing")
        game.take_seat(202, "fencer", "finesse")
    else:
        game.set_mode("standard")
        game.take_seat(101, "first", teams[0])
        game.take_seat(202, "second", teams[1])
    game.start(engine)
    match = MatchState.from_dict(game.match_state)
    transcript: list[str] = []

    def golds() -> dict[int, int]:
        return {player.seat: player.gold for player in match.players}

    def heard(run, before: dict[int, int]) -> None:
        lines = [line for group in run.groups for line in group.narration]
        lines += run.result.narration
        # Every change to a player's gold is said with where it now
        # stands -- "{gold:3} left" or "now {gold:5}" (the author,
        # 2026-10-16): the last line that moved it ends on the total.
        said = " ".join(lines)
        for seat, gold in golds().items():
            if gold != before.get(seat, gold):
                assert f"{{gold:{gold}}} left" in said or f"now {{gold:{gold}}}" in said, (
                    f"seat {seat}'s gold went from {before[seat]} to {gold} unsaid: {lines}"
                )
        for line in lines:
            if line:
                plain = tokens.render(line, plain_token)
                transcript.append(plain)
                if say:
                    say(plain)

    def reload(current: MatchState) -> MatchState:
        saved = current.to_dict()
        loaded = MatchState.from_dict(json.loads(json.dumps(saved)))
        loaded.validate(engine.catalog)
        assert loaded.to_dict() == saved, "a match did not round-trip"
        return loaded

    steps = 0
    while match.winner is None and match.turn <= turn_limit and steps < max_steps:
        steps += 1
        assert steps < 20000, "the game is not making progress"
        owed = owed_step(engine, game, match)
        if owed is not None:
            before = golds()
            heard(driver.advance(engine, game, match, StepResult(next=owed)), before)
            match = reload(match)
            continue
        # The other player's tech choice, answered once it is offered.
        for standing in standing_prompts(engine, match, game):
            if match.player(standing.asked_player).tech_choice is None:
                before = golds()
                run = driver.apply(engine, game, match, choose(engine, match, standing))
                assert not isinstance(run, driver.Refusal), run
                heard(run, before)
                match = reload(match)
        if match.dragons:
            # Both teammates are asked at once; the policy answers them in
            # turn, so their actions interleave in one main phase.
            asked = pending_prompts(engine, game, match)
            prompt = asked[steps % len(asked)]
        else:
            prompt = pending_prompt(engine, game, match)
        action = answer(engine, match, prompt)
        before = golds()
        run = driver.apply(engine, game, match, action)
        assert not isinstance(run, driver.Refusal), (prompt.kind, run)
        heard(run, before)
        match = reload(match)
    game.match_state = match.to_dict()
    return engine, game, match, transcript


#: Run in a fresh interpreter: `unittest discover` has imported the cogs
#: and discord long before this test runs, so only a new process can
#: say the game needs neither.
ISOLATED = """
import sys
sys.path.insert(0, "tests")
import test_codex_driver_full_game as full
engine, game, match, transcript = full.play()
leaked = sorted(name for name in sys.modules
                if name == "discord" or name.startswith("discord.")
                or name == "cogs" or name.startswith("cogs."))
print(repr((match.winner, leaked)))
"""


class CodexFullGameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        verbose = "-v" in sys.argv or "--verbose" in sys.argv
        cls.engine, cls.game, cls.match, cls.transcript = play(
            say=print if verbose else None,
        )

    def test_a_base_is_destroyed_within_the_bound(self) -> None:
        self.assertIsNotNone(self.match.winner)
        self.assertLessEqual(self.match.turn, TURN_LIMIT)
        loser = self.match.player(RulesEngine().opponents(self.match, self.match.winner)[0])
        self.assertEqual(loser.base_hp, 0)

    def test_the_finished_game_waits_on_game_over(self) -> None:
        prompt = pending_prompt(self.engine, self.game, self.match)
        self.assertIs(prompt.kind, PromptKind.GAME_OVER)
        self.assertEqual(prompt.options.winner, self.match.winner)
        self.assertEqual(standing_prompts(self.engine, self.match, self.game), ())

    def test_the_game_used_the_board(self) -> None:
        """The policy reached what the step has to cover: tech built, the
        hero in play, patrollers, and units destroyed in combat."""
        kinds = {event["kind"] for event in self.match.events}
        for kind in ("hired", "built", "played", "summoned", "attacked",
                     "patrolled", "destroyed", "turn_ended"):
            self.assertIn(kind, kinds)
        # Step 6: the policy casts spells, and they do what they say.
        cast = {event["slug"] for event in self.match.events
                if event["kind"] == "played" and self.engine.catalog.cards[event["slug"]].is_spell}
        self.assertTrue(cast, "no spell was cast")

    def test_two_runs_on_one_seed_agree(self) -> None:
        _, _, again, transcript = play()
        self.assertEqual(again.to_dict(), self.match.to_dict())
        self.assertEqual(transcript, self.transcript)

    def test_nothing_hidden_is_said(self) -> None:
        """A hired worker's card and a tech choice are never named: the
        transcript names the hire and the choice, not the cards."""
        for line in self.transcript:
            if "hires a worker" in line or "their tech" in line:
                for slug in self.engine.catalog.cards:
                    name = self.engine.catalog.name(slug)
                    self.assertNotIn(f" {name} ", f" {line} ")

    def test_the_game_needs_no_frontend(self) -> None:
        probe = subprocess.run(
            [sys.executable, "-c", ISOLATED],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=300,
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        winner, leaked = ast.literal_eval(probe.stdout.strip().splitlines()[-1])
        self.assertIn(winner, (1, 2))
        self.assertEqual(leaked, [])


class CodexStandardGameTests(unittest.TestCase):
    """
    Step 10's second game: a standard one, three red heroes against
    three green, through the driver alone -- the policy summoning and
    levelling each hero, choosing the first spec offered at Tech II, and
    playing red and green cards -- each doing what it says since step 11
    -- to a destroyed base.
    """

    @classmethod
    def setUpClass(cls) -> None:
        verbose = "-v" in sys.argv or "--verbose" in sys.argv
        cls.engine, cls.game, cls.match, cls.transcript = play(
            STANDARD_SEED, teams=STANDARD_TEAMS, say=print if verbose else None,
        )

    def test_a_base_is_destroyed_within_the_bound(self) -> None:
        self.assertIsNotNone(self.match.winner)
        self.assertLessEqual(self.match.turn, TURN_LIMIT)
        self.assertEqual(self.match.player(RulesEngine().opponents(self.match, self.match.winner)[0]).base_hp, 0)

    def test_three_heroes_a_side(self) -> None:
        for player, team in zip(self.match.players, STANDARD_TEAMS):
            self.assertEqual(player.specs, tuple(team))
            self.assertEqual(len(player.heroes), 3)
        self.assertEqual(self.match.player(1).deck_color, "red")
        self.assertEqual(self.match.player(2).deck_color, "green")

    def test_the_game_used_the_standard_games_rules(self) -> None:
        """More than one hero summoned on a side, a Tech II with its spec,
        and red and green cards played -- each doing what it says since
        step 11, so none is said to be played for its numbers."""
        summoned = {}
        for event in self.match.events:
            if event["kind"] == "summoned":
                summoned.setdefault(event["seat"], set()).add(event["slug"])
        self.assertTrue(any(len(heroes) > 1 for heroes in summoned.values()), summoned)
        self.assertTrue(any(player.tech2_spec for player in self.match.players))
        played = {event["slug"] for event in self.match.events if event["kind"] == "played"}
        from codex import effects

        self.assertTrue(played & effects.RED and played & effects.GREEN)
        self.assertFalse(any("(its text is not played yet)" in line for line in self.transcript))

    def test_nothing_hidden_is_said(self) -> None:
        for line in self.transcript:
            if "hires a worker" in line or "their tech" in line:
                for slug in self.engine.catalog.cards:
                    name = self.engine.catalog.name(slug)
                    self.assertNotIn(f" {name} ", f" {line} ")


class CodexPurpleBlackGameTests(unittest.TestCase):
    """
    Step 12's third game: three purple heroes against three black -- the
    Vortoss Conclave against the Blackhand Scourge -- through the driver
    alone, to a destroyed base.
    """

    @classmethod
    def setUpClass(cls) -> None:
        verbose = "-v" in sys.argv or "--verbose" in sys.argv
        cls.engine, cls.game, cls.match, cls.transcript = play(
            PURPLE_BLACK_SEED, teams=PURPLE_BLACK_TEAMS, say=print if verbose else None,
        )

    def test_a_base_is_destroyed_within_the_bound(self) -> None:
        self.assertIsNotNone(self.match.winner)
        self.assertLessEqual(self.match.turn, TURN_LIMIT)
        loser = self.match.player(RulesEngine().opponents(self.match, self.match.winner)[0])
        self.assertTrue(loser.base_hp == 0)

    def test_three_heroes_a_side_on_their_colours(self) -> None:
        for player, team in zip(self.match.players, PURPLE_BLACK_TEAMS):
            self.assertEqual(player.specs, tuple(team))
        self.assertEqual(self.match.player(1).deck_color, "purple")
        self.assertEqual(self.match.player(2).deck_color, "black")

    def test_purple_and_black_cards_were_played(self) -> None:
        from codex import effects

        played = {event["slug"] for event in self.match.events if event["kind"] == "played"}
        self.assertTrue(played & effects.PURPLE and played & effects.BLACK)

    def test_nothing_hidden_is_said(self) -> None:
        for line in self.transcript:
            if "hires a worker" in line or "their tech" in line:
                for slug in self.engine.catalog.cards:
                    name = self.engine.catalog.name(slug)
                    self.assertNotIn(f" {name} ", f" {line} ")


class CodexWhiteBlueGameTests(unittest.TestCase):
    """
    Step 13's fourth game: three white heroes against three blue -- the
    Whitestar Order against the Flagstone Dominion -- through the driver
    alone, to a destroyed base.
    """

    @classmethod
    def setUpClass(cls) -> None:
        verbose = "-v" in sys.argv or "--verbose" in sys.argv
        cls.engine, cls.game, cls.match, cls.transcript = play(
            WHITE_BLUE_SEED, teams=WHITE_BLUE_TEAMS, say=print if verbose else None,
        )

    def test_a_base_is_destroyed_within_the_bound(self) -> None:
        self.assertIsNotNone(self.match.winner)
        self.assertLessEqual(self.match.turn, TURN_LIMIT)
        loser = self.match.player(RulesEngine().opponents(self.match, self.match.winner)[0])
        self.assertTrue(loser.base_hp == 0)

    def test_three_heroes_a_side_on_their_colours(self) -> None:
        for player, team in zip(self.match.players, WHITE_BLUE_TEAMS):
            self.assertEqual(player.specs, tuple(team))
        self.assertEqual(self.match.player(1).deck_color, "white")
        self.assertEqual(self.match.player(2).deck_color, "blue")

    def test_white_and_blue_cards_were_played(self) -> None:
        from codex import effects

        played = {event["slug"] for event in self.match.events if event["kind"] == "played"}
        self.assertTrue(played & effects.WHITE and played & effects.BLUE)

    def test_nothing_hidden_is_said(self) -> None:
        for line in self.transcript:
            if "hires a worker" in line or "their tech" in line:
                for slug in self.engine.catalog.cards:
                    name = self.engine.catalog.name(slug)
                    self.assertNotIn(f" {name} ", f" {line} ")


#: The free-for-all's whole games (docs/codex-multiplayer.md, step 2):
#: three players and five, basic, the policy playing every seat.
FFA_THREE = ("bashing", "finesse", "bashing")
FFA_THREE_SEED = SEED
FFA_FIVE = ("bashing", "finesse", "bashing", "finesse", "bashing")
FFA_FIVE_SEED = SEED
#: A table of five ends on a tie for the most base HP on this seed, and
#: the playoff decides it.
FFA_TIED_SEED = SEED
FFA_TURN_LIMIT = 120


class CodexFreeForAllGameTests(unittest.TestCase):
    """
    A free-for-all of three and one of five, through the driver alone,
    from the deal to a winner on base HP (Rulebook p. 14), with nothing
    from `cogs/` or `discord` imported; one of them reaches a tie and its
    playoff. Run with -v, the three-player game's transcript prints, turn
    by turn with the score at its end.
    """

    @classmethod
    def setUpClass(cls) -> None:
        verbose = "-v" in sys.argv or "--verbose" in sys.argv
        cls.three = play(FFA_THREE_SEED, players=FFA_THREE, turn_limit=FFA_TURN_LIMIT,
                         say=print if verbose else None)
        cls.five = play(FFA_FIVE_SEED, players=FFA_FIVE, turn_limit=FFA_TURN_LIMIT)
        cls.tied = cls.five if FFA_TIED_SEED == FFA_FIVE_SEED else play(
            FFA_TIED_SEED, players=FFA_FIVE, turn_limit=FFA_TURN_LIMIT,
        )

    def check_won_on_base_hp(self, played, count: int) -> None:
        engine, game, match, transcript = played
        self.assertEqual(len(match.players), count)
        self.assertEqual(match.variant, "free_for_all")
        self.assertIsNotNone(match.winner)
        self.assertLessEqual(match.turn, FFA_TURN_LIMIT)
        self.assertIn(0, [match.base_of(player.seat) for player in match.players])
        among = match.tied or [player.seat for player in match.players]
        self.assertEqual(match.base_of(match.winner), max(match.base_of(seat) for seat in among))
        prompt = pending_prompt(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.GAME_OVER)
        self.assertEqual(prompt.ask, f"{tokens.player(match.winner)} wins!")
        self.assertEqual(standing_prompts(engine, match, game), ())

    def test_three_players_to_a_winner(self) -> None:
        self.check_won_on_base_hp(self.three, 3)

    def test_five_players_to_a_winner(self) -> None:
        self.check_won_on_base_hp(self.five, 5)

    def test_every_seat_played_and_the_mercenaries_arrived(self) -> None:
        _, _, match, transcript = self.five
        seats = {event["seat"] for event in match.events if event["kind"] == "turn_ended"}
        self.assertEqual(seats, {1, 2, 3, 4, 5})
        made = [event for event in match.events
                if event["kind"] == "summoned_token" and event["slug"] == "mercenary"]
        self.assertEqual(len(made), 6)
        self.assertTrue(any("Mercenaries arrive" in line for line in transcript))

    def test_a_tie_is_played_off(self) -> None:
        _, _, match, transcript = self.tied
        self.assertTrue(match.tied, "the seed no longer reaches a tie")
        self.assertTrue(any(line.startswith("A tie at") for line in transcript))
        self.assertIn(match.winner, match.tied)

    def test_nothing_hidden_is_said(self) -> None:
        engine = self.three[0]
        for line in self.three[3] + self.five[3]:
            if "hires a worker" in line or "their tech" in line:
                for slug in engine.catalog.cards:
                    self.assertNotIn(f" {engine.catalog.name(slug)} ", f" {line} ")

    def test_the_game_needs_no_frontend(self) -> None:
        probe = subprocess.run(
            [sys.executable, "-c", ISOLATED.replace("full.play()", f"full.play(players={FFA_THREE!r})")],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=300,
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        winner, leaked = ast.literal_eval(probe.stdout.strip().splitlines()[-1])
        self.assertIn(winner, (1, 2, 3))
        self.assertEqual(leaked, [])


#: The two-headed dragon's whole games (docs/codex-multiplayer.md, step
#: 5): two teams of two, basic and standard, the policy answering the two
#: teammates' questions in turn.
DRAGON_BASIC = (("bashing",), ("finesse",), ("bashing",), ("finesse",))
DRAGON_BASIC_SEED = SEED
DRAGON_STANDARD = (
    ("fire", "anarchy", "blood"), ("feral", "growth", "balance"),
    ("past", "present", "future"), ("demonology", "disease", "necromancy"),
)
DRAGON_STANDARD_SEED = STANDARD_SEED
DRAGON_TURN_LIMIT = 120


class CodexDragonGameTests(unittest.TestCase):
    """
    A two-headed dragon, basic and standard, through the driver alone,
    from the deal to a destroyed base (Rulebook p. 13), with nothing from
    `cogs/` or `discord` imported: both teammates acting in one main
    phase, the policy answering whichever seat is asked.
    """

    @classmethod
    def setUpClass(cls) -> None:
        verbose = "-v" in sys.argv or "--verbose" in sys.argv
        cls.basic = play(DRAGON_BASIC_SEED, dragon=DRAGON_BASIC, turn_limit=DRAGON_TURN_LIMIT,
                         say=print if verbose else None)
        cls.standard = play(DRAGON_STANDARD_SEED, dragon=DRAGON_STANDARD, turn_limit=DRAGON_TURN_LIMIT)

    def check_won(self, played, heroes: int) -> None:
        engine, game, match, transcript = played
        self.assertEqual(match.variant, "two_headed_dragon")
        self.assertEqual(match.dragons, [[1, 2], [3, 4]])
        self.assertIsNotNone(match.winner)
        self.assertLessEqual(match.turn, DRAGON_TURN_LIMIT)
        losers = engine.opponents(match, match.winner)
        self.assertEqual(match.base_of(losers[0]), 0)
        self.assertEqual(match.base_of(losers[0]), match.base_of(losers[1]))
        self.assertTrue(all(len(player.heroes) == heroes for player in match.players))
        prompt = pending_prompt(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.GAME_OVER)
        self.assertEqual(prompt.options.winners, engine.dragon_of(match, match.winner))
        self.assertEqual(standing_prompts(engine, match, game), ())

    def test_a_basic_dragon_to_a_destroyed_base(self) -> None:
        self.check_won(self.basic, 1)

    def test_a_standard_dragon_to_a_destroyed_base(self) -> None:
        self.check_won(self.standard, 3)

    def test_teammates_act_in_one_main_phase(self) -> None:
        """Both teammates of a team took actions in the same turn, their
        own, between the team's upkeep and its lock."""
        _, _, match, _ = self.basic
        by_turn: dict[int, set] = {}
        for event in match.events:
            if event["kind"] in ("hired", "played", "built", "summoned", "attacked", "patrolled"):
                by_turn.setdefault(event["turn"], set()).add(event["seat"])
        both = [turn for turn, seats_ in by_turn.items() if len(seats_) == 2]
        self.assertTrue(both, by_turn)
        self.assertEqual({seat for turn_seats in by_turn.values() for seat in turn_seats}, {1, 2, 3, 4})

    def test_a_team_turn_reads_as_one_turn_with_two_players_actions(self) -> None:
        """The transcript's first turn: one end-of-turn line, naming both
        players, with both players' actions before it."""
        _, _, _, transcript = self.basic
        ends = [index for index, line in enumerate(transcript) if "End of turn" in line]
        first = transcript[:ends[0] + 1]
        self.assertEqual(sum("End of turn" in line for line in first), 1)
        for seat in (3, 4):
            self.assertTrue(any(f"Player {seat} " in line for line in first), seat)
        self.assertIn("Player 3 (Bashing) and Player 4 (Finesse)", transcript[ends[0]])

    def test_the_shared_base_is_named_for_the_team(self) -> None:
        _, _, _, transcript = self.basic
        bases = [line for line in transcript if "base is destroyed" in line]
        self.assertTrue(bases)
        self.assertTrue(all(" and Player " in line for line in bases), bases)
        hits = [line for line in transcript if "'s base" in line and " deals " in line]
        self.assertTrue(hits)
        self.assertTrue(all(" and Player " in line.split("'s base")[0] for line in hits), hits)

    def test_nothing_hidden_is_said(self) -> None:
        engine = self.basic[0]
        for line in self.basic[3] + self.standard[3]:
            if "hires a worker" in line or "their tech" in line:
                for slug in engine.catalog.cards:
                    self.assertNotIn(f" {engine.catalog.name(slug)} ", f" {line} ")

    def test_two_runs_on_one_seed_agree(self) -> None:
        _, _, again, transcript = play(DRAGON_BASIC_SEED, dragon=DRAGON_BASIC,
                                       turn_limit=DRAGON_TURN_LIMIT)
        self.assertEqual(again.to_dict(), self.basic[2].to_dict())
        self.assertEqual(transcript, self.basic[3])

    def test_a_team_turn_replays_from_its_snapshot_and_journal(self) -> None:
        """The journal of one team turn -- both teammates' actions -- rebuilds
        the position byte for byte (the undos stand on it)."""
        from codex import history

        for steps in range(60, 120, 7):
            engine, game, match, _ = play(DRAGON_BASIC_SEED, dragon=DRAGON_BASIC,
                                          turn_limit=DRAGON_TURN_LIMIT, max_steps=steps)
            seated = {entry["action"]["arguments"].get("player") for entry in match.journal}
            if {1, 2} <= seated or {3, 4} <= seated:
                break
        else:
            self.fail("no stopping point had both teammates acting in the journal")
        rebuilt = history.replay(
            engine, game, history.latest_snapshot(match), match.journal,
            history=match.turn_snapshots,
        )
        self.assertEqual(rebuilt.to_dict(), match.to_dict())

    def test_the_game_needs_no_frontend(self) -> None:
        probe = subprocess.run(
            [sys.executable, "-c", ISOLATED.replace(
                "full.play()", f"full.play(dragon={DRAGON_BASIC!r}, turn_limit={DRAGON_TURN_LIMIT})")],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=300,
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        winner, leaked = ast.literal_eval(probe.stdout.strip().splitlines()[-1])
        self.assertIn(winner, (1, 3))
        self.assertEqual(leaked, [])


if __name__ == "__main__":
    unittest.main()

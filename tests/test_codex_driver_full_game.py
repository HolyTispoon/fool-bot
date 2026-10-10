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
        defender = "base" if "base" in options.defenders else options.defenders[0]
        return Action(kind, arguments={"defender": defender})
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
        return Action(kind, arguments={"hero": options.heroes[0]})
    if kind is PromptKind.PATROL:
        assignment = dict(zip(PATROL_SLOTS, options.candidates))
        return Action(kind, arguments={"assignment": assignment})
    # The main phase.
    player = match.active_player
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


def play(seed: int = SEED, *, say=None, teams=None) -> tuple[RulesEngine, CodexGame, MatchState, list[str]]:
    """Play a whole game -- Bashing against Finesse, or a standard game
    of `teams` -- and return the engine, the record, the final match and
    the transcript in plain words."""
    engine = RulesEngine(seed=seed)
    game = CodexGame("codex-full-game", 1)
    if teams is None:
        game.take_seat(101, "basher", "bashing")
        game.take_seat(202, "fencer", "finesse")
    else:
        game.set_mode("standard")
        game.take_seat(101, "first", teams[0])
        game.take_seat(202, "second", teams[1])
    game.start(engine)
    match = MatchState.from_dict(game.match_state)
    transcript: list[str] = []

    def heard(run) -> None:
        lines = [line for group in run.groups for line in group.narration]
        lines += run.result.narration
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
    while match.winner is None and match.turn <= TURN_LIMIT:
        steps += 1
        assert steps < 20000, "the game is not making progress"
        owed = owed_step(engine, game, match)
        if owed is not None:
            heard(driver.advance(engine, game, match, StepResult(next=owed)))
            match = reload(match)
            continue
        # The other player's tech choice, answered once it is offered.
        for standing in standing_prompts(engine, match, game):
            if match.player(standing.asked_player).tech_choice is None:
                run = driver.apply(engine, game, match, choose(engine, match, standing))
                assert not isinstance(run, driver.Refusal), run
                heard(run)
                match = reload(match)
        prompt = pending_prompt(engine, game, match)
        run = driver.apply(engine, game, match, choose(engine, match, prompt))
        assert not isinstance(run, driver.Refusal), (prompt.kind, run)
        heard(run)
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
        loser = self.match.opponent(self.match.winner)
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
        self.assertEqual(self.match.opponent(self.match.winner).base_hp, 0)

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
        loser = self.match.opponent(self.match.winner)
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
        loser = self.match.opponent(self.match.winner)
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


if __name__ == "__main__":
    unittest.main()

"""
Gambits: which hand a coach holds, when a gambit's effect
fires, and what each of the six does.

Three layers, and they fail for different reasons:

- **The hand.** `RulesEngine.maneuver_tiers` is the only answer to who
  may play what, and the buttons, the card image and the click that
  answers all read it. A basic game is three cards; a coach holding
  their gambits has six.
- **The outright rule.** `gambit_benefit_applies` and
  `gambit_cost_applies` are two questions about two cards -- did
  *this* card win on the cards, did *this* one lose on them -- rather
  than one question about the matchup. They are asserted against the
  ways a maneuver lands rather than against a list of matchups: the
  injury cases are exactly the ones a list would get wrong, and one of
  them is what retired the single predicate.
- **The six effects.** Each is asserted on what it *does to the
  board*, since the wording is prose and will be revised. What is
  checked is every claim the card makes that the data could
  contradict.

See "Gambits" in docs/living-rules.md and the matrix in
docs/gambit-matrix.md.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import (
    ManeuverActionPromptView,
    SetupPassChoiceView,
)
from d12ball.ai import build_ai_strategies
from d12ball.cards import maneuver_hand_combinations
from d12ball.components import (
    CONTESTED_DECISIONS,
    DECISION_UNCONTESTED,
    EVENT_MANEUVER,
    MANEUVER_TIER_GAMBIT,
    MANEUVER_TIER_BASIC,
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.game import (
    AIOpponent,
    D12BallGame,
    GameMode,
    GameStatus,
    Team,
)

from roster import benched, fielded
from save_patches import suppressed_cog_saves


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.coin_emojis = {}
    cog.ai_strategies = build_ai_strategies(
        cog.player_catalog, cog.maneuver_catalog,
    )
    cog.engine = RulesEngine(
        cog.player_catalog,
        cog.basic_ruleset,
        cog.maneuver_catalog,
        cog.ai_strategies,
    )
    cog.refresh_match_image = mock.AsyncMock()
    cog.announce_board_update = mock.AsyncMock()
    cog.build_field_file = mock.AsyncMock(return_value=None)
    # The hand images are drawn once at startup, which `object.__new__`
    # skips; only the key matters here, not the bytes.
    cog.maneuver_hand_image_bytes = {
        hands: b"" for hands in maneuver_hand_combinations()
    }
    return cog


def build_game(**overrides) -> D12BallGame:
    fields = dict(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=111,
        player_2_id=222,
        player_1_name="One",
        player_2_name="Two",
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        status=GameStatus.IN_PROGRESS,
        home_player_number=1,
        visiting_player_number=2,
        mode=GameMode.ADVANCED,
    )
    fields.update(overrides)
    return D12BallGame(**fields)


def build_interaction() -> SimpleNamespace:
    # `attachments` because the prompts that carry a field strip go on
    # to ask for a full-image link off the message that went out.
    sent = SimpleNamespace(id=999, attachments=[])
    # `channel.send` and `followup.send` are the same mock: which route
    # a given post takes depends on whether the interaction still had a
    # response to give at that point in the cascade, and these tests
    # read back "everything this resolution posted" without caring which
    # route carried which message.
    send = mock.AsyncMock(return_value=sent)
    return SimpleNamespace(
        user=SimpleNamespace(id=111, display_name="One"),
        # A resolution that runs all the way through hands the turn
        # back to `send_turn_prompt`, which reads both of these.
        guild=None,
        channel=SimpleNamespace(send=send),
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
            is_done=lambda: True,
        ),
        followup=SimpleNamespace(send=send),
        edit_original_response=mock.AsyncMock(),
    )


def clear_the_defense_off_the_ball(match: MatchState) -> None:
    """
    Move every defender off the ball's space, so the maneuver can go
    unchallenged: a defender standing on the ball challenges, and
    `begin_uncontested_maneuver` refuses while one is there.
    """
    for player_id in list(
        match.board.spaces[match.ball.zone][match.ball.space_index]
    ):
        if player_id in match.visiting.field_players:
            match.move_meeple(
                player_id,
                Zone.VISITORS_GOAL,
                match.board.layout.zone_spaces[Zone.VISITORS_GOAL] - 1,
            )


def open_gambits(match: MatchState) -> None:
    """
    Put **both** coaches in a position that holds their gambits.

    Since 2026-09-20 a hand of six needs a reason (`GambitAccessTests`
    below is the rule's own suite), and every test above about *what a
    hand looks like* would otherwise be drawing three cards and
    asserting nothing. Both routes at once, one per side, because only
    one team can be trailing: home is a goal down, and the visitors
    field an injured player home does not.
    """
    match.scoreboard.visiting_score += 1
    match.mark_injured(sorted(match.visiting.field_players)[0])


class GambitHarness:
    """
    An advanced-mode game mid-maneuver: home in possession in midfield,
    a challenger from the visitors on the ball, and both cards picked.
    """

    def build(
        self,
        offense_key: str,
        defense_key: str,
        board_size: int = 7,
    ) -> tuple[D12Ball, D12BallGame, MatchState]:
        cog = build_cog()
        game = build_game(board_size=board_size)
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)

        handler = match.eligible_ball_handlers()[0]
        match.select_ball_handler(handler)
        challenger = min(
            match.visiting.field_players, key=match.distance_to_ball,
        )
        match.choose_challenger(challenger)
        match.choose_offense_maneuver(offense_key)
        match.choose_defense_maneuver(defense_key)
        game.match_state = match.to_dict()
        return cog, game, match

    def flat(self, match: MatchState) -> int:
        return match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )

    def flat_of(self, match: MatchState, player_id: str) -> int:
        return match.board.flat_index(
            *match.board.meeple_position(player_id)
        )

    def put_a_teammate_at(
        self,
        match: MatchState,
        distance: int,
        exclude: tuple[str, ...] = (),
    ) -> str:
        """
        Stand one of the passer's own side `distance` spaces ahead of
        the ball, and hand back who it is. The standard deal decides
        where everybody starts, and a test about a pass should not also
        be a test of the deal.

        `exclude` is for a test standing two teammates out, which is
        what a reach is asserted with: one inside it and one past it,
        and the second must not be the first walked somewhere else.
        """
        target = match.relative_flat_index(
            self.flat(match), match.ball.possession, distance,
        )
        zone, space_index = match.board.position_at_flat_index(target)
        teammate = [
            player_id
            for player_id in match.home.field_players
            if player_id != match.active_player_id
            and player_id not in exclude
        ][0]
        match.move_meeple(teammate, zone, space_index)
        return teammate


class ManeuverHandTests(GambitHarness, unittest.TestCase):
    """
    Which cards a coach is offered. `maneuver_tiers` is the only
    reading of it -- the pick buttons, the hand image and the click
    that answers all ask it, so a hand that disagreed with its own
    buttons would need three changes rather than one.
    """

    def test_a_basic_game_offers_three_cards(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        game.mode = GameMode.BASIC

        for side in ("offense", "defense"):
            with self.subTest(side=side):
                hand = cog.engine.maneuver_hand(game, match, side)
                self.assertEqual(
                    [m.key for m in hand],
                    [
                        m.key
                        for m in cog.maneuver_catalog.for_tier(
                            side, MANEUVER_TIER_BASIC,
                        )
                    ],
                )

    def test_a_coach_holding_gambits_is_offered_six_in_rank_order(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        open_gambits(match)

        hand = cog.engine.maneuver_hand(game, match, "offense")

        self.assertEqual(
            [m.key for m in hand],
            [
                "low_pass",
                "skilled_pass",
                "dribble_advance",
                "dribble_burst",
                "high_pass",
                "setup_pass",
            ],
        )

    def test_an_unchallenged_maneuver_is_basic_even_with_gambits_on(
        self,
    ) -> None:
        """
        The author: "Gambit can only be played when a
        maneuver is challenged." It is answerable at the moment the
        hand is drawn because every route into the unopposed branch
        settles it before the offense is prompted -- which also makes
        sending nobody a defensive weapon rather than only a saving.
        """
        cog, game, match = self.build("low_pass", "pressure")
        open_gambits(match)
        clear_the_defense_off_the_ball(match)
        match.offense_maneuver = None
        match.defense_maneuver = None
        match.challenger_id = None
        match.begin_uncontested_maneuver()

        for side in ("offense", "defense"):
            with self.subTest(side=side):
                self.assertEqual(
                    cog.engine.maneuver_tiers(game, match, side),
                    (MANEUVER_TIER_BASIC,),
                )

    def test_the_buttons_are_the_hand(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        open_gambits(match)
        cog.engine.load_match_state = mock.Mock(return_value=match)

        view = ManeuverActionPromptView(cog, game.game_id)
        keys = [
            item.custom_id.rsplit(":", 1)[1]
            for item in view.children
            if item.custom_id.startswith(
                f"d12ball:maneuver_pick:{game.game_id}:defense:"
            )
        ]

        self.assertEqual(
            keys,
            [
                m.key
                for m in cog.engine.maneuver_hand(game, match, "defense")
            ],
        )

    def test_the_full_image_link_sits_after_the_gambits(self) -> None:
        # discord.py drops a rowless button into the first row with
        # space, which on a prompt carrying gambits (a hand of two rows of
        # three) is between a side's basic and gambits.
        # `full_image_row` points it at the reference's row instead.
        import asyncio

        from cogs.d12ball_helpers import (
            FULL_IMAGE_BUTTON_LABEL,
            add_full_image_button,
        )

        cog, game, match = self.build("low_pass", "pressure")
        open_gambits(match)
        cog.engine.load_match_state = mock.Mock(return_value=match)

        view = ManeuverActionPromptView(cog, game.game_id)

        message = SimpleNamespace(
            attachments=[SimpleNamespace(url="https://cdn/hand.png")],
            edit=mock.AsyncMock(),
        )
        asyncio.run(
            add_full_image_button(
                message, view=view, row=view.full_image_row,
            )
        )

        rendered = [
            [component.get("label") for component in row["components"]]
            for row in message.edit.await_args.kwargs["view"].to_components()
        ]
        self.assertEqual(
            rendered[-1], ["Maneuver Reference", FULL_IMAGE_BUTTON_LABEL],
        )
        self.assertNotIn(
            FULL_IMAGE_BUTTON_LABEL,
            [label for row in rendered[:-1] for label in row],
        )


class GambitAccessTests(GambitHarness, unittest.TestCase):
    """
    **A gambit needs a reason** (the author, 2026-09-20): a coach holds
    their gambits only while their team is behind -- trailing on the
    scoreboard, or fielding more injured players than the opponent.

    Asserted through `maneuver_hand` as well as through the predicate,
    because the hand is what a coach actually gets: `maneuver_tiers`
    takes a side for this rule's sake, and a version of it that
    answered for the game rather than for the coach would pass every
    test of `may_play_gambits` and still deal six cards to the side in
    front.
    """

    def hands(self, cog, game, match) -> dict[str, int]:
        return {
            side: len(cog.engine.maneuver_hand(game, match, side))
            for side in ("offense", "defense")
        }

    def test_a_level_game_closes_both_hands(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")

        self.assertEqual(self.hands(cog, game, match), {
            "offense": 3, "defense": 3,
        })
        for side in (TeamSide.HOME, TeamSide.VISITING):
            with self.subTest(side=side):
                self.assertFalse(
                    cog.engine.may_play_gambits(game, match, side)
                )

    def test_the_trailing_team_holds_them_and_the_leader_does_not(
        self,
    ) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        match.scoreboard.visiting_score += 1

        self.assertTrue(
            cog.engine.may_play_gambits(game, match, TeamSide.HOME)
        )
        self.assertFalse(
            cog.engine.may_play_gambits(game, match, TeamSide.VISITING)
        )
        # Home has the ball in this harness, so home is the offense.
        self.assertEqual(self.hands(cog, game, match), {
            "offense": 6, "defense": 3,
        })

    def test_fielding_more_injured_players_holds_them(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        match.mark_injured(fielded(match, PlayerRole.WINGER))

        self.assertTrue(
            cog.engine.may_play_gambits(game, match, TeamSide.HOME)
        )
        self.assertFalse(
            cog.engine.may_play_gambits(game, match, TeamSide.VISITING)
        )
        self.assertEqual(self.hands(cog, game, match), {
            "offense": 6, "defense": 3,
        })

    def test_an_even_injury_count_holds_nothing(self) -> None:
        """
        **More** than the other team, so a level count closes both
        hands exactly as a level score does. One apiece is the case a
        comparison written as "has any injured player" would get
        wrong.
        """
        cog, game, match = self.build("low_pass", "pressure")
        match.mark_injured(fielded(match, PlayerRole.WINGER))
        match.mark_injured(
            fielded(match, PlayerRole.WINGER, TeamSide.VISITING)
        )

        self.assertEqual(self.hands(cog, game, match), {
            "offense": 3, "defense": 3,
        })

    def test_an_injured_player_on_the_bench_does_not_count(self) -> None:
        """
        The rule is what a team **fields**: a coach who has already
        substituted their injured player off is not down a player any
        more, and `injured_field_players` is read rather than
        `match.injured`.
        """
        cog, game, match = self.build("low_pass", "pressure")
        match.mark_injured(benched(match, PlayerRole.STRIKER))

        self.assertFalse(
            cog.engine.may_play_gambits(game, match, TeamSide.HOME)
        )

    def test_both_coaches_can_hold_them_at_once(self) -> None:
        """
        The author called this out: one trailing while the other is the
        more hurt, and two gambits can still clash. It is why this is a
        question about one team rather than a comparison returning the
        side that holds them.
        """
        cog, game, match = self.build("low_pass", "pressure")
        match.scoreboard.visiting_score += 1
        match.mark_injured(
            fielded(match, PlayerRole.WINGER, TeamSide.VISITING)
        )

        for side in (TeamSide.HOME, TeamSide.VISITING):
            with self.subTest(side=side):
                self.assertTrue(
                    cog.engine.may_play_gambits(game, match, side)
                )
        self.assertEqual(self.hands(cog, game, match), {
            "offense": 6, "defense": 6,
        })

    def test_a_basic_game_holds_none_of_it(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        game.mode = GameMode.BASIC
        match.scoreboard.visiting_score += 1

        self.assertFalse(
            cog.engine.may_play_gambits(game, match, TeamSide.HOME)
        )

    def test_a_gambit_already_played_keeps_its_effect(self) -> None:
        """
        The gate is on the hand and nothing else. A coach who legally
        played a gambit and then equalised still gets its benefit, and
        the beaten card still pays its cost, because both are read off
        the two stored keys rather than off the position.
        """
        cog, game, match = self.build("skilled_pass", "pressure")
        match.scoreboard.visiting_score += 1
        self.assertTrue(
            cog.engine.gambit_benefit_applies(match, "skilled_pass")
        )

        match.scoreboard.home_score += 1

        self.assertFalse(
            cog.engine.may_play_gambits(game, match, TeamSide.HOME)
        )
        self.assertTrue(
            cog.engine.gambit_benefit_applies(match, "skilled_pass")
        )
        self.assertEqual(
            cog.engine.resolving_maneuver(match, "skilled_pass"),
            "skilled_pass",
        )

    def test_the_prompt_says_who_holds_them(self) -> None:
        """
        Public knowledge said out loud, because the prompt draws a hand
        only for a side a person still picks for -- in a solo game
        Dinky's cards never reach the message at all.
        """
        cog, game, match = self.build("low_pass", "pressure")

        self.assertEqual(cog.engine.describe_gambit_access(game, match), "")

        match.scoreboard.visiting_score += 1
        one = cog.engine.describe_gambit_access(game, match)
        self.assertIn("may play a gambit", one)
        self.assertIn(game.player_1_name, one)
        self.assertNotIn(game.player_2_name, one)

        match.mark_injured(
            fielded(match, PlayerRole.WINGER, TeamSide.VISITING)
        )
        self.assertEqual(
            cog.engine.describe_gambit_access(game, match),
            "Both coaches may play a gambit this maneuver.",
        )

    def test_an_unchallenged_maneuver_is_told_nothing(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        match.scoreboard.visiting_score += 1
        clear_the_defense_off_the_ball(match)
        match.offense_maneuver = None
        match.defense_maneuver = None
        match.challenger_id = None
        match.begin_uncontested_maneuver()

        self.assertEqual(cog.engine.describe_gambit_access(game, match), "")


class DinkyGambitPickTests(GambitHarness, unittest.TestCase):
    """
    Where Dinky holds its gambits it weighs all six cards on a side,
    not the three gambits alone or the three basic cards alone --
    `DinkyAI.choose_maneuver_action` rolls a rank on the d6 and then
    coin-flips the tier, which lands on each of the six with equal
    odds. See "Dinky rolls its rank as it always has and picks the
    tier at random" in docs/design/maneuvers.md.
    """

    def test_dinky_reaches_every_card_of_a_hand_with_gambits(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        open_gambits(match)
        strategy = cog.ai_strategies[AIOpponent.DINKY]

        self.assertEqual(
            len(cog.engine.maneuver_hand(game, match, "offense")), 6,
        )

        for side in ("offense", "defense"):
            with self.subTest(side=side):
                hand = cog.engine.maneuver_hand(game, match, side)
                picked = {
                    strategy.choose_maneuver_action(side, hand)
                    for _ in range(300)
                }

                self.assertEqual(picked, {m.key for m in hand})

    def test_a_closed_hand_leaves_dinky_the_basic_three(self) -> None:
        """
        Dinky needs no policy for the gate: it rolls a rank as it
        always has and picks at random among the cards on that rank
        that are actually in the hand it was given, so a Dinky the
        position has closed plays the basic three without knowing why.
        """
        cog, game, match = self.build("low_pass", "pressure")
        strategy = cog.ai_strategies[AIOpponent.DINKY]

        hand = cog.engine.maneuver_hand(game, match, "defense")
        picked = {
            strategy.choose_maneuver_action("defense", hand)
            for _ in range(300)
        }

        self.assertEqual(
            picked,
            {
                m.key
                for m in cog.maneuver_catalog.for_tier(
                    "defense", MANEUVER_TIER_BASIC,
                )
            },
        )

    def test_a_basic_hand_never_reaches_a_gambit(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        strategy = cog.ai_strategies[AIOpponent.DINKY]
        basic_hand = cog.maneuver_catalog.for_tier(
            "offense", MANEUVER_TIER_BASIC,
        )

        picked = {
            strategy.choose_maneuver_action("offense", basic_hand)
            for _ in range(150)
        }

        self.assertEqual(picked, {m.key for m in basic_hand})


class OutrightRuleTests(GambitHarness, unittest.TestCase):
    """
    **A benefit fires where the gambit won on the cards, and a
    cost where it lost on them** (the author, 2026-09-07).

    It used to be one predicate over the whole matchup -- "the cards
    were decisive" -- which is right in every case but one: a decisive
    matchup whose card-winner is injured is settled by a skill test,
    and the *other* side can win it. Then the card that lost on the
    cards is the one resolving, and the card that won on them is the
    one that lost the test. Asking about the matchup gave that pair a
    benefit and a cost neither had earned.

    A tie is still the common case where nothing fires; it is no
    longer the test.
    """

    def test_a_decisive_matchup_carries_the_effects(self) -> None:
        cog, game, match = self.build("skilled_pass", "double_team")

        self.assertTrue(
            cog.engine.gambit_benefit_applies(match, "skilled_pass"),
        )
        self.assertTrue(
            cog.engine.gambit_cost_applies(match, "double_team"),
        )
        self.assertEqual(
            cog.engine.gambit_cost(match, "skilled_pass"), "double_team",
        )

    def test_the_winning_card_owes_no_cost_and_the_loser_gains_nothing(
        self,
    ) -> None:
        # The two halves are mirrors, so each is only ever true of one
        # of the two cards.
        cog, game, match = self.build("skilled_pass", "double_team")

        self.assertFalse(
            cog.engine.gambit_cost_applies(match, "skilled_pass"),
        )
        self.assertFalse(
            cog.engine.gambit_benefit_applies(match, "double_team"),
        )

    def test_a_tie_carries_nothing_and_resolves_as_the_basic_card(
        self,
    ) -> None:
        cog, game, match = self.build("skilled_pass", "clear")

        self.assertFalse(
            cog.engine.gambit_benefit_applies(match, "skilled_pass"),
        )
        self.assertFalse(
            cog.engine.gambit_cost_applies(match, "clear"),
        )
        self.assertIsNone(cog.engine.gambit_cost(match, "skilled_pass"))
        self.assertEqual(
            cog.engine.resolving_maneuver(match, "skilled_pass"), "low_pass",
        )

    def test_an_injured_auto_loss_of_a_tie_carries_nothing(self) -> None:
        """
        It was a tie on the cards; the injury only settled it without a
        roll. Nobody won on the cards, so nobody carries anything.
        """
        cog, game, match = self.build("skilled_pass", "clear")
        match.injured.add(match.challenger_id)

        self.assertEqual(
            cog.engine.settled_maneuver_winner(match), "skilled_pass",
        )
        self.assertFalse(
            cog.engine.gambit_benefit_applies(match, "skilled_pass"),
        )
        self.assertEqual(
            cog.engine.resolving_maneuver(match, "skilled_pass"), "low_pass",
        )

    def test_an_injury_forced_test_the_card_winner_wins_carries_them(
        self,
    ) -> None:
        """
        The cards were decisive and the card-winner also won the roll,
        so both effects land exactly where the cards put them.
        """
        cog, game, match = self.build("skilled_pass", "double_team")
        match.injured.add(match.active_player_id)

        # Injury turns the decisive win into a test they have to win.
        self.assertIsNone(cog.engine.settled_maneuver_winner(match))

        self.assertEqual(
            cog.engine.resolving_maneuver(match, "skilled_pass"),
            "skilled_pass",
        )
        self.assertEqual(
            cog.engine.gambit_cost(match, "skilled_pass"), "double_team",
        )

    def test_an_injury_forced_test_the_card_loser_wins_carries_neither(
        self,
    ) -> None:
        """
        **The case the old reading got wrong.** The cards went to the
        offense, the injury forced a test, and the *defense* won it.
        Double Team never won on the cards, so it resolves basic; and
        Skilled Pass never lost on them, so it owes nothing -- where
        "the cards were decisive" charged the side that had actually
        won the matchup.
        """
        cog, game, match = self.build("skilled_pass", "double_team")
        match.injured.add(match.active_player_id)

        self.assertEqual(
            cog.engine.resolving_maneuver(match, "double_team"), "pressure",
        )
        self.assertIsNone(cog.engine.gambit_cost(match, "double_team"))

    def test_a_basic_winner_over_a_basic_loser_owes_no_cost(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")

        self.assertIsNone(cog.engine.gambit_cost(match, "low_pass"))

    def test_an_unchallenged_maneuver_carries_nothing(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        clear_the_defense_off_the_ball(match)
        match.defense_maneuver = None
        match.challenger_id = None
        match.begin_uncontested_maneuver()

        self.assertIsNone(cog.engine.cards_outcome(match))
        self.assertFalse(
            cog.engine.gambit_benefit_applies(match, "low_pass"),
        )
        self.assertFalse(
            cog.engine.gambit_cost_applies(match, "low_pass"),
        )


class EveryMatchupResolvesTests(
    GambitHarness, unittest.IsolatedAsyncioTestCase
):
    """
    Every one of the thirty-six pairings, on every board, driven
    through the real `resolve_maneuver`.

    It asserts almost nothing about what happens -- the tests above do
    that -- and everything about the fact that it *happens*. Twelve
    cards is twelve effects reached from four directions apiece (a
    decisive win, a decisive loss, a tie, an injury downgrade), and the
    boards differ in how much field there is to run out of. A branch
    nobody thought to build a fixture for shows up here as a traceback
    rather than as a coach's turn going nowhere in a real game.

    Both control paths, because they are different code: a human's
    prompts go out as messages, and Dinky's are answered inline.
    """

    async def resolve_every_pairing(self, solo: bool) -> None:
        catalog = load_maneuver_catalog()
        for offense in catalog.offense:
            for defense in catalog.defense:
                for board_size in (6, 7, 9):
                    with self.subTest(
                        offense=offense.key,
                        defense=defense.key,
                        board=board_size,
                    ):
                        cog, game, match = self.build(
                            offense.key, defense.key, board_size=board_size,
                        )
                        if solo:
                            game.player_2_id = None
                            game.ai_opponent = AIOpponent.DINKY
                        with suppressed_cog_saves():
                            await cog.resolve_maneuver(
                                build_interaction(), game, match,
                            )
                        self.assert_the_log_reads_back(
                            match, offense.key, defense.key,
                        )

    def assert_the_log_reads_back(
        self,
        match: MatchState,
        offense_key: str,
        defense_key: str,
    ) -> None:
        """
        That the maneuver the sweep just resolved went into the event
        log, and went in coherently.

        Worth asserting **here** rather than only in the statistics'
        own tests: this is the one place all thirty-six pairings are
        put through the real `resolve_maneuver`, on three boards and
        both control paths, which is exactly the coverage a log
        written at one funnel needs. `tests/test_d12ball_stats.py`
        checks the reading; this checks the writing.

        A pairing that ties leaves a skill test owed and logs no
        maneuver yet -- that is not a gap, it is the flow, so the
        assertion is on the events that *are* there.
        """
        logged = [
            event for event in match.events
            if event.kind == EVENT_MANEUVER
        ]
        self.assertLessEqual(len(logged), 1)
        for event in logged:
            details = event.details
            self.assertEqual(details["offense_key"], offense_key)
            self.assertEqual(details["defense_key"], defense_key)
            self.assertIn(
                details["winner_key"], (offense_key, defense_key),
            )
            self.assertIn(
                details["decision"],
                CONTESTED_DECISIONS | {DECISION_UNCONTESTED},
            )

    async def test_every_pairing_resolves_for_two_coaches(self) -> None:
        await self.resolve_every_pairing(solo=False)

    async def test_every_pairing_resolves_against_dinky(self) -> None:
        await self.resolve_every_pairing(solo=True)


class SkilledPassTests(GambitHarness, unittest.IsolatedAsyncioTestCase):
    def test_it_reaches_any_teammate_within_three_not_the_nearest_each_way(
        self,
    ) -> None:
        """
        What the card buys over a Low Pass: the nearest-each-way rule
        taken off. A teammate 1 ahead hides a teammate 2 ahead from a
        Low Pass and hides nobody from this.

        Asserted on the distances offered rather than on who is named
        at each one -- the standard deal has already put somebody on
        some of these spaces, and a destination button names whichever
        of them the roster lists first.
        """
        cog, game, match = self.build("skilled_pass", "double_team")
        near = self.put_a_teammate_at(match, 1)
        far = self.put_a_teammate_at(match, 2, exclude=(near,))

        basic = [distance for distance, _ in
                 cog.engine.low_pass_candidates(match)]
        skilled = [distance for distance, _ in
                   cog.engine.skilled_pass_candidates(match)]

        self.assertIn(1, basic)
        self.assertNotIn(2, basic)
        self.assertIn(1, skilled)
        self.assertIn(2, skilled)
        self.assertIn(far, cog.engine.low_pass_receivers(match, 2))

    def test_its_reach_stops_at_three(self) -> None:
        """
        The 2026-08-26 bound, asserted on the widest board there is --
        nine spaces, where a teammate four away is somebody the card
        used to reach and no longer does. The reach is the only thing
        keeping them out, which is why `low_pass_receivers` is asked
        as well: it names them happily.
        """
        cog, game, match = self.build(
            "skilled_pass", "double_team", board_size=9,
        )
        inside = self.put_a_teammate_at(match, 3)
        outside = self.put_a_teammate_at(match, 4, exclude=(inside,))

        distances = [distance for distance, _ in
                     cog.engine.skilled_pass_candidates(match)]

        self.assertIn(3, distances)
        self.assertNotIn(4, distances)
        self.assertNotIn(-4, distances)
        self.assertIn(outside, cog.engine.low_pass_receivers(match, 4))

    async def test_it_adds_three_to_ball_speed(self) -> None:
        cog, game, match = self.build("skilled_pass", "double_team")
        match.ball.speed = 4
        distance, receiver = cog.engine.skilled_pass_candidates(match)[-1]

        with suppressed_cog_saves():
            await cog.apply_low_pass(
                build_interaction(), game, match, distance,
                receiver_id=receiver, key="skilled_pass",
            )

        self.assertEqual(match.ball.speed, 7)
        self.assertEqual(match.ball_carrier_id, receiver)

    async def test_its_cost_shoves_both_defenders_a_space_forward(
        self,
    ) -> None:
        """
        Double Team's cost, paid inside the pass that beat it. No
        exhaustion: nobody chose to go, and every per-space charge in
        the game is for a move somebody was sent on.
        """
        cog, game, match = self.build("skilled_pass", "double_team")
        defense_side = match.defending_side()
        partner = cog.engine.double_team_partner(match)
        before = {
            player_id: self.flat_of(match, player_id)
            for player_id in (match.challenger_id, partner)
        }
        distance, receiver = cog.engine.skilled_pass_candidates(match)[-1]

        with suppressed_cog_saves():
            await cog.apply_low_pass(
                build_interaction(), game, match, distance,
                receiver_id=receiver, key="skilled_pass",
            )

        # The visitors attack from high flat indices to low, so "away
        # from their own goal" is one step down the board. Read off
        # `relative_flat_index` rather than assumed, so the assertion
        # survives the direction being reconsidered.
        for player_id, was in before.items():
            with self.subTest(player=player_id):
                self.assertEqual(
                    self.flat_of(match, player_id),
                    match.relative_flat_index(was, defense_side, 1),
                )
                self.assertEqual(match.exhaustion.get(player_id, 0), 0)


class DribbleBurstTests(GambitHarness, unittest.IsolatedAsyncioTestCase):
    """
    The run is the coach's now, bounded at
    `DRIBBLE_BURST_MAX_DISTANCE` (the author, 2026-08-26). It used to
    be to the last space of the goal they attack, which is why these
    are written against `apply_dribble_burst` and a chosen distance
    rather than against the resolution putting a menu up.
    """

    async def test_it_runs_the_chosen_distance_and_charges_a_token_a_space(
        self,
    ) -> None:
        cog, game, match = self.build("dribble_burst", "clear")
        # Explicitly not the Playmaker, who pays one fewer -- the deal
        # puts one in midfield, so "whoever has the ball" was quietly
        # testing the discounted case.
        handler = fielded(match, PlayerRole.MIDFIELDER)
        match.active_player_id = handler
        match.move_meeple(handler, match.ball.zone, match.ball.space_index)
        start = self.flat_of(match, handler)
        cog.offer_speed_choice = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.apply_dribble_burst(
                build_interaction(), game, match, 2,
            )

        end = self.flat_of(match, handler)
        # Home attacks toward high indices.
        self.assertEqual(end, start + 2)
        self.assertEqual(self.flat(match), end)
        self.assertEqual(match.exhaustion[handler], 2)
        self.assertEqual(match.ball_carrier_id, handler)
        cog.offer_speed_choice.assert_awaited_once()

    def test_the_run_is_bounded_at_four_and_by_the_field(self) -> None:
        """
        `dribble_burst_distances` is the whole of what may be picked.
        Board 9 is where the bound bites: from midfield the goal they
        attack is more than four spaces off, so the card stops short
        of it -- which is the change, and what "runs to the goal" used
        to mean.
        """
        cog, game, match = self.build("dribble_burst", "clear", board_size=9)
        handler = match.active_player_id
        # Back in their own goal zone, which on board 9 is eight
        # spaces from the end of the field -- twice what the card now
        # runs. From the kickoff space it is exactly four, so the
        # bound would not have bitten there.
        match.move_meeple(handler, *match.board.position_at_flat_index(0))
        match.set_ball_space(*match.board.meeple_position(handler))

        self.assertEqual(
            match.spaces_to_attacking_end(handler, match.ball.possession), 8,
        )
        self.assertEqual(
            cog.engine.dribble_burst_distances(match), [1, 2, 3, 4],
        )

        # Two spaces from the end of the field, only those two are on
        # offer -- the run cannot leave the board.
        end_flat = match.board.layout.board_size - 1
        match.move_meeple(
            handler, *match.board.position_at_flat_index(end_flat - 2),
        )
        self.assertEqual(cog.engine.dribble_burst_distances(match), [1, 2])

        # And from the last space itself there is nothing to ask.
        match.move_meeple(
            handler, *match.board.position_at_flat_index(end_flat),
        )
        self.assertEqual(cog.engine.dribble_burst_distances(match), [])

    def test_the_speed_after_a_burst_is_anything_from_one_to_twelve(
        self,
    ) -> None:
        """
        The card reads "adjust ball speed up to 12" (the sheet,
        2026-09-20) where a Dribble Advance's reads "up to oSkill":
        the burst sets the speed outright, the advance moves it by the
        handler's skill. `speed_choice_reach` is the one reading, and
        the targets built from it are what the buttons and the AI see.
        """
        cog, game, match = self.build("dribble_burst", "clear")
        handler = fielded(match, PlayerRole.MIDFIELDER)
        match.active_player_id = handler
        match.ball.speed = 5
        skill = cog.player_catalog.effective_profile(
            cog.engine.get_player_definition(handler),
        ).offense

        self.assertEqual(
            cog.engine.speed_choice_targets(
                match, handler, "offense", "dribble_burst",
            ),
            list(range(1, 13)),
        )
        # The advance is still bounded, and so is a burst that resolves
        # as one -- the key the caller passes is the resolving card's.
        self.assertEqual(
            cog.engine.speed_choice_targets(
                match, handler, "offense", "dribble_advance",
            ),
            list(range(5 - skill, 5 + skill + 1)),
        )

    async def test_the_burst_names_its_card_to_the_speed_choice(
        self,
    ) -> None:
        """
        The bound is decided by the card the follow-on names, so the
        burst has to say which it is -- a follow-on without the key is
        a Dribble Advance's, and would offer oSkill either way.
        """
        cog, game, match = self.build("dribble_burst", "clear")
        handler = fielded(match, PlayerRole.MIDFIELDER)
        match.active_player_id = handler
        match.move_meeple(handler, match.ball.zone, match.ball.space_index)
        cog.offer_speed_choice = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.apply_dribble_burst(
                build_interaction(), game, match, 1,
            )

        self.assertEqual(
            cog.offer_speed_choice.await_args.kwargs["maneuver_key"],
            "dribble_burst",
        )

    async def test_the_beaten_bursts_defender_is_still_bounded_by_skill(
        self,
    ) -> None:
        """
        The cost hands the defense the speed step, and that step is a
        steal's: the challenger adjusts by dSkill. Nothing on the
        beaten path names the burst to the speed choice.
        """
        cog, game, match = self.build("dribble_burst", "double_team")
        match.ball.speed = 9
        cog.begin_run_back = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.resolve_double_team(build_interaction(), game, match)

        self.assertNotIn(
            "maneuver_key", cog.begin_run_back.await_args.kwargs,
        )
        self.assertEqual(
            cog.engine.speed_choice_reach(match.challenger_id, "defense"),
            cog.player_catalog.effective_profile(
                cog.engine.get_player_definition(match.challenger_id),
            ).defense,
        )

    async def test_a_handler_on_the_last_space_is_asked_nothing(
        self,
    ) -> None:
        """
        The one position with no run in it. It still gets its speed
        choice, and it costs nothing -- a burst that moved nowhere is
        free, Playmaker or not.
        """
        cog, game, match = self.build("dribble_burst", "clear")
        handler = match.active_player_id
        end_flat = match.board.layout.board_size - 1
        match.move_meeple(
            handler, *match.board.position_at_flat_index(end_flat),
        )
        cog.offer_speed_choice = mock.AsyncMock()
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.resolve_dribble_burst(interaction, game, match)

        interaction.followup.send.assert_not_awaited()
        self.assertEqual(self.flat_of(match, handler), end_flat)
        self.assertEqual(match.exhaustion.get(handler, 0), 0)
        cog.offer_speed_choice.assert_awaited_once()

    async def test_a_playmaker_pays_one_token_fewer(self) -> None:
        """
        The one role ability that reads differently on the two cards of
        its rank (the author, 2026-08-19), and it stayed that way when
        the run was bounded on 2026-08-26: the discount is on what the
        run costs, not on how far it goes -- so the distances offered
        are the same ones everybody else gets.
        """
        cog, game, match = self.build("dribble_burst", "clear")
        playmaker = fielded(match, PlayerRole.PLAYMAKER)
        match.active_player_id = playmaker
        match.move_meeple(playmaker, match.ball.zone, match.ball.space_index)
        offered = cog.engine.dribble_burst_distances(match)
        cog.offer_speed_choice = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.apply_dribble_burst(
                build_interaction(), game, match, 3,
            )

        self.assertIn(3, offered)
        self.assertEqual(match.exhaustion[playmaker], 2)

    async def test_defenders_are_no_obstacle(self) -> None:
        """
        The card says the run passes everyone in the way, so a defender
        parked on the destination changes nothing about where it ends.
        """
        cog, game, match = self.build("dribble_burst", "clear")
        blocker = match.visiting.field_players[0]
        target = match.relative_flat_index(
            self.flat(match), match.ball.possession, 2,
        )
        match.move_meeple(
            blocker, *match.board.position_at_flat_index(target),
        )
        cog.offer_speed_choice = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.apply_dribble_burst(
                build_interaction(), game, match, 2,
            )

        self.assertEqual(self.flat(match), target)

    async def test_dinky_runs_the_full_distance_on_offer(self) -> None:
        """
        Dinky maximizes and is deliberately not weighing the tokens --
        the same call as never ceding. It also means a solo game never
        reaches the menu, which is why this asserts the run rather
        than the prompt.
        """
        cog, game, match = self.build("dribble_burst", "clear")
        game.player_2_id = None
        game.ai_opponent = AIOpponent.DINKY
        match.ball.possession = TeamSide.VISITING
        handler = match.visiting.field_players[0]
        match.active_player_id = handler
        match.move_meeple(handler, match.ball.zone, match.ball.space_index)
        offered = cog.engine.dribble_burst_distances(match)
        start = self.flat_of(match, handler)
        cog.offer_speed_choice = mock.AsyncMock()
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.resolve_dribble_burst(interaction, game, match)

        interaction.followup.send.assert_not_awaited()
        self.assertEqual(
            self.flat_of(match, handler),
            match.relative_flat_index(
                start, TeamSide.VISITING, offered[-1],
            ),
        )

    async def test_clears_cost_is_two_exhaustion_on_the_defender(
        self,
    ) -> None:
        cog, game, match = self.build("dribble_burst", "clear")
        defender = match.challenger_id
        cog.offer_speed_choice = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.apply_dribble_burst(
                build_interaction(), game, match, 1,
            )

        self.assertEqual(match.exhaustion[defender], 2)

    async def test_the_basic_dribble_also_charges_clears_cost(self) -> None:
        """
        A cost is the *loser's*, so it does not care which card beat
        it: Clear pays the same 2 whether it lost to Dribble Burst or
        to an ordinary Dribble Advance.
        """
        cog, game, match = self.build("dribble_advance", "clear")
        defender = match.challenger_id
        cog.offer_speed_choice = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.apply_dribble_advance(
                build_interaction(), game, match, 1,
            )

        self.assertEqual(match.exhaustion[defender], 2)


class ClearTests(GambitHarness, unittest.IsolatedAsyncioTestCase):
    async def test_it_drives_the_ball_back_three_and_drops_speed_by_three(
        self,
    ) -> None:
        # Against the *basic* High Pass, so nothing but Clear's own
        # benefit is in force -- Setup Pass would add its cost on top.
        cog, game, match = self.build("high_pass", "clear", board_size=9)
        match.ball.speed = 8
        start = self.flat(match)
        cog.begin_loose_ball = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.resolve_clear(build_interaction(), game, match)

        self.assertEqual(self.flat(match), start - 3)
        self.assertEqual(match.ball.speed, 5)
        cog.begin_loose_ball.assert_awaited_once()
        # Clear is Deflect's own landing rule, just at 3 (or 4) spaces
        # instead of 1 (or 2). Occupancy decides how it is won, which
        # since 2026-08-26 is every arrival's rule -- so what this
        # asserts is that the one exemption, a High Pass, is not taken.
        # See OccupancyDecidesTests in test_d12ball_loose_ball.py for
        # the three-way behavior itself.
        self.assertFalse(
            cog.begin_loose_ball.await_args.kwargs.get("is_high_pass", False),
        )

    async def test_a_fullback_clears_four_spaces(self) -> None:
        """
        The Fullback's ability is **+1 distance** (the author,
        2026-08-19), so it takes a Clear from 3 to 4 the same way it
        takes a Deflect from 1 to 2. Its sentence states a number
        because it was written against one card; the rule behind the
        number is what carries.
        """
        cog, game, match = self.build("high_pass", "clear", board_size=9)
        fullback = fielded(match, PlayerRole.FULLBACK, TeamSide.VISITING)
        match.challenger_id = fullback
        match.move_meeple(fullback, match.ball.zone, match.ball.space_index)
        start = self.flat(match)
        cog.begin_loose_ball = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.resolve_clear(build_interaction(), game, match)

        self.assertEqual(self.flat(match), start - 4)

    async def test_a_fullbacks_extra_space_is_not_extra_speed(self) -> None:
        """
        The speed drop is the card's, not the distance's. A Fullback's
        Deflect has always moved the ball 2 and cost 1 speed, so
        a Fullback's Clear moves 4 and still costs 3 -- the two numbers
        happen to match on an ordinary Clear, which is exactly how a
        distance-derived speed drop read correctly until now.
        """
        cog, game, match = self.build("high_pass", "clear", board_size=9)
        fullback = fielded(match, PlayerRole.FULLBACK, TeamSide.VISITING)
        match.challenger_id = fullback
        match.move_meeple(fullback, match.ball.zone, match.ball.space_index)
        match.ball.speed = 9
        cog.begin_loose_ball = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.resolve_clear(build_interaction(), game, match)

        self.assertEqual(match.ball.speed, 6)

    async def test_a_basic_deflection_is_unchanged_by_the_ruling(
        self,
    ) -> None:
        # The same +1, read on the card it was written against: 2
        # spaces, and still only 1 off the speed.
        cog, game, match = self.build("dribble_advance", "deflect")
        fullback = fielded(match, PlayerRole.FULLBACK, TeamSide.VISITING)
        match.challenger_id = fullback
        match.move_meeple(fullback, match.ball.zone, match.ball.space_index)
        match.ball.speed = 9
        start = self.flat(match)
        cog.begin_loose_ball = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.resolve_deflect(
                build_interaction(), game, match,
            )

        self.assertEqual(self.flat(match), start - 2)
        self.assertEqual(match.ball.speed, 8)


class InterceptTests(GambitHarness, unittest.IsolatedAsyncioTestCase):
    async def test_it_carries_the_ball_forward_not_back(self) -> None:
        """
        The sign is the whole card. A basic Steal falls back toward the
        new possessor's own goal, which is the way the offense was
        going; Intercept carries it the other way, toward the goal the
        interceptor now attacks. Read off `relative_flat_index` rather
        than a literal, since that is what the effect itself uses.
        """
        cog, game, match = self.build("low_pass", "intercept")
        challenger = match.challenger_id
        start = self.flat_of(match, challenger)
        cog.begin_run_back = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.resolve_intercept(build_interaction(), game, match)

        defense_side = match.ball.possession
        self.assertEqual(defense_side, TeamSide.VISITING)
        self.assertEqual(
            self.flat_of(match, challenger),
            match.relative_flat_index(start, defense_side, 1),
        )
        self.assertEqual(self.flat(match), self.flat_of(match, challenger))
        self.assertEqual(match.ball_carrier_id, challenger)
        self.assertEqual(match.ball.speed, 1)

    async def test_the_basic_steal_still_falls_back(self) -> None:
        cog, game, match = self.build("low_pass", "steal")
        challenger = match.challenger_id
        start = self.flat_of(match, challenger)
        cog.begin_run_back = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.resolve_steal(build_interaction(), game, match)

        self.assertEqual(
            self.flat_of(match, challenger),
            match.relative_flat_index(start, match.ball.possession, -1),
        )

    async def test_no_field_left_ahead_is_a_scoring_opportunity(
        self,
    ) -> None:
        """
        The author, 2026-08-19. The interceptor is already on the last
        space toward the goal they now attack, so there is nowhere to
        carry it -- they shoot instead.
        """
        cog, game, match = self.build("low_pass", "intercept")
        challenger = match.challenger_id
        zone, space_index = match.board.position_at_flat_index(0)
        match.move_meeple(challenger, zone, space_index)
        match.set_ball_space(zone, space_index)
        match.move_meeple(match.active_player_id, zone, space_index)
        cog.begin_shooter_choice = mock.AsyncMock()
        cog.begin_run_back = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.resolve_intercept(build_interaction(), game, match)

        cog.begin_shooter_choice.assert_awaited_once()
        cog.begin_run_back.assert_not_awaited()
        # Named rather than positional since rank D2: the step returns
        # a `FollowOn` and `dispatch_step_result` hands every follow-on
        # its arguments by keyword.
        self.assertEqual(
            cog.begin_shooter_choice.await_args.kwargs["candidates"],
            [challenger],
        )

    async def test_its_cost_leaves_a_long_high_pass_uncontested(
        self,
    ) -> None:
        """
        The one cost that can be inert -- but not here: a pass of 3
        with a teammate on the landing space is exactly the branch that
        would otherwise owe a contest.
        """
        cog, game, match = self.build("high_pass", "intercept", board_size=9)
        offense_side = match.ball.possession
        origin = self.flat(match)
        target = match.relative_flat_index(origin, offense_side, 3)
        zone, space_index = match.board.position_at_flat_index(target)
        receiver = [
            player_id
            for player_id in match.home.field_players
            if player_id != match.active_player_id
        ][0]
        match.move_meeple(receiver, zone, space_index)
        cog.begin_high_pass_contest = mock.AsyncMock()
        cog.finish_maneuver_resolution = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.apply_high_pass(build_interaction(), game, match, 3)

        cog.begin_high_pass_contest.assert_not_awaited()
        cog.finish_maneuver_resolution.assert_awaited_once()
        self.assertEqual(match.ball_carrier_id, receiver)

    async def test_a_basic_steal_leaves_the_contest_alone(self) -> None:
        cog, game, match = self.build("high_pass", "steal", board_size=9)
        offense_side = match.ball.possession
        origin = self.flat(match)
        target = match.relative_flat_index(origin, offense_side, 3)
        zone, space_index = match.board.position_at_flat_index(target)
        receiver = [
            player_id
            for player_id in match.home.field_players
            if player_id != match.active_player_id
        ][0]
        match.move_meeple(receiver, zone, space_index)
        cog.begin_high_pass_contest = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.apply_high_pass(build_interaction(), game, match, 3)

        cog.begin_high_pass_contest.assert_awaited_once()


class SetupPassTests(GambitHarness, unittest.IsolatedAsyncioTestCase):
    def test_it_offers_every_distance_that_fits_on_the_field(self) -> None:
        """
        The author, 2026-08-25: a distance is offered because it fits,
        not because somebody is standing there. `0` is the exception --
        see the test below.
        """
        cog, game, match = self.build("setup_pass", "steal", board_size=9)

        offered = cog.engine.setup_pass_distances(match)

        for distance in (1, 3):
            origin = self.flat(match)
            target = match.relative_flat_index(
                origin, match.ball.possession, distance,
            )
            with self.subTest(distance=distance):
                self.assertEqual(
                    distance in offered, abs(target - origin) == distance,
                )

    def test_a_distance_reaching_nobody_is_still_offered(self) -> None:
        """
        The whole of the change: picking the ball out into empty space
        is a bad choice a coach may make, not a choice the menu takes
        away. Before this, a passer with nobody 1 or 3 ahead of them
        had no Setup Pass at all.
        """
        cog, game, match = self.build("setup_pass", "steal", board_size=9)
        for player_id in list(match.home.field_players):
            if player_id != match.active_player_id:
                match.move_meeple(player_id, Zone.HOME_GOAL, 0)

        self.assertEqual(cog.engine.setup_pass_distances(match), [1, 3])

    async def test_a_pass_onto_nobody_leaves_the_ball_where_it_lands(
        self,
    ) -> None:
        """
        It settles exactly as a Deflect's does: loose on an empty
        space, the other side's outright where only they are standing,
        a contest where both are.
        """
        cog, game, match = self.build("setup_pass", "steal", board_size=9)
        for player_id in list(match.home.field_players):
            if player_id != match.active_player_id:
                match.move_meeple(player_id, Zone.HOME_GOAL, 0)
        start = self.flat(match)
        cog.begin_loose_ball = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.apply_setup_pass(build_interaction(), game, match, 3)

        self.assertEqual(self.flat(match), start + 3)
        cog.begin_loose_ball.assert_awaited_once()
        self.assertFalse(
            cog.begin_loose_ball.await_args.kwargs.get("is_high_pass", False),
        )
        # The ball is thrown, so it is still the offense's until the
        # landing decides otherwise -- and the pass costs its own 2
        # minutes however far it travelled.
        self.assertEqual(match.ball.possession, TeamSide.HOME)
        self.assertEqual(cog.begin_loose_ball.await_args.args[3], 2)

    def test_a_fullback_may_also_set_up_at_four(self) -> None:
        """
        The same +1 the Fullback brings to a High Pass and a Clear, on
        the card its sentence does not name. It is **appended** rather
        than replacing the 3: the ability adds a distance, it does not
        move one.
        """
        cog, game, match = self.build("setup_pass", "steal", board_size=9)
        fullback = fielded(match, PlayerRole.FULLBACK)
        match.active_player_id = fullback
        match.move_meeple(fullback, match.ball.zone, match.ball.space_index)
        teammate = [
            player_id
            for player_id in match.home.field_players
            if player_id != fullback
        ][0]
        target = match.relative_flat_index(
            self.flat(match), match.ball.possession, 4,
        )
        zone, space_index = match.board.position_at_flat_index(target)
        match.move_meeple(teammate, zone, space_index)

        self.assertIn(4, cog.engine.setup_pass_distances(match))

    def test_nobody_else_may_set_up_at_four(self) -> None:
        cog, game, match = self.build("setup_pass", "steal", board_size=9)
        striker = fielded(match, PlayerRole.STRIKER)
        match.active_player_id = striker
        match.move_meeple(striker, match.ball.zone, match.ball.space_index)
        teammate = [
            player_id
            for player_id in match.home.field_players
            if player_id != striker
        ][0]
        target = match.relative_flat_index(
            self.flat(match), match.ball.possession, 4,
        )
        zone, space_index = match.board.position_at_flat_index(target)
        match.move_meeple(teammate, zone, space_index)

        self.assertNotIn(4, cog.engine.setup_pass_distances(match))

    def test_zero_means_a_teammate_sharing_the_passers_space(self) -> None:
        """
        A passer never receives their own pass (2026-08-12), which is
        the whole of what makes 0 a distance at all.
        """
        cog, game, match = self.build("setup_pass", "steal")
        for player_id in list(
            match.board.spaces[match.ball.zone][match.ball.space_index]
        ):
            if player_id != match.active_player_id:
                match.move_meeple(player_id, Zone.HOME_GOAL, 0)

        self.assertNotIn(0, cog.engine.setup_pass_distances(match))

        teammate = [
            player_id
            for player_id in match.home.field_players
            if player_id != match.active_player_id
        ][0]
        match.move_meeple(teammate, match.ball.zone, match.ball.space_index)

        self.assertIn(0, cog.engine.setup_pass_distances(match))

    async def test_the_speed_comes_first_and_the_pass_is_owed_after_it(
        self,
    ) -> None:
        """
        The card's order, and the reason this card needs a persisted
        continuation: a speed choice has always been the *last* human
        step of an effect.
        """
        cog, game, match = self.build("setup_pass", "steal")
        cog.offer_speed_choice = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.resolve_setup_pass(build_interaction(), game, match)

        cog.offer_speed_choice.assert_awaited_once()
        self.assertEqual(
            match.pending_effect_continuation, {"kind": "setup_pass_shot"},
        )

    async def test_the_continuation_survives_a_save_and_reload(self) -> None:
        cog, game, match = self.build("setup_pass", "steal")
        cog.offer_speed_choice = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.resolve_setup_pass(build_interaction(), game, match)

        restored = MatchState.from_dict(match.to_dict(), cog.basic_ruleset)
        self.assertEqual(
            restored.pending_effect_continuation, {"kind": "setup_pass_shot"},
        )

    async def test_a_restart_between_the_halves_comes_back_to_the_pass(
        self,
    ) -> None:
        """
        The window is wide -- a coach may take hours over the second
        prompt -- so the continuation has to outlive its dispatch and
        `build_effect_choice_view` has to read it. Reading the winner
        instead would put Setup Pass's *speed* choice back up, and let
        a coach set the speed twice.
        """
        cog, game, match = self.build("setup_pass", "steal", board_size=9)
        self.put_a_teammate_at(match, 3)
        cog.offer_speed_choice = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.resolve_setup_pass(build_interaction(), game, match)
        game.match_state = match.to_dict()
        cog.engine.load_match_state = mock.Mock(return_value=match)

        restored = cog.build_effect_choice_view(game.game_id, match)

        self.assertIsInstance(restored, SetupPassChoiceView)

    async def test_the_pass_spends_the_continuation(self) -> None:
        cog, game, match = self.build("setup_pass", "steal", board_size=9)
        self.put_a_teammate_at(match, 3)
        match.pending_effect_continuation = {"kind": "setup_pass_shot"}
        cog.offer_scoring_attempt_choice = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.apply_setup_pass(build_interaction(), game, match, 3)

        self.assertIsNone(match.pending_effect_continuation)

    async def test_the_pass_offers_a_scoring_opportunity(self) -> None:
        cog, game, match = self.build("setup_pass", "steal", board_size=9)
        # The standard deal need not leave anybody 3 spaces ahead, and
        # what is under test is the set-up rather than the deal, so a
        # receiver is put there deliberately.
        receiver = self.put_a_teammate_at(match, 3)
        start = self.flat(match)
        cog.offer_scoring_attempt_choice = mock.AsyncMock()

        self.assertIn(3, cog.engine.setup_pass_distances(match))

        with suppressed_cog_saves():
            await cog.apply_setup_pass(build_interaction(), game, match, 3)

        self.assertEqual(self.flat(match), start + 3)
        self.assertEqual(match.ball_carrier_id, receiver)
        cog.offer_scoring_attempt_choice.assert_awaited_once()

    async def test_it_cannot_overshoot_and_goes_out_instead(self) -> None:
        """
        The one position a Setup Pass goes out from, since 2026-08-25:
        the passer on the very last space of the field -- where even 1
        runs off the end -- with no teammate beside them to take it at
        0. Then it runs out of play, the other team gains possession,
        and that is the existing out-of-bounds outcome and a fourth
        `new_play=True` call site.
        """
        cog, game, match = self.build("setup_pass", "steal")
        for player_id in list(match.home.field_players):
            if player_id != match.active_player_id:
                match.move_meeple(player_id, Zone.HOME_GOAL, 0)
        match.move_meeple(
            match.active_player_id, Zone.VISITORS_GOAL,
            match.board.layout.zone_spaces[Zone.VISITORS_GOAL] - 1,
        )
        match.set_ball_space(
            *match.board.meeple_position(match.active_player_id)
        )
        cog.begin_run_back = mock.AsyncMock()

        self.assertEqual(cog.engine.setup_pass_distances(match), [])

        with suppressed_cog_saves():
            await cog.offer_setup_pass_distance(
                build_interaction(), game, match,
            )

        cog.begin_run_back.assert_awaited_once()
        self.assertTrue(
            cog.begin_run_back.await_args.kwargs["new_play"],
        )
        self.assertTrue(match.pending_ball_recovery)
        self.assertEqual(match.ball.possession, TeamSide.VISITING)

    async def test_its_cost_drives_the_ball_back_and_leaves_it_loose(
        self,
    ) -> None:
        cog, game, match = self.build("setup_pass", "clear", board_size=9)
        cog.begin_loose_ball = mock.AsyncMock()
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.resolve_clear(interaction, game, match)

        # The deflection did not settle the ball itself: the cost put
        # the choice to the coach who beat the card.
        cog.begin_loose_ball.assert_not_awaited()
        interaction.followup.send.assert_awaited()

        # Clear has already driven it back 3, so how much field is
        # left is what decides the push -- asked of the board rather
        # than assumed, which is the same question the view asks before
        # it builds a button.
        after_clear = self.flat(match)
        push = max(
            distance
            for distance in (1, 2, 3)
            if abs(
                match.relative_flat_index(
                    after_clear, match.ball.possession, -distance,
                )
                - after_clear
            )
            == distance
        )

        with suppressed_cog_saves():
            await cog.apply_setup_pass_push_back(
                interaction, game, match, push,
            )

        self.assertEqual(self.flat(match), after_clear - push)
        cog.begin_loose_ball.assert_awaited_once()
        # Same occupancy rule as the plain Deflect/Clear landing --
        # see OccupancyDecidesTests in test_d12ball_loose_ball.py for
        # the three-way behavior this lands in.
        self.assertFalse(
            cog.begin_loose_ball.await_args.kwargs.get("is_high_pass", False),
        )

    async def test_no_legal_push_back_still_wires_the_occupancy_rule(
        self,
    ) -> None:
        # With the ball already at the edge of the field, none of 1/2/3
        # fits -- the loose ball happens right where the beaten card
        # left it, through the `if not distances:` fallback rather than
        # apply_setup_pass_push_back, and it still has to settle by
        # occupancy like every other arrival.
        cog, game, match = self.build("setup_pass", "clear", board_size=9)
        edge_zone, edge_space = match.board.position_at_flat_index(0)
        match.set_ball_space(edge_zone, edge_space)
        cog.begin_loose_ball = mock.AsyncMock()

        self.assertEqual(
            [
                distance
                for distance in (1, 2, 3)
                if abs(
                    match.relative_flat_index(
                        0, match.ball.possession, -distance,
                    )
                )
                == distance
            ],
            [],
        )

        with suppressed_cog_saves():
            await cog.offer_setup_pass_push_back(
                build_interaction(), game, match, lead_in="",
            )

        cog.begin_loose_ball.assert_awaited_once()
        self.assertFalse(
            cog.begin_loose_ball.await_args.kwargs.get("is_high_pass", False),
        )


class DoubleTeamTests(GambitHarness, unittest.IsolatedAsyncioTestCase):
    async def test_it_pushes_the_handler_back_two_and_brings_a_partner(
        self,
    ) -> None:
        cog, game, match = self.build("dribble_burst", "double_team")
        handler = match.active_player_id
        challenger = match.challenger_id
        partner = cog.engine.double_team_partner(match)
        start = self.flat_of(match, handler)
        cog.finish_maneuver_resolution = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.resolve_double_team(build_interaction(), game, match)

        end = self.flat_of(match, handler)
        self.assertEqual(end, start - 2)
        self.assertEqual(self.flat(match), end)
        # Both defenders end on the handler's space, and neither pays a
        # token for it -- "no exhaustion cost" is the card's own words.
        self.assertEqual(self.flat_of(match, challenger), end)
        self.assertEqual(self.flat_of(match, partner), end)
        self.assertEqual(match.exhaustion.get(partner, 0), 0)
        self.assertEqual(match.pending_double_team, [challenger, partner])

    async def test_the_pair_survives_a_save_and_reload(self) -> None:
        cog, game, match = self.build("dribble_burst", "double_team")
        cog.finish_maneuver_resolution = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.resolve_double_team(build_interaction(), game, match)

        restored = MatchState.from_dict(match.to_dict(), cog.basic_ruleset)
        self.assertEqual(
            restored.pending_double_team, match.pending_double_team,
        )

    def test_the_partner_is_the_defender_nearest_the_ball(self) -> None:
        cog, game, match = self.build("dribble_advance", "double_team")

        partner = cog.engine.double_team_partner(match)

        others = [
            player_id
            for player_id in match.visiting.field_players
            if player_id != match.challenger_id
        ]
        self.assertEqual(
            match.distance_to_ball(partner),
            min(match.distance_to_ball(other) for other in others),
        )

    def test_both_defenders_challenge_the_next_maneuver(self) -> None:
        cog, game, match = self.build("dribble_advance", "double_team")
        challenger = match.challenger_id
        partner = cog.engine.double_team_partner(match)
        match.pending_double_team = [challenger, partner]

        self.assertEqual(
            cog.engine.double_team_defenders(match), [challenger, partner],
        )

    def test_without_a_double_team_only_the_challenger_challenges(
        self,
    ) -> None:
        cog, game, match = self.build("dribble_advance", "pressure")

        self.assertEqual(
            cog.engine.double_team_defenders(match), [match.challenger_id],
        )

    async def test_dribble_bursts_cost_turns_the_ball_over_at_speed(
        self,
    ) -> None:
        """
        **The first exception to "every turnover resets ball speed to
        1".** Neither a turnover nor a speed step is something a
        pressure does on its own -- the cost grants the defense both.
        """
        cog, game, match = self.build("dribble_burst", "double_team")
        match.ball.speed = 9
        cog.begin_run_back = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.resolve_double_team(build_interaction(), game, match)

        self.assertEqual(match.ball.possession, TeamSide.VISITING)
        self.assertEqual(match.ball.speed, 9)
        self.assertEqual(match.ball_carrier_id, match.challenger_id)
        cog.begin_run_back.assert_awaited_once()
        self.assertTrue(
            cog.begin_run_back.await_args.kwargs["speed_choice_after"],
        )
        # The run-back announcement must not claim a reset to 1 that
        # never happened -- see announce_run_back's speed_reset.
        self.assertFalse(
            cog.begin_run_back.await_args.kwargs["speed_reset"],
        )

    async def test_a_basic_dribble_loses_the_ball_at_speed_one(self) -> None:
        """
        The exception is Dribble Burst's cost and nothing else: a
        Defender's steal on a won Pressure still resets.
        """
        cog, game, match = self.build("dribble_advance", "pressure")
        defender = fielded(match, PlayerRole.DEFENDER, TeamSide.VISITING)
        match.challenger_id = defender
        match.move_meeple(defender, match.ball.zone, match.ball.space_index)
        match.ball.speed = 9
        cog.begin_run_back = mock.AsyncMock()

        with suppressed_cog_saves():
            await cog.resolve_pressure(build_interaction(), game, match)

        self.assertEqual(match.ball.possession, TeamSide.VISITING)
        self.assertEqual(match.ball.speed, 1)


if __name__ == "__main__":
    unittest.main()

"""
Advanced maneuvers: which hand a coach holds, when an advanced effect
fires, and what each of the six does.

Three layers, and they fail for different reasons:

- **The hand.** `RulesEngine.maneuver_tiers` is the only answer to who
  may play what, and the buttons, the card image and the click that
  answers all read it. A basic game is three cards; an advanced one is
  six, except where the maneuver went unchallenged.
- **The outright rule.** `advanced_effects_apply` decides whether the
  cards' benefit and cost are in force at all. It is asserted against
  the four ways a maneuver lands rather than against a list of
  matchups -- the injury cases are exactly the ones a list would get
  wrong.
- **The six effects.** Each is asserted on what it *does to the
  board*, since the wording is prose and will be revised. What is
  checked is every claim the card makes that the data could
  contradict.

See "Advanced maneuvers" in docs/living-rules.md and the matrix in
docs/advanced-maneuver-matrix.md.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import (
    ManeuverActionSelectView,
    SetupPassChoiceView,
)
from d12ball.ai import build_ai_strategies
from d12ball.components import (
    MANEUVER_TIER_ADVANCED,
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

from roster import fielded


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.team_emojis = {}
    cog.condition_emojis = {}
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
        (side, tiers): b""
        for side in ("offense", "defense")
        for tiers in (
            (MANEUVER_TIER_BASIC,),
            (MANEUVER_TIER_BASIC, MANEUVER_TIER_ADVANCED),
        )
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
    return SimpleNamespace(
        user=SimpleNamespace(id=111, display_name="One"),
        # A resolution that runs all the way through hands the turn
        # back to `send_turn_prompt`, which reads both of these.
        guild=None,
        channel=None,
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
        ),
        followup=SimpleNamespace(send=mock.AsyncMock(return_value=sent)),
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


class AdvancedHarness:
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

    def put_a_teammate_at(self, match: MatchState, distance: int) -> str:
        """
        Stand one of the passer's own side `distance` spaces ahead of
        the ball, and hand back who it is. The standard deal decides
        where everybody starts, and a test about a pass should not also
        be a test of the deal.
        """
        target = match.relative_flat_index(
            self.flat(match), match.ball.possession, distance,
        )
        zone, space_index = match.board.position_at_flat_index(target)
        teammate = [
            player_id
            for player_id in match.home.field_players
            if player_id != match.active_player_id
        ][0]
        match.move_meeple(teammate, zone, space_index)
        return teammate


class ManeuverHandTests(AdvancedHarness, unittest.TestCase):
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

    def test_an_advanced_game_offers_six_in_rank_order(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")

        hand = cog.engine.maneuver_hand(game, match, "offense")

        self.assertEqual(
            [m.key for m in hand],
            [
                "low_pass",
                "precise_pass",
                "dribble_advance",
                "dribble_burst",
                "high_pass",
                "setup_pass",
            ],
        )

    def test_an_unchallenged_maneuver_is_basic_even_in_advanced_mode(
        self,
    ) -> None:
        """
        The author: "Advanced maneuver can only be played when a
        maneuver is challenged." It is answerable at the moment the
        hand is drawn because every route into the unopposed branch
        settles it before the offense is prompted -- which also makes
        sending nobody a defensive weapon rather than only a saving.
        """
        cog, game, match = self.build("low_pass", "pressure")
        clear_the_defense_off_the_ball(match)
        match.offense_maneuver = None
        match.defense_maneuver = None
        match.challenger_id = None
        match.begin_uncontested_maneuver()

        self.assertEqual(
            cog.engine.maneuver_tiers(game, match), (MANEUVER_TIER_BASIC,),
        )

    def test_the_buttons_are_the_hand(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        cog.engine.load_match_state = mock.Mock(return_value=match)

        view = ManeuverActionSelectView(cog, game.game_id, "defense")
        keys = [
            item.custom_id.rsplit(":", 1)[1]
            for item in view.children
            if item.custom_id.startswith("d12ball:maneuver_pick:")
        ]

        self.assertEqual(
            keys,
            [
                m.key
                for m in cog.engine.maneuver_hand(game, match, "defense")
            ],
        )


class DinkyAdvancedManeuverPickTests(AdvancedHarness, unittest.TestCase):
    """
    In advanced mode Dinky weighs all six cards on a side, not the
    three advanced ones alone or the three basic ones alone --
    `DinkyAI.choose_maneuver_action` rolls a rank on the d6 and then
    coin-flips the tier, which lands on each of the six with equal
    odds. See "Dinky rolls its rank as it always has and picks the
    tier at random" in CLAUDE.md.
    """

    def test_dinky_reaches_every_card_of_an_advanced_hand(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        strategy = cog.ai_strategies[AIOpponent.DINKY]

        for side in ("offense", "defense"):
            with self.subTest(side=side):
                hand = cog.engine.maneuver_hand(game, match, side)
                picked = {
                    strategy.choose_maneuver_action(side, hand)
                    for _ in range(300)
                }

                self.assertEqual(picked, {m.key for m in hand})

    def test_a_basic_hand_never_reaches_an_advanced_card(self) -> None:
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


class OutrightRuleTests(AdvancedHarness, unittest.TestCase):
    """
    **An advanced effect follows the cards, not the dice.** Asserted
    against the four ways a maneuver lands rather than a table of
    matchups, because the two injury cases are exactly what a table
    gets wrong.
    """

    def test_a_decisive_matchup_carries_the_effects(self) -> None:
        cog, game, match = self.build("precise_pass", "double_team")

        self.assertTrue(cog.engine.advanced_effects_apply(match))
        self.assertEqual(
            cog.engine.advanced_cost(match, "precise_pass"), "double_team",
        )

    def test_a_tie_carries_nothing_and_resolves_as_the_basic_card(
        self,
    ) -> None:
        cog, game, match = self.build("precise_pass", "clear")

        self.assertFalse(cog.engine.advanced_effects_apply(match))
        self.assertIsNone(cog.engine.advanced_cost(match, "precise_pass"))
        self.assertEqual(
            cog.engine.resolving_maneuver(match, "precise_pass"), "low_pass",
        )

    def test_an_injured_auto_loss_of_a_tie_carries_nothing(self) -> None:
        """
        It was a tie on the cards; the injury only settled it without a
        roll. Same reading that makes the downgrade below carry them.
        """
        cog, game, match = self.build("precise_pass", "clear")
        match.injured.add(match.challenger_id)

        self.assertEqual(
            cog.engine.settled_maneuver_winner(match), "precise_pass",
        )
        self.assertFalse(cog.engine.advanced_effects_apply(match))
        self.assertEqual(
            cog.engine.resolving_maneuver(match, "precise_pass"), "low_pass",
        )

    def test_an_injury_downgrade_still_carries_them(self) -> None:
        """
        The author, 2026-08-19: "It wasn't a tie on the cards, so it can
        trigger the benefit/cost depending on the results of the skill
        test." The cards were decisive; the roll only decides which way
        the effects point, which is why the winner is still None here
        and the effects are still in force.
        """
        cog, game, match = self.build("precise_pass", "double_team")
        match.injured.add(match.active_player_id)

        self.assertIsNone(cog.engine.settled_maneuver_winner(match))
        self.assertTrue(cog.engine.advanced_effects_apply(match))
        self.assertEqual(
            cog.engine.resolving_maneuver(match, "precise_pass"),
            "precise_pass",
        )

    def test_a_basic_winner_over_a_basic_loser_owes_no_cost(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")

        self.assertTrue(cog.engine.advanced_effects_apply(match))
        self.assertIsNone(cog.engine.advanced_cost(match, "low_pass"))

    def test_an_unchallenged_maneuver_carries_nothing(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        clear_the_defense_off_the_ball(match)
        match.defense_maneuver = None
        match.challenger_id = None
        match.begin_uncontested_maneuver()

        self.assertFalse(cog.engine.advanced_effects_apply(match))


class EveryMatchupResolvesTests(
    AdvancedHarness, unittest.IsolatedAsyncioTestCase
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
                        with mock.patch("cogs.d12ball.save_games"):
                            await cog.resolve_maneuver(
                                build_interaction(), game, match,
                            )

    async def test_every_pairing_resolves_for_two_coaches(self) -> None:
        await self.resolve_every_pairing(solo=False)

    async def test_every_pairing_resolves_against_dinky(self) -> None:
        await self.resolve_every_pairing(solo=True)


class PrecisePassTests(AdvancedHarness, unittest.IsolatedAsyncioTestCase):
    def test_it_reaches_every_teammate_not_the_nearest_each_way(
        self,
    ) -> None:
        cog, game, match = self.build("precise_pass", "double_team")

        basic = cog.engine.low_pass_candidates(match)
        precise = cog.engine.precise_pass_candidates(match)

        self.assertGreater(len(precise), len(basic))
        # Every Low Pass destination is still a Precise Pass one: the
        # card takes the reach off, it does not change what a pass is.
        self.assertTrue(set(basic).issubset(set(precise)))

    async def test_it_adds_three_to_ball_speed(self) -> None:
        cog, game, match = self.build("precise_pass", "double_team")
        match.ball.speed = 4
        distance, receiver = cog.engine.precise_pass_candidates(match)[-1]

        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_low_pass(
                build_interaction(), game, match, distance,
                receiver_id=receiver, key="precise_pass",
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
        cog, game, match = self.build("precise_pass", "double_team")
        defense_side = match.defending_side()
        partner = cog.engine.double_team_partner(match)
        before = {
            player_id: self.flat_of(match, player_id)
            for player_id in (match.challenger_id, partner)
        }
        distance, receiver = cog.engine.precise_pass_candidates(match)[-1]

        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_low_pass(
                build_interaction(), game, match, distance,
                receiver_id=receiver, key="precise_pass",
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


class DribbleBurstTests(AdvancedHarness, unittest.IsolatedAsyncioTestCase):
    async def test_it_runs_to_the_last_space_and_charges_a_token_a_space(
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

        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_dribble_burst(build_interaction(), game, match)

        end = self.flat_of(match, handler)
        # Home attacks toward high indices, so the last space it can
        # reach is the top of the board.
        self.assertEqual(end, match.board.layout.board_size - 1)
        self.assertEqual(self.flat(match), end)
        self.assertEqual(match.exhaustion[handler], end - start)
        self.assertEqual(match.ball_carrier_id, handler)
        cog.offer_speed_choice.assert_awaited_once()

    async def test_a_playmaker_pays_one_token_fewer(self) -> None:
        """
        The one role ability that reads differently on the two cards of
        its rank (the author, 2026-08-19). A Dribble Burst's distance
        is not a choice, so the Playmaker's extra space has nothing to
        add to -- it lands on what the run costs instead.
        """
        cog, game, match = self.build("dribble_burst", "clear")
        playmaker = fielded(match, PlayerRole.PLAYMAKER)
        match.active_player_id = playmaker
        match.move_meeple(playmaker, match.ball.zone, match.ball.space_index)
        start = self.flat_of(match, playmaker)
        cog.offer_speed_choice = mock.AsyncMock()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_dribble_burst(build_interaction(), game, match)

        travelled = self.flat_of(match, playmaker) - start
        self.assertGreater(travelled, 0)
        self.assertEqual(match.exhaustion[playmaker], travelled - 1)

    async def test_defenders_are_no_obstacle(self) -> None:
        """
        The card says the run passes everyone in the way, so a defender
        parked on the destination changes nothing about where it ends.
        """
        cog, game, match = self.build("dribble_burst", "clear")
        blocker = match.visiting.field_players[0]
        last = match.board.layout.board_size - 1
        zone, space_index = match.board.position_at_flat_index(last)
        match.move_meeple(blocker, zone, space_index)
        cog.offer_speed_choice = mock.AsyncMock()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_dribble_burst(build_interaction(), game, match)

        self.assertEqual(self.flat(match), last)

    async def test_clears_cost_is_two_exhaustion_on_the_defender(
        self,
    ) -> None:
        cog, game, match = self.build("dribble_burst", "clear")
        defender = match.challenger_id
        cog.offer_speed_choice = mock.AsyncMock()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_dribble_burst(build_interaction(), game, match)

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

        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_dribble_advance(
                build_interaction(), game, match, 1,
            )

        self.assertEqual(match.exhaustion[defender], 2)


class ClearTests(AdvancedHarness, unittest.IsolatedAsyncioTestCase):
    async def test_it_drives_the_ball_back_three_and_drops_speed_by_three(
        self,
    ) -> None:
        # Against the *basic* High Pass, so nothing but Clear's own
        # benefit is in force -- Setup Pass would add its cost on top.
        cog, game, match = self.build("high_pass", "clear", board_size=9)
        match.ball.speed = 8
        start = self.flat(match)
        cog.begin_loose_ball = mock.AsyncMock()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_clear(build_interaction(), game, match)

        self.assertEqual(self.flat(match), start - 3)
        self.assertEqual(match.ball.speed, 5)
        cog.begin_loose_ball.assert_awaited_once()

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

        with mock.patch("cogs.d12ball.save_games"):
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

        with mock.patch("cogs.d12ball.save_games"):
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

        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_deflect(
                build_interaction(), game, match,
            )

        self.assertEqual(self.flat(match), start - 2)
        self.assertEqual(match.ball.speed, 8)


class InterceptTests(AdvancedHarness, unittest.IsolatedAsyncioTestCase):
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

        with mock.patch("cogs.d12ball.save_games"):
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

        with mock.patch("cogs.d12ball.save_games"):
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

        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_intercept(build_interaction(), game, match)

        cog.begin_shooter_choice.assert_awaited_once()
        cog.begin_run_back.assert_not_awaited()
        self.assertEqual(
            cog.begin_shooter_choice.await_args.args[3], [challenger],
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

        with mock.patch("cogs.d12ball.save_games"):
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

        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_high_pass(build_interaction(), game, match, 3)

        cog.begin_high_pass_contest.assert_awaited_once()


class SetupPassTests(AdvancedHarness, unittest.IsolatedAsyncioTestCase):
    def test_it_offers_only_distances_that_reach_a_teammate(self) -> None:
        cog, game, match = self.build("setup_pass", "steal", board_size=9)

        offered = cog.engine.setup_pass_distances(match)

        offense_players = set(match.home.field_players)
        for distance in (0, 1, 3):
            origin = self.flat(match)
            target = match.relative_flat_index(
                origin, match.ball.possession, distance,
            )
            reaches = abs(target - origin) == distance
            zone, space_index = match.board.position_at_flat_index(target)
            occupied = reaches and any(
                player_id in offense_players
                and player_id != match.active_player_id
                for player_id in match.board.spaces[zone][space_index]
            )
            with self.subTest(distance=distance):
                self.assertEqual(distance in offered, occupied)

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

        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_setup_pass(build_interaction(), game, match)

        cog.offer_speed_choice.assert_awaited_once()
        self.assertEqual(
            match.pending_effect_continuation, {"kind": "setup_pass_shot"},
        )

    async def test_the_continuation_survives_a_save_and_reload(self) -> None:
        cog, game, match = self.build("setup_pass", "steal")
        cog.offer_speed_choice = mock.AsyncMock()

        with mock.patch("cogs.d12ball.save_games"):
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

        with mock.patch("cogs.d12ball.save_games"):
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

        with mock.patch("cogs.d12ball.save_games"):
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

        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_setup_pass(build_interaction(), game, match, 3)

        self.assertEqual(self.flat(match), start + 3)
        self.assertEqual(match.ball_carrier_id, receiver)
        cog.offer_scoring_attempt_choice.assert_awaited_once()

    async def test_it_cannot_overshoot_and_goes_out_instead(self) -> None:
        """
        **Setup Pass cannot overshoot**: with no teammate at 0, 1 or 3
        the pass runs out of play and the other team gains possession.
        That is the existing out-of-bounds outcome, and a fourth
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

        with mock.patch("cogs.d12ball.save_games"):
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

        with mock.patch("cogs.d12ball.save_games"):
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

        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_setup_pass_push_back(
                interaction, game, match, push,
            )

        self.assertEqual(self.flat(match), after_clear - push)
        cog.begin_loose_ball.assert_awaited_once()


class DoubleTeamTests(AdvancedHarness, unittest.IsolatedAsyncioTestCase):
    async def test_it_pushes_the_handler_back_two_and_brings_a_partner(
        self,
    ) -> None:
        cog, game, match = self.build("dribble_burst", "double_team")
        handler = match.active_player_id
        challenger = match.challenger_id
        partner = cog.engine.double_team_partner(match)
        start = self.flat_of(match, handler)
        cog.finish_maneuver_resolution = mock.AsyncMock()

        with mock.patch("cogs.d12ball.save_games"):
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

        with mock.patch("cogs.d12ball.save_games"):
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

        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_double_team(build_interaction(), game, match)

        self.assertEqual(match.ball.possession, TeamSide.VISITING)
        self.assertEqual(match.ball.speed, 9)
        self.assertEqual(match.ball_carrier_id, match.challenger_id)
        cog.begin_run_back.assert_awaited_once()
        self.assertTrue(
            cog.begin_run_back.await_args.kwargs["speed_choice_after"],
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

        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_pressure(build_interaction(), game, match)

        self.assertEqual(match.ball.possession, TeamSide.VISITING)
        self.assertEqual(match.ball.speed, 1)


if __name__ == "__main__":
    unittest.main()

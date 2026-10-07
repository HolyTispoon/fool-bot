"""
Gambits: which hand a coach holds, when a gambit's effect
fires, and what each of the six does.

Three layers, and they fail for different reasons:

- **The hand.** `RulesEngine.maneuver_tiers` is the only answer to who
  may play what, and the buttons, the card image and the click that
  answers all read it. A standard game is three cards; a coach holding
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

import inspect
import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import (
    ManeuverActionPromptView,
    SetupPassChoiceView,
    SpeedDeltaChoiceView,
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
from d12ball import tokens
from d12ball.flow.arrivals import finish_maneuver_resolution
from d12ball.flow.effects import (
    offer_setup_pass_distance as flow_offer_setup_pass_distance,
    speed_choice_step,
)
from d12ball.flow.turn import declare_gambit_step
from ai_answers import ai_answers
from d12ball.prompts import PromptKind, pending_prompt
from d12ball.game import (
    AIOpponent,
    CoinFace,
    D12BallGame,
    GameMode,
    GameStatus,
    Team,
)

from roster import benched, fielded
from d12ball.flow import FollowOnStep
from flow_stubs import REAL_MODEL_STEPS
from flow_stubs import driver_reaches_cog_stubs
from save_patches import suppressed_cog_saves
from cog_steps import apply_dribble_advance, apply_dribble_burst, apply_high_pass, apply_low_pass, apply_setup_pass, build_effect_choice_view, offer_setup_pass_distance, resolve_clear, resolve_deflect, resolve_double_team, resolve_dribble_burst, resolve_intercept, resolve_maneuver, resolve_pressure, resolve_setup_pass, resolve_steal


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


def loose_ball_distance(call) -> int:
    """
    The `distance_moved` a recorded `begin_loose_ball` was called with,
    read through the real method's signature rather than off
    `call.args`.

    A Cross that lands on nobody reaches it as a `FollowOn` since
    rank O3 of docs/design/model-discord-split.md, and `dispatch_step_result`
    passes a follow-on's arguments **by keyword** -- so an argument the
    cog used to hand over positionally now arrives named. Binding the
    call to the signature answers for both shapes, which is the reading
    rank D2 wrote down: fix the assertion, not the call. The same
    helper is in `tests/test_d12ball_loose_ball.py` and
    `tests/test_d12ball_components.py`, from rank D1.
    """
    return inspect.signature(
        REAL_MODEL_STEPS[FollowOnStep.BEGIN_LOOSE_BALL],
    ).bind(*call.args, **call.kwargs).arguments["distance_moved"]


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
                Zone.VISITORS_ZONE,
                match.board.layout.zone_spaces[Zone.VISITORS_ZONE] - 1,
            )


def open_gambits(match: MatchState) -> None:
    """
    Put **both** hands in the harness on their gambits (Law 19.3).

    Since 2026-09-28 nobody holds a gambit until the coach holding the
    coin declares one, and the other coach, where behind, answers first
    with a gambit of their own or their basic cards. So: the visitors
    (the defense here) hold the coin and declare, and home (the offense,
    a goal down) answers with a gambit -- both hands the three advanced
    maneuvers. Every test about *what a hand looks like* would otherwise
    be drawing three basic cards and asserting nothing.
    """
    match.coin_holder = TeamSide.VISITING
    match.declare_gambit("defense", TeamSide.VISITING)
    match.scoreboard.visiting_score += 1
    match.answer_gambit("offense", True)


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
        self.enterContext(driver_reaches_cog_stubs(cog))
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

    def test_a_standard_game_offers_three_cards(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        game.mode = GameMode.STANDARD

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

    def test_a_coach_holding_gambits_is_offered_the_three_in_rank_order(
        self,
    ) -> None:
        """Only the gambits: a hand is always three cards (the author,
        2026-09-28)."""
        cog, game, match = self.build("low_pass", "pressure")
        open_gambits(match)

        for side, keys in (
            ("offense", ["skilled_pass", "dribble_burst", "setup_pass"]),
            ("defense", ["clear", "intercept", "double_team"]),
        ):
            with self.subTest(side=side):
                self.assertEqual(
                    [m.key for m in cog.engine.maneuver_hand(game, match, side)],
                    keys,
                )

    def test_the_gambits_withheld_are_the_rest_of_the_sides_cards(
        self,
    ) -> None:
        """
        `withheld_gambits` is the complement of the hand within the
        side's cards: empty in a standard game, empty for a side
        holding them -- the one that declared, and the one answering
        while behind -- and the three in rank order for a side that
        holds none (step 5 of docs/web-app-redesign.md dims them).
        """
        cog, game, match = self.build("low_pass", "pressure")
        engine = cog.engine

        # Level and unhurt: nobody holds a gambit.
        for side in ("offense", "defense"):
            with self.subTest(side=side, position="level"):
                held = {m.key for m in engine.maneuver_hand(game, match, side)}
                withheld = [
                    m.key for m in engine.withheld_gambits(game, match, side)
                ]
                self.assertEqual(len(withheld), 3)
                self.assertFalse(held & set(withheld))
                self.assertEqual(
                    held | set(withheld),
                    {m.key for m in cog.maneuver_catalog.side(side)},
                )
        self.assertEqual(
            [m.key for m in engine.withheld_gambits(game, match, "offense")],
            ["skilled_pass", "dribble_burst", "setup_pass"],
        )

        open_gambits(match)
        for side in ("offense", "defense"):
            with self.subTest(side=side, position="behind"):
                self.assertEqual(
                    engine.withheld_gambits(game, match, side), (),
                )

        game.mode = GameMode.STANDARD
        self.assertEqual(engine.withheld_gambits(game, match, "offense"), ())

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
        # Still picking: the view builds its rows from the prompt's
        # options, and the chain reads two picks made as the maneuver
        # settled.
        match.offense_maneuver = None
        match.defense_maneuver = None
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
        # The coin's buttons share that row (here, "Confirm maneuver":
        # the harness's offense pick is in question), and the link
        # still comes last.
        self.assertEqual(
            rendered[-1][-2:], ["Maneuver Reference", FULL_IMAGE_BUTTON_LABEL],
        )
        self.assertNotIn(
            FULL_IMAGE_BUTTON_LABEL,
            [label for row in rendered[:-1] for label in row],
        )


class CoinTests(GambitHarness, unittest.TestCase):
    """
    **The coin decides who may make a gambit** (Law 19.3, the author,
    2026-09-28): the toss winner keeps it, its holder may declare a
    gambit at a challenged maneuver -- setting their three basic cards
    aside for their three advanced maneuvers -- and declaring hands it to
    the other coach. That coach may answer with a gambit of their own
    only while behind.

    Asserted through `maneuver_hand` as well as the predicates, because
    the hand is what a coach actually gets.
    """

    def hands(self, cog, game, match) -> dict[str, int]:
        return {
            side: len(cog.engine.maneuver_hand(game, match, side))
            for side in ("offense", "defense")
        }

    def unpicked(self):
        cog, game, match = self.build("low_pass", "pressure")
        match.offense_maneuver = None
        match.defense_maneuver = None
        return cog, game, match

    def test_the_toss_winner_holds_the_coin(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        game.coin_winner_player_number = 2   # the visitors' coach
        self.assertEqual(
            cog.engine.coin_holder(game, match), TeamSide.VISITING,
        )
        game.coin_winner_player_number = 1
        self.assertEqual(cog.engine.coin_holder(game, match), TeamSide.HOME)

    def test_a_game_seated_without_a_toss_starts_it_with_home(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        self.assertIsNone(game.coin_winner_player_number)
        self.assertEqual(cog.engine.coin_holder(game, match), TeamSide.HOME)

    def test_a_standard_game_has_no_coin_to_hold(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        game.mode = GameMode.STANDARD
        self.assertIsNone(cog.engine.coin_holder(game, match))
        for side in ("offense", "defense"):
            self.assertFalse(cog.engine.may_declare_gambit(game, match, side))

    def test_nobody_holds_a_gambit_until_one_is_declared(self) -> None:
        """Behind or not: being behind only answers a gambit now."""
        cog, game, match = self.unpicked()
        match.scoreboard.visiting_score += 1
        match.mark_injured(
            fielded(match, PlayerRole.WINGER, TeamSide.VISITING)
        )
        self.assertEqual(self.hands(cog, game, match), {
            "offense": 3, "defense": 3,
        })

    def test_only_the_coin_holder_may_declare(self) -> None:
        cog, game, match = self.unpicked()
        # Home has the ball in this harness, and holds the coin.
        self.assertTrue(cog.engine.may_declare_gambit(game, match, "offense"))
        self.assertFalse(
            cog.engine.may_declare_gambit(game, match, "defense")
        )

    def test_declaring_swaps_the_hand_and_hands_over_the_coin(self) -> None:
        cog, game, match = self.unpicked()
        match.declare_gambit("offense", TeamSide.HOME)

        self.assertEqual(match.coin_holder, TeamSide.VISITING)
        self.assertEqual(
            [m.key for m in cog.engine.maneuver_hand(game, match, "offense")],
            ["skilled_pass", "dribble_burst", "setup_pass"],
        )
        # Level and unhurt: the visitors may not answer.
        self.assertEqual(
            len(cog.engine.maneuver_hand(game, match, "defense")), 3,
        )
        # Nobody declares twice in one maneuver, the new holder included.
        for side in ("offense", "defense"):
            self.assertFalse(
                cog.engine.may_declare_gambit(game, match, side)
            )

    def test_the_coin_is_the_new_holders_at_the_next_maneuver(self) -> None:
        cog, game, match = self.unpicked()
        match.declare_gambit("offense", TeamSide.HOME)
        match.reset_maneuver()

        self.assertEqual(
            cog.engine.coin_holder(game, match), TeamSide.VISITING,
        )
        self.assertIsNone(match.gambit_declared_by)
        self.assertFalse(
            cog.engine.may_declare_gambit(game, match, "offense")
        )

    def test_declaring_withdraws_a_pick_and_puts_the_others_in_question(
        self,
    ) -> None:
        cog, game, match = self.unpicked()
        match.choose_offense_maneuver("low_pass")
        match.choose_defense_maneuver("steal")

        match.declare_gambit("offense", TeamSide.HOME)

        self.assertIsNone(match.offense_maneuver)
        self.assertEqual(match.defense_maneuver, "steal")
        self.assertEqual(match.pick_unconfirmed, "defense")
        self.assertFalse(match.maneuver_selections_complete)

        match.choose_offense_maneuver("setup_pass")
        self.assertFalse(
            match.maneuver_selections_complete,
            "a pick in question still waits on its coach",
        )
        match.confirm_maneuver("defense")
        self.assertTrue(match.maneuver_selections_complete)

    def test_a_pick_in_question_may_be_changed(self) -> None:
        cog, game, match = self.unpicked()
        match.defense_maneuver = "steal"
        match.declare_gambit("offense", TeamSide.HOME)
        match.offense_maneuver = "setup_pass"

        match.change_maneuver("defense", "deflect")

        self.assertEqual(match.defense_maneuver, "deflect")
        self.assertIsNone(match.pick_unconfirmed)
        self.assertTrue(match.maneuver_selections_complete)

    def test_a_second_declaration_is_refused(self) -> None:
        from d12ball.components import RuleRefusal

        cog, game, match = self.unpicked()
        match.declare_gambit("offense", TeamSide.HOME)
        with self.assertRaises(RuleRefusal):
            match.declare_gambit("defense", TeamSide.VISITING)

    def test_trailing_lets_the_other_coach_answer_before_the_cards(
        self,
    ) -> None:
        cog, game, match = self.unpicked()
        match.scoreboard.home_score += 1          # the visitors trail
        match.declare_gambit("offense", TeamSide.HOME)

        self.assertTrue(cog.engine.may_answer_gambit(game, match, "defense"))
        self.assertEqual(cog.engine.gambit_answer_owed(game, match), "defense")

        match.answer_gambit("defense", True)

        self.assertIsNone(cog.engine.gambit_answer_owed(game, match))
        self.assertEqual(
            [m.key for m in cog.engine.maneuver_hand(game, match, "defense")],
            ["clear", "intercept", "double_team"],
        )

    def test_answering_with_the_basic_cards_keeps_them(self) -> None:
        cog, game, match = self.unpicked()
        match.scoreboard.home_score += 1
        match.choose_defense_maneuver("steal")
        match.declare_gambit("offense", TeamSide.HOME)

        match.answer_gambit("defense", False)

        self.assertEqual(
            [m.key for m in cog.engine.maneuver_hand(game, match, "defense")],
            ["deflect", "steal", "pressure"],
        )
        self.assertEqual(match.defense_maneuver, "steal")
        self.assertEqual(match.pick_unconfirmed, "defense")

    def test_a_counter_sets_an_earlier_pick_aside(self) -> None:
        cog, game, match = self.unpicked()
        match.scoreboard.home_score += 1
        match.choose_defense_maneuver("steal")
        match.declare_gambit("offense", TeamSide.HOME)

        match.answer_gambit("defense", True)

        self.assertIsNone(match.defense_maneuver)
        self.assertIsNone(match.pick_unconfirmed)

    def test_answering_leaves_the_coin_where_it_is(self) -> None:
        cog, game, match = self.unpicked()
        match.scoreboard.home_score += 1
        match.declare_gambit("offense", TeamSide.HOME)
        match.answer_gambit("defense", True)
        match.choose_defense_maneuver("intercept")

        self.assertEqual(match.coin_holder, TeamSide.VISITING)

    def test_the_declarer_being_behind_gives_the_other_nothing(self) -> None:
        cog, game, match = self.unpicked()
        match.scoreboard.visiting_score += 1      # home trails
        match.declare_gambit("offense", TeamSide.HOME)

        self.assertFalse(
            cog.engine.may_answer_gambit(game, match, "defense")
        )
        self.assertIsNone(cog.engine.gambit_answer_owed(game, match))
        self.assertEqual(self.hands(cog, game, match), {
            "offense": 3, "defense": 3,
        })

    def test_fielding_more_injured_players_is_behind(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        match.mark_injured(fielded(match, PlayerRole.WINGER))

        self.assertTrue(cog.engine.behind(match, TeamSide.HOME))
        self.assertFalse(cog.engine.behind(match, TeamSide.VISITING))

    def test_fielding_more_exhausted_players_is_behind(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        match.exhausted.add(fielded(match, PlayerRole.WINGER))

        self.assertTrue(cog.engine.behind(match, TeamSide.HOME))
        self.assertFalse(cog.engine.behind(match, TeamSide.VISITING))

    def test_exhausted_and_injured_combine_on_the_same_side(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        match.mark_injured(fielded(match, PlayerRole.WINGER))
        match.exhausted.add(fielded(match, PlayerRole.STRIKER))
        match.mark_injured(
            fielded(match, PlayerRole.WINGER, TeamSide.VISITING)
        )

        self.assertTrue(cog.engine.behind(match, TeamSide.HOME))
        self.assertFalse(cog.engine.behind(match, TeamSide.VISITING))

    def test_level_counts_are_not_behind(self) -> None:
        """**Strictly** more (the author, 2026-09-28): a level score, a
        level injury count and a level combined count are behind for
        nobody."""
        cog, game, match = self.build("low_pass", "pressure")
        match.exhausted.add(fielded(match, PlayerRole.WINGER))
        match.mark_injured(
            fielded(match, PlayerRole.WINGER, TeamSide.VISITING)
        )
        for side in (TeamSide.HOME, TeamSide.VISITING):
            with self.subTest(side=side):
                self.assertFalse(cog.engine.behind(match, side))

    def test_the_bench_does_not_count(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        match.mark_injured(benched(match, PlayerRole.STRIKER))
        match.exhausted.add(benched(match, PlayerRole.DEFENDER))

        self.assertFalse(cog.engine.behind(match, TeamSide.HOME))

    def test_both_teams_can_be_behind_at_once(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        match.scoreboard.visiting_score += 1
        match.mark_injured(
            fielded(match, PlayerRole.WINGER, TeamSide.VISITING)
        )
        for side in (TeamSide.HOME, TeamSide.VISITING):
            with self.subTest(side=side):
                self.assertTrue(cog.engine.behind(match, side))

    def test_a_gambit_already_played_keeps_its_effect(self) -> None:
        """
        The coin is on the hand and nothing else: a gambit legally
        played keeps its benefit whoever holds the coin afterwards,
        because both outcomes are read off the two stored keys.
        """
        cog, game, match = self.build("skilled_pass", "pressure")
        self.assertTrue(
            cog.engine.gambit_benefit_applies(match, "skilled_pass")
        )
        match.coin_holder = TeamSide.VISITING
        self.assertEqual(
            cog.engine.resolving_maneuver(match, "skilled_pass"),
            "skilled_pass",
        )

    def test_the_prompt_says_who_holds_the_coin_and_who_may_answer(
        self,
    ) -> None:
        cog, game, match = self.unpicked()

        before = cog.engine.describe_gambit_access(game, match)
        self.assertIn("holds the coin", before)
        self.assertIn(game.player_1_name, before)
        self.assertNotIn(game.player_2_name, before)

        match.declare_gambit("offense", TeamSide.HOME)
        after = cog.engine.describe_gambit_access(game, match)
        self.assertIn("has declared a gambit", after)
        self.assertNotIn("may answer", after)

        match.scoreboard.home_score += 1
        self.assertIn(
            "may answer", cog.engine.describe_gambit_access(game, match),
        )

    def test_an_unchallenged_maneuver_is_told_nothing(self) -> None:
        cog, game, match = self.build("low_pass", "pressure")
        clear_the_defense_off_the_ball(match)
        match.offense_maneuver = None
        match.defense_maneuver = None
        match.challenger_id = None
        match.begin_uncontested_maneuver()

        self.assertEqual(cog.engine.describe_gambit_access(game, match), "")
        self.assertFalse(
            cog.engine.may_declare_gambit(game, match, "offense")
        )

    def test_the_coin_survives_a_save(self) -> None:
        cog, game, match = self.unpicked()
        match.defense_maneuver = "steal"
        match.declare_gambit("offense", TeamSide.HOME)

        reloaded = MatchState.from_dict(
            match.to_dict(), cog.engine.basic_ruleset,
        )

        self.assertEqual(reloaded.coin_holder, TeamSide.VISITING)
        self.assertEqual(reloaded.gambit_declared_by, "offense")
        self.assertEqual(reloaded.pick_unconfirmed, "defense")

    def test_the_coin_shows_the_toss_until_it_passes(self) -> None:
        """Law 3.1.4: the winner keeps the coin on the face it landed on,
        whoever flipped it; a game seated without a toss shows Fortune."""
        cog, game, match = self.unpicked()
        self.assertEqual(cog.engine.coin_face(game, match), CoinFace.FORTUNE)
        game.coin_face = CoinFace.DOOM
        self.assertEqual(cog.engine.coin_face(game, match), CoinFace.DOOM)
        game.mode = GameMode.STANDARD
        self.assertIsNone(cog.engine.coin_face(game, match))

    def test_the_coach_it_goes_to_flips_it(self) -> None:
        """Law 19.3.3: a declaration hands the coin over and it is
        flipped, the engine's draw, said in the narration with the
        coin's own mark -- and the face it landed on is the one shown."""
        cog, game, match = self.unpicked()
        game.coin_face = CoinFace.FORTUNE
        with mock.patch.object(
            cog.engine, "flip_coin", return_value=CoinFace.DOOM,
        ) as flip:
            result = declare_gambit_step(cog.engine, game, match, side="offense")

        flip.assert_called_once_with()
        self.assertEqual(match.coin_face, CoinFace.DOOM)
        self.assertEqual(cog.engine.coin_face(game, match), CoinFace.DOOM)
        said = " ".join(result.narration)
        self.assertIn(
            f"who flips it: {tokens.coin(CoinFace.DOOM)} Doom.", said,
        )

    def test_the_holder_is_said_with_the_face_up(self) -> None:
        cog, game, match = self.unpicked()
        game.coin_face = CoinFace.DOOM
        said = cog.engine.describe_gambit_access(game, match)
        self.assertIn(
            f"holds the coin, {tokens.coin(CoinFace.DOOM)} Doom up, and may "
            "declare a gambit.",
            said,
        )

    def test_the_face_survives_a_save(self) -> None:
        cog, game, match = self.unpicked()
        match.declare_gambit("offense", TeamSide.HOME, CoinFace.DOOM)

        reloaded = MatchState.from_dict(
            match.to_dict(), cog.engine.basic_ruleset,
        )

        self.assertEqual(reloaded.coin_face, CoinFace.DOOM)
        self.assertEqual(cog.engine.coin_face(game, reloaded), CoinFace.DOOM)

    def test_a_save_from_before_the_flip_shows_the_toss(self) -> None:
        cog, game, match = self.unpicked()
        match.declare_gambit("offense", TeamSide.HOME)
        data = match.to_dict()
        data.pop("coin_face")
        game.coin_face = CoinFace.DOOM

        reloaded = MatchState.from_dict(data, cog.engine.basic_ruleset)

        self.assertIsNone(reloaded.coin_face)
        self.assertEqual(cog.engine.coin_face(game, reloaded), CoinFace.DOOM)

    def test_a_save_from_before_the_coin_reads_the_toss(self) -> None:
        cog, game, match = self.unpicked()
        data = match.to_dict()
        for key in ("coin_holder", "gambit_declared_by", "pick_unconfirmed"):
            data.pop(key)
        game.coin_winner_player_number = 2

        reloaded = MatchState.from_dict(data, cog.engine.basic_ruleset)

        self.assertIsNone(reloaded.coin_holder)
        self.assertEqual(
            cog.engine.coin_holder(game, reloaded), TeamSide.VISITING,
        )


class CoinThroughTheDriverTests(GambitHarness, unittest.TestCase):
    """The declaration, the answer and the confirmation, as a click
    makes them: through `driver.apply`, off the prompt's own options."""

    def setUp(self) -> None:
        from d12ball.flow import driver
        from d12ball.prompts import pending_prompt

        self.driver = driver
        self.pending_prompt = pending_prompt
        cog, game, match = self.build("low_pass", "pressure")
        match.offense_maneuver = None
        match.defense_maneuver = None
        self.cog, self.game, self.match = cog, game, match

    def apply(self, choice: str, kind=PromptKind.MANEUVER_ACTION, **arguments):
        from d12ball.prompts import Action

        return self.driver.apply(
            self.cog.engine, self.game, self.match,
            Action(kind, choice, arguments),
        )

    def hand(self, side: str):
        prompt = self.pending_prompt(self.cog.engine, self.game, self.match)
        self.assertIs(prompt.kind, PromptKind.MANEUVER_ACTION)
        return next(h for h in prompt.options.hands if h.side == side)

    def test_the_prompt_offers_the_declaration_to_the_holder_alone(
        self,
    ) -> None:
        self.assertTrue(self.hand("offense").may_declare)
        self.assertFalse(self.hand("defense").may_declare)

    def test_a_declaration_without_the_coin_is_refused(self) -> None:
        from d12ball.flow.driver import Refusal

        run = self.apply("gambit", side="defense")

        self.assertIsInstance(run, Refusal)
        self.assertEqual(run.law, "who-may-make-a-gambit")
        self.assertIsNone(self.match.gambit_declared_by)

    def test_declare_then_confirm_resolves_the_maneuver(self) -> None:
        from d12ball.flow.driver import Refusal

        self.apply("", side="defense", maneuver_key="steal")
        run = self.apply("gambit", side="offense")
        self.assertNotIsInstance(run, Refusal)
        self.assertTrue(self.hand("defense").unconfirmed)
        self.assertIn("declares a gambit", " ".join(run.result.narration))

        # The declarer's hand is the three advanced maneuvers.
        self.assertEqual(
            self.hand("offense").maneuver_keys,
            ("skilled_pass", "dribble_burst", "setup_pass"),
        )
        refused = self.apply("", side="offense", maneuver_key="low_pass")
        self.assertIsInstance(refused, Refusal)

        self.apply("", side="offense", maneuver_key="setup_pass")
        self.assertEqual(
            self.pending_prompt(
                self.cog.engine, self.game, self.match,
            ).kind,
            PromptKind.MANEUVER_ACTION,
            "the defense's pick still waits to be confirmed",
        )
        self.apply("confirm", side="defense")
        after = self.pending_prompt(self.cog.engine, self.game, self.match)
        self.assertIsNot(
            getattr(after, "kind", None), PromptKind.MANEUVER_ACTION,
            "confirming the last pick in question resolves the maneuver",
        )

    def test_the_declarer_may_change_while_the_other_waits_to_confirm(
        self,
    ) -> None:
        """Law 19.3.7: the other side's pick is not down while a gambit
        has put it in question."""
        from d12ball.flow.driver import Refusal

        self.apply("", side="defense", maneuver_key="deflect")
        self.apply("gambit", side="offense")
        self.apply("", side="offense", maneuver_key="skilled_pass")

        changed = self.apply("", side="offense", maneuver_key="dribble_burst")

        self.assertNotIsInstance(changed, Refusal)
        self.assertEqual(self.match.offense_maneuver, "dribble_burst")
        self.assertEqual(self.match.pick_unconfirmed, "defense")

    def test_a_side_not_behind_at_the_declaration_is_never_asked(
        self,
    ) -> None:
        """Behind is read as the maneuvers are chosen: a score that moves
        later in the maneuver (an own-goal roll) must not put the
        question up in the middle of its resolution."""
        self.apply("gambit", side="offense")
        self.assertEqual(self.match.gambit_answer, "basic")

        self.match.scoreboard.home_score += 1   # the visitors now trail

        self.assertIsNone(
            self.cog.engine.gambit_answer_owed(self.game, self.match),
        )

    def test_confirm_with_nothing_to_confirm_is_refused(self) -> None:
        from d12ball.flow.driver import Refusal

        self.assertIsInstance(self.apply("confirm", side="defense"), Refusal)

    def test_the_answer_comes_before_either_side_picks(self) -> None:
        from d12ball.flow.driver import GAMBIT_ANSWER_FIRST, Refusal

        self.match.scoreboard.home_score += 1       # the visitors trail
        self.apply("gambit", side="offense")

        prompt = self.pending_prompt(self.cog.engine, self.game, self.match)
        self.assertIs(prompt.kind, PromptKind.GAMBIT_ANSWER)
        self.assertEqual(prompt.side, TeamSide.VISITING)
        refused = self.apply("", side="offense", maneuver_key="setup_pass")
        self.assertIsInstance(refused, Refusal)
        self.assertEqual(refused.reason, GAMBIT_ANSWER_FIRST)

        run = self.apply("gambit", kind=PromptKind.GAMBIT_ANSWER)

        self.assertIn(
            "answers with a gambit of their own",
            " ".join(run.result.narration),
        )
        self.assertEqual(
            self.hand("defense").maneuver_keys,
            ("clear", "intercept", "double_team"),
        )
        self.assertEqual(
            self.hand("offense").maneuver_keys,
            ("skilled_pass", "dribble_burst", "setup_pass"),
        )
        self.assertEqual(self.match.coin_holder, TeamSide.VISITING)


class DinkyGambitPickTests(GambitHarness, unittest.TestCase):
    """
    Dinky's gambits. Holding the coin, it declares on a coin flip; once
    a gambit is on the table it rolls a rank on the d6 and coin-flips
    the tier where its hand holds both -- which is only when it is
    answering while behind. See "Dinky rolls its rank as it always has
    and picks the tier at random" in docs/design/maneuvers.md.

    Asked the way the game asks it: the maneuver prompt, with Dinky's
    hand on it, through `driver.ai_action`.
    """

    def unpicked(self, side: str):
        """The harness's position with the cards not yet picked, and
        the AI on `side`."""
        cog, game, match = self.build("low_pass", "pressure")
        match.offense_maneuver = None
        match.defense_maneuver = None
        game.player_2_id = None
        if side == "offense":
            game.home_player_number, game.visiting_player_number = 2, 1
        return cog, game, match

    def picks(self, cog, game, match, side: str, times: int) -> set[str]:
        keys = set()
        for _ in range(times):
            action = ai_answers(cog.engine, game, match)
            self.assertIs(action.kind, PromptKind.MANEUVER_ACTION)
            self.assertEqual(action.arguments["side"], side)
            keys.add(action.arguments["maneuver_key"])
        return keys

    def test_dinky_behind_answers_both_ways(self) -> None:
        cog, game, match = self.unpicked("defense")
        match.scoreboard.home_score += 1                 # Dinky trails
        match.declare_gambit("offense", TeamSide.HOME)

        answers = set()
        for _ in range(60):
            action = ai_answers(cog.engine, game, match)
            self.assertIs(action.kind, PromptKind.GAMBIT_ANSWER)
            answers.add(action.choice)
        self.assertEqual(answers, {"gambit", "basic"})

        match.answer_gambit("defense", True)
        picked = self.picks(cog, game, match, "defense", 200)
        self.assertEqual(picked, {"clear", "intercept", "double_team"})

    def test_dinky_having_declared_plays_an_advanced_maneuver(self) -> None:
        cog, game, match = self.unpicked("defense")
        match.coin_holder = TeamSide.VISITING
        match.declare_gambit("defense", TeamSide.VISITING)

        picked = self.picks(cog, game, match, "defense", 200)

        self.assertEqual(
            picked,
            {
                m.key
                for m in cog.maneuver_catalog.for_tier(
                    "defense", MANEUVER_TIER_GAMBIT,
                )
            },
        )

    def test_dinky_holding_the_coin_sometimes_declares(self) -> None:
        cog, game, match = self.unpicked("defense")
        match.coin_holder = TeamSide.VISITING
        choices = {
            ai_answers(cog.engine, game, match).choice for _ in range(100)
        }
        self.assertEqual(choices, {"", "gambit"})

    def test_a_closed_hand_leaves_dinky_the_basic_three(self) -> None:
        """
        Without the coin and with nothing to answer, Dinky plays the
        basic three without knowing why.
        """
        cog, game, match = self.unpicked("defense")

        picked = self.picks(cog, game, match, "defense", 300)

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
        cog, game, match = self.unpicked("offense")
        match.coin_holder = TeamSide.VISITING   # the human's coin
        basic_hand = cog.maneuver_catalog.for_tier(
            "offense", MANEUVER_TIER_BASIC,
        )

        picked = self.picks(cog, game, match, "offense", 150)

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
        Pinpoint never lost on them, so it owes nothing -- where
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
                for board_size in (7, 9, 10):
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
                            await resolve_maneuver(cog, 
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
            await apply_low_pass(cog, 
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
            await apply_low_pass(cog, 
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
        match.ball.speed = 3
        cog.offer_speed_choice = mock.AsyncMock()
        cog.finish_maneuver_resolution = mock.AsyncMock()

        with suppressed_cog_saves():
            await apply_dribble_burst(cog, 
                build_interaction(), game, match, 2,
            )

        end = self.flat_of(match, handler)
        # Home attacks toward high indices.
        self.assertEqual(end, start + 2)
        self.assertEqual(self.flat(match), end)
        self.assertEqual(match.exhaustion[handler], 2)
        self.assertEqual(match.ball_carrier_id, handler)
        # The ball is left at 12 and nobody is asked about it (the
        # author, 2026-09-20: "precisely 12, not any number"), so the
        # burst ends on the tail rather than the speed choice, and says
        # the speed the way a speed choice would have.
        self.assertEqual(match.ball.speed, 12)
        cog.offer_speed_choice.assert_not_awaited()
        cog.finish_maneuver_resolution.assert_awaited_once()
        self.assertIn(
            "Ball speed is now **12**.",
            cog.finish_maneuver_resolution.await_args.kwargs["lead_in"],
        )

    def test_the_run_is_bounded_at_five_for_a_playmaker_and_by_the_field(
        self,
    ) -> None:
        """
        `dribble_burst_distances` is the whole of what may be picked.
        The harness's kickoff handler is a Playmaker, whose ability
        (since 2026-09-26) is an additional space on either Dribble
        card, so the bound here is one more than
        `DRIBBLE_BURST_MAX_DISTANCE`. Board 9 is where it bites: from
        their own goal zone the goal they attack is more than five
        spaces off, so the card stops short of it -- which is the
        change, and what "runs to the goal" used to mean.
        """
        cog, game, match = self.build("dribble_burst", "clear", board_size=9)
        handler = match.active_player_id
        self.assertEqual(
            cog.engine.get_player_definition(handler).role,
            PlayerRole.PLAYMAKER,
        )
        # Back in their own goal zone, which on board 9 is eight
        # spaces from the end of the field -- more than the five
        # spaces a Playmaker's burst now runs. From the kickoff space
        # it is exactly four, so the bound would not have bitten
        # there even before the ability moved onto it.
        match.move_meeple(handler, *match.board.position_at_flat_index(0))
        match.set_ball_space(*match.board.meeple_position(handler))

        self.assertEqual(
            match.spaces_to_attacking_end(handler, match.ball.possession), 8,
        )
        self.assertEqual(
            cog.engine.dribble_burst_distances(match), [1, 2, 3, 4, 5],
        )

        # Two spaces from the end of the field, only those two are on
        # offer -- the run cannot leave the board, Playmaker or not.
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

        # Somebody who is not a Playmaker stops at four instead of
        # five.
        midfielder = fielded(match, PlayerRole.MIDFIELDER)
        match.active_player_id = midfielder
        match.move_meeple(midfielder, *match.board.position_at_flat_index(0))
        match.set_ball_space(*match.board.meeple_position(midfielder))
        self.assertEqual(
            cog.engine.dribble_burst_distances(match), [1, 2, 3, 4],
        )

    async def test_a_handler_on_the_last_space_is_asked_nothing(
        self,
    ) -> None:
        """
        The one position with no run in it. The ball still goes to 12
        and it costs nothing -- a burst that moved nowhere is free,
        Playmaker or not -- and with no distance to pick and no speed
        to pick, nothing is asked at all: the burst resolves straight
        through to the tail like a Deflect.
        """
        cog, game, match = self.build("dribble_burst", "clear")
        handler = match.active_player_id
        end_flat = match.board.layout.board_size - 1
        match.move_meeple(
            handler, *match.board.position_at_flat_index(end_flat),
        )
        cog.offer_speed_choice = mock.AsyncMock()
        cog.finish_maneuver_resolution = mock.AsyncMock()
        interaction = build_interaction()

        with suppressed_cog_saves():
            await resolve_dribble_burst(cog, interaction, game, match)

        interaction.followup.send.assert_not_awaited()
        self.assertEqual(self.flat_of(match, handler), end_flat)
        self.assertEqual(match.exhaustion.get(handler, 0), 0)
        self.assertEqual(match.ball.speed, 12)
        cog.offer_speed_choice.assert_not_awaited()
        cog.finish_maneuver_resolution.assert_awaited_once()

    async def test_a_playmaker_pays_the_plain_cost_for_the_extra_space(
        self,
    ) -> None:
        """
        Since 2026-09-26 the ability is an additional space, same as
        the Dribble's -- no longer a token off the cost (that
        reading held from 2026-08-19 to 2026-08-26). A Playmaker's run
        is charged the same token a space as anybody else's.
        """
        cog, game, match = self.build("dribble_burst", "clear")
        playmaker = fielded(match, PlayerRole.PLAYMAKER)
        match.active_player_id = playmaker
        match.move_meeple(playmaker, match.ball.zone, match.ball.space_index)
        offered = cog.engine.dribble_burst_distances(match)
        cog.offer_speed_choice = mock.AsyncMock()

        with suppressed_cog_saves():
            await apply_dribble_burst(cog,
                build_interaction(), game, match, 3,
            )

        self.assertIn(3, offered)
        self.assertEqual(match.exhaustion[playmaker], 3)

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
            await apply_dribble_burst(cog, 
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
        cog.finish_maneuver_resolution = mock.AsyncMock()
        interaction = build_interaction()

        with suppressed_cog_saves():
            await resolve_dribble_burst(cog, interaction, game, match)

        interaction.followup.send.assert_not_awaited()
        self.assertEqual(
            self.flat_of(match, handler),
            match.relative_flat_index(
                start, TeamSide.VISITING, offered[-1],
            ),
        )
        self.assertEqual(match.ball.speed, 12)

    async def test_clears_cost_is_two_exhaustion_on_the_defender(
        self,
    ) -> None:
        cog, game, match = self.build("dribble_burst", "clear")
        defender = match.challenger_id
        cog.offer_speed_choice = mock.AsyncMock()

        with suppressed_cog_saves():
            await apply_dribble_burst(cog, 
                build_interaction(), game, match, 1,
            )

        self.assertEqual(match.exhaustion[defender], 2)

    async def test_the_basic_dribble_also_charges_clears_cost(self) -> None:
        """
        A cost is the *loser's*, so it does not care which card beat
        it: Clear pays the same 2 whether it lost to Burst or
        to an ordinary Dribble.
        """
        cog, game, match = self.build("dribble_advance", "clear")
        defender = match.challenger_id
        cog.offer_speed_choice = mock.AsyncMock()

        with suppressed_cog_saves():
            await apply_dribble_advance(cog, 
                build_interaction(), game, match, 1,
            )

        self.assertEqual(match.exhaustion[defender], 2)


class ClearTests(GambitHarness, unittest.IsolatedAsyncioTestCase):
    async def test_it_drives_the_ball_back_three_and_drops_speed_by_three(
        self,
    ) -> None:
        # Against the *basic* High Pass, so nothing but Clear's own
        # benefit is in force -- Cross would add its cost on top.
        cog, game, match = self.build("high_pass", "clear", board_size=9)
        match.ball.speed = 8
        start = self.flat(match)
        cog.begin_loose_ball = mock.AsyncMock()

        with suppressed_cog_saves():
            await resolve_clear(cog, build_interaction(), game, match)

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
            await resolve_clear(cog, build_interaction(), game, match)

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
            await resolve_clear(cog, build_interaction(), game, match)

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
            await resolve_deflect(cog, 
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
            await resolve_intercept(cog, build_interaction(), game, match)

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
            await resolve_steal(cog, build_interaction(), game, match)

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
            await resolve_intercept(cog, build_interaction(), game, match)

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
            await apply_high_pass(cog, build_interaction(), game, match, 3)

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
            await apply_high_pass(cog, build_interaction(), game, match, 3)

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
        had no Cross at all.
        """
        cog, game, match = self.build("setup_pass", "steal", board_size=9)
        for player_id in list(match.home.field_players):
            if player_id != match.active_player_id:
                match.move_meeple(player_id, Zone.HOME_ZONE, 0)

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
                match.move_meeple(player_id, Zone.HOME_ZONE, 0)
        start = self.flat(match)
        cog.begin_loose_ball = mock.AsyncMock()

        with suppressed_cog_saves():
            await apply_setup_pass(cog, build_interaction(), game, match, 3)

        self.assertEqual(self.flat(match), start + 3)
        cog.begin_loose_ball.assert_awaited_once()
        self.assertFalse(
            cog.begin_loose_ball.await_args.kwargs.get("is_high_pass", False),
        )
        # The ball is thrown, so it is still the offense's until the
        # landing decides otherwise -- and the pass costs its own 2
        # minutes however far it travelled.
        self.assertEqual(match.ball.possession, TeamSide.HOME)
        self.assertEqual(
            loose_ball_distance(cog.begin_loose_ball.await_args), 2,
        )

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
                match.move_meeple(player_id, Zone.HOME_ZONE, 0)

        self.assertNotIn(0, cog.engine.setup_pass_distances(match))

        teammate = [
            player_id
            for player_id in match.home.field_players
            if player_id != match.active_player_id
        ][0]
        match.move_meeple(teammate, match.ball.zone, match.ball.space_index)

        self.assertIn(0, cog.engine.setup_pass_distances(match))

    async def test_the_pass_is_asked_straight_away(self) -> None:
        """
        The card sets no speed (Law 19.7.2, 2026-10-03): a won Cross
        asks where the pass lands, and nothing about the ball's speed,
        and nothing is recorded on the match for it.
        """
        cog, game, match = self.build("setup_pass", "steal", board_size=9)
        self.put_a_teammate_at(match, 3)
        speed = match.ball.speed

        result = flow_offer_setup_pass_distance(cog.engine, game, match)

        self.assertIs(result.next.kind, PromptKind.SETUP_PASS_CHOICE)
        self.assertIsNone(match.pending_effect_continuation)
        self.assertEqual(match.ball.speed, speed)
        self.assertIs(
            pending_prompt(cog.engine, game, match).kind,
            PromptKind.SETUP_PASS_CHOICE,
        )

    async def test_a_game_saved_after_the_old_speed_choice_asks_the_pass(
        self,
    ) -> None:
        """
        A game saved between the speed choice the card used to ask and
        the pass carries a `setup_pass_shot` continuation; it comes back
        to the same pass the card now asks first.
        """
        cog, game, match = self.build("setup_pass", "steal", board_size=9)
        self.put_a_teammate_at(match, 3)
        match.pending_effect_continuation = {"kind": "setup_pass_shot"}
        game.match_state = match.to_dict()
        cog.engine.load_match_state = mock.Mock(return_value=match)

        self.assertIsInstance(
            build_effect_choice_view(cog, game.game_id, match),
            SetupPassChoiceView,
        )

    async def test_the_pass_spends_the_continuation(self) -> None:
        cog, game, match = self.build("setup_pass", "steal", board_size=9)
        self.put_a_teammate_at(match, 3)
        match.pending_effect_continuation = {"kind": "setup_pass_shot"}
        cog.offer_scoring_attempt_choice = mock.AsyncMock()

        with suppressed_cog_saves():
            await apply_setup_pass(cog, build_interaction(), game, match, 3)

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
            await apply_setup_pass(cog, build_interaction(), game, match, 3)

        self.assertEqual(self.flat(match), start + 3)
        self.assertEqual(match.ball_carrier_id, receiver)
        cog.offer_scoring_attempt_choice.assert_awaited_once()

    async def test_it_cannot_overshoot_and_goes_out_instead(self) -> None:
        """
        The one position a Cross goes out from, since 2026-08-25:
        the passer on the very last space of the field -- where even 1
        runs off the end -- with no teammate beside them to take it at
        0. Then it runs out of play, the other team gains possession,
        and that is the existing out-of-bounds outcome and a fourth
        `new_play=True` call site.
        """
        cog, game, match = self.build("setup_pass", "steal")
        for player_id in list(match.home.field_players):
            if player_id != match.active_player_id:
                match.move_meeple(player_id, Zone.HOME_ZONE, 0)
        match.move_meeple(
            match.active_player_id, Zone.VISITORS_ZONE,
            match.board.layout.zone_spaces[Zone.VISITORS_ZONE] - 1,
        )
        match.set_ball_space(
            *match.board.meeple_position(match.active_player_id)
        )
        cog.begin_run_back = mock.AsyncMock()

        self.assertEqual(cog.engine.setup_pass_distances(match), [])

        with suppressed_cog_saves():
            await offer_setup_pass_distance(cog, 
                build_interaction(), game, match,
            )

        cog.begin_run_back.assert_awaited_once()
        self.assertTrue(
            cog.begin_run_back.await_args.kwargs["new_play"],
        )
        self.assertTrue(match.pending_ball_recovery)
        self.assertEqual(match.ball.possession, TeamSide.VISITING)

    async def test_a_failed_gambit_is_the_clear_itself(self) -> None:
        """
        Beaten by a Clear, the Cross is a Clear: 3 spaces back and 3 off
        the speed, landing as any Clear does (Law 19.7.7, the author,
        2026-10-03). What the failure changes is only the contest the
        landing may lead to -- `FailedCrossContestTests` in
        `tests/test_d12ball_deflection_flow.py`.
        """
        cog, game, match = self.build("setup_pass", "clear", board_size=9)
        cog.begin_loose_ball = mock.AsyncMock()
        before = self.flat(match)
        speed = match.ball.speed

        with suppressed_cog_saves():
            await resolve_clear(cog, build_interaction(), game, match)

        self.assertEqual(
            self.flat(match),
            match.relative_flat_index(before, match.ball.possession, -3),
        )
        self.assertEqual(match.ball.speed, max(1, speed - 3))
        cog.begin_loose_ball.assert_awaited_once()
        self.assertFalse(
            cog.begin_loose_ball.await_args.kwargs.get("is_high_pass", False),
        )


class DoubleTeamTests(GambitHarness, unittest.IsolatedAsyncioTestCase):
    def partner_of(self, cog, match) -> str:
        candidates = cog.engine.double_team_partner_candidates(match)
        self.assertEqual(len(candidates), 1)
        return candidates[0]

    async def test_it_pushes_the_handler_back_one_and_brings_a_partner(
        self,
    ) -> None:
        cog, game, match = self.build("dribble_advance", "double_team")
        handler = match.active_player_id
        challenger = match.challenger_id
        partner = self.partner_of(cog, match)
        start = self.flat_of(match, handler)
        cog.finish_maneuver_resolution = mock.AsyncMock()

        with suppressed_cog_saves():
            await resolve_double_team(cog, build_interaction(), game, match)

        end = self.flat_of(match, handler)
        self.assertEqual(
            end, match.relative_flat_index(start, match.ball.possession, -1),
        )
        self.assertEqual(self.flat(match), end)
        # Both defenders end on the handler's space, and neither pays a
        # token for it -- "no exhaustion cost" is the card's own words.
        self.assertEqual(self.flat_of(match, challenger), end)
        self.assertEqual(self.flat_of(match, partner), end)
        self.assertEqual(match.exhaustion.get(partner, 0), 0)
        # The partner, and only the partner, Merges next (Law 19.10.5).
        self.assertEqual(match.pending_double_team, [partner])

    async def test_the_merge_survives_a_save_and_reload(self) -> None:
        cog, game, match = self.build("dribble_advance", "double_team")
        cog.finish_maneuver_resolution = mock.AsyncMock()

        with suppressed_cog_saves():
            await resolve_double_team(cog, build_interaction(), game, match)

        restored = MatchState.from_dict(match.to_dict(), cog.basic_ruleset)
        self.assertTrue(restored.pending_double_team)
        self.assertEqual(
            restored.pending_double_team, match.pending_double_team,
        )

    def test_the_partner_is_on_the_ball_or_behind_it(self) -> None:
        """
        The nearest defender on the ball's space or behind it -- toward
        their own goal -- and never one ahead of it, however near (Law
        19.10.3).
        """
        cog, game, match = self.build("dribble_advance", "double_team")
        defense = match.defending_side()
        ball = self.flat(match)
        ahead = match.relative_flat_index(ball, defense, 1)
        behind = match.relative_flat_index(ball, defense, -2)
        near, far = [
            player_id for player_id in match.visiting.field_players
            if player_id != match.challenger_id
        ][:2]
        for player_id in match.visiting.field_players:
            if player_id != match.challenger_id:
                match.move_meeple(
                    player_id, *match.board.position_at_flat_index(
                        match.relative_flat_index(ball, defense, -3),
                    ),
                )
        match.move_meeple(near, *match.board.position_at_flat_index(ahead))
        match.move_meeple(far, *match.board.position_at_flat_index(behind))

        self.assertEqual(
            cog.engine.double_team_partner_candidates(match), [far],
        )

    def test_a_tie_is_the_defending_coachs_to_choose(self) -> None:
        cog, game, match = self.build("dribble_advance", "double_team")
        others = [
            player_id for player_id in match.visiting.field_players
            if player_id != match.challenger_id
        ][:2]
        for player_id in others:
            match.move_meeple(player_id, match.ball.zone, match.ball.space_index)
        self.assertGreater(
            len(cog.engine.double_team_partner_candidates(match)), 1,
        )

        self.assertIsNone(cog.engine.double_team_partner(match))
        self.assertTrue(
            cog.engine.double_team_partner_owed(match, "double_team"),
        )
        self.assertIs(
            pending_prompt(cog.engine, game, match).kind,
            PromptKind.DOUBLE_TEAM_PARTNER,
        )

        cog.engine.record_double_team_partner(match, others[1])
        self.assertEqual(cog.engine.double_team_partner(match), others[1])
        self.assertFalse(
            cog.engine.double_team_partner_owed(match, "double_team"),
        )

    def test_the_partner_merges_on_the_ball(self) -> None:
        """
        Merge as an Ooze has it (Law 20.5): on the ball's space and not
        rolling, the partner may pay 1 to add their defensive skill to
        the defense, and is offered it; off it, nothing.
        """
        cog, game, match = self.build("dribble_advance", "pressure")
        partner = next(
            player_id for player_id in match.visiting.field_players
            if player_id != match.challenger_id
        )
        match.pending_double_team = [partner]
        rolling = (match.active_player_id, match.challenger_id)
        defense = match.defending_side()
        skill = cog.engine.skills(game, partner).defense

        match.move_meeple(partner, match.ball.zone, match.ball.space_index)
        self.assertIn(
            partner,
            cog.engine.merge_candidates(
                game, match, defense, rolling, "defense",
            ),
        )
        match.declare_merge(partner)
        self.assertIn(
            (partner, skill),
            cog.engine.merge_contributions(
                game, match, defense, rolling, "defense",
            ),
        )
        match.move_player_relative(partner, defense, -1)
        self.assertNotIn(
            partner,
            [
                player_id for player_id, _ in cog.engine.merge_contributions(
                    game, match, defense, rolling, "defense",
                )
            ],
        )

    def test_the_merge_ends_with_the_next_maneuver(self) -> None:
        """Kept past the Double Team that granted it, and no further."""
        cog, game, match = self.build("dribble_advance", "double_team")
        partner = self.partner_of(cog, match)

        match.pending_double_team = [partner]
        cog.engine.record_double_team_partner(match, partner, merges=True)
        finish_maneuver_resolution(cog.engine, game, match)
        self.assertEqual(match.pending_double_team, [partner])

        finish_maneuver_resolution(cog.engine, game, match)
        self.assertEqual(match.pending_double_team, [])

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
            await resolve_double_team(cog, build_interaction(), game, match)

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
        The exception is Burst's cost and nothing else: a
        Defender's steal on a won Pressure still resets.
        """
        cog, game, match = self.build("dribble_advance", "pressure")
        defender = fielded(match, PlayerRole.DEFENDER, TeamSide.VISITING)
        match.challenger_id = defender
        match.move_meeple(defender, match.ball.zone, match.ball.space_index)
        match.ball.speed = 9
        cog.begin_run_back = mock.AsyncMock()

        with suppressed_cog_saves():
            await resolve_pressure(cog, build_interaction(), game, match)

        self.assertEqual(match.ball.possession, TeamSide.VISITING)
        self.assertEqual(match.ball.speed, 1)


if __name__ == "__main__":
    unittest.main()

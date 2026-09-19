"""
A ball nobody is holding, the pickup after one goes out, and the
contest that settles either -- which the long High Pass borrows. See
"Where the ball comes to rest" in docs/design/loose-balls.md.
"""

import discord
import random
from typing import Optional, TYPE_CHECKING

from d12ball import tutorial
from d12ball.components import (
    MatchState,
    PlayerDefinition,
)
from d12ball.engine import IgnitedRoll
from d12ball.game import (
    D12BallGame,
    Team,
)
from gamesaves.d12ball.storage import save_games
from cogs.d12ball_helpers import (
    contest_noun,
    format_player_with_team,
    format_team_side_label,
    player_with_role,
    space_label,
)

from cogs.d12ball_views.base import (
    SafeView,
    contestant_detail,
    render_contest_dice,
)

if TYPE_CHECKING:
    from cogs.d12ball import D12Ball


class LooseBallChoiceView(SafeView):
    """
    Who one side sends after a loose ball, plus the option of sending
    nobody. The candidates are the nearest player either side of the
    ball, from any zone (see "Sending a player" in
    docs/living-rules.md).

    One side at a time, the team that last had possession first: they
    are the ones losing the ball, and offering both at once let
    whoever clicked second answer the first's pick. Once this side
    settles, the cog rebuilds the prompt for the other.

    "Send nobody" is a real move, not a way out of the prompt -- with
    neither side contesting, the ball goes out of bounds and the side
    that last held it loses it (see resolve_loose_ball). It is
    offered even when there's only one candidate, which is why a lone
    candidate isn't auto-picked the way a forced run back is.

    **It is not offered to a side with somebody standing on the ball**
    (may_decline_loose_ball): they contest for nothing, so there is no
    walk-in for that coach to refuse to pay. Such a prompt is only ever
    a pick between two or more of them -- one is settled without asking.
    Built, not disabled: there is nothing a coach could do to enable it.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        side: str,
        candidates: list[str],
        match: MatchState,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.side = side

        ball_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )

        for player_id in candidates:
            player = cog.engine.get_player_definition(player_id)
            zone, space_index = match.board.meeple_position(player_id)
            distance = abs(
                match.board.flat_index(zone, space_index) - ball_flat
            )
            space_word = "space" if distance == 1 else "spaces"
            location_note = (
                f"({space_label(zone, space_index)}, {distance} "
                f"{space_word} from the ball)"
            )
            button = discord.ui.Button(
                label=f"{player_with_role(player)} {location_note}"[:80],
                style=(
                    discord.ButtonStyle.primary
                    if side == "offense"
                    else discord.ButtonStyle.danger
                ),
                custom_id=(
                    f"d12ball:loose_ball:{game_id}:{side}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_player_id: str = player_id,
            ) -> None:
                await self.choose(interaction, chosen_player_id)

            button.callback = callback
            self.add_item(button)

        if match.may_decline_loose_ball(
            match.ball.possession
            if side == "offense"
            else match.defending_side()
        ):
            decline = discord.ui.Button(
                label="Send nobody",
                style=discord.ButtonStyle.secondary,
                custom_id=f"d12ball:loose_ball_decline:{game_id}:{side}",
                row=4,
                # Railed during the tutorial. Waving the ball through
                # would not derail the story -- Dinky takes it either
                # way -- but the lesson beside this prompt is that both
                # sides send somebody, and a greyed button is the one
                # way to say so on the prompt itself.
                disabled=cog.tutorial_railed_option(
                    cog.games.get(game_id),
                    "loose_ball_decline",
                    ("never",),
                ) == "never",
            )
            decline.callback = self.decline
            self.add_item(decline)

    async def claim(
        self,
        interaction: discord.Interaction,
    ) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        """The game and match if this click may settle this side's
        pick, or (None, None) after replying with why it may not."""
        game, match = await self.require_match(interaction)
        if game is None:
            return None, None

        if self.cog.engine.loose_ball_side_on_the_clock(match) != self.side:
            await interaction.response.send_message(
                "That side has already answered.",
                ephemeral=True,
            )
            return None, None

        authorized = (
            self.may_act_for_possession(interaction, game, match)
            if self.side == "offense"
            else self.may_act_for_defense(interaction, game, match)
        )
        if not authorized:
            await interaction.response.send_message(
                "Only the player on that side can choose.",
                ephemeral=True,
            )
            return None, None
        return game, match

    async def choose(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        if self.side == "offense":
            match.choose_loose_ball_offense_player(player_id)
        else:
            match.choose_loose_ball_defense_player(player_id)

        player = self.cog.engine.get_player_definition(player_id)
        await self.settled(
            interaction,
            game,
            match,
            f"{self.cog.player_label(match, player)} "
            f"contests the {contest_noun(match)} ({self.side}).",
        )

    async def decline(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        side = (
            match.ball.possession
            if self.side == "offense"
            else match.defending_side()
        )
        # The button is not built for a side with somebody on the ball,
        # so this is a stale click -- a prompt a restart re-attached
        # from before the ball reached them. Same reason
        # ManeuverChallengeView.decline re-checks its own.
        if not match.may_decline_loose_ball(side):
            await interaction.response.send_message(
                "Somebody of theirs is standing on the ball -- they "
                "contest it, and cannot be held back.",
                ephemeral=True,
            )
            return

        if self.cog.tutorial_railed_option(
            game, "loose_ball_decline", ("never",),
        ) == "never":
            await interaction.response.send_message(
                "This step of the tutorial is about fighting for a "
                "loose ball -- send somebody after it.",
                ephemeral=True,
            )
            return

        match.decline_loose_ball(side)
        await self.settled(
            interaction,
            game,
            match,
            f"{format_team_side_label(match.setup_for_side(side))} send "
            f"nobody after the {contest_noun(match)}.",
        )

    async def settled(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        announcement: str,
    ) -> None:
        """Save this side's answer, then either put the prompt up for
        the other side or resolve."""
        self.cog.persist(game, match)

        await interaction.response.edit_message(
            content=announcement, view=None,
        )

        if self.cog.engine.loose_ball_side_on_the_clock(match) is None:
            await self.cog.resolve_loose_ball(interaction, game, match)
            return

        prompt_message = await interaction.followup.send(
            self.cog.engine.build_loose_ball_prompt(
                game, match, self.cog.team_emojis,
            ),
            view=self.cog.build_loose_ball_view(self.game_id, match),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.cog.games)


class BallRecoveryView(SafeView):
    """
    Which player goes and picks up an out-of-bounds ball or one a
    time out left behind,
    offered to the side that won it once everyone is back on their
    arrangement -- the nearest either side of it, from any zone, at one
    exhaustion token per space traveled (see "Sending a player" in
    docs/living-rules.md, and D12Ball.begin_ball_recovery).
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game, match = self.load_match()
        if game is None:
            return
        side = match.ball.possession

        for player_id in match.contest_candidates(side):
            player = cog.engine.get_player_definition(player_id)
            distance = match.distance_to_ball(player_id)
            space_word = "space" if distance == 1 else "spaces"
            button = discord.ui.Button(
                label=(
                    f"{player_with_role(player)} ({distance} {space_word} "
                    "away)"
                )[:80],
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:ball_recovery:{game_id}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_player_id: str = player_id,
            ) -> None:
                await self.choose(interaction, chosen_player_id)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not match.pending_ball_recovery:
            await interaction.response.send_message(
                "The ball has already been picked up.",
                ephemeral=True,
            )
            return
        if not self.may_act_for_possession(interaction, game, match):
            await interaction.response.send_message(
                "Only the side that won the ball can choose.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(view=None)
        await self.cog.apply_ball_recovery(
            interaction, game, match, player_id,
        )


class LooseBallSkillTestView(SafeView):
    """
    The roll that settles a loose ball -- or a High Pass, which runs
    the same contest for an entirely different reason (see
    contest_noun). The custom_id stays `loose_ball_test` either way,
    since it's what already-posted messages are keyed on.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game = cog.games.get(game_id)
        noun = "loose ball"
        if game is not None and game.match_state is not None:
            noun = contest_noun(cog.engine.load_match_state(game))

        button = discord.ui.Button(
            label=f"Roll for the {noun}",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:loose_ball_test:{game_id}",
        )
        button.callback = self.roll
        self.add_item(button)

        # Overdrive, for whichever contestant is a Cyborg.
        game, match = self.load_match()
        if game is not None and match is not None:
            self.add_overdrive_buttons(
                game,
                match,
                [
                    match.loose_ball_offense_player,
                    match.loose_ball_defense_player,
                ],
            )

    def score_loose_ball(
        self,
        game: D12BallGame,
        match: MatchState,
        offense_player: PlayerDefinition,
        defense_player: PlayerDefinition,
    ) -> tuple[
        list[tuple[int, Team, list[str], int, bool, list[tuple[str, int]]]],
        int,
        int,
        IgnitedRoll,
        IgnitedRoll,
    ]:
        """
        Roll the contest for the ball and add what counts towards it,
        as the two sides `render_contest_dice` draws plus the totals
        the winner is read off. Serves the loose ball and the long High
        Pass alike, which is the only contest injury and the ball speed
        modifier both bite in.

        No text breakdown goes alongside it: the dice image already
        names both players and shows every modifier that built the
        totals. **Both ignites come back with them**, because the
        second die each one rolled is posted on an image of its own --
        see `D12Ball.post_volatile_ignition`.
        """
        # An injured contestant adds no skill modifier -- their own
        # offensive or defensive skill stays off the roll, and that is
        # the whole of the disadvantage here (see "Injured players" in
        # docs/living-rules.md). It is only the skill: every other
        # modifier still applies, which is why the ball speed modifier
        # below is added without asking about injury.
        offense_injured = match.loose_ball_offense_player in match.injured
        defense_injured = match.loose_ball_defense_player in match.injured
        offense_skill = (
            0
            if offense_injured
            else self.cog.player_catalog.effective_profile(
                offense_player,
            ).offense
        )
        defense_skill = (
            0
            if defense_injured
            else self.cog.player_catalog.effective_profile(
                defense_player,
            ).defense
        )

        scripted = self.cog.tutorial_dice(game, "loose_ball", 2)
        offense_roll, defense_roll = (
            scripted if scripted else
            (random.randint(1, 12), random.randint(1, 12))
        )

        # Volatile, per side and on the natural face. **Injury does not
        # withhold it**: what an injured contestant loses here is their
        # own skill modifier and only that, and an ignite is the die
        # rather than a modifier the player brings -- the same reading
        # that leaves the ball speed modifier below alone.
        offense_ignite = self.cog.engine.ignite(
            game, offense_player.player_id, offense_roll,
        )
        defense_ignite = self.cog.engine.ignite(
            game, defense_player.player_id, defense_roll,
        )

        offense_overdrive = match.overdrive_modifier(
            offense_player.player_id,
        )
        defense_overdrive = match.overdrive_modifier(
            defense_player.player_id,
        )
        offense_total = (
            offense_roll + offense_skill + offense_ignite.modifier
            + offense_overdrive
        )
        defense_total = (
            defense_roll + defense_skill + defense_ignite.modifier
            + defense_overdrive
        )

        offense_detail = contestant_detail(
            offense_player, "Offensive", offense_skill,
            injured=offense_injured,
        )
        defense_detail = contestant_detail(
            defense_player, "Defensive", defense_skill,
            injured=defense_injured,
        )
        for detail, line in (
            (offense_detail, offense_ignite.detail),
            (offense_detail, self.cog.engine.overdrive_detail(
                match, offense_player.player_id,
            )),
            (defense_detail, defense_ignite.detail),
            (defense_detail, self.cog.engine.overdrive_detail(
                match, defense_player.player_id,
            )),
        ):
            if line:
                detail.append(line)

        # A High Pass's receiver adds the ball speed modifier to keep
        # what the pass delivered (2026-08-07). A genuine loose ball is
        # nobody's yet, so neither side gets it there.
        #
        # The modifier is signed: this contest is also where a declined
        # overshoot set-up lands, and an overshoot pays the modifier
        # against the receiver in the contest exactly as it would have
        # against the shot (2026-08-10). See ball_speed_modifier.
        if match.pending_loose_ball_is_high_pass:
            modifier = match.ball_speed_modifier()
            offense_total += modifier
            offense_detail.append(f"{modifier:+d} ball speed modifier")

        # **Merge**, for a contest fought on the ball's space -- which
        # this always is: both contestants have been walked onto it by
        # the time the roll happens. An Ooze of either side standing
        # there who is not one of the two rolling adds to their own.
        rolling = (
            match.loose_ball_offense_player,
            match.loose_ball_defense_player,
        )
        offense_merge, offense_lines, offense_contributors = (
            self.cog.engine.merge_bonus(
                game, match, match.ball.possession, rolling, "offense",
            )
        )
        defense_merge, defense_lines, defense_contributors = (
            self.cog.engine.merge_bonus(
                game, match, match.defending_side(), rolling, "defense",
            )
        )
        offense_total += offense_merge
        defense_total += defense_merge
        offense_detail.extend(offense_lines)
        defense_detail.extend(defense_lines)

        return (
            [
                (
                    offense_roll,
                    match.team_for_player(offense_player.player_id),
                    offense_detail,
                    offense_total,
                    bool(offense_overdrive),
                    offense_contributors,
                ),
                (
                    defense_roll,
                    match.team_for_player(defense_player.player_id),
                    defense_detail,
                    defense_total,
                    bool(defense_overdrive),
                    defense_contributors,
                ),
            ],
            offense_total,
            defense_total,
            offense_ignite,
            defense_ignite,
        )

    def settle_loose_ball_winner(
        self,
        game: D12BallGame,
        match: MatchState,
        offense_player: PlayerDefinition,
        defense_player: PlayerDefinition,
        offense_total: int,
        defense_total: int,
    ) -> tuple[str, list[PlayerDefinition], int, bool]:
        """
        Give the ball to whoever won the contest and word the result:
        the announcement, who owes an injury test, and the two things
        the run back behind it needs -- both read off the match before
        this clears them.
        """
        outcome = "offense" if offense_total > defense_total else "defense"
        winner_side = (
            match.ball.possession
            if outcome == "offense"
            else match.defending_side()
        )
        turnover_occurred = winner_side != match.ball.possession
        winner_number = (
            self.cog.engine.possession_player_number(game, match)
            if outcome == "offense"
            else self.cog.engine.defending_player_number(game, match)
        )
        winner_mention = format_player_with_team(
            game, winner_number, self.cog.team_emojis, mention=True,
        )
        winner_player = (
            offense_player if outcome == "offense" else defense_player
        )

        exhausted_participants = [
            player
            for player in (offense_player, defense_player)
            if player.player_id in match.exhausted
        ]
        distance_moved = match.pending_loose_ball_distance
        is_high_pass = match.pending_loose_ball_is_high_pass
        # Read with the rest of the position, before anything below
        # clears it: what the ball was is a fact about where it came
        # down, and only a space nobody was standing on makes it loose
        # (the author, 2026-08-26). Two players rolling for it is a
        # contest, and calling that a loose ball in the result told a
        # coach the opposite of what they had just watched.
        noun = contest_noun(match)

        match.ball.possession = winner_side
        if turnover_occurred:
            match.ball.speed = 1
        # Whoever won the contest is holding the ball, and takes the
        # next turn -- the receiver who kept a long High Pass, or
        # either side's contestant who won a loose ball. Confirmed by
        # the author 2026-08-09; see "Choosing the handler" in
        # docs/living-rules.md.
        match.set_ball_carrier(winner_player.player_id)
        match.pending_loose_ball = False
        match.loose_ball_offense_player = None
        match.loose_ball_defense_player = None
        self.cog.persist(game, match)

        turnover_line = "# Turnover!\n\n" if turnover_occurred else ""
        winner_bracket = self.cog.player_label(match, winner_player)
        if is_high_pass:
            outcome_line = (
                f"{winner_bracket} wins possession off the high pass! "
                f"{winner_mention} has possession."
                if turnover_occurred
                else f"{winner_bracket} keeps possession after the high "
                f"pass! {winner_mention} has possession."
            )
        else:
            outcome_line = (
                f"{winner_bracket} wins the {noun}! {winner_mention} "
                "has possession."
            )

        return (
            f"{turnover_line}{outcome_line}",
            exhausted_participants,
            distance_moved,
            turnover_occurred,
        )

    async def roll(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if (
            not match.pending_loose_ball
            or match.loose_ball_offense_player is None
            or match.loose_ball_defense_player is None
        ):
            await interaction.response.send_message(
                f"This {contest_noun(match)} is no longer active.",
                ephemeral=True,
            )
            return

        if not self.may_act_in_game(interaction, game):
            await interaction.response.send_message(
                "Only a player in this game can roll for the "
                f"{contest_noun(match)}.",
                ephemeral=True,
            )
            return

        offense_player = self.cog.engine.get_player_definition(
            match.loose_ball_offense_player,
        )
        defense_player = self.cog.engine.get_player_definition(
            match.loose_ball_defense_player,
        )

        (
            contestants,
            offense_total,
            defense_total,
            offense_ignite,
            defense_ignite,
        ) = self.score_loose_ball(
            game, match, offense_player, defense_player,
        )
        match.consume_overdrive()
        dice_file = await render_contest_dice(
            contestants, filename="loose_ball_dice.png",
        )

        if offense_total == defense_total:
            await interaction.response.edit_message(
                content=self.pay_skill_test_tie(
                    game,
                    match,
                    match.loose_ball_offense_player,
                    match.loose_ball_defense_player,
                    offense_total,
                    defense_total,
                ),
                attachments=[dice_file],
                view=LooseBallSkillTestView(self.cog, self.game_id),
            )
            # A tie is re-rolled, and the ignites that produced it are
            # still worth showing -- see SkillTestView.roll's own tie.
            await self.cog.post_volatile_ignition(
                interaction,
                match,
                (offense_player.player_id, offense_ignite),
                (defense_player.player_id, defense_ignite),
            )
            await self.cog.refresh_match_image(interaction, game)
            return

        (
            announcement,
            exhausted_participants,
            distance_moved,
            turnover_occurred,
        ) = self.settle_loose_ball_winner(
            game, match, offense_player, defense_player,
            offense_total, defense_total,
        )
        # The result follows the dice in its own message, the way every
        # other skill test announces itself -- a message's attachments
        # render below its content, so writing the outcome into this
        # one would put it above the roll that decided it. The tie
        # above is the exception, since that message carries the
        # roll-again button. See SkillTestView.roll.
        await interaction.response.edit_message(
            content=None,
            attachments=[dice_file],
            view=None,
        )
        # The ignition dice sit between the roll and the result, which
        # is where they belong: they are what settled it.
        await self.cog.post_volatile_ignition(
            interaction,
            match,
            (offense_player.player_id, offense_ignite),
            (defense_player.player_id, defense_ignite),
        )
        await interaction.followup.send(
            announcement,
            # The edit this replaced never pinged the winner, and the
            # prompt that follows does; one ping per turn is plenty.
            allowed_mentions=discord.AllowedMentions(
                users=False, roles=False, everyone=False,
            ),
        )
        await self.cog.refresh_match_image(interaction, game)

        # Winning a live ball off the other side -- a loose ball or a
        # long High Pass -- is a steal however it was contested, so no
        # substitution window either way. The run back waits behind
        # whatever injury tests this contest owes, and carries its two
        # arguments through the queue because nothing left in the match
        # still says what they were -- see begin_injury_tests.
        await self.cog.begin_injury_tests(
            interaction,
            game,
            match,
            exhausted_participants,
            {
                "kind": "run_back",
                "distance_moved": distance_moved,
                "turnover_occurred": turnover_occurred,
            },
        )

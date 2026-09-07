"""
The rolls a coach presses for: a maneuver's skill test, an injury
test, an own goal, and a score attempt. See "Every roll is a coach's"
in CLAUDE.md -- nothing in the game rolls on its own.
"""

import asyncio
import discord
import random
from typing import TYPE_CHECKING

from d12ball.components import (
    EVENT_SHOT,
    EVENT_SKILL_TEST,
    MatchState,
    PlayerDefinition,
    PlayerRole,
    TeamSetup,
)
from d12ball.engine import IgnitedRoll
from d12ball.game import (
    D12BallGame,
    Team,
    team_display_name,
)
from d12ball.render import render_player_portrait
from cogs.d12ball_helpers import (
    ROLE_INITIALS,
    format_goal_time,
    format_team_side_label,
)

from cogs.d12ball_views.base import (
    SafeView,
    contestant_detail,
    render_contest_dice,
)
from cogs.d12ball_views.effects import SetUpAttemptChoiceView
from cogs.d12ball_views.turn import PlayerActionView

if TYPE_CHECKING:
    from cogs.d12ball import D12Ball


class SkillTestView(SafeView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        button = discord.ui.Button(
            label="Roll the skill test",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:skill_test:{game_id}",
        )
        button.callback = self.roll
        self.add_item(button)

    def score_skill_test(
        self,
        game: D12BallGame,
        match: MatchState,
        offense_player: PlayerDefinition,
        defense_player: PlayerDefinition,
    ) -> tuple[
        list[tuple[int, Team, list[str], int]],
        int,
        int,
        IgnitedRoll,
        IgnitedRoll,
    ]:
        """
        Roll the maneuver skill test and add everything that counts
        towards it, as the two sides `render_contest_dice` draws plus
        the totals the outcome is read off.

        The dice image carries the whole arithmetic -- who rolled, what
        they rolled, every modifier and the total -- which is why no
        message that posts one repeats it in text.

        Nothing here is withheld for injury. What an injured player
        loses is their own offensive or defensive skill and only in a
        contest, which is the loose ball and the shootout; a maneuver's
        skill test pays every modifier to an injured player. See
        "Injured players" in docs/living-rules.md.

        **Both ignites come back with the totals**, because this is the
        one roll site where Volatile does something besides arithmetic:
        the caller needs to know which side surged or backfired to set
        the tier rider once it knows who won. See
        `RulesEngine.volatile_raises_tier`.
        """
        offense_skill = self.cog.player_catalog.effective_profile(
            offense_player,
        ).offense
        defense_skill = self.cog.player_catalog.effective_profile(
            defense_player,
        ).defense

        scripted = self.cog.tutorial_dice(game, "skill_test", 2)
        offense_roll, defense_roll = (
            scripted if scripted else
            (random.randint(1, 12), random.randint(1, 12))
        )

        # Volatile, on each side's own die and before any skill is
        # added -- the ignite reads the natural face. Both are asked
        # even in a basic game, where they come back as the face and
        # nothing else. "If both players rolling are Fire Demons, each
        # checks their own" falls out of asking per side.
        offense_ignite = self.cog.engine.ignite(
            game, offense_player.player_id, offense_roll,
        )
        defense_ignite = self.cog.engine.ignite(
            game, defense_player.player_id, defense_roll,
        )

        offense_total = offense_roll + offense_skill + offense_ignite.modifier
        defense_total = defense_roll + defense_skill + defense_ignite.modifier

        offense_detail = contestant_detail(
            offense_player, "Offensive", offense_skill,
        )
        defense_detail = contestant_detail(
            defense_player, "Defensive", defense_skill,
        )
        if offense_ignite.detail:
            offense_detail.append(offense_ignite.detail)
        if defense_ignite.detail:
            defense_detail.append(defense_ignite.detail)

        # Role ability -- Midfielder: +3 on a skill test when
        # attempting Low Pass (offense) or Pressure (defense).
        #
        # **Read by rank, so an advanced card inherits it.** The
        # Midfielder's +3 and the ball speed modifier below are listed
        # against both cards on their rank in the sheet's own
        # `Interactions` column, and neither contradicts what the
        # advanced card does. The three that *do* contradict -- the
        # Fullback on Clear, the Playmaker on Dribble Burst, the
        # Fullback's pass distance on Setup Pass -- are the author's to
        # settle and are deliberately not inherited anywhere; see
        # "Still open" in docs/advanced-maneuver-matrix.md.
        if (
            offense_player.role == PlayerRole.MIDFIELDER
            and match.offense_maneuver in ("low_pass", "skilled_pass")
        ):
            offense_total += 3
            offense_detail.append("+3 Midfielder ability")

        if (
            defense_player.role == PlayerRole.MIDFIELDER
            and match.defense_maneuver in ("pressure", "double_team")
        ):
            defense_total += 3
            defense_detail.append("+3 Midfielder ability")

        if match.defense_maneuver in ("steal", "intercept"):
            modifier = match.ball.speed // 2
            defense_total += modifier
            defense_detail.append(f"+{modifier} ball speed modifier")

        # **A won Double Team lands on the *next* maneuver**: both
        # defenders challenge the ball holder, and both add their
        # defensive skill. `double_team_defenders` is challenger-first
        # and holds the second only while `pending_double_team` is set,
        # which one card sets and a new play clears -- so this is a
        # no-op in every game that never played it.
        double_team_detail = ""
        partners = [
            player_id
            for player_id in self.cog.engine.double_team_defenders(match)
            if player_id != match.challenger_id
        ]
        for player_id in partners:
            partner = self.cog.engine.get_player_definition(player_id)
            partner_skill = self.cog.player_catalog.effective_profile(
                partner
            ).defense
            defense_total += partner_skill
            double_team_detail = (
                f"+{partner_skill} {partner.name} (Double Team)"
            )
        if double_team_detail:
            defense_detail.append(double_team_detail)

        return (
            [
                (
                    offense_roll,
                    match.team_for_player(offense_player.player_id),
                    offense_detail,
                    offense_total,
                ),
                (
                    defense_roll,
                    match.team_for_player(defense_player.player_id),
                    defense_detail,
                    defense_total,
                ),
            ],
            offense_total,
            defense_total,
            offense_ignite,
            defense_ignite,
        )

    async def roll(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if match.offense_maneuver is None or match.defense_maneuver is None:
            await interaction.response.send_message(
                "This skill test is no longer active.",
                ephemeral=True,
            )
            return

        if not self.is_game_participant(game, interaction.user.id):
            await interaction.response.send_message(
                "Only a player in this game can roll the skill test.",
                ephemeral=True,
            )
            return

        # Acknowledge immediately, before the dice image is rendered.
        # Discord invalidates the interaction token if the first
        # response doesn't arrive within 3 seconds, which turns into a
        # NotFound("Unknown interaction") on edit_message farther down
        # if rendering (or anything else on the way there) is slow --
        # deferring buys the rest of this method the usual 15 minutes.
        await interaction.response.defer()

        offense_player = self.cog.engine.get_player_definition(
            match.active_player_id,
        )
        defense_player = self.cog.engine.get_player_definition(
            match.challenger_id,
        )

        (
            contestants,
            offense_total,
            defense_total,
            offense_ignite,
            defense_ignite,
        ) = self.score_skill_test(
            game, match, offense_player, defense_player,
        )
        # Logged before either branch, so a tie that re-rolls is in the
        # record as well as the roll that settles it -- a maneuver
        # decided on the third attempt cost three rolls and six
        # exhaustion tokens, and only the log says so. It is also what
        # `record_maneuver` reads to tell a win on the dice from a win
        # on the cards, so it has to be written before the effect is
        # dispatched.
        match.record_event(
            EVENT_SKILL_TEST,
            side=match.ball.possession,
            player_id=match.active_player_id,
            offense_total=offense_total,
            defense_total=defense_total,
            tied=offense_total == defense_total,
            offense_key=match.offense_maneuver,
            defense_key=match.defense_maneuver,
        )
        dice_file = await render_contest_dice(
            contestants, filename="skill_test_dice.png",
        )

        if offense_total == defense_total:
            await interaction.edit_original_response(
                content=self.pay_skill_test_tie(
                    game,
                    match,
                    match.active_player_id,
                    match.challenger_id,
                    offense_total,
                    defense_total,
                ),
                attachments=[dice_file],
                view=SkillTestView(self.cog, self.game_id),
            )
            await self.cog.refresh_match_image(interaction, game)
            return

        outcome = "offense" if offense_total > defense_total else "defense"
        winner_key = (
            match.offense_maneuver
            if outcome == "offense"
            else match.defense_maneuver
        )
        winner_name = self.cog.engine.maneuver_name(winner_key)

        # **Volatile's tier rider**, settled here because this is the
        # first point that knows who won. Both of the rules' two cases
        # raise the winner's card, so this is one flag -- see
        # `RulesEngine.volatile_raises_tier`. It is written onto the
        # match rather than passed down to the effect because the
        # injury tests run in between: `resolving_maneuver` is asked on
        # the far side of them, possibly after a restart.
        winner_ignite, loser_ignite = (
            (offense_ignite, defense_ignite)
            if outcome == "offense"
            else (defense_ignite, offense_ignite)
        )
        match.volatile_tier_upgrade = self.cog.engine.volatile_raises_tier(
            game, winner_ignite, loser_ignite,
        )
        if match.volatile_tier_upgrade:
            raised = self.cog.engine.maneuver_name(
                self.cog.engine.resolving_maneuver(match, winner_key),
            )
            volatile_note = (
                f"\n🔥 **Volatile** — "
                + (
                    "the surge"
                    if winner_ignite.surge
                    else "the backfire"
                )
                + f" raises it to **{raised}**."
            )
        else:
            volatile_note = ""

        exhausted_participants = [
            player
            for player in (offense_player, defense_player)
            if player.player_id in match.exhausted
        ]

        # Result after the dice, not above them: a message's
        # attachments render below its content, so the winner announced
        # in this message would be read before the roll that decided
        # it. The tie above keeps its text here instead, because that
        # message also carries the roll-again button.
        await interaction.edit_original_response(
            content=None,
            attachments=[dice_file],
            view=None,
        )
        await interaction.followup.send(
            f"## **{winner_name}** wins the skill test!{volatile_note}"
        )
        await self.cog.refresh_match_image(interaction, game)

        # The effect is on the far side of the injury tests now that
        # each of those is a click of its own, so it is handed over as
        # the queue's continuation rather than awaited here -- see
        # begin_injury_tests. With nobody exhausted this still resolves
        # in the same breath as the roll.
        await self.cog.begin_injury_tests(
            interaction,
            game,
            match,
            exhausted_participants,
            {"kind": "maneuver_effect", "winner_key": winner_key},
        )


class InjuryTestView(SafeView):
    """
    The injury test one exhausted participant owes after a contest.
    Posted one at a time by `continue_injury_tests`, which is also what
    the click hands the turn back to.

    The player is in the custom_id as well as the queue, so a coach who
    scrolls back to the first of two prompts and clicks it again cannot
    roll the second player's test with it.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        player_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id
        self.player_id = player_id

        button = discord.ui.Button(
            label="Roll the injury test",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:injury_test:{game_id}:{player_id}",
        )
        button.callback = self.roll
        self.add_item(button)

    async def roll(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if self.player_id not in match.pending_injury_tests:
            await interaction.response.send_message(
                "This injury test is no longer active.",
                ephemeral=True,
            )
            return

        if not self.is_game_participant(game, interaction.user.id):
            await interaction.response.send_message(
                "Only a player in this game can roll the injury test.",
                ephemeral=True,
            )
            return

        # Deferred before the die is rendered, for the reason spelled
        # out in SkillTestView.roll.
        await interaction.response.defer()

        await self.cog.run_injury_test(
            interaction,
            game,
            match,
            self.cog.engine.get_player_definition(self.player_id),
        )


class OwnGoalRollView(SafeView):
    """
    The roll that decides an own goal Pressure has pushed a side into.
    One roll, by one player, but any coach in the game may press it --
    the same as the skill test and the score attempt, and what keeps a
    solo game moving when the risk is the AI's.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        button = discord.ui.Button(
            label="Roll for the own goal",
            style=discord.ButtonStyle.danger,
            custom_id=f"d12ball:own_goal:{game_id}",
        )
        button.callback = self.roll
        self.add_item(button)

    async def roll(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not match.pending_own_goal or match.active_player_id is None:
            await interaction.response.send_message(
                "This own goal roll is no longer active.",
                ephemeral=True,
            )
            return

        if not self.is_game_participant(game, interaction.user.id):
            await interaction.response.send_message(
                "Only a player in this game can roll for the own goal.",
                ephemeral=True,
            )
            return

        # Deferred before the dice are rendered, for the reason spelled
        # out in SkillTestView.roll.
        await interaction.response.defer()

        await self.cog.run_own_goal_roll(interaction, game, match)


class ScoreAttemptView(SafeView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        button = discord.ui.Button(
            label="Roll the score attempt",
            style=discord.ButtonStyle.danger,
            custom_id=f"d12ball:score_attempt:{game_id}",
        )
        button.callback = self.roll
        self.add_item(button)

        # A shot not yet rolled always has somewhere to walk back to --
        # see `MatchState.may_cancel_pending_shot` -- and only the side
        # that chose it may reconsider. No `possession_user_id` means
        # Dinky is the one shooting, which is not a choice a human
        # standing in for its rolls gets to undo either (see "Every
        # roll is a coach's" in CLAUDE.md).
        game, match = self.load_match()
        if (
            game is not None
            and match is not None
            and match.may_cancel_pending_shot()
            and cog.engine.possession_user_id(game, match) is not None
        ):
            back = discord.ui.Button(
                label="Back",
                style=discord.ButtonStyle.secondary,
                custom_id=f"d12ball:score_attempt_back:{game_id}",
                # Built disabled, never absent, exactly like
                # SetUpAttemptChoiceView's own decline button -- a
                # tutorial beat that rails a set-up shot to "attempt"
                # is railing this same choice (Back leads straight back
                # to that view's decline), and the scripted goal at the
                # end of beat 5 depends on nobody reaching it.
                disabled=(
                    match.pending_shot_is_set_up
                    and cog.tutorial_railed_option(
                        game, "setup_attempt", ("attempt", "decline"),
                    ) == "attempt"
                ),
            )
            back.callback = self.back
            self.add_item(back)

    def score_score_attempt(
        self,
        game: D12BallGame,
        match: MatchState,
        shooter: PlayerDefinition,
        attacking_setup: TeamSetup,
        defending_setup: TeamSetup,
    ) -> tuple[list[tuple[int, Team, list[str], int]], int, int]:
        """
        Roll the shot and price the wall in front of it, as the two
        sides `render_contest_dice` draws plus the totals the verdict
        is read off.

        Everything that built the two totals is drawn on the dice
        image, which is why no message that posts one repeats it in
        text.

        **Only the shooter's die can ignite.** A score attempt's second
        die is the defence's, and the defence here is a wall of
        meeples rather than a player rolling -- it belongs to no card,
        so there is no species behind it. See "Volatile" in
        docs/living-rules.md, which names "the shooter's die" and no
        other.
        """
        offense_skill = self.cog.player_catalog.effective_profile(
            shooter,
        ).offense
        speed_modifier = match.ball_speed_modifier()
        defenders = self.cog.engine.intervening_defenders(match)
        # What each defender is worth here, not what they are worth --
        # a defender off the ball adds half their skill, rounded up.
        # See ShotDefender.
        defense_skill_total = sum(defender.value for defender in defenders)

        # Two dice, one per human: the attacker adds the shooting
        # player's offensive skill and the ball-speed modifier, the
        # defence adds the defensive skill of every meeple in the way.
        # The speed modifier is signed -- an overshot High Pass pays it
        # against the shot -- so it is added, never abs()'d.
        attack_roll = random.randint(1, 12)
        defense_roll = random.randint(1, 12)
        attack_ignite = self.cog.engine.ignite(
            game, shooter.player_id, attack_roll,
        )
        attack_total = (
            attack_roll + offense_skill + speed_modifier + attack_ignite.modifier
        )
        defense_total = defense_roll + defense_skill_total

        attack_detail = contestant_detail(shooter, "Offensive", offense_skill)
        if speed_modifier:
            attack_detail.append(f"{speed_modifier:+d} ball speed modifier")
        if attack_ignite.detail:
            attack_detail.append(attack_ignite.detail)

        # Role ability -- Striker: +3 on any scoring attempt off a
        # set-up. Injury does not withhold this one, deliberately: an
        # injured player loses their ability modifier on a roll someone
        # is contesting, and nobody contests a shot (see "Injured
        # players" in docs/living-rules.md). Don't add match.injured
        # here to match the skill test.
        if match.pending_shot_is_set_up and shooter.role == PlayerRole.STRIKER:
            attack_total += 3
            attack_detail.append("+3 Striker ability")

        if defenders:
            defense_detail = [
                f"{defender.player.name} "
                f"[{ROLE_INITIALS[defender.player.role.value]}] "
                f"+{defender.value}"
                + ("" if defender.on_ball else f" (half of {defender.defense})")
                for defender in defenders
            ]
            if len(defenders) > 1:
                defense_detail.append(
                    f"Total defensive skill +{defense_skill_total}"
                )
        else:
            defense_detail = ["No one in the way"]

        return (
            [
                (
                    attack_roll,
                    attacking_setup.team,
                    attack_detail,
                    attack_total,
                ),
                (
                    defense_roll,
                    defending_setup.team,
                    defense_detail,
                    defense_total,
                ),
            ],
            attack_total,
            defense_total,
        )

    def settle_score_attempt(
        self,
        game: D12BallGame,
        match: MatchState,
        shooter: PlayerDefinition,
        attacking_setup: TeamSetup,
        defending_setup: TeamSetup,
        scored: bool,
    ) -> tuple[str, int]:
        """
        Credit the goal or the miss, restart play from it, and word the
        verdict -- with the clock cost the run back behind it is owed.
        """
        if scored:
            # Logged as it is credited, and stamped with the clock as
            # it stands: the shot's own cost is charged afterwards, so
            # this is the minute the ball crossed the line rather than
            # the minute play restarted.
            match.award_goal(shooter.player_id)
            verdict = (
                "# GOAL!\n"
                f"{self.cog.player_label(match, shooter)} scores "
                f"for {format_team_side_label(attacking_setup)} on "
                f"**{format_goal_time(match.goals[-1])}**!\n"
                f"{team_display_name(match.home.team)} "
                f"{match.scoreboard.home_score}:"
                f"{match.scoreboard.visiting_score} "
                f"{team_display_name(match.visiting.team)}"
            )
        else:
            verdict = (
                "# Missed attempt!\n"
                f"{format_team_side_label(defending_setup)} manages to avoid a goal! (phew)"
            )

        # A plain score attempt costs no exhaustion and owes no injury
        # check -- only a shot taken off a set-up gains a token, taken
        # after the roll regardless of outcome, and injury checks stay
        # exclusive to skill tests either way.
        if match.pending_shot_is_set_up:
            verdict += "\n\n" + self.cog.apply_exhaustion(
                match, shooter.player_id, 1,
            )

        # Every score attempt is a turnover, win or miss: the clock
        # cost is a flat space minute (2026-08-16), plus the cost of
        # whatever maneuver set it up if this was a set-up shot rather
        # than an ordinary one -- pending_shot_setup_cost is 0 for an
        # ordinary shot, so this is 1 there and maneuver-cost-plus-1
        # for a set-up. The team that just defended restarts play --
        # in the middle of the midfield on a goal (the same kickoff
        # rule as the start of a half), or at the space closest to
        # their own goal on a miss.
        #
        # The shooter stops being the active player right here: unlike
        # a maneuver's turnover (exempted from validate()'s
        # active-player check for as long as challenger_id/offense_
        # maneuver/defense_maneuver stay set), a score attempt has none
        # of those, so a stale active_player_id would trip that check
        # the moment pending_run_back next goes false -- which can
        # happen before reset_maneuver() finally clears it, e.g. inside
        # a deferred loose-ball contest for an empty kickoff space.
        match.active_player_id = None
        space_minutes = 1 + match.pending_shot_setup_cost
        new_possession_side = defending_setup.side
        if scored:
            match.restart_after_goal(new_possession_side)
        else:
            # Unlike a goal's kickoff space, nothing guarantees an
            # arrangement covers the space closest to the defending
            # side's own goal -- so, since 2026-08-24, this restart
            # owes the same pickup an out-of-bounds ball does rather
            # than falling through to a two-sided loose ball. Set
            # before the reset (in roll, via begin_run_back's
            # new_play): begin_ball_recovery checks
            # eligible_ball_handlers() first and asks nobody when the
            # arrangement already covers it.
            match.restart_after_missed_score(new_possession_side)
            match.pending_ball_recovery = True

        # Save a reconstructible run-back state before refreshing the
        # persistent board. begin_run_back repeats this assignment
        # idempotently when it posts the run-back announcement.
        match.pending_run_back = True
        match.pending_run_back_distance = space_minutes
        match.pending_run_back_turnover = True
        self.cog.persist(game, match)

        return verdict, space_minutes

    async def roll(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if match.pending_action != "shoot" or match.active_player_id is None:
            await interaction.response.send_message(
                "This score attempt is no longer active.",
                ephemeral=True,
            )
            return

        if not self.is_game_participant(game, interaction.user.id):
            await interaction.response.send_message(
                "Only a player in this game can roll the score attempt.",
                ephemeral=True,
            )
            return

        shooter = self.cog.engine.get_player_definition(match.active_player_id)
        attacking_setup = match.setup_for_side(match.ball.possession)
        defending_setup = match.setup_for_side(match.defending_side())

        contestants, attack_total, defense_total = self.score_score_attempt(
            game, match, shooter, attacking_setup, defending_setup,
        )
        dice_file = await render_contest_dice(
            contestants, filename="score_attempt_dice.png",
        )

        scored = attack_total >= defense_total
        # Ahead of `settle_score_attempt`, which is what awards the
        # goal: the shot goes into the log before the goal it produced,
        # so a fold reading the two in order sees cause and then
        # effect. Everything that priced the shot rides on it, because
        # a bare conversion rate says nothing about why -- these four
        # are what a coach can actually change: who takes it, whether
        # it came off a set-up, at what ball speed, and through how
        # many defenders. The two are recomputed rather than threaded
        # out of `score_score_attempt`, which owns them and mutates
        # nothing.
        match.record_event(
            EVENT_SHOT,
            side=match.ball.possession,
            player_id=shooter.player_id,
            scored=scored,
            set_up=bool(match.pending_shot_is_set_up),
            speed_modifier=match.ball_speed_modifier(),
            defender_count=len(
                self.cog.engine.intervening_defenders(match)
            ),
            attack_total=attack_total,
            defense_total=defense_total,
        )
        verdict, space_minutes = self.settle_score_attempt(
            game, match, shooter, attacking_setup, defending_setup, scored,
        )

        # The dice image carries the maths that produced it, and the
        # verdict follows in its own message. A message's attachments
        # always render *below* its content, so a verdict written into
        # this one would be read before the roll it is announcing.
        await interaction.response.edit_message(
            content=None,
            attachments=[dice_file],
            view=None,
        )
        await interaction.followup.send(verdict)
        if scored:
            # The scorer, posted under the announcement -- its own
            # message rather than an attachment on it, which would put
            # the portrait above the "GOAL!" it belongs to.
            portrait = await asyncio.to_thread(
                render_player_portrait, shooter.name,
            )
            if portrait is not None:
                await interaction.followup.send(
                    file=discord.File(
                        portrait,
                        filename=f"{shooter.player_id}_goal.png",
                    ),
                )
        # No board refresh here: every path out of begin_run_back
        # below puts one up within the same click, over a position
        # this one would draw a moment before. A new play goes to
        # announce_new_play_reset, which restores both arrangements
        # and posts the settled board through post_new_play_board;
        # last possession goes to end_period, which refreshes in both
        # of its own branches. So this drew a board nobody reads --
        # the restarted ball without the reset behind it -- and, worse,
        # it took the game's write window, pushing the board that *is*
        # worth reading out of the render post_new_play_board already
        # has in hand and into a trailing pass. See "Discord's rate
        # limits" in CLAUDE.md.
        #
        # Goal or miss, the ball is dead and being restarted, so this
        # is a new play and both restarts open a substitution window.
        await self.cog.begin_run_back(
            interaction,
            game,
            match,
            distance_moved=space_minutes,
            turnover_occurred=True,
            new_play=True,
        )

    async def back(self, interaction: discord.Interaction) -> None:
        """
        Walk an unrolled "shoot" choice back to wherever it was chosen.
        The composition image already posted stays in the channel as a
        harmless remnant -- the same tradeoff a picked maneuver's hand
        image makes.

        An ordinary turn's shot and a set-up's are two different
        choices with two different ways back, so they split here:
        `retract_pending_shot` undoes the former (the turn prompt's own
        "Shoot to score" button) and `back_from_set_up_shot` the latter
        (`SetUpAttemptChoiceView`'s "attempt" button). Both are real
        choices a coach made a moment ago and neither has happened to
        anything else in between, which is what makes either safe to
        undo -- see `MatchState.may_cancel_pending_shot`.
        """
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not match.may_cancel_pending_shot():
            await interaction.response.send_message(
                "This score attempt is no longer active.",
                ephemeral=True,
            )
            return

        if not self.cog.engine.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player who chose to shoot can change their "
                "mind.",
                ephemeral=True,
            )
            return

        if match.pending_shot_is_set_up:
            await self.back_from_set_up_shot(interaction, game, match)
            return

        match.retract_pending_shot()
        self.cog.persist(game, match)

        await interaction.response.edit_message(
            content=self.cog.engine.build_turn_prompt(game, match),
            view=PlayerActionView(self.cog, self.game_id),
        )

    async def back_from_set_up_shot(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Undo `start_set_up_shot` and put its own "attempt or decline"
        choice back up -- the real reconsideration point for a scoring
        opportunity, since the maneuver that earned it (a Low Pass, a
        Deflect overshoot, a High Pass) had already resolved before the
        shot was ever offered.

        Every argument `SetUpAttemptChoiceView` needs is still sitting
        on the match, because nothing has touched it since
        `start_set_up_shot` wrote it a moment ago: the shooter is
        `active_player_id` (that call is what pointed it at them),
        the distance is `pending_shot_setup_cost` (read before it is
        zeroed back out), and whether declining lands in a contest
        rather than a settled pass is `pending_high_pass_overshoot` --
        the same flag `resolve_high_pass_overshoot` set before ever
        offering this choice the first time, and which nothing before
        `reset_maneuver` clears.
        """
        shooter_id = match.active_player_id
        distance_moved = match.pending_shot_setup_cost
        contest_on_decline = match.pending_high_pass_overshoot

        match.pending_action = None
        match.pending_shot_is_set_up = False
        match.pending_shot_setup_cost = 0
        self.cog.persist(game, match)

        shooter = self.cog.engine.get_player_definition(shooter_id)
        await interaction.response.edit_message(
            content=(
                f"{self.cog.player_label(match, shooter)} can attempt "
                "the scoring opportunity, or let it go:"
            ),
            view=SetUpAttemptChoiceView(
                self.cog,
                self.game_id,
                shooter_id,
                distance_moved,
                contest_on_decline=contest_on_decline,
            ),
        )

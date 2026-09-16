"""
The clock and everything hanging off the end of it: the tail of a
maneuver, the period whistle, halftime, the window before the
shootout, and the shootout itself.
"""

import discord
import time
from typing import Optional

from d12ball.engine import (
    FULL_TIME_STAGES,
    HALFTIME_STAGES,
    SETUP_STAGES,
)
from d12ball.components import (
    CoachingOccasion,
    MatchPeriod,
    MatchState,
    SECOND_HALF_START_MINUTE,
    TeamSide,
    Zone,
    kickoff_space_index,
)
from d12ball.game import D12BallGame
from d12ball import tutorial
from gamesaves.d12ball.storage import save_games
from cogs.d12ball_helpers import (
    add_full_image_button,
    build_full_time_summary,
    build_goal_log,
    format_team_side_label,
    space_label,
)
from cogs.d12ball_views import (
    HalftimeExtraTokenView,
    RematchView,
    ShootoutOrderPromptView,
    ShootoutPickPromptView,
    ShootoutTestView,
)


class PeriodMixin:
    """
    The clock and everything hanging off the end of it: the tail of a
    """

    # -- Clock, period transitions, and the turn loop -----------------

    async def finish_maneuver_resolution(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int = 1,
        turnover_occurred: bool = False,
        lead_in: str = "",
    ) -> None:
        """
        The tail of every maneuver-effect path once movement, speed,
        any turnover, and run-back are all settled: advance the clock,
        end the period if this turnover closes out last possession,
        clear the maneuver state, and hand the offensive choice back to
        whoever now has the ball.

        The maneuver that reaches the period's last minute never ends it,
        even when it is itself a turnover: last possession is the
        possession that starts there, so whoever comes out of that
        maneuver with the ball gets to play it out and only loses the
        period when *they* lose the ball. Only a turnover under a last
        possession that was already in force ends it -- which is the
        case begin_run_back catches earlier, before any run back.

        `lead_in`, if given, is narration from earlier in the same
        effect that hasn't been posted yet -- it rides along on this
        function's own first message instead of being sent separately,
        so a deterministic effect (no further human choice in between)
        reads as one message rather than a chain of them.

        Checked first, before the clock moves: does the possessing team
        actually have a player on the ball's space? If the maneuver left
        it somewhere they don't -- an empty space, or one only the other
        team occupies -- this detours into the loose-ball flow instead,
        which re-enters this function itself once it's settled.
        """
        # **Mind Pull first**, because it pre-empts the arrival rather
        # than reacting to it: a pull that lands stops the ball on the
        # Telekinetic's space, so whether the possessing side has
        # anybody where the maneuver *would* have left it is a
        # question that must not be asked yet.
        if await self.check_for_mind_pull(
            interaction,
            game,
            match,
            {
                "kind": "finish_maneuver",
                "distance_moved": distance_moved,
                "turnover_occurred": turnover_occurred,
                "lead_in": lead_in,
            },
        ):
            return

        if await self.check_for_loose_ball(
            interaction, game, match, distance_moved, lead_in=lead_in,
        ):
            return

        entered_last_possession = match.advance_time(distance_moved)
        if entered_last_possession:
            prefix = f"{lead_in}\n\n" if lead_in else ""
            possessing_side = format_team_side_label(
                match.setup_for_side(match.ball.possession)
            )
            body = (
                "The turnover that got here doesn't end it -- "
                f"{possessing_side} came out of that maneuver with the "
                "ball, so they play last possession out."
                if turnover_occurred
                else "Play continues until the ball turns over, which "
                "ends the period."
            )
            # The minute is the period's own, and the clock does not
            # stop on it: from here every turn is charged as usual and
            # only the turnover ends the period.
            await interaction.followup.send(
                f"{prefix}The clock reaches "
                f"{match.scoreboard.last_minute:02d} -- this is now "
                f"**last possession**. {body} The clock keeps running."
            )
            lead_in = ""

        if (
            turnover_occurred
            and match.scoreboard.last_possession
            and not entered_last_possession
        ):
            await self.end_period(interaction, game, match, lead_in=lead_in)
            return

        match.reset_maneuver()
        self.persist(game, match)

        # One last board refresh with everything settled (run-back,
        # speed choice, own-goal, etc. may have landed after the last
        # refresh inside the effect itself), right before the
        # offensive choice comes back up. The snapshot below is that
        # same board, so it is drawn once and uploaded twice.
        png = await self.render_match_png(game)
        await self.refresh_match_image(interaction, game, png=png)

        prefix = f"{lead_in}\n\n" if lead_in else ""
        # Every maneuver costs at least its flat space minute
        # (2026-08-16), ceding included, so there is no longer a
        # zero-cost turn to word specially here.
        clock = (
            f"Time has advanced {distance_moved}, now "
            f"at {match.scoreboard.time:02d}."
        )
        snapshot = await interaction.followup.send(
            content=(
                f"{prefix}Ball is now "
                f"{space_label(match.ball.zone, match.ball.space_index)}, "
                f"{format_team_side_label(match.setup_for_side(match.ball.possession))} "
                f"has possession. {clock}"
            ),
            file=self.match_file_from_png(game, png),
            wait=True,
        )
        await add_full_image_button(snapshot)

        try:
            await self.send_turn_prompt(interaction, game)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)

    async def end_period(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        The turnover that closes out last possession: transition to the
        second half, or end the game at full time -- which, on a level
        score, means opening the [extreme shootout](begin_shootout)
        rather than finishing anything.
        """
        prefix = f"{lead_in}\n\n" if lead_in else ""

        # The turnover that ends a period is the one carry that must
        # not survive it: a Steal under last possession names
        # a carrier, and the second half kicks off from the coaches'
        # arrangement with nobody holding anything.
        match.clear_ball_carrier()

        if match.scoreboard.period == MatchPeriod.FIRST_HALF:
            first_half_ended_at = match.scoreboard.time
            match.scoreboard.period = MatchPeriod.SECOND_HALF
            # The second half starts at 16 however far past 15 the
            # first half ran, so the number on the clock means the same
            # thing in every game. It is set here rather than at the
            # kickoff for the reason everything else in this branch is:
            # halftime is played with the second half's board already
            # on the scoreboard.
            match.scoreboard.time = SECOND_HALF_START_MINUTE
            match.scoreboard.last_possession = False
            # A time out is once every half, so both sides get theirs
            # back. Their two substitutions for the half come back with
            # it; halftime's own two are counted separately and are not
            # touched here.
            match.time_outs_used.clear()
            match.half_substitutions_used.clear()
            match.close_coaching_window()
            kickoff_index = kickoff_space_index(
                len(match.board.spaces[Zone.MIDFIELD]),
                TeamSide.VISITING,
            )
            match.restart_ball_at(Zone.MIDFIELD, kickoff_index)
            match.ball.possession = TeamSide.VISITING
            match.ball.speed = 1
            match.reset_maneuver()
            self.persist(game, match)

            await interaction.followup.send(
                f"{prefix}**End of the first half!** The ball turns over "
                f"at {first_half_ended_at:02d} under last possession -- "
                "the period ends. The second half starts at "
                f"{SECOND_HALF_START_MINUTE:02d}."
            )
            await self.refresh_match_image(interaction, game)
            await self.begin_halftime(interaction, game, match)
            return

        match.reset_maneuver()
        self.persist(game, match)

        whistle = (
            f"{prefix}**Full time!** The ball turns over at "
            f"{match.scoreboard.time:02d} under last possession -- the "
            "game ends.\n\n"
            f"{build_full_time_summary(game, match)}"
        )

        if match.scoreboard.home_score == match.scoreboard.visiting_score:
            # Level, so nothing is finished: the summary above says the
            # game goes to the shootout, and the shootout is what ends
            # it -- the game record stays in progress until then, so a
            # restart mid-shootout comes back to a live game. One
            # substitution a side comes first.
            await interaction.followup.send(whistle)
            await self.refresh_match_image(interaction, game)
            await self.begin_full_time_coaching(interaction, game, match)
            return

        game.finish_game()
        save_games(self.games)

        # No refresh of its own: announce_game_over settles the
        # persistent message from the board it posts.
        await self.announce_game_over(
            interaction, game, f"{whistle}\n\n{self.build_goal_log(match)}"
        )

    def build_goal_log(self, match: MatchState) -> str:
        """
        The scoresheet, with this cog's roster and emoji behind it.

        It is built by the callers of announce_game_over rather than
        inside it, because that function is handed a string and has no
        match: the whistle and the shootout each already hold one, and
        passing it in would be for this alone.
        """
        return build_goal_log(match, self.player_catalog, self.team_emojis)

    async def announce_game_over(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        content: str,
    ) -> None:
        """
        The last message of a game: the result, the board the game
        ended on, and the rematch and archive buttons under it. Both
        endings post it -- the whistle when full time settles the game,
        and the shootout when it does not.

        The final board rides on this message rather than being left to
        the persistent one, for the reason a loose ball's does (see
        announce_board_update): by full time the persistent message has
        scrolled hours up the channel, and the result is exactly the
        thing nobody should have to go looking for the position of. It
        is the same render-once-upload-twice -- the persistent message
        is settled from these bytes -- so the callers no longer refresh
        it themselves. It is deliberately *not* pinned: pinning stays
        the new play's alone, and a pin here would be the one at the
        very bottom of a channel nobody is playing in any more.
        """
        view = RematchView(self, game.game_id)
        png = await self.render_match_png(game)
        final = await interaction.followup.send(
            content,
            file=self.match_file_from_png(game, png),
            view=view,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
            wait=True,
        )
        # Handed the view, or the edit that adds the link drops the two
        # buttons this message exists for.
        await add_full_image_button(final, view)
        # Remembered so the buttons come back after a restart: the
        # channel stays where it is until someone clicks one, which can
        # be days later.
        game.rematch_message_id = final.id
        save_games(self.games)
        await self.refresh_match_image(interaction, game, png=png)

    # -- Halftime ------------------------------------------------------

    async def begin_halftime(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Kicks off halftime cleanup once end_period has already flipped
        the period, reset the clock, and moved the ball to the
        second-half kickoff space: automatic exhaustion recovery for
        every fielded player, then the rest of the sequence (each
        side's extra-token choice, substitution window, and free
        repositioning) driven by `match.pending_halftime_stage` --
        see advance_halftime_stage.
        """
        recovery_lines = []
        for side in (TeamSide.HOME, TeamSide.VISITING):
            for player_id in match.setup_for_side(side).field_players:
                player = self.engine.get_player_definition(player_id)
                # A Cyborg's own line, not their defensive skill --
                # "Drained counts as Exhausted everywhere the rules use
                # that word", the halftime re-test included.
                threshold = self.engine.exhaustion_threshold(game, player_id)
                removed = match.recover_exhaustion(player_id, 1, threshold)
                if removed:
                    remaining = match.exhaustion.get(player_id, 0)
                    recovery_lines.append(
                        f"{self.player_label(match, player)} "
                        f"recovers 1 exhaustion token (now {remaining})."
                    )

        self.persist(game, match)

        body = (
            "\n".join(recovery_lines)
            if recovery_lines
            else "No fielded player had any exhaustion tokens to recover."
        )
        await interaction.followup.send(
            f"# Halftime\nEvery fielded player recovers 1 exhaustion "
            f"token:\n{body}"
        )
        await self.refresh_match_image(interaction, game)

        match.pending_halftime_stage = HALFTIME_STAGES[0]
        self.persist(game, match)
        await self.advance_halftime_stage(interaction, game, match)

    async def begin_setup_coaching(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        """
        Offer both coaches a Coaching Choice before kickoff, home
        first -- see "Setup" in docs/living-rules.md. Both
        teams are dealt the standard 2-2-2 and, in basic mode, dealt
        identically; this is where a coach may change any of it rather
        than waiting for their first window.

        Substitutions here are unlimited and a player taken off goes
        back to the bench: nobody has played, so nothing is used up.
        A coach happy with the deal finishes without changing anything.
        """
        match = self.engine.load_match_state(game)

        # A tutorial kicks off on the standard deal. The Coaching
        # Choice is the most involved menu in the game and the script
        # explains it at beat 6, on the window a real new play offers;
        # putting a coach through it before they have seen a turn is
        # asking them to rearrange a board they cannot read yet. It
        # costs them nothing -- both sides are dealt the same 2-2-2,
        # and the tutorial re-deals both of them every beat anyway.
        if game.tutorial:
            match.pending_setup_stage = None
            self.persist(game, match)
            await self.finish_setup_coaching(interaction, game, match)
            return

        match.pending_setup_stage = SETUP_STAGES[0]
        self.persist(game, match)
        await self.advance_setup_stage(interaction, game, match)


    async def advance_setup_stage(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """Hand the next coach their pre-kickoff Coaching Choice, or
        kick off."""
        stage = match.pending_setup_stage
        if stage in ("coaching_home", "coaching_visiting"):
            side = (
                TeamSide.HOME
                if stage == "coaching_home"
                else TeamSide.VISITING
            )
            setup = match.setup_for_side(side)
            await self.begin_substitution_window(
                interaction,
                game,
                match,
                side,
                occasion=CoachingOccasion.SETUP,
                lead_in=(
                    f"## Before kickoff\n{format_team_side_label(setup)} "
                    "set their line-up. Substitutions are unlimited here "
                    "and anyone taken off goes back to the bench -- the "
                    "game has not started, so nothing is used up."
                ),
            )
            return

        await self.finish_setup_coaching(interaction, game, match)

    async def finish_setup_coaching(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Both coaches are done, so the game can start -- and this is
        where the board first goes up. Nothing has been played yet, so
        a board posted before the windows would show a deal neither
        coach had finished with, and be redrawn twice over before
        anyone acted on it; the one worth looking at is the line-up the
        game actually kicks off from.

        A kickoff is a new play, so it posts its board the way every
        other one does: as its own message, under the coaching it came
        out of. It used to attach the board to the persistent message
        instead, which is a message near the top of the channel -- and
        Discord leaves an edited message where it was, so the board a
        coach had just finished setting appeared *above* the windows
        that set it, looking for all the world like the board had gone
        up before kickoff coaching rather than after it.
        """
        match.pending_setup_stage = None
        self.persist(game, match)

        kicking_off = match.setup_for_side(match.ball.possession)
        await self.post_new_play_board(
            interaction,
            game,
            (
                "**The teams are dealt.** The game kicks off with "
                f"{format_team_side_label(kicking_off)} in possession."
                if game.tutorial
                else "**Both coaches are set.** The game kicks off with "
                f"{format_team_side_label(kicking_off)} in possession."
            ),
        )

        # The script arms here rather than at creation, so everything
        # up to the kickoff -- teams, the toss, home or visiting -- is
        # played exactly as an ordinary game plays it. The welcome goes
        # under the board it describes; the first beat is staged by the
        # send_turn_prompt below.
        async def begin_play(inner_interaction: discord.Interaction) -> None:
            try:
                await self.send_turn_prompt(inner_interaction, game)
            except ValueError as error:
                await inner_interaction.followup.send(
                    str(error), ephemeral=True,
                )

        if game.tutorial:
            game.tutorial_step = tutorial.FIRST_STEP
            game.tutorial_staged = False
            save_games(self.games)
            # The welcome and beat 1's own lesson are two narration
            # messages with nothing for the coach to click between
            # them, so the first is held behind Continue rather than
            # posted alongside it -- see post_tutorial_note.
            await self.post_tutorial_note(
                interaction, game, tutorial.WELCOME, begin_play,
            )
            return

        await begin_play(interaction)

    async def advance_halftime_stage(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """Dispatch to whichever halftime stage comes next, or finish."""
        stage = self.engine.halftime_stage(match)
        if stage == "extra_token_home":
            await self.begin_halftime_extra_token(
                interaction, game, match, TeamSide.HOME,
            )
        elif stage == "extra_token_visiting":
            await self.begin_halftime_extra_token(
                interaction, game, match, TeamSide.VISITING,
            )
        elif stage == "coaching_home":
            await self.begin_halftime_substitutions(
                interaction, game, match, TeamSide.HOME,
            )
        elif stage == "coaching_visiting":
            await self.begin_halftime_substitutions(
                interaction, game, match, TeamSide.VISITING,
            )
        else:
            await self.finish_halftime(interaction, game, match)

    async def begin_halftime_extra_token(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
    ) -> None:
        """
        The coach's choice of one fielded player to lose an extra
        exhaustion token, on top of the automatic recovery every
        fielded player already got in begin_halftime.
        """
        setup = match.setup_for_side(side)
        eligible = [
            player_id
            for player_id in setup.field_players
            if player_id not in match.injured
        ]

        if not eligible:
            self.engine.next_halftime_stage(match)
            self.persist(game, match)
            await self.advance_halftime_stage(interaction, game, match)
            return

        if self.engine.side_is_ai(game, side):
            player_id = max(
                eligible, key=lambda pid: match.exhaustion.get(pid, 0),
            )
            threshold = self.engine.exhaustion_threshold(game, player_id)
            removed = match.recover_exhaustion(player_id, 1, threshold)
            self.engine.next_halftime_stage(match)
            self.persist(game, match)

            if removed:
                player = self.engine.get_player_definition(player_id)
                remaining = match.exhaustion.get(player_id, 0)
                await interaction.followup.send(
                    f"{format_team_side_label(setup)} removes an extra "
                    "exhaustion token from "
                    f"{self.player_label(match, player)} "
                    f"(now {remaining})."
                )
                await self.refresh_match_image(interaction, game)
            await self.advance_halftime_stage(interaction, game, match)
            return

        controller_id = self.engine.side_controller_id(game, side)
        mention = f"<@{controller_id}>" if controller_id else "Someone"
        prompt = await interaction.followup.send(
            f"{mention}, {format_team_side_label(setup)}: choose one "
            "fielded player to lose an extra exhaustion token.",
            view=HalftimeExtraTokenView(self, game.game_id, side),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt.id
        save_games(self.games)

    async def begin_halftime_substitutions(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
    ) -> None:
        """
        Give `side` a full substitution window (see
        begin_substitution_window) -- unlike a turnover's
        declare-then-respond pairing, halftime gives each side its own
        independent window, so finish_substitution_window routes back
        into the halftime sequence instead of chaining to the other
        side's response.

        Nobody is asked whether to declare, and nothing is charged for
        it: halftime substitutions just happen ("the coach can change
        their team's formation and the players' assignment as they
        please", End of Time), and they leave the side's once-a-half
        declaration unspent for the second half. A side with nothing
        it wants to change finishes the menu without doing anything,
        which is the same as passing used to be.
        """
        setup = match.setup_for_side(side)
        await self.begin_substitution_window(
            interaction,
            game,
            match,
            side,
            occasion=CoachingOccasion.HALFTIME,
            lead_in=(
                f"## Halftime\n{format_team_side_label(setup)} set up "
                "for the second half."
            ),
        )

    async def finish_halftime(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The last step of halftime -- the visiting kickoff-space
        guarantee is already enforced before this is reached (see
        coaching_finish_refusal), so this just clears the halftime flag
        and hands play to the second half.
        """
        match.pending_halftime_stage = None
        self.persist(game, match)

        # A half begins the way any other new play does: with the board
        # everyone is about to play from, posted and pinned.
        await self.post_new_play_board(
            interaction,
            game,
            "**Halftime is over.** The second half kicks off with "
            f"{format_team_side_label(match.visiting)} in possession.",
        )

        try:
            await self.send_turn_prompt(interaction, game)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)

    # -- The window before the shootout --------------------------------

    async def begin_full_time_coaching(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The last Coaching Choice of a level game, one to each coach
        before the shootout opens -- see "Full time" in
        docs/living-rules.md. **One substitution and nothing else**: a
        shootout is played by who is on the field and by nothing about
        where they stand, so the three positional actions would
        rearrange a side that never plays from a position again.

        Home go first, which is the author's call rather than anything
        the position decides: nobody kicks off here, so the reason
        setup and halftime have an order does not apply.

        It runs as a stage sequence for the same reason halftime does:
        two windows one after the other are two live interactions with
        the bot's own step between them, and a restart in the middle
        has nothing to click. `pending_full_time_stage` is what a
        restart reads.
        """
        match.pending_full_time_stage = FULL_TIME_STAGES[0]
        self.persist(game, match)
        await self.advance_full_time_stage(interaction, game, match)


    async def advance_full_time_stage(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """Hand the next coach their one substitution, or shoot out."""
        stage = match.pending_full_time_stage
        if stage in ("coaching_home", "coaching_visiting"):
            side = (
                TeamSide.HOME
                if stage == "coaching_home"
                else TeamSide.VISITING
            )
            # A menu whose only action is disabled is a Done button
            # with extra steps, and this window has no other action to
            # fall back on -- so a side with nobody it could bring on
            # is passed over in silence, the way halftime passes over a
            # side with nobody to take an extra token off. It takes
            # both benches spent: three substitutions to drain the
            # bench, and every one of the three who came off injured.
            if not match.substitution_pool(side):
                self.engine.next_full_time_stage(match)
                self.persist(game, match)
                await self.advance_full_time_stage(interaction, game, match)
                return

            setup = match.setup_for_side(side)
            await self.begin_substitution_window(
                interaction,
                game,
                match,
                side,
                occasion=CoachingOccasion.FULL_TIME,
                lead_in=(
                    f"## Before the shootout\n{format_team_side_label(setup)} "
                    "may make **one substitution** -- the last change "
                    "either side gets. Nothing else is offered: the "
                    "shootout is played by whoever is on the field, and "
                    "not by where they are standing."
                ),
            )
            return

        await self.finish_full_time_coaching(interaction, game, match)

    async def finish_full_time_coaching(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """Both coaches are done, so the shooting can start."""
        match.pending_full_time_stage = None
        self.persist(game, match)
        await self.begin_shootout(interaction, game, match)

    # -- The extreme shootout ------------------------------------------

    async def begin_shootout(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Open the shootout that settles a game level at full time. See
        "Extreme shootout" in docs/living-rules.md.

        The shootout is **four steps that hand back to each other**,
        and `advance_shootout` is the single reading of which one a
        saved game is on -- the same job `pending_turn_view` does for
        a turn, and for the same reason: two of the four are the
        bot's own move, so a restart between them has no button
        anywhere to press.
        """
        match.begin_shootout()
        self.persist(game, match)

        await interaction.followup.send(
            "# Extreme shootout\n"
            "The scores are level, so the game is settled on the "
            "extreme shootout.\n\n"
            "Each coach secretly puts their **six field players** in "
            "the order they will shoot. Both sides then reveal their "
            "top card together and those two players roll a **skill "
            "test**, each adding their offensive skill -- an injured "
            "player adds none and rolls the bare d12. The winner "
            "scores a goal; a tie scores for nobody. Six skill tests "
            "is a **round**, and a level round goes to sudden death."
        )
        await self.advance_shootout(interaction, game, match)

    async def advance_shootout(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Put the shootout's next step in front of whoever owes it.

        Everything routes through here -- opening the shootout, the
        end of a skill test, and `/d12ball resume` -- so there is one
        answer to "what is this shootout waiting on?" and no way for
        the resume to offer a different step from the one a restart
        restores. `pending_turn_view` reads the same three states off
        the same three questions.
        """
        if not match.shootout_orders_complete:
            await self.ask_shootout_orders(interaction, game, match)
            return

        if not match.shootout_shooters_complete:
            await self.ask_shootout_shooters(interaction, game, match)
            return

        await self.reveal_shootout_test(interaction, game, match)

    async def ask_shootout_orders(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The secret ordering both coaches do before the first test. An
        AI side sets its own here and now, so a solo game only ever
        waits on the one coach who has a choice to make.
        """
        for side in (TeamSide.HOME, TeamSide.VISITING):
            if match.shootout_order_complete(side):
                continue
            if not self.engine.side_is_ai(game, side):
                continue
            match.set_shootout_order(
                side,
                self.engine.get_ai_strategy(game).choose_shootout_order(
                    match.shootout_squad(side),
                ),
            )

        self.persist(game, match)

        if match.shootout_orders_complete:
            await self.reveal_shootout_test(interaction, game, match)
            return

        owing = [
            side
            for side in (TeamSide.HOME, TeamSide.VISITING)
            if not match.shootout_order_complete(side)
        ]
        await self.post_shootout_prompt(
            interaction,
            game,
            match,
            f"{self.engine.shootout_mentions(game, match, owing)}: set the "
            "order your six players shoot in. Nobody else sees it.",
            ShootoutOrderPromptView(self, game.game_id),
            # Nobody has shot, so the usual "skill test 1 of 6, 0 — 0"
            # is a scoreline with nothing in it yet.
            heading="### Extreme shootout",
        )

    async def ask_shootout_shooters(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Sudden death's pick. Only ever reached in a round past the
        first: the first round's shooter is read off the order, so
        there is nothing to ask for and nothing to lose in a restart.
        """
        for side in (TeamSide.HOME, TeamSide.VISITING):
            if match.shootout_shooter(side) is not None:
                continue
            if not self.engine.side_is_ai(game, side):
                continue
            match.set_shootout_shooter(
                side,
                self.engine.get_ai_strategy(game).choose_shootout_shooter(
                    match.shootout_eligible(side),
                ),
            )

        self.persist(game, match)

        if match.shootout_shooters_complete:
            await self.reveal_shootout_test(interaction, game, match)
            return

        owing = [
            side
            for side in (TeamSide.HOME, TeamSide.VISITING)
            if match.shootout_shooter(side) is None
        ]
        await self.post_shootout_prompt(
            interaction,
            game,
            match,
            f"{self.engine.shootout_mentions(game, match, owing)}: choose who "
            "goes out next, from the players who have not shot yet "
            "this round. Nobody else sees it until the reveal.",
            ShootoutPickPromptView(self, game.game_id),
        )

    async def post_shootout_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        content: str,
        view: discord.ui.View,
        heading: Optional[str] = None,
    ) -> None:
        prompt = await interaction.followup.send(
            f"{heading or self.engine.shootout_heading(match)}\n{content}",
            view=view,
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt.id
        save_games(self.games)





    def shootout_order_text(
        self,
        match: MatchState,
        side: TeamSide,
    ) -> str:
        """The order a coach has built so far, on their own menu."""
        lines = []
        for position, player_id in enumerate(
            match.shootout_order(side), start=1,
        ):
            player = self.engine.get_player_definition(player_id)
            note = " — injured" if player_id in match.injured else ""
            lines.append(
                f"{position}. "
                f"{self.player_label(match, player)}{note}"
            )

        if match.shootout_order_complete(side):
            header = (
                "**Your shooting order is set.** You may look at it, "
                "but not reorder it."
            )
        elif lines:
            header = "Keep going -- click the next player to shoot."
        else:
            header = (
                "Click your six players in the order they shoot. Only "
                "you can see this."
            )

        return "\n".join([header, *lines])

    async def reveal_shootout_test(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Both top cards, turned over together, and the button that
        rolls them against each other. Either coach may press it, like
        every other roll in the game.
        """
        lines = []
        for side in (TeamSide.HOME, TeamSide.VISITING):
            shooter_id = match.shootout_shooter(side)
            if shooter_id is None:
                # Nothing to reveal means the state moved under us --
                # advance_shootout is the only way back in.
                await self.advance_shootout(interaction, game, match)
                return
            player = self.engine.get_player_definition(shooter_id)
            note = (
                " — injured, no skill modifier"
                if shooter_id in match.injured
                else ""
            )
            lines.append(
                f"{self.player_label(match, player)}{note}"
            )

        prompt = await interaction.followup.send(
            f"{self.engine.shootout_heading(match)}\n"
            f"{lines[0]}\nversus\n{lines[1]}\n\nEither player can roll:",
            view=ShootoutTestView(self, game.game_id),
            wait=True,
        )
        game.turn_message_id = prompt.id
        save_games(self.games)

    async def close_shootout_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        """
        Drop the "set your order" or "choose your shooter" prompt once
        both sides have answered it. Its button has nothing left to
        open, and the reveal posted underneath it is what the channel
        should end on -- the same reasoning as close_maneuver_prompt,
        including clearing `turn_message_id` so nothing re-attaches a
        view to a message that is gone.
        """
        if game.turn_message_id is None or interaction.channel is None:
            return

        try:
            await interaction.channel.get_partial_message(
                game.turn_message_id,
            ).delete()
        except (discord.NotFound, discord.HTTPException):
            pass

        game.turn_message_id = None
        save_games(self.games)

    async def continue_shootout(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        What a settled skill test hands back to: end the shootout, or
        set the next test up.

        The test has already retired its two shooters by the time this
        runs (`finish_shootout_test`, in the same save as the goal),
        which is what lets `shootout_winner` count the tests still to
        come simply by asking who is left.
        """
        winner = match.shootout_winner()
        if winner is None:
            await self.advance_shootout(interaction, game, match)
            return

        match.pending_shootout = False
        self.persist(game, match)
        game.finish_game()
        save_games(self.games)

        home = match.shootout_goals_for(TeamSide.HOME)
        visiting = match.shootout_goals_for(TeamSide.VISITING)
        await self.announce_game_over(
            interaction,
            game,
            f"**The extreme shootout is settled, {home}-{visiting}.**"
            f"\n\n{build_full_time_summary(game, match)}"
            f"\n\n{self.build_goal_log(match)}",
        )

"""
What the coach sees: prompts, the images under them, the board
message, the tutorial's narration, the AI's turn, and a game's
channel. Nothing here decides anything about the game.

The board write gate itself is `cogs/d12ball_boards.py`; the six
methods here that name it are the forwarders that kept its call
sites still.
"""

import aiohttp
import asyncio
import discord
import io
import random
import time
from typing import Awaitable, Callable, Optional

from discord.ext import commands
from d12ball.components import (
    CYBORG_DRAINED_AT,
    SPECIES_CYBORG,
    MatchState,
    PlayerRole,
    TeamSetup,
    TeamSide,
)
from d12ball.engine import IgnitedRoll
from d12ball.game import D12BallGame, team_display_name
from d12ball import tutorial
from d12ball.render import (
    TEAM_COLORS,
    render_field_image,
    render_maneuver_challenge,
    render_match_image,
    render_score_attempt,
    render_volatile_die,
    zone_labels,
)
from gamesaves.d12ball.storage import save_games
from cogs.d12ball_helpers import (
    FIELD_IMAGE_FILENAME,
    PBD_ARCHIVE_CATEGORY_NAME,
    add_full_image_button,
    board_image_filename,
    challenger_prompt_ask,
    format_ai_name,
    format_player_with_team,
    format_team_side_label,
    get_exhaust_emoji,
    get_exhausted_emoji,
    get_injured_emoji,
    get_or_create_category,
    pin_board_message,
    refresh_player_names,
    space_label,
)
from cogs.d12ball_views import (
    BallHandlerSelectionView,
    ManeuverActionPromptView,
    ManeuverChallengeView,
    PlayerActionView,
    TutorialContinueView,
)
from cogs.d12ball_boards import BoardRefresher


class PresentationMixin:
    """
    What the coach sees: prompts, the images under them, the board
    """

    async def close_maneuver_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Delete the public "choose your maneuver" prompt once every
        side it was waiting on has picked: its button has nothing left
        to open, and the resolution posted underneath it is what the
        channel should end on. An uncontested maneuver is waiting on
        the offense alone, so its prompt goes on that one pick.

        Until then it is left alone. It used to be re-edited with a
        fresh `ManeuverActionPromptView` on each pick, which changed
        nothing a coach could see -- the message says who it is waiting
        on and both sides share one button, so the prompt reads the
        same after one pick as before it, and the view is built from
        the game id alone. That edit was a request out of the tightest
        bucket in the game (see "Discord's rate limits" in CLAUDE.md),
        spent once a maneuver, immediately before the resolution's own
        board refresh, for nothing. Who has picked is announced in its
        own message.

        Deleting clears `turn_message_id` with it, so nothing tries to
        edit or re-attach a view to a message that is gone; whatever
        prompt the resolution posts next sets its own.
        """
        if game.turn_message_id is None or interaction.channel is None:
            return

        if not match.maneuver_selections_complete:
            return

        try:
            await interaction.channel.get_partial_message(
                game.turn_message_id,
            ).delete()
        except (discord.NotFound, discord.HTTPException):
            pass

        game.turn_message_id = None
        save_games(self.games)


    def apply_exhaustion(
        self,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
        amount: int,
    ) -> str:
        """
        Charge `amount` exhaustion tokens, re-test Exhausted, and
        describe both.

        Charging and testing belong in one step. They used to be two:
        callers added the tokens, saved the match, and only then built
        the message that ran the threshold test -- so the flag the
        test set was never written out. The next interaction reloaded
        the saved state and saw a player over their defensive skill
        who was not marked Exhausted, which cost a skill test the
        injury check for anyone the test's own tokens pushed over.
        Anything that charges exhaustion should call this and save
        afterwards.

        It takes the `game` because the threshold is not always the
        player's defensive skill: a Cyborg's tokens are **drain** and
        the line is a flat 7 -- see `RulesEngine.exhaustion_threshold`.
        Nothing else about charging a token differs by species, which
        is why this stayed one method rather than growing a branch.
        """
        match.add_exhaustion(player_id, amount)
        return self.describe_exhaustion_gain(game, match, player_id, amount)

    def describe_exhaustion_gain(
        self,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
        amount: int,
    ) -> str:
        """
        Text describing an exhaustion-token gain that has already been
        applied to `match` — the running total, plus a line the moment
        it pushes the player's token count past their own threshold.

        Testing the threshold is a state change, so this has to be
        called before `match` is saved -- prefer `apply_exhaustion`,
        which keeps the two together, wherever the tokens are being
        charged here rather than inside `MatchState`.
        """
        player = self.engine.get_player_definition(player_id)
        if player_id in match.injured:
            return (
                f"{self.player_label(match, player)} is injured "
                f"{get_injured_emoji(self.condition_emojis)} and gains no "
                "exhaustion tokens."
            )
        if amount <= 0:
            # Nothing to say, and the silence is the answer (the
            # author, 2026-08-27). Every move that costs a token says
            # so right here, so a result carrying no exhaustion line
            # already tells a coach none was charged -- where "no
            # exhaustion cost" answered a question the message had not
            # raised, and "free" left it to the coach to work out what
            # was free about it. Callers join on what is there rather
            # than interpolating, or the empty string shows as a blank
            # line.
            return ""

        exhaust_emoji = get_exhaust_emoji(self.condition_emojis)
        total = match.exhaustion.get(player_id, 0)
        token_word = "token" if amount == 1 else "tokens"
        # A Cyborg's tokens are drain, and are called that everywhere a
        # coach reads them -- the mechanic is the same and the word is
        # the ability. See "Lithium Powered" in docs/living-rules.md.
        drain = self.engine.has_species_ability(
            game, player_id, SPECIES_CYBORG,
        )
        noun = "drain" if drain else "exhaustion"
        text = (
            f"{self.player_label(match, player)} gains {amount} {noun} "
            f"{token_word} {exhaust_emoji * amount} (now {total} total)."
        )

        if self.engine.retest_exhausted(game, match, player_id):
            exhausted_emoji = get_exhausted_emoji(self.condition_emojis)
            if drain:
                text += (
                    f"\n{self.player_label(match, player)} is now "
                    f"**Drained** {exhausted_emoji} — {total} drain "
                    f"tokens reaches {CYBORG_DRAINED_AT}. Drained counts "
                    "as Exhausted everywhere the rules use the word."
                )
            else:
                defense_skill = self.player_catalog.effective_profile(
                    player,
                ).defense
                text += (
                    f"\n{self.player_label(match, player)} now has the "
                    f"condition **exhausted** {exhausted_emoji} — {total} "
                    "exhaustion tokens exceeds their defense skill of "
                    f"{defense_skill}."
                )
        return text

    def describe_challenger_walk_in(
        self,
        game: D12BallGame,
        match: MatchState,
        defender_id: str,
        distance: int,
    ) -> str:
        """
        The challenger's walk-in and what it cost, or "" when they were
        already on the ball's space.

        Like every other exhaustion message this tests the Exhausted
        threshold as it writes it, so it has to be built before `match`
        is saved -- see apply_exhaustion.
        """
        if distance <= 0:
            return ""

        defender = self.engine.get_player_definition(defender_id)
        space_word = "space" if distance == 1 else "spaces"
        return (
            f"{defender.name} has moved {distance} {space_word}."
            f"\n{self.describe_exhaustion_gain(game, match, defender_id, distance)}"
        )


    async def build_maneuver_challenge_file(
        self,
        match: MatchState,
        defender_id: str,
    ) -> discord.File:
        """
        The matchup about to be contested, as a picture. It stands in
        for the two lines of prose that used to announce a challenge:
        the players' skills and abilities are what a coach weighs while
        choosing a maneuver, and neither was in the text.

        Drawn in a worker thread for the same reason the board is --
        see render_match_png.
        """
        return discord.File(
            await asyncio.to_thread(
                render_maneuver_challenge,
                self.engine.challenge_side(
                    match.active_player_id,
                    match.team_for_player(match.active_player_id),
                    attacking=True,
                ),
                self.engine.challenge_side(
                    defender_id,
                    match.team_for_player(defender_id),
                    attacking=False,
                ),
                location=(
                    f"{space_label(match.ball.zone, match.ball.space_index)}"
                    f" — {zone_labels(match.board.layout.board_size)[match.ball.zone].title()}"
                ),
            ),
            filename="maneuver_challenge.png",
        )

    async def build_score_attempt_file(self, match: MatchState) -> discord.File:
        """
        What the shot is made of: the shooter with the modifiers this
        particular attempt earns them, and every defender between them
        and the goal.

        The two modifiers are listed on the shooter rather than folded
        into their skill, because both are conditions of this attempt
        and not of the player -- the ball speed is spent on the shot,
        and the Striker's +3 only applies off a set-up.

        The defenders are the other way round: what each one adds is
        folded in, as their `contribution`, because a coach counting
        the wall is asking what it comes to and not what it would come
        to somewhere else on the field.
        """
        shooter = self.engine.get_player_definition(match.active_player_id)
        speed_modifier = match.ball_speed_modifier()
        defenders = self.engine.intervening_defenders(match)
        defending_setup = match.setup_for_side(match.defending_side())

        modifiers = []
        if speed_modifier:
            modifiers.append(
                f"{speed_modifier:+d} ball speed ({match.ball.speed})"
            )
        if match.pending_shot_is_set_up and shooter.role == PlayerRole.STRIKER:
            modifiers.append("+3 Striker ability")

        return discord.File(
            await asyncio.to_thread(
                render_score_attempt,
                self.engine.challenge_side(
                    shooter.player_id,
                    match.team_for_player(shooter.player_id),
                    attacking=True,
                    modifiers=tuple(modifiers),
                ),
                [
                    self.engine.challenge_side(
                        defender.player.player_id,
                        match.team_for_player(defender.player.player_id),
                        attacking=False,
                        contribution=defender.value,
                        halved=not defender.on_ball,
                    )
                    for defender in defenders
                ],
                location=(
                    f"{space_label(match.ball.zone, match.ball.space_index)}"
                    f" → {format_team_side_label(defending_setup)} goal"
                ),
            ),
            filename="score_attempt.png",
        )

    async def post_volatile_ignition(
        self,
        interaction: discord.Interaction,
        match: MatchState,
        *rolls: tuple[Optional[str], IgnitedRoll],
    ) -> None:
        """
        The second die an ignite rolled, shown on its own and explained
        -- one message per ignited roll, and nothing at all for the
        rolls that did not ignite, which is almost all of them.

        **One helper for every caller of `RulesEngine.ignite`** -- the
        six roll sites the rules name, plus the Mind Pull roll that
        asks anyway -- which is that funnel read from the other end:
        it owns what a die means and this owns what a coach is shown
        of it, so the next ability that adds a die to a roll is drawn
        and worded in one place rather than seven. Each site passes
        the pairs it has: a contest both sides, a score attempt only
        the shooter, whose die is the only one of its two that can
        ignite at all.

        **It goes between the roll's own dice image and the result.**
        The ignite happened to the die a coach has just watched and
        before the verdict they are about to read, and a message's
        attachments render below its content, so posting it here is the
        only order in which the three read as what happened -- see
        `SkillTestView.roll` for the same reasoning about a result.

        The sentence is above its own die rather than under it, unlike
        every result in the game: it is not a verdict the picture is
        about to reveal, it is the caption explaining why a second die
        exists at all, and the alternative is two messages an ignite.

        A roll that did not ignite carries no image and no line, which
        is "a move that costs nothing says nothing" -- and is what lets
        a caller hand over both sides of a contest without asking.
        """
        for player_id, ignite in rolls:
            if player_id is None or not ignite.ignited:
                continue
            player = self.engine.get_player_definition(player_id)
            team = match.team_for_player(player_id)
            await interaction.followup.send(
                ignite.explain(self.player_label(match, player)),
                file=discord.File(
                    await asyncio.to_thread(
                        render_volatile_die,
                        ignite.second,
                        ignite.face,
                        TEAM_COLORS[team],
                        team_display_name(team),
                        player.name,
                        ignite.surge,
                        ignite.modifier,
                    ),
                    filename="volatile_ignition_die.png",
                ),
            )

    async def announce_maneuver_challenge(
        self,
        interaction: discord.Interaction,
        match: MatchState,
        defender_id: str,
        walk_in_text: str,
    ) -> None:
        """
        Post the matchup image, with the challenger's walk-in above it
        rather than below: the image is meant to sit directly on top of
        the maneuver prompt, which is the message a coach is reading it
        for.
        """
        if walk_in_text:
            await interaction.followup.send(
                walk_in_text,
                allowed_mentions=discord.AllowedMentions(
                    users=False, roles=False, everyone=False,
                ),
            )
        await interaction.followup.send(
            file=await self.build_maneuver_challenge_file(match, defender_id),
        )

    async def drop_turn_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        """
        Delete the prompt whose choice has just been made, the same way
        close_maneuver_prompt drops the maneuver prompt once both
        sides have picked: what it asked for is settled, and the
        challenge image posted underneath says who is involved better
        than the "has chosen to..." line the message would otherwise be
        edited down to.

        The caller must have acknowledged the interaction already
        (`response.defer()`), since deleting is not itself a response.
        """
        try:
            await interaction.delete_original_response()
        except (discord.NotFound, discord.HTTPException):
            pass

        if game.turn_message_id is not None:
            game.turn_message_id = None
            save_games(self.games)

    async def refresh_match_image(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        png: Optional[bytes] = None,
    ) -> None:
        """
        Bring the persistent board message up to date, through the
        gate that decides when it may actually be written.

        This is the way in for the fifty-odd call sites that put a
        board up, and the only part of `BoardRefresher` the rest of the
        cog touches. The interaction is here because they all hold one;
        the gate itself wants nothing from it but the channel.
        """
        if interaction.channel is None:
            return

        await self.boards.refresh(interaction.channel, game, png)

    # The five below forward for the same reason: the gate moved, the
    # call sites did not. Each is the identical call on `self.boards`,
    # and the reasoning for every one of them is on the method it
    # forwards to.

    def schedule_board_refresh(
        self,
        channel: discord.TextChannel,
        game: D12BallGame,
        delay: float,
    ) -> None:
        self.boards.schedule(channel, game, delay)

    def board_refresh_interval(self, game: D12BallGame) -> float:
        return self.boards.interval(game)

    def note_board_write_refused(self, game: D12BallGame) -> None:
        self.boards.note_write_refused(game)

    async def wait_out_board_interval(self, game: D12BallGame) -> None:
        await self.boards.wait_out_interval(game)

    async def write_board_message(
        self,
        channel: discord.TextChannel,
        game: D12BallGame,
        png: Optional[bytes] = None,
        *,
        relink: bool = True,
    ) -> None:
        await self.boards.write(channel, game, png, relink=relink)

    async def settle_board_link(
        self,
        channel: discord.TextChannel,
        game: D12BallGame,
    ) -> None:
        await self.boards.settle_link(channel, game)



    def format_team_roster_entry(
        self,
        match: MatchState,
        player_id: str,
        location: Optional[str] = None,
        show_abilities: bool = False,
    ) -> str:
        """
        One roster line. `location` is the space the player stands on
        (e.g. "H1") for a player on the board, and None on a bench --
        the group heading above the line already names the place, so
        the line only has to say where within it.
        """
        player = self.engine.get_player_definition(player_id)
        tokens = match.exhaustion.get(player_id, 0)

        conditions = []
        if player_id in match.exhausted:
            conditions.append(
                f"exhausted {get_exhausted_emoji(self.condition_emojis)}"
            )
        if player_id in match.injured:
            conditions.append(
                f"injured {get_injured_emoji(self.condition_emojis)}"
            )

        entry = self.player_label(match, player)
        if location is not None:
            entry += f" — {location}"
        entry += f" — {tokens} {get_exhaust_emoji(self.condition_emojis)}"
        if conditions:
            entry += f" — {', '.join(conditions)}"
        if show_abilities:
            ability = self.player_catalog.effective_profile(player).ability
            entry += f"\n     *{ability}*"
        return entry



    def build_team_roster_section(
        self,
        match: MatchState,
        setup: TeamSetup,
        show_abilities: bool = False,
    ) -> str:
        lines = [f"**{format_team_side_label(setup)}**"]
        for heading, members in self.engine.roster_places(match, setup):
            lines.append(f"\n__{heading}__")
            if not members:
                lines.append("*nobody*")
                continue
            lines.extend(
                self.format_team_roster_entry(
                    match,
                    player_id,
                    location=location,
                    show_abilities=show_abilities,
                )
                for player_id, location in members
            )
        return "\n".join(lines)


    async def play_ai_turn(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Play out the AI opponent's turn with possession: pick a ball
        handler, then shoot if the ball is already on the space closest
        to the opponent's goal, call a time out if one of theirs is
        injured on the field, otherwise maneuver.
        """
        ai_name = format_ai_name(game.ai_opponent)
        ai_strategy = self.engine.get_ai_strategy(game)
        handler_id = ai_strategy.choose_ball_handler(match)
        match.select_ball_handler(handler_id)
        handler = self.engine.get_player_definition(handler_id)
        action = ai_strategy.choose_action(match)

        # **Ahead of the turn-action record**, because a time out is
        # not a turn action -- `begin_time_out` logs its own event
        # instead, and recording one here would open a turn for a pause
        # and hang the real turn's events off it. See
        # `MatchState.record_event` and EVENT_TIME_OUT.
        #
        # Dinky calls one to get an injured player off (the author,
        # 2026-09-16); `DinkyAI.choose_action` is the whole of when.
        # The window it opens runs through `run_ai_substitution_window`
        # like any other AI window, and the human coach gets theirs in
        # reply exactly as a human caller's opponent would.
        if action == "time_out":
            await interaction.followup.send(
                f"{ai_name} calls a time out."
            )
            await self.begin_time_out(interaction, game, match)
            return

        # Recorded here rather than in the two branches below: the AI
        # has no prompt and no stale click to guard against, so the
        # strategy's answer *is* the turn it takes.
        self.record_turn_action(match, action, by_ai=True)

        if action == "shoot":
            match.pending_action = "shoot"
            self.persist(game, match)

            await interaction.followup.send(
                f"{ai_name} has chosen to shoot to score with "
                f"{self.player_label(match, handler)}.",
            )
            await self.begin_score_attempt(interaction, game, match)
            return

        # Unchallenged, so the AI's pick succeeds outright -- the same
        # branch a human offense takes, see
        # PlayerActionView.choose_action.
        eligible_challengers = match.eligible_challengers()
        if not eligible_challengers:
            match.begin_uncontested_maneuver()
            self.persist(game, match)

            await interaction.followup.send(
                f"{ai_name} has chosen to maneuver with "
                f"{self.player_label(match, handler)}."
            )
            await self.announce_uncontested_maneuver(
                interaction, game, match,
            )
            return

        match.pending_action = "maneuver"

        # *One* defender already sharing the ball's exact space leaves
        # nothing to choose -- see PlayerActionView.choose_action, and
        # note that this is a count and not a flag there too: two of
        # them on the ball is the defending coach's pick (the author,
        # 2026-08-17), and taking `on_ball_space[0]` here picked for
        # them off placement order without asking.
        on_ball_space = match.automatic_challengers()
        if len(on_ball_space) == 1:
            self.persist(game, match)

            # Nothing is announced here: the challenge image
            # auto_resolve_challenger posts names the handler the AI
            # picked, along with everything else about the matchup.
            await self.auto_resolve_challenger(
                interaction, game, match, on_ball_space[0],
            )
            return

        self.persist(game, match)

        defender_number = self.engine.defending_player_number(game, match)
        defender_mention = format_player_with_team(
            game,
            defender_number,
            mention=True,
        )

        challenge_view = ManeuverChallengeView(self, game.game_id)
        challenge_message = await interaction.followup.send(
            f"{ai_name} will maneuver with "
            f"{self.player_label(match, handler)}.\n\n"
            f"{defender_mention}, {challenger_prompt_ask(match)}",
            view=challenge_view,
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
        game.turn_message_id = challenge_message.id
        save_games(self.games)

    def tutorial_player_side(self, game: D12BallGame) -> TeamSide:
        """
        Which side of the board the coach being taught is playing.

        Player 1 is always the human in a tutorial -- it is refused any
        other shape (see `create_game`) -- so this is whichever side the
        coin toss put them on. Nothing forces that toss, which is why
        every beat's position is written from a side's own goal forward
        and mirrored on the way in. See `d12ball/tutorial.py`.
        """
        return (
            TeamSide.HOME
            if game.home_player_number == 1
            else TeamSide.VISITING
        )

    def tutorial_beat(self, game: D12BallGame):
        """
        The beat now in progress, or None when no rail applies -- an
        ordinary game, or a tutorial whose script has run out or been
        skipped. Every rail in the views comes through here, so there
        is one answer to "is this coach being taught right now".
        """
        if not game.in_tutorial:
            return None
        return tutorial.beat_for_step(game.tutorial_step)

    def tutorial_railed_option(
        self,
        game: Optional[D12BallGame],
        key: str,
        options,
    ) -> Optional[object]:
        """
        The one option the beat now running allows out of `options`, or
        None when nothing is railed.

        One question for every sub-choice a beat pins down -- the
        dribble distance, the ball speed, the pass distance, the set-up
        shot, whether a loose ball may be waved through -- so a view
        adds a rail with one call rather than a branch of its own. See
        `d12ball/tutorial.py` for why those are railed and a run-back
        space is not.

        It takes the options rather than a single value because one of
        the rails cannot name its value up front: the ball speed a
        steal may set is capped by the stealer's own defensive skill.
        """
        if game is None:
            return None
        return tutorial.resolve_choice(
            self.tutorial_beat(game), key, options,
        )

    def tutorial_dice(
        self,
        game: D12BallGame,
        kind: str,
        count: int,
    ) -> Optional[list[int]]:
        """
        The die values the script fixes for this contest, or None to
        roll for real.

        Every `random.randint(1, 12)` in a contest a tutorial can reach
        asks this first. What it answers for, and what it deliberately
        leaves to the dice, is in `d12ball/tutorial.py` -- the short of
        it is that a beat only scripts a roll the *next* beat depends
        on, and the score attempt at the end is not one of them.
        """
        return tutorial.scripted_dice(
            self.tutorial_beat(game), kind, count,
        )

    async def post_tutorial_note(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        text: str,
        then: Callable[[discord.Interaction], Awaitable[None]],
    ) -> None:
        """
        Post one piece of tutorial narration and hold whatever `then`
        would send next behind a Continue button.

        Two narration messages posted back to back with nothing for
        the coach to click in between is exactly what gets scrolled
        past in a busy channel -- see TutorialContinueView. `then`
        receives the interaction the button click produced, not this
        one, since everything after the click has to answer with that.
        """
        await interaction.followup.send(
            text,
            view=TutorialContinueView(self, game.game_id, then),
        )

    async def stage_tutorial_beat(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        then: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    ) -> None:
        """
        Advance the script to the turn about to be played and post its
        lesson.

        **It moves nothing.** The board is set once, at kickoff, and
        every beat after that is played from wherever the previous
        turn left it -- see the module docstring in
        `d12ball/tutorial.py`. This used to re-deal both sides before
        each beat, which put a seam in the middle of the story; if a
        beat ever needs a position again, the fix is to change the
        script so the play arrives there.

        Called at the top of every `send_turn_prompt` for a tutorial
        game, which is once a turn -- so the *advance* is what counts
        the beats. `tutorial_staged` is what keeps that honest: the
        recovery commands (`/d12ball offensive_choice` and `resume
        force:true`) also send a turn prompt without a turn having been
        played, and re-entering a beat must not silently skip the next
        one.

        `then`, when given, is what `send_turn_prompt` would show
        next -- held behind a Continue button rather than posted
        alongside this beat's note, the same reasoning as every other
        `post_tutorial_note` call site. Left out, the note is posted
        plainly with nothing gating it: the staging tests ask only
        whether the right note went out, never what follows it.
        """
        if not game.in_tutorial:
            return

        if game.tutorial_staged:
            game.tutorial_step = (game.tutorial_step or 0) + 1
            game.tutorial_staged = False

        beat = tutorial.beat_for_step(game.tutorial_step)

        if beat is None:
            # Past the last beat: the script is over. The flag is
            # cleared before anything else, so the prompt this turn
            # puts up is built with no rails on it at all.
            game.tutorial_step = None
            game.tutorial_staged = False
            save_games(self.games)
            if then is not None:
                await self.post_tutorial_note(
                    interaction, game, tutorial.HANDOVER, then,
                )
            else:
                await interaction.followup.send(tutorial.HANDOVER)
            return

        game.tutorial_staged = True
        save_games(self.games)
        if then is not None:
            await self.post_tutorial_note(interaction, game, beat.lesson, then)
        else:
            await interaction.followup.send(beat.lesson)

    async def send_turn_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        async def continue_turn_prompt(
            inner_interaction: discord.Interaction,
        ) -> None:
            refresh_player_names(game, inner_interaction.guild)
            match = self.engine.load_match_state(game)
            # The carrier, when the last resolution left the ball with
            # somebody; everyone on the ball's space otherwise. Either
            # way a single candidate is selected below without asking,
            # so the rule costs a coach a click rather than adding one.
            #
            # Through the engine, so **Slimey** is in it: an Ooze on
            # the ball may take the handler's turn, which turns the
            # one-candidate case back into a real choice and is
            # therefore the one thing that can add a click here.
            eligible_handlers = self.engine.turn_handler_candidates(
                game, match,
            )
            if not eligible_handlers:
                raise ValueError(
                    "The team in possession has no player in the ball's "
                    "space."
                )
            carrying = match.ball_carrier_id in eligible_handlers

            offense_number = self.engine.possession_player_number(game, match)
            if game.is_solo_game and offense_number == 2:
                await self.play_ai_turn(inner_interaction, game, match)
                return

            if len(eligible_handlers) == 1:
                match.select_ball_handler(
                    eligible_handlers[0],
                    self.engine.slip_in_candidates(game, match),
                )
                game.match_state = match.to_dict()
                view: discord.ui.View = PlayerActionView(
                    self,
                    game.game_id,
                )
            else:
                view = BallHandlerSelectionView(
                    self,
                    game.game_id,
                )

            turn_message = await inner_interaction.followup.send(
                self.engine.build_turn_prompt(game, match, carrying=carrying),
                view=view,
                wait=True,
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )
            game.turn_message_id = turn_message.id
            save_games(self.games)

        # Ahead of everything, including the AI branch above: a beat
        # the coach is *defending* is still a beat, and its position
        # has to be down before Dinky takes a turn on it. The note is
        # gated behind Continue, so what follows it -- an AI turn or
        # the ordinary action prompt -- waits on the coach's click
        # rather than landing in the same breath as the note itself.
        if game.in_tutorial:
            await self.stage_tutorial_beat(
                interaction, game, then=continue_turn_prompt,
            )
            return

        await continue_turn_prompt(interaction)

    async def render_match_png(self, game: D12BallGame) -> bytes:
        """
        The board as PNG bytes. The Pillow render is pure CPU work with
        no awaits in it, so it runs in a worker thread via to_thread --
        run inline, it would block the single asyncio event loop for
        every game and every user for as long as the render takes.

        Bytes rather than a `discord.File`, because uploading a File
        consumes the stream inside it: a turn that puts the same board
        in two places (the persistent message and the snapshot under
        the result) needs two Files over one render, not two renders.
        """
        match = self.engine.load_match_state(game)
        home_player = format_player_with_team(
            game,
            game.home_player_number,
        )
        visiting_player = format_player_with_team(
            game,
            game.visiting_player_number,
        )
        period = (
            "First Half"
            if match.scoreboard.period.value == "first_half"
            else "Second Half"
        )
        title = (
            f"PBD{game.game_number} - {home_player} vs. "
            f"{visiting_player}, {period}"
        )
        image = await asyncio.to_thread(
            render_match_image,
            match,
            self.player_catalog,
            title=title,
        )
        return image.getvalue()

    def match_file_from_png(
        self,
        game: D12BallGame,
        png: bytes,
    ) -> discord.File:
        """One upload of an already-rendered board."""
        return discord.File(
            io.BytesIO(png),
            filename=board_image_filename(game.game_number),
        )

    async def build_match_file(self, game: D12BallGame) -> discord.File:
        """Render the board and wrap it for a single upload."""
        return self.match_file_from_png(
            game, await self.render_match_png(game),
        )

    async def post_field_image(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        """
        The field under the maneuver prompt: what each maneuver would do
        depends on where everybody is standing, and the persistent board
        has usually scrolled up the channel by the time a turn resolves.

        **A message of its own, not a second attachment on the prompt.**
        Discord lays two images on one message out side by side, which
        would show a field the width of the whole board at half the
        width of a phone. It also keeps the prompt's own full-image link
        pointing at the cards -- `build_full_image_button` reads the
        first attachment, and "View full image" under a hand means the
        hand.

        It is public now rather than a private send to each coach, which
        is one upload where there used to be one apiece. Both are the
        webhook route, so neither competes with the board for the
        channel's edit bucket -- see "Discord's rate limits".

        A failure here loses the field and nothing else: the prompt is
        already up and clickable, which is worth more than the picture
        under it.
        """
        try:
            message = await interaction.followup.send(
                file=await self.build_field_file(game),
                wait=True,
            )
        except (discord.HTTPException, aiohttp.ClientError):
            return

        # A field is the whole width of the board in a strip a fifth as
        # tall, so inline it is smaller than anything else the bot
        # sends -- the names on the meeples need the full-size upload
        # more than the cards do.
        await add_full_image_button(message)

    async def build_field_file(self, game: D12BallGame) -> discord.File:
        """
        The field on its own -- where everybody is standing and where
        the ball is, with nothing else on it -- which is what a coach
        gets under their maneuver cards. See
        `D12Ball.begin_maneuver_action_selection`.

        Unlike the maneuver hand, this cannot be drawn once at startup:
        it is the position, so it is different on every pick. Bytes are
        not kept for the same reason -- the render is uploaded once and
        is stale immediately -- so it goes straight into a File rather
        than through the `render_match_png` / `match_file_from_png`
        pair, which exists for the board that is put in two places at
        once.
        """
        image = await asyncio.to_thread(
            render_field_image,
            self.engine.load_match_state(game),
            self.player_catalog,
        )
        return discord.File(image, filename=FIELD_IMAGE_FILENAME)

    async def post_new_play_board(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        message: str,
    ) -> None:
        """
        The board at the top of a new play -- a kickoff, halftime, or
        the restart after a goal, an own goal, a missed shot or a ball
        out of bounds -- posted as its own message and pinned.

        These are the boards worth coming back to, which is why they
        are the ones pinned; see pin_board_message for what happens at
        the pin cap. Everything else a turn puts out still goes to the
        persistent board message only.

        The persistent message is brought in line with the same render
        rather than a second one, exactly as announce_board_update
        does.
        """
        png = await self.render_match_png(game)
        snapshot = await interaction.followup.send(
            message,
            file=self.match_file_from_png(game, png),
            wait=True,
        )
        await add_full_image_button(snapshot)
        await self.refresh_match_image(interaction, game, png=png)
        await pin_board_message(snapshot)

    async def announce_board_update(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        message: str,
    ) -> None:
        """
        A message a coach cannot read without seeing the board, with a
        fresh snapshot attached directly to it, in addition to keeping
        the persistent board message in sync.

        Two kinds of message qualify. A manual board correction
        (/coach, /ref, /meeple move, /ball move/possession/speed,
        /score, /time) is confirmed by showing what it did. A loose
        ball is announced by showing where it is: the ball is lying in
        a space nothing else in the channel names, and the question
        that follows -- who to send after it -- is a question about how
        far away everybody is.

        Both show the same board, so it is rendered once and uploaded
        twice.
        """
        png = await self.render_match_png(game)
        snapshot = await interaction.followup.send(
            message,
            file=self.match_file_from_png(game, png),
            wait=True,
        )
        await add_full_image_button(snapshot)
        await self.refresh_match_image(interaction, game, png=png)

    async def fetch_game_channel(
        self,
        game: D12BallGame,
    ) -> discord.TextChannel:
        """
        The channel a game is played in. Split out from archiving so
        that a `discord.NotFound` raised here means one thing only --
        the channel is gone -- and cannot be confused with a 404 from
        the category or the move that follows it.
        """
        guild = self.bot.get_guild(game.guild_id)
        if guild is None:
            raise ValueError("The server for this game is not available.")

        channel = guild.get_channel(game.channel_id)
        if channel is None:
            channel = await guild.fetch_channel(game.channel_id)

        if not isinstance(channel, discord.TextChannel):
            raise ValueError("The channel for this game is not a text channel.")

        return channel

    async def move_channel_to_archive(
        self,
        channel: discord.TextChannel,
    ) -> None:
        if (
            channel.category is not None
            and channel.category.name.casefold()
            == PBD_ARCHIVE_CATEGORY_NAME.casefold()
        ):
            return

        archive_category = await get_or_create_category(
            channel.guild,
            PBD_ARCHIVE_CATEGORY_NAME,
            "Create the category for finished PBD games.",
        )
        await channel.edit(
            category=archive_category,
            reason="Move a finished D12 Ball game to the PBD archive.",
        )

    async def archive_game_channel(
        self,
        game: D12BallGame,
    ) -> None:
        await self.move_channel_to_archive(await self.fetch_game_channel(game))

    def game_channel_is_archived(self, game: D12BallGame) -> bool:
        """
        Whether this game's channel is already filed away, read out of
        the client's cache so a view can ask it while it is being
        built.

        The same test `move_channel_to_archive` makes before it moves
        anything, which is why an unknown channel answers False: the
        move is idempotent, so a button offered when it need not have
        been costs one no-op, where a button withheld leaves a pair
        with no way to archive.
        """
        channel = self.bot.get_channel(game.channel_id)
        category = getattr(channel, "category", None)
        return bool(
            category is not None
            and category.name.casefold()
            == PBD_ARCHIVE_CATEGORY_NAME.casefold()
        )

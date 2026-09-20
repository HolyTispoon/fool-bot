"""
A turn as the coach drives it -- picking the handler, picking the
action, ceding, answering a challenge, and the public maneuver prompt
both sides pick off. See "The maneuver prompt" in docs/design/maneuver-prompt.md.
"""

import discord
from math import ceil
from typing import Optional, TYPE_CHECKING

from d12ball import tutorial
from d12ball.components import (
    MANEUVER_TIER_BASIC,
    MatchState,
)
from d12ball.game import (
    D12BallGame,
    team_display_name,
)
from gamesaves.d12ball.storage import save_games
from cogs.d12ball_helpers import (
    add_full_image_button_to_response,
    challenger_prompt_ask,
    format_player_with_team,
    player_with_role,
    refresh_player_names,
    send_new_prompt,
)

from cogs.d12ball_views.base import SafeView

if TYPE_CHECKING:
    from cogs.d12ball import D12Ball


class BallHandlerSelectionView(SafeView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id
        game, match = self.load_match()
        if game is None:
            return

        # Not eligible_ball_handlers: a ball carrier narrows this to
        # one button, which is the rule showing up as a menu with no
        # choice in it. send_turn_prompt normally skips the view
        # entirely in that case; this is the restore path.
        #
        # Through the engine, so a Telekinetic standing on the ball
        # gets a button of their own -- see "Mind Pull (Telekinetic)"
        # in the living rules.
        for player_id in cog.engine.turn_handler_candidates(game, match):
            player = self.cog.engine.get_player_definition(player_id)
            button = discord.ui.Button(
                label=player_with_role(player)[:80],
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:ball_handler:{game_id}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                selected_player_id: str = player_id,
            ) -> None:
                await self.select_handler(
                    interaction,
                    selected_player_id,
                )

            button.callback = callback
            self.add_item(button)

    async def select_handler(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if match.active_player_id is not None:
            await interaction.response.edit_message(
                content=self.cog.engine.build_turn_prompt(game, match),
                view=PlayerActionView(self.cog, self.game_id),
            )
            await interaction.followup.send(
                "A player has already been selected.",
                ephemeral=True,
            )
            return

        if not self.may_act_for_possession(interaction, game, match):
            await interaction.response.send_message(
                "Only the player whose team has possession can "
                "choose the ball handler.",
                ephemeral=True,
            )
            return

        try:
            match.select_ball_handler(
                player_id,
                self.cog.engine.slip_in_candidates(game, match),
            )
        except ValueError as error:
            await interaction.response.send_message(
                str(error),
                ephemeral=True,
            )
            return

        self.cog.persist(game, match)
        await interaction.response.edit_message(
            content=self.cog.engine.build_turn_prompt(game, match),
            view=PlayerActionView(self.cog, self.game_id),
        )


class PlayerActionView(SafeView):
    """
    The turn's choice: shoot, maneuver, or call a time out.
    **Shooting is only offered from within shooting range and a time
    out only from outside it**, so a coach never sees both -- see
    `MatchState.can_attempt_score`, `MatchState.may_call_time_out`,
    and `D12Ball.build_turn_prompt`, which says why whichever one is
    missing is missing. Rebuilt from match state on every restart like
    every other persistent view here, so the ball's position always
    decides afresh.
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
        can_shoot = True
        can_time_out = False
        if game is not None and game.match_state is not None:
            match = cog.engine.load_match_state(game)
            can_shoot = match.can_attempt_score()
            can_time_out = match.may_call_time_out()

        actions = [
            (
                "Maneuver",
                "maneuver",
                discord.ButtonStyle.primary,
            ),
        ]
        if can_shoot:
            actions.append(
                (
                    "Shoot to score",
                    "shoot",
                    discord.ButtonStyle.danger,
                ),
            )
        if can_time_out:
            # Grey, and last: it is what a coach does when there is
            # nothing worth playing, and it should never sit beside
            # Maneuver as an equal.
            actions.append(
                (
                    "Time out",
                    "time_out",
                    discord.ButtonStyle.secondary,
                ),
            )

        # A tutorial beat names the one action it wants pressed, and
        # the rest are built **disabled** rather than left out: a coach
        # should see that shooting and the time out exist and read in
        # the lesson why neither is theirs yet. See d12ball/tutorial.py.
        allowed = tutorial.allowed_actions(
            self.cog.tutorial_beat(game) if game is not None else None
        )

        for label, action, style in actions:
            button = discord.ui.Button(
                label=label,
                style=style,
                custom_id=f"d12ball:action:{game_id}:{action}",
                disabled=allowed is not None and action not in allowed,
            )

            async def callback(
                interaction: discord.Interaction,
                selected_action: str = action,
                action_label: str = label,
            ) -> None:
                await self.choose_action(
                    interaction,
                    selected_action,
                    action_label,
                )

            button.callback = callback
            self.add_item(button)

    async def choose_action(
        self,
        interaction: discord.Interaction,
        action: str,
        action_label: str,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if match.active_player_id is None:
            await interaction.response.send_message(
                "Choose a player to handle the ball first.",
                ephemeral=True,
            )
            return

        if not self.may_act_for_possession(interaction, game, match):
            await interaction.response.send_message(
                "Only the player whose team has possession can "
                "choose this action.",
                ephemeral=True,
            )
            return

        # The button was built disabled, so this is a click on a prompt
        # from an earlier beat still sitting in the channel -- the same
        # stale-view guard the shot and the time out keep.
        allowed = tutorial.allowed_actions(self.cog.tutorial_beat(game))
        if allowed is not None and action not in allowed:
            await interaction.response.send_message(
                "The tutorial is on this step's action. Use the prompt "
                "at the bottom of the channel.",
                ephemeral=True,
            )
            return

        if action == "shoot":
            await self.begin_shot_action(
                interaction, game, match, action_label,
            )
            return

        if action == "time_out":
            await self.begin_time_out_action(interaction, game, match)
            return

        await self.begin_maneuver_action(interaction, game, match)

    async def begin_shot_action(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        action_label: str,
    ) -> None:
        """Take the shot on, and say who is taking it."""
        # The button is only built when the shot is legal, so this is a
        # click on a prompt the ball has since moved out from under --
        # the same stale-view guard the other choices keep.
        if not match.can_attempt_score():
            await interaction.response.send_message(
                "The ball is out of shooting range.",
                ephemeral=True,
            )
            return

        self.cog.record_turn_action(match, "shoot")
        match.pending_action = "shoot"
        self.cog.persist(game, match)

        refresh_player_names(game, interaction.guild)
        handler = self.cog.engine.get_player_definition(match.active_player_id)
        offense_number = self.cog.engine.possession_player_number(game, match)
        offense_display = format_player_with_team(
            game, offense_number, self.cog.team_emojis,
        )

        await interaction.response.edit_message(
            content=(
                f"{offense_display} has chosen to {action_label} with "
                f"{self.cog.player_label(match, handler)}."
            ),
            view=None,
        )
        await self.cog.begin_score_attempt(interaction, game, match)

    async def begin_time_out_action(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Put what a time out costs in front of the coach before anything
        happens. It spends a minute and the side's one time out for the
        half, and it sits one button along from Maneuver, so it is
        confirmed rather than taken -- see TimeOutConfirmView.
        """
        # Same stale-view guard the shot keeps, and the same three
        # reasons the button would not have been built: the ball has
        # moved into shooting range since, the side has spent its time
        # out, or last possession has been declared under it.
        if not match.may_call_time_out():
            if match.can_attempt_score():
                refusal = (
                    "The ball is in shooting range now, so there is "
                    "nothing to stop play for."
                )
            elif match.scoreboard.last_possession:
                refusal = (
                    "Last possession has been declared, so there are "
                    "no more time outs this period."
                )
            else:
                refusal = "Your side has already taken its time out this half."
            await interaction.response.send_message(refusal, ephemeral=True)
            return

        await interaction.response.edit_message(
            content=self.cog.engine.time_out_confirmation(game, match),
            view=TimeOutConfirmView(
                self.cog, self.game_id, interaction.message.content,
            ),
        )

    async def begin_maneuver_action(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Start a maneuver, which reaches the offense's pick by one of
        three routes: nobody to challenge at all, a challenger settled
        without asking, or the defending coach's own choice.
        """
        self.cog.record_turn_action(match, "maneuver")

        # Nobody left to challenge with at all -- a side with a meeple
        # anywhere on the board has a candidate, so this needs an empty
        # field: the maneuver succeeds automatically and the offense
        # still picks which one
        # (docs/living-rules.md, "Maneuvers"). There is no challenger to
        # choose and nothing for the defense to do, so this skips
        # straight to the offense's pick. A defense that is offered a
        # challenge and sends nobody lands in the same place, from
        # ManeuverChallengeView.decline.
        if not match.eligible_challengers():
            match.begin_uncontested_maneuver()
            self.cog.persist(game, match)

            await interaction.response.defer()
            await self.cog.drop_turn_prompt(interaction, game)
            await self.cog.announce_uncontested_maneuver(
                interaction, game, match,
            )
            return

        match.pending_action = "maneuver"
        defender_number = self.cog.engine.defending_player_number(game, match)

        # One defender already sharing the ball's exact space leaves
        # nothing to choose -- they pay nothing to challenge, so the
        # challenge is neither theirs to decline nor a pick between
        # players, and it goes ahead the same way it does when the AI
        # is the one picking. Two of them is a pick, and the defending
        # coach makes it (the author, 2026-08-17): they are the whole
        # of the choice, since nobody may be walked in past them. See
        # MatchState.challenge_candidates.
        on_ball_space = match.automatic_challengers()
        if len(on_ball_space) == 1 or (
            game.is_solo_game and defender_number == 2
        ):
            challenger_id = (
                on_ball_space[0]
                if len(on_ball_space) == 1
                else self.cog.engine.get_ai_strategy(game).choose_challenger(match)
            )

            # This prompt goes rather than being edited down to who
            # chose what: the challenge image posted a moment from now
            # names the handler, the challenger and everything about
            # the matchup. See D12Ball.drop_turn_prompt.
            await interaction.response.defer()
            await self.cog.drop_turn_prompt(interaction, game)
            await self.cog.auto_resolve_challenger(
                interaction, game, match, challenger_id,
            )
            return

        self.cog.persist(game, match)

        await self.send_challenger_prompt(
            interaction, game, match, defender_number,
        )

    async def send_challenger_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        defender_number: int,
    ) -> None:
        """
        Ask the defending coach who challenges, when the answer is
        genuinely theirs to give.
        """
        refresh_player_names(game, interaction.guild)
        handler = self.cog.engine.get_player_definition(match.active_player_id)
        defender_mention = format_player_with_team(
            game,
            defender_number,
            self.cog.team_emojis,
            mention=True,
        )

        await interaction.response.defer()
        await self.cog.drop_turn_prompt(interaction, game)

        # The handler is named here, unlike in the automatic case:
        # the defense is being asked to choose a challenger
        # before the challenge image exists, so this is the only place
        # they can read who they would be up against.
        # Two defenders on the ball are the whole of the choice and
        # neither of them can be kept back, so the prompt must not
        # offer what the view does not build -- see
        # challenger_prompt_ask, which the AI's own turn asks as well.
        ask = challenger_prompt_ask(match)
        handler_team = match.team_for_player(handler.player_id)
        challenge_view = ManeuverChallengeView(self.cog, self.game_id)
        challenge_message = await send_new_prompt(
            interaction,
            f"{self.cog.player_label(match, handler)} will "
            f"maneuver for {team_display_name(handler_team)}.\n\n"
            f"{defender_mention}, {ask}",
            view=challenge_view,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
        game.turn_message_id = challenge_message.id
        save_games(self.cog.games)


class TimeOutConfirmView(SafeView):
    """
    "Are you sure?" for the one turn action that buys something
    instead of playing the ball -- see `D12Ball.begin_time_out`. Every
    other choice a coach makes can be argued with afterwards; this one
    spends a minute and the side's one time out for the half, and it
    sits one button along from Maneuver.

    **It replaces the turn prompt in place rather than posting a
    second message**, so Back is genuinely a way out (it puts the
    prompt back, word for word, which is why `prompt` is carried
    rather than rebuilt -- `build_turn_prompt` can no longer tell
    whether the handler was carrying the ball) and the confirmed click
    can drop the prompt the ordinary way. It is an
    `interaction.response.edit_message` at both ends, so unlike a board
    write it costs nothing out of the channel's edit bucket.

    A restart between opening this and answering it leaves the buttons
    dead -- a restart re-arms the message with `PlayerActionView`, this
    view being nothing the match records. The coach is one `/d12ball
    resume` from the turn prompt they started at, and nothing has
    happened to the match in the meantime.
    """

    def __init__(self, cog: "D12Ball", game_id: str, prompt: str):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id
        self.prompt = prompt

        confirm = discord.ui.Button(
            label="Take the time out",
            style=discord.ButtonStyle.danger,
            custom_id=f"d12ball:time_out_confirm:{game_id}",
        )
        confirm.callback = self.confirm
        self.add_item(confirm)

        back = discord.ui.Button(
            label="Back",
            style=discord.ButtonStyle.secondary,
            custom_id=f"d12ball:time_out_cancel:{game_id}",
        )
        back.callback = self.back
        self.add_item(back)

    async def claim(
        self,
        interaction: discord.Interaction,
    ) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        """The game and match, if this click may act on them."""
        game, match = await self.require_match(interaction)
        if game is None:
            return None, None

        if not self.may_act_for_possession(interaction, game, match):
            await interaction.response.send_message(
                "Only the team with the ball can call a time out.",
                ephemeral=True,
            )
            return None, None
        return game, match

    async def back(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        await interaction.response.edit_message(
            content=self.prompt,
            view=PlayerActionView(self.cog, self.game_id),
        )

    async def confirm(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        # Asked again rather than trusted from the click that opened
        # this: the prompt underneath is a live message and the match
        # can have moved on under it.
        if not match.may_call_time_out():
            await interaction.response.edit_message(
                content=self.prompt,
                view=PlayerActionView(self.cog, self.game_id),
            )
            await interaction.followup.send(
                "A time out can no longer be called from here.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        await self.cog.begin_time_out(interaction, game, match)


class ManeuverChallengeView(SafeView):
    """
    Who the defense puts up against the maneuver -- or nobody. The
    candidates are `MatchState.challenge_candidates`: the nearest
    defender either side of the ball, from any zone (see "Sending a
    player" in docs/living-rules.md), or the defenders already standing
    on the ball wherever there are any. Walking in costs 1 token per
    space, and the author's 2026-08-12 ruling is that a defense may
    refuse to pay it and let the maneuver through; a defender on the
    ball pays nothing, so that challenge is not theirs to refuse and no
    Send nobody button is built.

    **One defender on the ball never reaches this prompt** -- there is
    nothing to choose. Two or more do, since which of them challenges
    is the coach's call (the author, 2026-08-17) and a challenge is
    settled on defensive skill.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        game, match = self.load_match()
        if game is None:
            return

        for player_id in match.challenge_candidates():
            player = self.cog.engine.get_player_definition(player_id)
            distance = match.distance_to_ball(player_id)
            button = discord.ui.Button(
                label=f"{player_with_role(player)} ({distance})"[:80],
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:challenger:{game_id}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                selected_player_id: str = player_id,
            ) -> None:
                await self.select_challenger(
                    interaction,
                    selected_player_id,
                )

            button.callback = callback
            self.add_item(button)

        # Asked rather than assumed: this view is normally only built
        # where the choice is real, but a restart can re-attach it to a
        # prompt saved with a defender standing on the ball -- and that
        # challenge is not the defense's to refuse.
        if match.may_decline_challenge():
            decline = discord.ui.Button(
                label="Send nobody",
                style=discord.ButtonStyle.secondary,
                custom_id=f"d12ball:challenge_decline:{game_id}",
                row=4,
                # Railed during the tutorial's beat 3: the coach has
                # nobody standing near the ball there, and letting
                # Dinky's maneuver through unchallenged would leave
                # nothing for the lesson's Pressure to defend against.
                disabled=cog.tutorial_railed_option(
                    cog.games.get(game_id),
                    "challenge_decline",
                    ("never",),
                ) == "never",
            )
            decline.callback = self.decline
            self.add_item(decline)

    async def claim(
        self,
        interaction: discord.Interaction,
    ) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        """
        The game and match if this click may still settle the
        challenge, or (None, None) after replying with why it may not.
        Both answers come through here, because either one closes the
        question: a challenger walks in, or the defense sends nobody
        and the maneuver goes unchallenged.
        """
        game, match = await self.require_match(interaction)
        if game is None:
            return None, None

        if match.challenger_id is not None or match.maneuver_uncontested:
            await interaction.response.edit_message(
                content=self.cog.engine.build_turn_prompt(game, match),
                view=PlayerActionView(self.cog, self.game_id),
            )
            await interaction.followup.send(
                "A defender has already been chosen."
                if match.challenger_id is not None
                else "This maneuver has already gone unchallenged.",
                ephemeral=True,
            )
            return None, None

        if not self.may_act_for_defense(interaction, game, match):
            await interaction.response.send_message(
                "Only the player whose team is defending can make "
                "this choice.",
                ephemeral=True,
            )
            return None, None

        return game, match

    async def select_challenger(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        try:
            distance = match.choose_challenger(player_id)
        except ValueError as error:
            await interaction.response.send_message(
                str(error),
                ephemeral=True,
            )
            return

        # Built before the save: a walk-in's tokens can cross the
        # Exhausted threshold, and this description is what tests it.
        walk_in_text = self.cog.describe_challenger_walk_in(
            game,
            match,
            player_id,
            distance,
        )

        self.cog.persist(game, match)

        # The prompt goes rather than being edited down to "has chosen
        # their challenger" -- the challenge image below says who was
        # picked, and a good deal more. See D12Ball.drop_turn_prompt.
        await interaction.response.defer()
        await self.cog.drop_turn_prompt(interaction, game)
        await self.cog.announce_maneuver_challenge(
            interaction,
            match,
            player_id,
            walk_in_text,
        )

        await self.cog.refresh_match_image(interaction, game)
        await self.cog.begin_maneuver_action_selection(
            interaction,
            game,
            match,
        )

    async def decline(self, interaction: discord.Interaction) -> None:
        """
        Send nobody: the maneuver goes unchallenged, exactly as it does
        when the defense has nobody to send at all. Nothing moves
        and nobody is charged, so there is no board to refresh -- the
        one thing a challenge would have cost is the walk-in this
        refuses to pay.
        """
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        try:
            match.begin_uncontested_maneuver()
        except ValueError as error:
            await interaction.response.send_message(
                str(error),
                ephemeral=True,
            )
            return

        self.cog.persist(game, match)

        await interaction.response.defer()
        await self.cog.drop_turn_prompt(interaction, game)
        await self.cog.announce_uncontested_maneuver(
            interaction, game, match,
        )


# Discord's own component limits: five rows to a message, five buttons
# to a row.
MAX_BUTTON_ROWS = 5
MAX_BUTTONS_PER_ROW = 5


def even_button_rows(
    buttons: list[discord.ui.Button],
) -> list[list[discord.ui.Button]]:
    """
    Split one side's maneuver buttons into as few rows as Discord
    allows, and then **evenly** across them.

    Six gambits do not fit a row, and chunking at the limit
    would lay them out five and one -- which reads as a row plus an
    afterthought rather than as one hand. Two rows of three is the same
    number of rows and says what it is.
    """
    if not buttons:
        return []
    rows = ceil(len(buttons) / MAX_BUTTONS_PER_ROW)
    per_row = ceil(len(buttons) / rows)
    return [
        buttons[start:start + per_row]
        for start in range(0, len(buttons), per_row)
    ]


class ManeuverActionPromptView(SafeView):
    """
    The maneuver pick, on **one public message carrying both sides'
    buttons**.

    It used to be two steps: a public prompt with a single "Choose Your
    Maneuver" button that opened an ephemeral menu of the clicking
    coach's own cards. The ephemeral menu was never about privacy of
    the *cards* -- the twelve of them and the defeat cycle are public
    information either coach may ask for at any time. What has to stay
    hidden is the **pick**, and that is hidden by the reply to the
    click being ephemeral, not by the menu being private. Discord tells
    nobody else who pressed what, so a coach reading this message
    cannot tell whether the other side has clicked, and the message is
    never edited to say (see `D12Ball.close_maneuver_prompt`).

    So the extra click bought nothing but the round trip. It existed
    because an ephemeral message must answer *that coach's own*
    interaction, and only one of the two coaches is ever holding a live
    interaction when a maneuver begins -- whoever picked Maneuver, or
    picked the challenger. Putting the buttons on the message removes
    the need for either coach to hold one.

    Two things follow, and both are improvements:

    - **A restart re-attaches this like any other view.** It is on a
      real message recorded in `turn_message_id`, so `on_ready` handles
      it through `pending_turn_view` and the message-agnostic
      `add_view` registration the ephemeral menu needed is gone. (The
      shootout's two menus are still ephemeral and still need it -- see
      `D12Ball.restore_shootout_menus`.)
    - **The uploads halve.** One public hand image and one public field
      strip, against a hand and a field to each of two coaches.

    **Every side on the prompt keeps its buttons for the whole
    maneuver**, picked or not. The message is deliberately never
    edited, so the buttons a restored view dispatches have to match the
    buttons sitting on the message; taking a picked side's row away
    would leave those clicks answered by nothing. `pick` refuses the
    second click instead. Which sides are on it at all is
    `RulesEngine.maneuver_pick_sides`.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        timeout: Optional[float] = None,
    ):
        super().__init__(timeout=timeout)

        self.cog = cog
        self.game_id = game_id

        game, match = self.load_match()
        sides = (
            cog.engine.maneuver_pick_sides(game, match)
            if game is not None and match is not None
            else ("offense",)
        )
        self.sides = sides

        rows: list[list[discord.ui.Button]] = []

        for side in sides:
            # **The hand is the engine's answer, not the whole
            # catalog.** A basic game is three cards and an advanced one
            # is six, and an unchallenged maneuver is basic whatever the
            # mode -- see `RulesEngine.maneuver_tiers`. Asking there is
            # what keeps these buttons, the hand image above them and
            # `pick`'s own check from disagreeing about what a coach may
            # play.
            maneuvers = (
                cog.engine.maneuver_hand(game, match, side)
                if game is not None and match is not None
                else cog.maneuver_catalog.for_tier(side, MANEUVER_TIER_BASIC)
            )

            # A tutorial beat rails the coach onto one card, and the
            # others are built **disabled** rather than left out -- the
            # whole point of the lesson is reading what the hand holds.
            # Dinky's side is never on this prompt at all, so this only
            # ever narrows a human's. See d12ball/tutorial.py.
            allowed = (
                tutorial.allowed_maneuvers(cog.tutorial_beat(game), side)
                if game is not None
                else None
            )

            buttons = []
            for maneuver in maneuvers:
                button = discord.ui.Button(
                    label=maneuver.name,
                    # The cards' own two colours, so a coach picks their
                    # row out of a prompt holding both without reading
                    # the labels: offense red, defense green, exactly as
                    # `d12ball/cards.py` and the reference hexagon draw
                    # them.
                    style=(
                        discord.ButtonStyle.danger
                        if side == "offense"
                        else discord.ButtonStyle.success
                    ),
                    custom_id=(
                        f"d12ball:maneuver_pick:{game_id}:{side}:"
                        f"{maneuver.key}"
                    ),
                    disabled=(
                        allowed is not None and maneuver.key not in allowed
                    ),
                )

                async def callback(
                    interaction: discord.Interaction,
                    chosen_side: str = side,
                    chosen_key: str = maneuver.key,
                ) -> None:
                    await self.pick(interaction, chosen_side, chosen_key)

                button.callback = callback
                buttons.append(button)

            rows.extend(even_button_rows(buttons))

        # Its own row where there is one, so a grey button does not read
        # as the tail of a coloured row. Its custom_id carries the game
        # like the picks do but no side: the hexagon is the same picture
        # for both coaches.
        reference = discord.ui.Button(
            label="Maneuver Reference",
            style=discord.ButtonStyle.secondary,
            custom_id=f"d12ball:maneuver_reference:{game_id}",
        )
        reference.callback = self.show_reference
        if len(rows) < MAX_BUTTON_ROWS:
            rows.append([reference])
        else:
            # Only reachable if a side ever grows past what four rows
            # hold. Falling back to the first row with space keeps the
            # reference reachable rather than raising on view build.
            next(row for row in rows if len(row) < MAX_BUTTONS_PER_ROW).append(
                reference
            )

        for index, row in enumerate(rows):
            for button in row:
                button.row = index
                self.add_item(button)

        # The full-image link is added after the message is posted (the
        # URL does not exist until then -- see `add_full_image_button`),
        # and discord.py drops a rowless button into the *first* row with
        # space. A side holding gambits has a hand of two rows of
        # three, so that first gap is between its basic cards and
        # its gambits. Point it at the reference's row instead, so it lands
        # after every maneuver button. None where the fallback above
        # packed the reference onto a maneuver row -- that row may be
        # full, and the default placement is fine there anyway.
        self.full_image_row = (
            reference.row if reference in rows[-1] else None
        )

    async def show_reference(self, interaction: discord.Interaction) -> None:
        """
        The defeat cycle, ephemeral to the coach who asked.

        Ephemeral for the pick's own reason rather than its own:
        answering in the channel would tell the other side that this
        coach is still choosing. The image is public information either
        coach may ask for at any time, so nothing is hidden by it --
        only the timing.
        """
        await interaction.response.send_message(
            file=self.cog.build_maneuver_reference_file(
                self.cog.reference_tier(self.cog.games.get(self.game_id))
            ),
            ephemeral=True,
        )
        # The hexagon's labels are small print at the size Discord shows
        # an image inline, the same reason the hand carries a link. No
        # view goes with it, so there are no buttons for the edit to
        # drop. Webhook route -- see "Discord's rate limits".
        await add_full_image_button_to_response(interaction)

    def pick_refusal(
        self,
        game: D12BallGame,
        match: MatchState,
        side: str,
        maneuver_key: str,
        interaction: discord.Interaction,
    ) -> Optional[str]:
        """
        Why this click cannot be taken as a pick, or None.

        **Authorization is answered first**, and that ordering is a
        rule rather than a habit: the other coach's row is sitting on
        the same message, so replying "that side has already chosen"
        to a click on it would say whether they had.

        It takes the interaction rather than the clicker's id because a
        game helper may pick for either side and the permission is on
        the member -- see "Who may act on a game" in docs/design/permissions.md.
        """
        if side == "offense":
            authorized = self.may_act_for_possession(
                interaction, game, match,
            )
            already_chosen = match.offense_maneuver is not None
        else:
            authorized = self.may_act_for_defense(
                interaction, game, match,
            )
            already_chosen = match.defense_maneuver is not None

        if not authorized:
            return "Only the player on that side can choose this maneuver."

        if already_chosen:
            return "You have already chosen your maneuver."

        # An older prompt can still be sitting in the channel, so the
        # rail is re-read here rather than trusted from the build --
        # exactly as the distances are in HighPassChoiceView.choose.
        allowed = tutorial.allowed_maneuvers(
            self.cog.tutorial_beat(game), side,
        )
        if allowed is not None and maneuver_key not in allowed:
            return (
                "This step of the tutorial wants "
                f"**{self.cog.engine.maneuver_name(allowed[0])}**. Use the "
                "prompt at the bottom of the channel."
            )

        # Same reason as the rail above: a gambit clicked off an
        # older prompt would be a maneuver this turn does not play.
        playable = {
            maneuver.key
            for maneuver in self.cog.engine.maneuver_hand(game, match, side)
        }
        if maneuver_key not in playable:
            return (
                "That maneuver isn't in your hand for this turn. Use the "
                "prompt at the bottom of the channel."
            )

        return None

    async def pick(
        self,
        interaction: discord.Interaction,
        side: str,
        maneuver_key: str,
    ) -> None:
        """
        One coach's pick, answered **ephemerally** -- which is the whole
        of what keeps it secret now that the buttons are public. The
        prompt itself is untouched, so the other coach sees no change of
        any kind.
        """
        game, match = await self.require_match(interaction)
        if game is None:
            return

        refusal = self.pick_refusal(
            game, match, side, maneuver_key, interaction,
        )
        if refusal is not None:
            await interaction.response.send_message(refusal, ephemeral=True)
            return

        if side == "offense":
            match.choose_offense_maneuver(maneuver_key)
        else:
            match.choose_defense_maneuver(maneuver_key)

        self.cog.persist(game, match)

        await interaction.response.send_message(
            "You chose "
            f"**{self.cog.engine.maneuver_name(maneuver_key)}**.",
            ephemeral=True,
        )

        # "Someone has picked, you can't see what" is only worth a
        # message while the other side is still choosing. An
        # uncontested maneuver has nobody else to keep in the dark,
        # and the reveal a moment from now names the pick anyway.
        if not match.maneuver_uncontested:
            side_number = (
                self.cog.engine.possession_player_number(game, match)
                if side == "offense"
                else self.cog.engine.defending_player_number(game, match)
            )
            side_display = format_player_with_team(
                game, side_number, self.cog.team_emojis,
            )
            await send_new_prompt(
                interaction,
                f"{side_display} has picked their maneuver.",
            )

        await self.cog.close_maneuver_prompt(interaction, game, match)

        if match.maneuver_selections_complete:
            await self.cog.resolve_maneuver(interaction, game, match)

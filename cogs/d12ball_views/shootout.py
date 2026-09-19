"""
The extreme shootout: the order, the sudden-death pick, and the
tests. Two of these are ephemeral and so cannot be re-attached to
their message after a restart -- see `restore_shootout_menus`.
"""

import discord
import random
from typing import Optional, TYPE_CHECKING

from d12ball.components import (
    MatchState,
    TeamSide,
)
from d12ball.engine import IgnitedRoll
from d12ball.game import D12BallGame
from cogs.d12ball_helpers import format_team_side_label

from cogs.d12ball_views.base import (
    SafeView,
    contestant_detail,
    render_contest_dice,
)

if TYPE_CHECKING:
    from cogs.d12ball import D12Ball


class ShootoutView(SafeView):
    """
    Shared plumbing for the shootout's public prompts: load the game,
    and work out which side the person clicking coaches.

    Every prompt in the shootout is **one button both coaches share**,
    the way the maneuver prompt is: which menu opens depends only on
    who clicked, so nobody has to find "which button is mine" first.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

    def load(self) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        return self.load_match()

    def owes(self, match: MatchState, side: TeamSide) -> bool:
        """Whether this prompt is still waiting on `side`."""
        raise NotImplementedError

    async def claim(
        self,
        interaction: discord.Interaction,
    ) -> Optional[tuple[D12BallGame, MatchState, TeamSide]]:
        """
        Which side the person clicking is answering for.

        **A side that still owes an answer wins**, because in a test
        game one user coaches both and would otherwise never be able
        to answer for the second: the home side is theirs, so the
        visiting order could never be set. The maneuver prompt picks
        its ephemeral menu the same way and for the same reason.
        """
        game, match = self.load()
        if game is None or match is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return None

        if not match.pending_shootout:
            await interaction.response.send_message(
                "This game is not in the extreme shootout.",
                ephemeral=True,
            )
            return None

        # **A coach gets their own side, and only their own**, whether
        # or not they also hold `manage_channels`: a coach who is a
        # helper is pressing this for themselves, like anybody else,
        # and a helper's wider reach is for a game they are not in. It
        # was read the other way round -- a helper got both sides, home
        # first -- which handed a visiting coach with the permission
        # the *home* order to set. See "Who may act on a game" in
        # CLAUDE.md.
        sides = (TeamSide.HOME, TeamSide.VISITING)
        own = [
            side
            for side in sides
            if interaction.user.id
            == self.cog.engine.side_controller_id(game, side)
        ]
        if own:
            theirs = own
        else:
            # Not a coach in the game: a helper acting for one, which
            # the gate puts behind a confirmation. They get both
            # sides, and `owes` below picks whichever still has an
            # order to set. That does show a helper both coaches'
            # picks, which the secrecy of an order otherwise turns on
            # -- it is the price of being able to set one for
            # somebody.
            theirs = [
                side
                for side in sides
                if self.may_act_for(
                    interaction,
                    self.cog.engine.side_controller_id(game, side),
                )
            ]
        if not theirs:
            await interaction.response.send_message(
                "Only a coach in this game can do that.",
                ephemeral=True,
            )
            return None

        for side in theirs:
            if self.owes(match, side):
                return game, match, side

        return game, match, theirs[0]


class ShootoutOrderPromptView(ShootoutView):
    """The public button that opens a coach's own ordering menu."""

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(cog, game_id)

        button = discord.ui.Button(
            label="Set Your Shooting Order",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:shootout_order_prompt:{game_id}",
        )
        button.callback = self.open_menu
        self.add_item(button)

    def owes(self, match: MatchState, side: TeamSide) -> bool:
        return not match.shootout_order_complete(side)

    async def open_menu(self, interaction: discord.Interaction) -> None:
        claimed = await self.claim(interaction)
        if claimed is None:
            return
        game, match, side = claimed

        if match.shootout_order_complete(side):
            # A coach may look at their order but not reorder it, so
            # this shows it rather than reopening the menu.
            await interaction.response.send_message(
                "Your order is set:\n"
                f"{self.cog.shootout_order_text(match, side)}",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            content=self.cog.shootout_order_text(match, side),
            view=ShootoutOrderSelectView(self.cog, self.game_id, side),
            ephemeral=True,
        )


class ShootoutOrderSelectView(SafeView):
    """
    A coach putting their six in order, one click at a time, on an
    ephemeral message -- the other coach must not see it, and
    ephemeral is the only thing Discord offers that hides it. That
    makes this and `ShootoutPickSelectView` the shootout's share of
    the problem the maneuver menu has: no durable message id, so a
    restart re-registers them message-agnostically instead (see
    `D12Ball.restore_shootout_menus`, which is also why `timeout` is
    an argument rather than a constant).

    **The part-built order is on the match, not on this view**, so a
    coach who ordered five and lost the bot comes back to five rather
    than to an empty menu -- see `MatchState.add_to_shootout_order`.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        side: TeamSide,
        timeout: Optional[float] = 600,
    ):
        super().__init__(timeout=timeout)

        self.cog = cog
        self.game_id = game_id
        self.side = TeamSide(side)

        game = cog.games.get(game_id)
        match = (
            cog.engine.load_match_state(game)
            if game is not None and game.match_state is not None
            else None
        )
        remaining = (
            match.shootout_order_remaining(self.side)
            if match is not None
            else []
        )

        for player_id in remaining:
            button = discord.ui.Button(
                label=cog.engine.shootout_button_label(match, player_id),
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:shootout_order:{game_id}:"
                    f"{self.side.value}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_id: str = player_id,
            ) -> None:
                await self.pick(interaction, chosen_id)

            button.callback = callback
            self.add_item(button)

        restart = discord.ui.Button(
            label="Start Over",
            style=discord.ButtonStyle.secondary,
            custom_id=(
                f"d12ball:shootout_order_restart:{game_id}:{self.side.value}"
            ),
            row=1,
        )
        restart.callback = self.restart
        self.add_item(restart)

    async def load(
        self,
        interaction: discord.Interaction,
    ) -> Optional[tuple[D12BallGame, MatchState]]:
        game, match = await self.require_match(interaction)
        if game is None:
            return None

        if not match.pending_shootout or not self.may_act_for(
            interaction, self.cog.engine.side_controller_id(game, self.side),
        ):
            await interaction.response.edit_message(
                content="That order is no longer being asked for.",
                view=None,
            )
            return None

        return game, match

    async def restart(self, interaction: discord.Interaction) -> None:
        loaded = await self.load(interaction)
        if loaded is None:
            return
        game, match = loaded

        if match.shootout_order_complete(self.side):
            await interaction.response.edit_message(
                content=(
                    "Your order is already set, and an order cannot be "
                    "changed once it is."
                ),
                view=None,
            )
            return

        match.clear_shootout_order(self.side)
        self.cog.persist(game, match)

        await interaction.response.edit_message(
            content=self.cog.shootout_order_text(match, self.side),
            view=ShootoutOrderSelectView(self.cog, self.game_id, self.side),
        )

    async def pick(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        loaded = await self.load(interaction)
        if loaded is None:
            return
        game, match = loaded

        try:
            match.add_to_shootout_order(self.side, player_id)
        except ValueError as error:
            # A click on a stale copy of the menu -- a coach who
            # scrolled back, or one restored after a restart.
            await interaction.response.edit_message(
                content=(
                    f"{error}\n\n"
                    f"{self.cog.shootout_order_text(match, self.side)}"
                ),
                view=(
                    None
                    if match.shootout_order_complete(self.side)
                    else ShootoutOrderSelectView(
                        self.cog, self.game_id, self.side,
                    )
                ),
            )
            return

        self.cog.persist(game, match)

        settled = match.shootout_order_complete(self.side)
        await interaction.response.edit_message(
            content=self.cog.shootout_order_text(match, self.side),
            view=(
                None
                if settled
                else ShootoutOrderSelectView(
                    self.cog, self.game_id, self.side,
                )
            ),
        )

        if not settled:
            return

        await interaction.followup.send(
            f"{format_team_side_label(match.setup_for_side(self.side))} "
            "has set their shooting order."
        )

        if match.shootout_orders_complete:
            await self.cog.close_shootout_prompt(interaction, game)
            await self.cog.advance_shootout(interaction, game, match)


class ShootoutPickPromptView(ShootoutView):
    """The public button that opens a sudden-death shooter pick."""

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(cog, game_id)

        button = discord.ui.Button(
            label="Choose Your Shooter",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:shootout_pick_prompt:{game_id}",
        )
        button.callback = self.open_menu
        self.add_item(button)

    def owes(self, match: MatchState, side: TeamSide) -> bool:
        return match.shootout_shooter(side) is None

    async def open_menu(self, interaction: discord.Interaction) -> None:
        claimed = await self.claim(interaction)
        if claimed is None:
            return
        game, match, side = claimed

        if match.shootout_shooter(side) is not None:
            await interaction.response.send_message(
                "You have already chosen your shooter.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            content=(
                "Choose who goes out next. Everyone who has not shot "
                "yet this round is eligible."
            ),
            view=ShootoutPickSelectView(self.cog, self.game_id, side),
            ephemeral=True,
        )


class ShootoutPickSelectView(SafeView):
    """
    The sudden-death shooter pick, ephemeral for the same reason the
    ordering menu is: neither coach may see the other's before the
    reveal.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        side: TeamSide,
        timeout: Optional[float] = 600,
    ):
        super().__init__(timeout=timeout)

        self.cog = cog
        self.game_id = game_id
        self.side = TeamSide(side)

        game = cog.games.get(game_id)
        match = (
            cog.engine.load_match_state(game)
            if game is not None and game.match_state is not None
            else None
        )
        eligible = (
            match.shootout_eligible(self.side) if match is not None else []
        )

        for player_id in eligible:
            button = discord.ui.Button(
                label=cog.engine.shootout_button_label(match, player_id),
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:shootout_pick:{game_id}:"
                    f"{self.side.value}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_id: str = player_id,
            ) -> None:
                await self.pick(interaction, chosen_id)

            button.callback = callback
            self.add_item(button)

    async def pick(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not match.pending_shootout or not self.may_act_for(
            interaction, self.cog.engine.side_controller_id(game, self.side),
        ):
            await interaction.response.edit_message(
                content="That pick is no longer being asked for.",
                view=None,
            )
            return

        if match.shootout_shooter(self.side) is not None:
            await interaction.response.edit_message(
                content="You have already chosen your shooter.",
                view=None,
            )
            return

        try:
            match.set_shootout_shooter(self.side, player_id)
        except ValueError as error:
            await interaction.response.edit_message(
                content=str(error),
                view=None,
            )
            return

        self.cog.persist(game, match)

        player = self.cog.engine.get_player_definition(player_id)
        await interaction.response.edit_message(
            content=(
                "You send out "
                f"{self.cog.player_label(match, player)}."
            ),
            view=None,
        )
        await interaction.followup.send(
            f"{format_team_side_label(match.setup_for_side(self.side))} "
            "has chosen their shooter."
        )

        if match.shootout_shooters_complete:
            await self.cog.close_shootout_prompt(interaction, game)
            await self.cog.advance_shootout(interaction, game, match)


class ShootoutTestView(ShootoutView):
    """
    The roll that settles one shootout skill test. Either coach may
    press it, like every other roll in the game.

    It carries the "look at your order" button as well, because this
    is the message a coach is looking at for most of a shootout: the
    order prompt is deleted once both sides have set theirs, and a
    coach may look at their own order any time they like -- they just
    may not reorder it.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(cog, game_id)

        button = discord.ui.Button(
            label="Roll the skill test",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:shootout_test:{game_id}",
        )
        button.callback = self.roll
        self.add_item(button)

        review = discord.ui.Button(
            label="Your Order",
            style=discord.ButtonStyle.secondary,
            custom_id=f"d12ball:shootout_review:{game_id}",
        )
        review.callback = self.review
        self.add_item(review)

        # Overdrive, for whichever of the two shooters is a Cyborg. A
        # shootout test costs no exhaustion and owes no injury check,
        # but Overdrive is a Cyborg spending their own drain rather
        # than the test charging it -- so it is offered here like
        # anywhere else.
        game, match = self.load_match()
        if game is not None and match is not None:
            self.add_overdrive_buttons(
                game,
                match,
                [
                    match.shootout_shooter(side)
                    for side in (TeamSide.HOME, TeamSide.VISITING)
                ],
            )

    def owes(self, match: MatchState, side: TeamSide) -> bool:
        # Nothing is owed here -- both coaches may look at their own,
        # so whichever side is theirs is the answer.
        return True

    async def review(self, interaction: discord.Interaction) -> None:
        """
        A coach's own order, or -- in sudden death, which has none --
        who they have left to send out this round. Ephemeral, so the
        other coach learns nothing from it.
        """
        claimed = await self.claim(interaction)
        if claimed is None:
            return
        _, match, side = claimed

        if match.shootout_round > 1:
            remaining = [
                self.cog.player_id_label(match, player_id)
                for player_id in match.shootout_eligible(side)
            ]
            await interaction.response.send_message(
                "\n".join(
                    [
                        "Still to go out this round:",
                        *remaining,
                    ]
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            self.cog.shootout_order_text(match, side),
            ephemeral=True,
        )

    def score_shootout_test(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> tuple[list, dict, dict, list[tuple[str, IgnitedRoll]]]:
        """
        Roll both shooters and total them up, as the sides
        `render_contest_dice` draws plus the totals and the players
        behind them.

        Both sides add their **offensive** skill -- a shootout has no
        defender -- and an injured player adds none at all, the same
        withholding the loose ball and the long High Pass make. See
        "Extreme shootout" in docs/living-rules.md.

        **Volatile fires here too**, on each shooter's own die: the
        rules list a shootout test among the rolls it covers. A
        shootout owes no injury check, which the ignite does not
        change -- what a backfire costs here is the goal, not a card.
        Both ignites come back with the rest, in shooting order, for
        the caller to post as dice of their own.
        """
        totals: dict[TeamSide, int] = {}
        players = {}
        dice = []
        ignites: list[tuple[str, IgnitedRoll]] = []

        for side in (TeamSide.HOME, TeamSide.VISITING):
            player = self.cog.engine.get_player_definition(
                match.shootout_shooter(side),
            )
            players[side] = player
            injured = player.player_id in match.injured
            skill = (
                0
                if injured
                else self.cog.player_catalog.effective_profile(player).offense
            )
            roll = random.randint(1, 12)
            ignite = self.cog.engine.ignite(game, player.player_id, roll)
            ignites.append((player.player_id, ignite))
            overdrive = match.overdrive_modifier(player.player_id)
            totals[side] = roll + skill + ignite.modifier + overdrive
            detail = contestant_detail(
                player, "Offensive", skill, injured=injured,
            )
            for line in (
                ignite.detail,
                self.cog.engine.overdrive_detail(match, player.player_id),
            ):
                if line:
                    detail.append(line)
            dice.append(
                (
                    roll,
                    match.setup_for_side(side).team,
                    detail,
                    totals[side],
                    bool(overdrive),
                    [],
                )
            )

        return dice, totals, players, ignites

    def settle_shootout_test(
        self,
        match: MatchState,
        totals: dict,
        players: dict,
    ) -> tuple[Optional[TeamSide], str]:
        """
        Award the goal, if there is one, and word the result.

        **A shootout skill test is not re-rolled.** A tie scores for
        nobody and the shootout moves on, which is the one place the
        game settles a tied skill test by leaving it tied.
        """
        home_total = totals[TeamSide.HOME]
        visiting_total = totals[TeamSide.VISITING]

        if home_total == visiting_total:
            return None, (
                f"**A tie, {home_total}-{visiting_total}.** Neither "
                "side scores."
            )

        winner = (
            TeamSide.HOME
            if home_total > visiting_total
            else TeamSide.VISITING
        )
        scorer = players[winner]
        match.award_shootout_goal(winner, scorer.player_id)
        return winner, (
            "## "
            f"{self.cog.player_label(match, scorer)} "
            "scores!"
        )

    async def roll(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not match.pending_shootout or not match.shootout_shooters_complete:
            await interaction.response.send_message(
                "That skill test has already been rolled.",
                ephemeral=True,
            )
            return

        if not self.may_act_in_game(interaction, game):
            await interaction.response.send_message(
                "Only a player in this game can roll the skill test.",
                ephemeral=True,
            )
            return

        # Deferred before the dice are rendered, for the reason spelled
        # out in SkillTestView.roll.
        await interaction.response.defer()

        dice, totals, players, ignites = self.score_shootout_test(game, match)
        match.consume_overdrive()
        dice_file = await render_contest_dice(
            dice, filename="shootout_dice.png",
        )
        winner, outcome = self.settle_shootout_test(match, totals, players)

        # The goal and the retirement go out in one save, so a restart
        # between this roll and what follows it can never re-roll a
        # test that has already been paid for -- see
        # finish_shootout_test.
        match.finish_shootout_test()
        self.cog.persist(game, match)

        # Result under the dice, not above them, for the reason
        # SkillTestView.roll gives: attachments render below content.
        await interaction.edit_original_response(
            content=None,
            attachments=[dice_file],
            view=None,
        )
        # Between the dice and the result, as at every other roll site.
        await self.cog.post_volatile_ignition(interaction, match, *ignites)
        await interaction.followup.send(
            f"{outcome}\n"
            f"Extreme shootout: {self.cog.engine.shootout_running_score(match)}"
        )
        if winner is not None:
            await self.cog.refresh_match_image(interaction, game)

        # A shootout test owes no injury checks (2026-08-15). It costs
        # no exhaustion either -- it is not one of the ways to gain a
        # token -- so an Exhausted shooter carries that into the
        # shootout and out the other side unchanged. The round goes
        # straight on to the next test, which is what the injury
        # queue's continuation did once the queue drained.
        await self.cog.continue_shootout(interaction, game, match)

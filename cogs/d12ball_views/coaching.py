"""
The Coaching Choice: one flow, five occasions, four actions. See "The
Coaching Choice" in docs/design/coaching-choice.md for what varies between them, all of
which is on `CoachingOccasion` rather than in these views.
"""

import discord
from typing import Optional, TYPE_CHECKING

from d12ball.components import (
    MatchState,
    TeamSide,
    Zone,
)
from d12ball.game import (
    D12BallGame,
    Formation,
    Team,
)
from cogs.d12ball_helpers import (
    destination_display_name,
    format_team_side_label,
    get_team_emoji,
    space_label,
)

from cogs.d12ball_views.base import SafeView

if TYPE_CHECKING:
    from cogs.d12ball import D12Ball


class CoachingView(SafeView):
    """
    Shared plumbing for the Coaching Choice flow -- the four actions a
    coach may take at setup, at a new play's window and at halftime,
    which are the same four every time; the window between full time
    and the shootout offers the substitution alone. See "Coaching
    Choice" in docs/living-rules.md.

    **The whole flow lives on one message.** Every step edits it
    through `interaction.response.edit_message`, and nothing in the
    flow ever sends another. Two reasons:

    - It used to be a message per step, and a coach making two
      substitutions and a rearrangement put eight of them into the
      channel plus a board refresh apiece. See "Discord's rate limits"
      in docs/design/rate-limits.md: the fix for that is always fewer requests.
    - Only the newest message could be restored after a restart, but
      every older one kept a live view. A coach could scroll up and
      click a menu from three steps ago, and it would act on the
      current state.

    `interaction.response.edit_message` is the interaction-callback
    route, so unlike `channel.get_partial_message().edit()` it does not
    compete for the five-in-five bucket the board refresh spends.
    Passing no `attachments` leaves the image alone, so only a step
    that actually moved something re-uploads it.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

    def load(self) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        return self.load_match()

    def side(self, match: MatchState) -> TeamSide:
        return TeamSide(match.pending_coaching_side)

    async def claim(
        self,
        interaction: discord.Interaction,
    ) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        """
        The game and match if this click is allowed to act on the open
        window, or (None, None) after replying with why it isn't.
        """
        game, match = self.load()
        if game is None or match is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return None, None
        if match.pending_coaching_side is None:
            await interaction.response.send_message(
                "That Coaching Choice has already closed.",
                ephemeral=True,
            )
            return None, None
        if not self.may_act_for(
            interaction,
            self.cog.engine.side_controller_id(game, self.side(match)),
        ):
            await interaction.response.send_message(
                "Only that team's coach can choose this.",
                ephemeral=True,
            )
            return None, None
        return game, match

    async def show(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        view: "CoachingView",
        note: str = "",
        moved: bool = False,
    ) -> None:
        """
        Put `view` up on the coaching message, with `note` under the
        heading. `moved` re-renders the half-field image; without it
        the attachment already there is left alone, which is most
        steps -- opening a submenu changes nothing on the board.
        """
        payload = {
            "content": self.cog.engine.coaching_prompt(
                game, match, self.side(match), note,
            ),
            "view": view,
        }
        if moved:
            payload["attachments"] = [
                await self.cog.coaching_file(game, match, self.side(match))
            ]
        await interaction.response.edit_message(**payload)

    async def back_to_hub(
        self,
        interaction: discord.Interaction,
        note: str = "",
        moved: bool = False,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return
        await self.show(
            interaction,
            game,
            match,
            CoachingHubView(self.cog, self.game_id),
            note=note,
            moved=moved,
        )

    def add_back_button(self, row: Optional[int] = None) -> None:
        # Named for the view it sits on: a custom_id has to be unique
        # within its message, and every one of these steps puts its
        # Back button on the same message as the last.
        button = discord.ui.Button(
            label="Back",
            style=discord.ButtonStyle.secondary,
            custom_id=(
                f"d12ball:coach_back:{self.game_id}:"
                f"{type(self).__name__}"
            ),
            row=row,
        )

        async def callback(interaction: discord.Interaction) -> None:
            await self.back_to_hub(interaction)

        button.callback = callback
        self.add_item(button)

    def player_button_label(
        self,
        match: MatchState,
        player_id: str,
        with_space: bool = False,
    ) -> str:
        """
        A fielded player on a button: who they are, and where they are.
        Both matter to every choice in this flow and neither is on the
        button otherwise.

        Not `D12Ball.player_label`, which is the name a *message* calls
        a player by: this one carries the position instead of the team
        emoji, since every card on a coaching button is that coach's
        own side, and it is cut to Discord's 80-character button label.
        """
        setup = match.setup_for_side(self.side(match))
        zone = setup.assigned_zone(player_id)
        where = destination_display_name(zone.value, match.board.layout.board_size)
        if with_space:
            position = match.board.meeple_position(player_id)
            where = space_label(*position) if position else where
        return f"{self.cog.engine.format_roster_player(player_id)} - {where}"[:80]


class CoachingOfferView(CoachingView):
    """
    Declare-or-pass, for the side a new play has just handed the window
    to. Only a new play asks: setup and halftime are given rather than
    declared, so both open straight onto the hub.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(cog, game_id)

        declare = discord.ui.Button(
            label="Coach",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:coach_declare:{game_id}",
        )
        declare.callback = self.declare
        self.add_item(declare)

        # Passing is always on offer -- nothing forces a declaration,
        # an injured player included.
        decline = discord.ui.Button(
            label="Pass",
            style=discord.ButtonStyle.secondary,
            custom_id=f"d12ball:coach_pass:{game_id}",
        )
        decline.callback = self.decline
        self.add_item(decline)

    async def declare(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        match.declare_coaching()
        self.cog.persist(game, match)

        # No attachments: the offer this replaces already carried the
        # image, and taking the window up moves nobody.
        await self.show(
            interaction,
            game,
            match,
            CoachingHubView(self.cog, self.game_id),
        )

    async def decline(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        setup = match.setup_for_side(self.side(match))
        await interaction.response.edit_message(
            content=(
                f"# Coaching Choice\n"
                f"**{get_team_emoji(self.cog.team_emojis, setup.team)} "
                f"{interaction.user.display_name} passed.**"
            ),
            view=None,
        )
        await self.cog.finish_substitution_window(interaction, game, match)


class CoachingHubView(CoachingView):
    """
    The buttons a Coaching Choice offers -- six of them, or three at
    full time. Each opens its own menu on this same message and every
    one of those comes back here.

    **The window before the shootout offers the substitution alone**,
    so the three positional buttons are not built at all rather than
    built and disabled: there is nothing a coach could do to enable
    them, and a shootout is not played on the board. That is the
    occasion's own property (`offers_positioning`) rather than a check
    on which occasion this is -- and it is why the three openers below
    need no stale-click guard, since a window that closes takes its
    view with it (see `finish`) and every hub is rebuilt from the state
    it is put up against.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(cog, game_id)

        game, match = self.load()
        if match is None or match.pending_coaching_side is None:
            return
        side = self.side(match)
        occasion = match.coaching_occasion
        positioning = occasion is None or occasion.offers_positioning

        if positioning:
            formation = cog.engine.current_formation(match, side)
            # The shape in brackets is the one they are in now, not the
            # one the button switches to, so it says so -- a bare
            # "(2-2-2)" reads as the destination.
            self.add_action(
                "Formation"
                + (f" (currently {formation.value})" if formation else ""),
                f"d12ball:coach_formation:{game_id}",
                self.open_formation,
            )
        self.add_action(
            f"Substitution ({cog.engine.substitution_button_label(match)})",
            f"d12ball:coach_sub:{game_id}",
            self.open_substitution,
            enabled=match.may_substitute()
            and bool(match.substitution_pool(side)),
        )
        if positioning:
            self.add_action(
                "Zone Assignment",
                f"d12ball:coach_zone:{game_id}",
                self.open_zone_assignment,
            )
            self.add_action(
                "Space Positioning",
                f"d12ball:coach_space:{game_id}",
                self.open_space_positioning,
                row=1,
            )
        self.add_action(
            "Team roster",
            f"d12ball:coach_roster:{game_id}",
            self.show_roster,
            row=1,
            style=discord.ButtonStyle.secondary,
        )
        self.add_action(
            "Done coaching",
            f"d12ball:coach_done:{game_id}",
            self.finish,
            row=1,
            style=discord.ButtonStyle.success,
        )

    def add_action(
        self,
        label: str,
        custom_id: str,
        callback,
        row: int = 0,
        enabled: bool = True,
        style: discord.ButtonStyle = discord.ButtonStyle.primary,
    ) -> None:
        button = discord.ui.Button(
            label=label[:80],
            style=style if enabled else discord.ButtonStyle.secondary,
            custom_id=custom_id,
            row=row,
            disabled=not enabled,
        )
        button.callback = callback
        self.add_item(button)

    async def open_formation(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return
        await self.show(
            interaction,
            game,
            match,
            CoachingFormationView(self.cog, self.game_id),
            note=(
                "Which formation? The numbers read from your own goal "
                "forward. Changing shape re-deals your six by defensive "
                "skill, best defenders furthest back -- move anyone you "
                "want elsewhere afterwards."
            ),
        )

    async def open_substitution(
        self,
        interaction: discord.Interaction,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return
        await self.show(
            interaction,
            game,
            match,
            CoachingSubstitutionOutView(self.cog, self.game_id),
            note="Who comes off?",
        )

    async def open_zone_assignment(
        self,
        interaction: discord.Interaction,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return
        await self.show(
            interaction,
            game,
            match,
            CoachingZoneView(self.cog, self.game_id),
            note=(
                "Which two change places? Their meeples move with them, "
                "so the shape is unchanged."
            ),
        )

    async def open_space_positioning(
        self,
        interaction: discord.Interaction,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return
        await self.show(
            interaction,
            game,
            match,
            CoachingPlaceView(self.cog, self.game_id),
            note="Whose meeple moves?",
        )

    async def show_roster(self, interaction: discord.Interaction) -> None:
        # Deliberately not gated on claim(): reading a roster is not
        # acting on the window, so the coach who is waiting on the
        # other side can look too. Answers privately, so the coaching
        # message stays where it is.
        game, match = self.load()
        if game is None or match is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        setups = self.cog.engine.roster_setups_for_user(
            game, match, interaction.user.id,
        )
        if setups is None:
            await interaction.response.send_message(
                "You are not one of the players in this game. Use "
                "/team_roster with all_teams:true to see both rosters.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "\n\n".join(
                self.cog.build_team_roster_section(match, setup)
                for setup in setups
            ),
            ephemeral=True,
        )

    async def finish(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        side = self.side(match)
        refusal = self.cog.engine.coaching_finish_refusal(match, side)
        if refusal is not None:
            await interaction.response.send_message(refusal, ephemeral=True)
            return

        # What they did, while the window still remembers it: closing
        # it clears the record, and every note the flow put up along
        # the way was written over by the step after it -- this
        # message is the only place a coach's substitutions survive.
        setup = match.setup_for_side(side)
        changes = self.cog.coaching_summary(match, side)
        await interaction.response.edit_message(
            content="\n".join(
                [
                    "# Coaching Choice",
                    f"**{format_team_side_label(setup)} are done.**",
                    *(
                        changes
                        or ["No substitutions, and no change of shape."]
                    ),
                ]
            ),
            view=None,
        )
        await self.cog.finish_substitution_window(interaction, game, match)


class CoachingFormationView(CoachingView):
    """
    Pick a shape. Applying it re-deals the whole side by defensive
    skill and places every meeple, so this is one click rather than the
    six it used to take -- see D12Ball.formation_placement.

    Only the shapes this match's board plays are offered
    (D12Ball.available_formations): 3-2-1 and 1-2-3 are the nine-space
    board's, so on 6 and 7 there is nothing to grey out and three
    buttons is the whole menu.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(cog, game_id)

        game, match = self.load()
        if match is None or match.pending_coaching_side is None:
            return
        current = cog.engine.current_formation(match, self.side(match))

        for choice in cog.engine.available_formations(match):
            button = discord.ui.Button(
                label=(
                    f"{choice.value}"
                    + (" (current)" if choice == current else "")
                ),
                style=(
                    discord.ButtonStyle.secondary
                    if choice == current
                    else discord.ButtonStyle.primary
                ),
                custom_id=(
                    f"d12ball:coach_formation_pick:{game_id}:{choice.value}"
                ),
                # Picking the shape you are already in changes nothing,
                # and re-dealing would shuffle a coach's own
                # arrangement out from under them.
                disabled=choice == current,
            )

            async def callback(
                interaction: discord.Interaction,
                picked: Formation = choice,
            ) -> None:
                await self.choose(interaction, picked)

            button.callback = callback
            self.add_item(button)

        self.add_back_button(row=1)

    async def choose(
        self,
        interaction: discord.Interaction,
        formation: Formation,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        try:
            note = self.cog.engine.apply_formation(
                match, self.side(match), formation,
            )
        except ValueError as error:
            await interaction.response.send_message(
                str(error), ephemeral=True,
            )
            return

        self.cog.persist(game, match)
        await self.back_to_hub(interaction, note=note, moved=True)


class CoachingSubstitutionOutView(CoachingView):
    """Who comes off. Injured players are marked."""

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(cog, game_id)

        game, match = self.load()
        if match is None or match.pending_coaching_side is None:
            return
        side = self.side(match)
        # Who may come on does not depend on who goes off, so this is
        # all-or-nothing: with both benches spent there is nobody to
        # offer for anybody, and the hub has already disabled the
        # button that opens this. It used to be a per-player filter,
        # from when the back bench opened only for an injured swap.
        if not match.substitution_pool(side):
            self.add_back_button(row=4)
            return

        for player_id in match.setup_for_side(side).field_players:
            injured = player_id in match.injured
            injured_word, _ = self.cog.injured_word_and_emoji(
                game, player_id,
            )
            button = discord.ui.Button(
                label=(
                    f"{self.player_button_label(match, player_id)}"
                    f"{f' - {injured_word}' if injured else ''}"
                )[:80],
                style=(
                    discord.ButtonStyle.danger
                    if injured
                    else discord.ButtonStyle.secondary
                ),
                custom_id=f"d12ball:coach_sub_off:{game_id}:{player_id}",
            )

            async def callback(
                interaction: discord.Interaction,
                outgoing: str = player_id,
            ) -> None:
                await self.choose(interaction, outgoing)

            button.callback = callback
            self.add_item(button)

        self.add_back_button(row=4)

    async def choose(
        self,
        interaction: discord.Interaction,
        outgoing_player_id: str,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        player = self.cog.engine.get_player_definition(outgoing_player_id)
        await self.show(
            interaction,
            game,
            match,
            CoachingSubstitutionInView(
                self.cog, self.game_id, outgoing_player_id,
            ),
            note=(
                "Who comes on for "
                f"{self.cog.player_label(match, player)}? "
                "They take their zone and their space exactly."
            ),
        )


class CoachingSubstitutionInView(CoachingView):
    """Who comes on for the player just taken off."""

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        outgoing_player_id: str,
    ):
        super().__init__(cog, game_id)
        self.outgoing_player_id = outgoing_player_id

        game, match = self.load()
        if match is None or match.pending_coaching_side is None:
            return

        for player_id in match.substitution_pool(self.side(match)):
            button = discord.ui.Button(
                label=cog.engine.format_roster_player(player_id)[:80],
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:coach_sub_on:{game_id}:{player_id}",
            )

            async def callback(
                interaction: discord.Interaction,
                incoming: str = player_id,
            ) -> None:
                await self.choose(interaction, incoming)

            button.callback = callback
            self.add_item(button)

        self.add_back_button(row=4)

    async def choose(
        self,
        interaction: discord.Interaction,
        incoming_player_id: str,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        try:
            note = self.cog.apply_substitution(
                game,
                match,
                self.side(match),
                self.outgoing_player_id,
                incoming_player_id,
            )
        except ValueError as error:
            await interaction.response.send_message(
                str(error), ephemeral=True,
            )
            return

        self.cog.persist(game, match)
        await self.back_to_hub(interaction, note=note, moved=True)


class CoachingZoneView(CoachingView):
    """
    Exchange two players' zones. Picking the first re-renders with
    everyone in a *different* zone as the second pick -- an exchange
    inside one zone would change nothing about the assignment, and
    moving a meeple within its zone is what space positioning is for.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        first_player_id: Optional[str] = None,
    ):
        super().__init__(cog, game_id)
        self.first_player_id = first_player_id

        game, match = self.load()
        if match is None or match.pending_coaching_side is None:
            return
        setup = match.setup_for_side(self.side(match))
        first_zone = (
            setup.assigned_zone(first_player_id)
            if first_player_id
            else None
        )

        for player_id in setup.field_players:
            if player_id == first_player_id:
                continue
            if (
                first_zone is not None
                and setup.assigned_zone(player_id) == first_zone
            ):
                continue
            button = discord.ui.Button(
                label=self.player_button_label(match, player_id),
                style=discord.ButtonStyle.secondary,
                custom_id=f"d12ball:coach_zone_pick:{game_id}:{player_id}",
            )

            async def callback(
                interaction: discord.Interaction,
                picked: str = player_id,
            ) -> None:
                await self.pick(interaction, picked)

            button.callback = callback
            self.add_item(button)

        self.add_back_button(row=4)

    async def pick(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        if self.first_player_id is None:
            player = self.cog.engine.get_player_definition(player_id)
            await self.show(
                interaction,
                game,
                match,
                CoachingZoneView(self.cog, self.game_id, player_id),
                note=(
                    "Who does "
                    f"{self.cog.player_label(match, player)} "
                    "change places with?"
                ),
            )
            return

        try:
            note = self.cog.apply_position_swap(
                match, self.side(match), self.first_player_id, player_id,
            )
        except ValueError as error:
            await interaction.response.send_message(
                str(error), ephemeral=True,
            )
            return

        self.cog.persist(game, match)
        await self.back_to_hub(interaction, note=note, moved=True)


class CoachingPlaceView(CoachingView):
    """Whose meeple moves, within its own assigned zone."""

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(cog, game_id)

        game, match = self.load()
        if match is None or match.pending_coaching_side is None:
            return

        for player_id in match.setup_for_side(
            self.side(match),
        ).field_players:
            button = discord.ui.Button(
                label=self.player_button_label(match, player_id, with_space=True),
                style=discord.ButtonStyle.secondary,
                custom_id=f"d12ball:coach_place:{game_id}:{player_id}",
            )

            async def callback(
                interaction: discord.Interaction,
                picked: str = player_id,
            ) -> None:
                await self.choose(interaction, picked)

            button.callback = callback
            self.add_item(button)

        self.add_back_button(row=4)

    async def choose(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        player = self.cog.engine.get_player_definition(player_id)
        await self.show(
            interaction,
            game,
            match,
            CoachingPlaceSpaceView(self.cog, self.game_id, player_id),
            note=(
                "Where should "
                f"{self.cog.player_label(match, player)} "
                "stand? A space one of your own is already on trades "
                "places with them."
            ),
        )


class CoachingPlaceSpaceView(CoachingView):
    """
    Which space in their own zone. **Every space is offered**, because
    the trade rule keeps coverage satisfied whichever one is picked --
    see MatchState.position_meeple.
    """

    def __init__(self, cog: "D12Ball", game_id: str, player_id: str):
        super().__init__(cog, game_id)
        self.player_id = player_id

        game, match = self.load()
        if match is None or match.pending_coaching_side is None:
            return
        side = self.side(match)
        zone = match.setup_for_side(side).assigned_zone(player_id)
        position = match.board.meeple_position(player_id)
        team_players = set(match.setup_for_side(side).field_players)

        for space_index in range(len(match.board.spaces[zone])):
            if position == (zone, space_index):
                continue
            here = [
                occupant
                for occupant in match.board.spaces[zone][space_index]
                if occupant in team_players
            ]
            button = discord.ui.Button(
                label=(
                    space_label(zone, space_index)
                    + (f" - {len(here)} of yours" if here else " - free")
                ),
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:coach_place_space:{game_id}:"
                    f"{player_id}:{space_index}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen: int = space_index,
            ) -> None:
                await self.choose(interaction, chosen)

            button.callback = callback
            self.add_item(button)

        self.add_back_button(row=4)

    async def choose(
        self,
        interaction: discord.Interaction,
        space_index: int,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        side = self.side(match)
        candidates = match.positioning_swap_candidates(
            side, self.player_id, space_index,
        )
        if len(candidates) > 1:
            player = self.cog.engine.get_player_definition(self.player_id)
            await self.show(
                interaction,
                game,
                match,
                CoachingPlaceSwapView(
                    self.cog, self.game_id, self.player_id, space_index,
                ),
                note=(
                    "More than one of yours is standing there. Who "
                    "comes back to make room for "
                    f"{self.cog.player_label(match, player)}?"
                ),
            )
            return

        await apply_positioning(
            self, interaction, game, match, self.player_id, space_index,
        )


async def apply_positioning(
    view: CoachingView,
    interaction: discord.Interaction,
    game: D12BallGame,
    match: MatchState,
    player_id: str,
    space_index: int,
    swap_with: Optional[str] = None,
) -> None:
    """
    Make a space-positioning move and go back to the hub. Shared by the
    two views that can arrive at one: the space pick, and the extra
    pick a stacked target needs.
    """
    try:
        note = view.cog.apply_reposition(
            match,
            view.side(match),
            player_id,
            space_index,
            swap_with=swap_with,
        )
    except ValueError as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return

    view.cog.persist(game, match)
    await view.back_to_hub(interaction, note=note, moved=True)


class CoachingPlaceSwapView(CoachingView):
    """
    Which of several teammates on the target space comes back. Only
    reachable where a zone is stacked, which on the three basic shapes
    means board 6's two-space midfield.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        player_id: str,
        space_index: int,
    ):
        super().__init__(cog, game_id)
        self.player_id = player_id
        self.space_index = space_index

        game, match = self.load()
        if match is None or match.pending_coaching_side is None:
            return

        for other_id in match.positioning_swap_candidates(
            self.side(match), player_id, space_index,
        ):
            button = discord.ui.Button(
                label=self.cog.engine.format_roster_player(other_id)[:80],
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:coach_place_swap:{game_id}:{other_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                picked: str = other_id,
            ) -> None:
                await self.choose(interaction, picked)

            button.callback = callback
            self.add_item(button)

        self.add_back_button(row=4)

    async def choose(
        self,
        interaction: discord.Interaction,
        other_player_id: str,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return
        await apply_positioning(
            self,
            interaction,
            game,
            match,
            self.player_id,
            self.space_index,
            swap_with=other_player_id,
        )

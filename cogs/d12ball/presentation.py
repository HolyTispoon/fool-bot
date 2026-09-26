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
from typing import Optional

from d12ball.components import (
    MatchState,
    PlayerRole,
    TeamSetup,
    load_species_abilities,
)
from d12ball.engine import IgnitedRoll
from d12ball.flow import FollowOnStep
from d12ball.formatting import role_initials
from d12ball.game import D12BallGame, Team, team_display_name
from d12ball.player_cards import render_player_card, render_player_card_back
from d12ball.render import (
    TEAM_COLORS,
    ChallengeSide,
    render_field_image,
    render_maneuver_challenge,
    render_match_image,
    render_score_attempt,
    render_volatile_die,
    zone_labels,
)
from d12ball.role_cards import render_role_reference
from d12ball.species_cards import render_species_reference
from gamesaves.d12ball.storage import save_games
from cogs.d12ball_helpers import (
    FIELD_IMAGE_FILENAME,
    PBD_ARCHIVE_CATEGORY_NAME,
    add_full_image_button,
    ball_space_label,
    board_image_filename,
    capitalized,
    format_player_with_team_name,
    format_team_side_label,
    get_or_create_category,
    pin_board_message,
    send_new_prompt,
    space_label,
)


def card_png(render, *args) -> bytes:
    """
    One printed card, drawn and encoded as PNG in the same worker
    thread: the encode is as CPU-bound as the draw. The cards are the
    print modules' own layout at print size, which is what makes a card
    on Discord the card on the table (see docs/design/cards.md).
    """
    buffer = io.BytesIO()
    render(*args).save(buffer, format="PNG")
    return buffer.getvalue()


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
        bucket in the game (see "Discord's rate limits" in docs/design/rate-limits.md),
        spent once a maneuver, immediately before the resolution's own
        board refresh, for nothing. Who has picked is announced in its
        own message.

        Deleting clears `turn_message_id` with it, so nothing tries to
        edit or re-attach a view to a message that is gone; whatever
        prompt the resolution posts next sets its own.
        """
        if not match.maneuver_selections_complete:
            return
        await self.close_turn_prompt(interaction, game)

    async def close_turn_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        """
        Delete the message `turn_message_id` names -- the maneuver
        prompt once both sides have picked, the shootout's "set your
        order" or "choose your shooter" once both have answered -- and
        clear the id with it, so nothing edits or re-attaches a view
        to a message that is gone. Whatever prompt comes next records
        its own.
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

    def challenge_side(
        self,
        player_id: str,
        team: Team,
        attacking: bool,
        modifiers: tuple[str, ...] = (),
        contribution: Optional[int] = None,
        halved: bool = False,
        game: Optional[D12BallGame] = None,
    ) -> ChallengeSide:
        """
        A player as a matchup image draws them. The ability is the
        short form: this is a caption under a portrait, next to
        another player's, and the sentence version wrapped to three
        lines and set the height of the whole image. The full text is
        still what the roster and the rules listing show.

        `contribution` and `halved` are a score attempt's defenders
        only -- everyone else adds their whole skill and is drawn
        without a word about it. `team` is which of the player's two
        rosters this match is fielding them as -- read by both callers
        off `match.team_for_player`, since a player's own definition no
        longer carries one.

        A rendering brief, so it is the frontend's: it was
        `RulesEngine.challenge_side` until step 9 of
        docs/architecture-migration.md, and the one thing that made
        the engine import `d12ball/render.py` -- and Pillow with it,
        in every process that loaded the model. The numbers it reads
        are the catalog's; the colour is `TEAM_COLORS`'s, which lives
        with the renderer that draws it. The skill is the game's
        (`RulesEngine.skills`), so an advanced score is drawn as the
        dice add it.
        """
        player = self.engine.get_player_definition(player_id)
        profile = self.engine.player_catalog.effective_profile(player)
        skills = self.engine.skills(game, player_id)
        return ChallengeSide(
            name=player.name,
            role=role_initials(player),
            team_color=TEAM_COLORS[Team(team)],
            team_label=team_display_name(team),
            skill_name="Offensive" if attacking else "Defensive",
            skill=skills.offense if attacking else skills.defense,
            ability=profile.short_ability,
            modifiers=modifiers,
            contribution=contribution,
            halved=halved,
        )

    async def build_maneuver_challenge_file(
        self,
        match: MatchState,
        defender_id: str,
        game: Optional[D12BallGame] = None,
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
                self.challenge_side(
                    match.active_player_id,
                    match.team_for_player(match.active_player_id),
                    attacking=True,
                    game=game,
                ),
                self.challenge_side(
                    defender_id,
                    match.team_for_player(defender_id),
                    attacking=False,
                    game=game,
                ),
                location=capitalized(
                    f"{ball_space_label(match)}"
                    f" — {zone_labels(match.board.layout.board_size)[match.ball.zone].title()}"
                ),
            ),
            filename="maneuver_challenge.png",
        )

    async def build_score_attempt_file(
        self,
        match: MatchState,
        game: Optional[D12BallGame] = None,
    ) -> discord.File:
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
        defenders = self.engine.intervening_defenders(match, game)
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
                self.challenge_side(
                    shooter.player_id,
                    match.team_for_player(shooter.player_id),
                    attacking=True,
                    game=game,
                    modifiers=tuple(modifiers),
                ),
                [
                    self.challenge_side(
                        defender.player.player_id,
                        match.team_for_player(defender.player.player_id),
                        attacking=False,
                        contribution=defender.value,
                        halved=defender.halved,
                        game=game,
                    )
                    for defender in defenders
                ],
                location=capitalized(
                    f"{ball_space_label(match)}"
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
            await send_new_prompt(
                interaction,
                ignite.explain(self.player_label(match, player)),
                file=discord.File(
                    await asyncio.to_thread(
                        render_volatile_die,
                        ignite.second,
                        ignite.face,
                        TEAM_COLORS[team],
                        team_display_name(team),
                        player.name,
                        ignite.blaze,
                        ignite.modifier,
                        ignite.rule,
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
        game: Optional[D12BallGame] = None,
    ) -> None:
        """
        Post the matchup image, with the challenger's walk-in above it
        rather than below: the image is meant to sit directly on top of
        the maneuver prompt, which is the message a coach is reading it
        for.
        """
        if walk_in_text:
            await send_new_prompt(
                interaction,
                walk_in_text,
                allowed_mentions=discord.AllowedMentions(
                    users=False, roles=False, everyone=False,
                ),
            )
        await send_new_prompt(
            interaction,
            file=await self.build_maneuver_challenge_file(
                match, defender_id, game,
            ),
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

    def format_team_roster_entry(
        self,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
        location: Optional[str] = None,
        show_role_abilities: bool = False,
        show_advanced_abilities: bool = True,
    ) -> str:
        """
        One roster line. `location` is the space the player stands on
        (e.g. "H1") for a player on the board, and None on a bench --
        the group heading above the line already names the place, so
        the line only has to say where within it.

        It takes the `game` for the three words a Cyborg reads their
        own condition in -- drain tokens, Drained, Damaged. They are
        the model's answers (`CoreMixin.token_word_and_emoji` and its
        two neighbours) rather than a species check here: whose
        exhaustion is drain is a rule, and this is a frontend.
        """
        player = self.engine.get_player_definition(player_id)
        count = match.exhaustion.get(player_id, 0)
        _, token_emoji = self.token_word_and_emoji(game, player_id)

        conditions = []
        if player_id in match.exhausted:
            word, emoji = self.exhausted_word_and_emoji(game, player_id)
            conditions.append(f"{word} {emoji}")
        if player_id in match.injured:
            word, emoji = self.injured_word_and_emoji(game, player_id)
            conditions.append(f"{word} {emoji}")

        entry = self.player_label(match, player)
        if location is not None:
            entry += f" — {location}"
        entry += f" — {count} {token_emoji}"
        if conditions:
            entry += f" — {', '.join(conditions)}"
        # The personal ability, in a game playing them, is on unless the
        # coach turns it off, where the role's is off unless asked for:
        # the role's is the same on every roster and the badge already
        # names it, and a personal ability is the one thing here a coach
        # cannot read off the badge. It is played beside the role's
        # (Law 21), so both may show. Not in italics, which is how the
        # role's reads, and because the sheet's own sentence may carry
        # markdown of its own (Gearclaw's "*Boost*").
        personal = (
            self.engine.personal_ability_text(game, player_id)
            if show_advanced_abilities
            else ""
        )
        if personal:
            entry += f"\n     **Personal:** {personal}"
        if show_role_abilities:
            ability = self.player_catalog.effective_profile(player).ability
            entry += f"\n     *{ability}*"
        return entry


    def build_team_roster_section(
        self,
        game: D12BallGame,
        match: MatchState,
        setup: TeamSetup,
        show_role_abilities: bool = False,
        show_advanced_abilities: bool = True,
    ) -> str:
        lines = [f"**{format_team_side_label(setup)}**"]
        for heading, members in self.engine.roster_places(match, setup):
            lines.append(f"\n__{heading}__")
            if not members:
                lines.append("*nobody*")
                continue
            lines.extend(
                self.format_team_roster_entry(
                    game,
                    match,
                    player_id,
                    location=location,
                    show_role_abilities=show_role_abilities,
                    show_advanced_abilities=show_advanced_abilities,
                )
                for player_id, location in members
            )
        return "\n".join(lines)

    async def build_role_reference_file(self) -> discord.File:
        """
        The role-ability reference card, for
        `/d12ball role_abilities_reference`: the printed card's one
        face, since both of its faces are the same image
        (`render_role_card_set`), in the dark palette a screen gets
        (`render_role_reference`).
        """
        png = await asyncio.to_thread(
            card_png, render_role_reference,
            self.player_catalog.role_profiles,
        )
        return discord.File(io.BytesIO(png), filename="role_abilities.png")

    async def build_species_reference_file(self) -> discord.File:
        """
        The species-ability reference, for
        `/d12ball species_abilities_reference`: the two faces of the
        printed set's first card on one image, in the dark palette a
        screen gets (`render_species_reference`), which between them
        carry all four abilities once each.
        """
        png = await asyncio.to_thread(
            card_png, render_species_reference, load_species_abilities(),
        )
        return discord.File(
            io.BytesIO(png), filename="species_abilities.png",
        )

    async def build_team_reference_files(
        self, game: D12BallGame, team: Team,
    ) -> list[discord.File]:
        """
        A team's printed player cards, one file each, for
        `/d12ball team_reference`: the advanced face in a game playing
        the personal abilities and advanced skills, and the front
        everywhere else -- the front carries the role's ability and
        skills, which is the whole of a player in training and basic
        mode. Which face is `personal_abilities_apply`'s answer, not
        the game's mode read here.

        In catalog order, which is the same whatever has happened on
        the board, so a coach finds a card in the same place each time.
        A team is nine players, inside Discord's ten attachments to a
        message.
        """
        render = (
            render_player_card_back
            if self.engine.personal_abilities_apply(game)
            else render_player_card
        )
        files = []
        for player in self.player_catalog.teams[team].players:
            png = await asyncio.to_thread(
                card_png, render, self.player_catalog, player, team, False,
            )
            files.append(
                discord.File(
                    io.BytesIO(png), filename=f"{player.player_id}.png",
                )
            )
        return files


    async def send_turn_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        """
        Hand the offensive choice to whoever now has the ball, as an
        entry point: `d12ball.flow.turn.begin_turn`, which stages a
        tutorial beat and holds its lesson behind Continue, and
        `start_turn` behind it. Both callers, the two recovery
        commands, hold only the game.
        """
        await self.present_result(
            interaction,
            game,
            self.service.run_step(game.game_id, FollowOnStep.SEND_TURN_PROMPT),
        )

    async def render_match_png(
        self,
        game: D12BallGame,
        snapshot: Optional[dict] = None,
    ) -> bytes:
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
        # `snapshot` is the position to draw where the caller has one
        # -- the dict the service took at a stop, rebuilt here -- and
        # the save otherwise, which is the position after the click.
        if snapshot is not None:
            match = MatchState.from_dict(snapshot, self.engine.basic_ruleset)
        else:
            match = self.engine.load_match_state(game)
        home_player = format_player_with_team_name(game, game.home_player_number)
        visiting_player = format_player_with_team_name(
            game, game.visiting_player_number,
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
            species_icons=self.engine.species_abilities_apply(game),
            cyborg_ids=self.engine.cyborg_condition_ids(game, match),
            card_skills=self.engine.card_skills(game, match),
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
            message = await send_new_prompt(
                interaction,
                file=await self.build_field_file(game),
            )
        except (discord.HTTPException, aiohttp.ClientError):
            return

        # A field is the whole width of the board in a strip a fifth as
        # tall, so inline it is smaller than anything else the bot
        # sends -- the names on the meeples need the full-size upload
        # more than the cards do.
        await add_full_image_button(message)

    async def send_field_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        content: str,
        view: discord.ui.View,
    ) -> None:
        """
        Put an effect's own question up over the field strip.

        **Six prompts ask a version of one question** -- how far does
        the ball or its handler go, and who ends up with it: the Low
        Pass and Skilled Pass destination, the High Pass and Setup Pass
        distance, both dribbles' run, and (through its own sender) the
        run back. Every one is answered by reading where everybody is
        standing relative to the ball, and by the time a maneuver has
        resolved the persistent board has scrolled away up the channel.
        So they share this, rather than six copies of the same four
        lines drifting apart a comment at a time.

        **The strip, not the coaching image's half-field.** These
        questions are about the position, and a position is both sides:
        a pass can be contested where it lands, a dribble can run into
        somebody, and the space a shot would be taken from is priced by
        who is standing in front of it. `render_field_image` is a crop
        of the match image's own board, so it is the same pixels both
        coaches are already reading -- where the coaching image is a
        second layout showing one side's row, which is right for
        arranging your own team and wrong for reading a live position.
        It is also the smallest thing the bot sends inline, which is
        what the full-image link below is for.

        **One attachment, on the prompt rather than beside it.**
        Discord lays two images on a message out side by side and
        halves both, which is why the strip under the maneuver *cards*
        is a message of its own and this is not. Riding on the prompt
        is what lets the click that answers take the picture away with
        `attachments=[]` -- it shows the position the effect was chosen
        against, and that position has just moved. Both sends are the
        webhook route, so neither competes with the board for the
        channel's edit bucket; see "Discord's rate limits".
        """
        prompt_message = await send_new_prompt(
            interaction,
            content,
            file=await self.build_field_file(game),
            view=view,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)
        # Handed the view, or the edit that adds the link drops the
        # buttons the prompt exists for -- see add_full_image_button.
        await add_full_image_button(prompt_message, view)

    async def build_field_file(self, game: D12BallGame) -> discord.File:
        """
        The field on its own -- where everybody is standing and where
        the ball is, with nothing else on it -- which is what a coach
        gets under their maneuver cards. See
        `d12ball.flow.turn.begin_maneuver_action_selection`.

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
            species_icons=self.engine.species_abilities_apply(game),
        )
        return discord.File(image, filename=FIELD_IMAGE_FILENAME)

    async def post_new_play_board(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        message: str,
        snapshot: Optional[dict] = None,
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
        png = await self.render_match_png(game, snapshot)
        snapshot = await send_new_prompt(
            interaction,
            message,
            file=self.match_file_from_png(game, png),
        )
        await add_full_image_button(snapshot)
        await self.refresh_match_image(interaction, game, png=png)
        await pin_board_message(snapshot)

    async def announce_board_update(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        message: str,
        snapshot: Optional[dict] = None,
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
        png = await self.render_match_png(game, snapshot)
        snapshot = await send_new_prompt(
            interaction,
            message,
            file=self.match_file_from_png(game, png),
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
        if game.guild_id is None or game.channel_id is None:
            raise ValueError("This game is not played in a Discord channel.")

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
        if game.channel_id is None:
            return False
        channel = self.bot.get_channel(game.channel_id)
        category = getattr(channel, "category", None)
        return bool(
            category is not None
            and category.name.casefold()
            == PBD_ARCHIVE_CATEGORY_NAME.casefold()
        )

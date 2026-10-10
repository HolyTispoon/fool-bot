"""
A turn on Discord (docs/codex-bot.md, step 4; docs/design/codex.md,
"The turn on Discord"): the panel shown to whoever is asked, `present`
-- the one presenter over a `GameResult` -- the turn's message rolled
over when a turn ends, the finished game's last line, and the two undos.

**The table is the channel's last message, and the panel is under it**
(docs/design/codex.md, "The turn message, posted again"). A click that
puts something in public posts the turn message again at the foot of
the channel and deletes the old one -- two requests of the channel's --
then sends the panel afresh under it through the click's own webhook,
which spends nothing from the channel's bucket, and deletes the panel
clicked. A click that puts nothing in public edits the panel in place
and nothing else. A turn's end adds the old message's last edit, which
leaves it standing as that turn's summary. Nothing here decides a rule:
what is asked, what may be chosen and which undos are open are the
model's answers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import discord

from codex.formatting import team_name
from codex.components import MatchState
from codex.flow.result import FollowOnStep
from codex.game import CodexGame, RuleRefusal
from codex.render import render_board, render_hand, render_side
from codex.prompts import PendingPrompt, PromptKind, owed_step, pending_prompt, standing_prompts
from cogs.codex_views import (
    RematchView, UndoConfirmView, hand_file, kept_pictures, picture_file, revealed_caption,
    revealed_files, send_ephemeral,
)
from cogs.codex.core import TECH_GATE_KINDS
from cogs.codex_helpers import elapsed_ms, pictures_size
from cogs.game_auth import send_new_prompt
from gamesaves.codex.service import GameResult

LOGGER = logging.getLogger(__name__)

PANEL_NOTE = "*Only you can see this.*"

#: The prompts whose panel is pictured with the asked player's hand, as
#: the main phase's is: Appel Stomp's place, which is about their own
#: draw pile, and the card a stash keeps (step 13) -- its owner's alone.
PANEL_HAND_KINDS = (
    PromptKind.APPEL_STOMP_TOP,
    PromptKind.STASH,
)
#: The prompts whose panel is pictured with a side of the board rather
#: than the hand (the author, 2026-10-09): what is chosen from is on the
#: table, the opponent's side as a rule, both sides stacked for a target
#: on either -- the defender, the three choices inside an attack, and an
#: effect's target (`side_shown`).
PANEL_SIDE_KINDS = (
    PromptKind.CHOOSE_DEFENDER,
    PromptKind.OBLITERATE_CHOICE,
    PromptKind.SPARKSHOT_TARGET,
    PromptKind.OVERPOWER_TARGET,
    PromptKind.TARGET,
    PromptKind.DIVIDE_DAMAGE,
)


def private_choices(prompt: PendingPrompt) -> list[str]:
    """The cards a `TARGET` offers from a hidden pile -- its asked player's
    own hand, codex, discard or draw pile (Sanatorium, Feral Strike,
    Calamandra, Garth, Vir), or the opponent's hand Carrion Curse looks at
    -- by slug, pictured as a hand is, to them alone, never on the table.
    Where the prompt shows more than it offers (`shown`, all of the hand
    looked at), all of it."""
    from codex.engine import CODEX, DECK, DISCARD, HAND

    if prompt.kind is not PromptKind.TARGET:
        return []
    if prompt.options.shown:
        return list(prompt.options.shown)
    return [row.ref.split(":", 1)[1] for row in prompt.options.targets
            if row.ref.startswith((HAND, CODEX, DISCARD, DECK))]


NOTHING_ASKED = "Nothing is asked of you now."
STEP_OWED = (
    "The game has a step of its own to run before anybody is asked anything: "
    "`/codex resume` runs it."
)
TURN_OVER = (
    "Patrol locked: your turn is over. Choose your tech now -- or later, from "
    "**Tech** on the turn message, until your next turn begins."
)
#: The Lock where nothing stands for the side that ended its turn: a
#: test game's (`codex.prompts.tech_stands`), where the one person plays
#: on from My hand as the other side, choosing that side's tech first
#: where it owes one -- or any game whose turn ended owing no tech.
TURN_OVER_TEST = "Patrol locked: {ended}'s turn is over. **My hand** opens {begins}'s turn{tech}."
TURN_OVER_NOTHING_OWED = "Patrol locked: your turn is over."


def split_at_turn_end(result: GameResult) -> tuple[list[str], Optional[dict], list[str], bool]:
    """
    A result's lines cut where the turn ended: what the ending turn said
    (the patrol lock, the draw's count, the buildings finished), the
    position as it stood there (the group's `board`, `DiscordBatching`'s
    `draw_after`), what the next turn said, and whether the turn ended.
    """
    closing: list[str] = []
    opening: list[str] = []
    board = None
    ended = False
    for group in result.groups:
        (opening if ended else closing).extend(line for line in group.lines if line)
        if not ended and group.step is FollowOnStep.BEGIN_TECH:
            ended, board = True, group.board
    (opening if ended else closing).extend(line for line in result.narration if line)
    return closing, board, opening, ended


def side_shown(prompt: PendingPrompt) -> Optional[int]:
    """The side a target prompt's panel pictures: the opponent's, the
    asked player's own where every target the prompt offers is theirs,
    or `None` -- both sides, stacked -- where the targets are on both
    (the author, 2026-10-09)."""
    asked = prompt.asked_player
    opponent = 2 if asked == 1 else 1
    if prompt.kind is PromptKind.TARGET:
        seats = {row.seat for row in prompt.options.targets}
        if seats == {asked}:
            return asked
        if seats == {asked, opponent}:
            return None
    if prompt.kind is PromptKind.DIVIDE_DAMAGE:
        seats = {int(key.split(":", 1)[0]) for key, _ in prompt.options.split}
        if seats == {asked}:
            return asked
        if seats == {asked, opponent}:
            return None
    return opponent


class TurnsMixin:
    # -- Who is asked what -----------------------------------------------------

    def standing_for(self, game: CodexGame, match, seat: int) -> Optional[PendingPrompt]:
        """The standing prompt `seat` may answer meanwhile -- the tech
        choice -- or `None`: always, in a test game, whose tech is
        chosen in each side's own ready phase (`codex.prompts.tech_stands`)."""
        for prompt in standing_prompts(self.engine, match, game):
            if prompt.asked_player == seat:
                return prompt
        return None

    def prompt_for(self, game: CodexGame, match, seat: int,
                   standing: bool = False) -> Optional[PendingPrompt]:
        """What `seat` is asked: the match's question where it is theirs,
        or with `standing`, their standing one."""
        if standing:
            return self.standing_for(game, match, seat)
        prompt = pending_prompt(self.engine, game, match)
        return prompt if prompt is not None and prompt.asked_player == seat else None

    def tech_asked(self, game: CodexGame, match, seat: int) -> bool:
        """Whether `seat`'s turn waits on their tech -- the confirmation,
        or the picker where nothing was picked -- which **Tech** opens
        and **My hand** puts behind a Tech button (`TECH_GATE_KINDS`)."""
        prompt = self.prompt_for(game, match, seat)
        return prompt is not None and prompt.kind in TECH_GATE_KINDS

    # -- The panel -------------------------------------------------------------

    def panel_caption(self, game: CodexGame, prompt: PendingPrompt, extra: str = "") -> str:
        """The panel's text: the model's ask, rendered, what the view
        adds beneath it, and that it is the clicker's alone."""
        lines = [self.render_text(prompt.ask, game)]
        if extra:
            lines.append(extra)
        lines.append(PANEL_NOTE)
        return "\n".join(lines)

    async def panel_parts(self, game: CodexGame, match, prompt: PendingPrompt,
                          note: str = "", gate: bool = False,
                          ) -> tuple[str, list[discord.File], Optional[discord.ui.View]]:
        """The panel for `prompt`: its text, its picture -- the hand,
        numbered, for the main phase, and for a turn's tech behind its
        Tech button (`gate`); a side of the board for a target
        (`side_shown`); the prompt's own (`render_prompt`) for the rest
        -- and its view (`view_for_prompt`)."""
        view = self.view_for_prompt(game, prompt, match, gate=gate)
        caption = getattr(view, "caption", None)
        extra = [note] if note else []
        if callable(caption):
            extra.append(caption())
        private = private_choices(prompt)
        if private:
            files = [await self.choices_file(private)]
        elif prompt.kind is PromptKind.MAIN_ACTION:
            # The opponent's hand under one's own where Eyes of the
            # Chancellor reveals it -- to this player alone (step 13).
            files = [await hand_file(self.engine, match, prompt.asked_player, prompt.options.hand),
                     *await revealed_files(self.engine, match, prompt.asked_player)]
            revealed = revealed_caption(self.engine, match, prompt.asked_player)
            if revealed:
                extra.append(revealed)
        elif prompt.kind in PANEL_SIDE_KINDS:
            files = [await self.side_file(game, match, prompt.asked_player, side_shown(prompt))]
        elif prompt.kind in PANEL_HAND_KINDS or gate:
            files = [await hand_file(self.engine, match, prompt.asked_player)]
        elif prompt.kind is PromptKind.TECH_CONFIRM:
            # The hand, then the picks: My hand opens the confirmation
            # at once (the author, 2026-10-10), and always shows the hand
            # (2026-10-09).
            picture = await self.render_prompt(game, prompt)
            files = [await hand_file(self.engine, match, prompt.asked_player),
                     *([] if picture is None else [picture])]
        else:
            picture = await self.render_prompt(game, prompt)
            files = [] if picture is None else [picture]
        return self.panel_caption(game, prompt, "\n".join(extra)), files, view

    async def choices_file(self, slugs: list[str]) -> discord.File:
        """The cards a private target offers, pictured as a hand is, off
        the event loop -- its asked player's alone."""
        cards = self.engine.catalog
        webp = await asyncio.to_thread(
            render_hand, slugs, [True] * len(slugs),
            [cards.cards[slug].cost or 0 for slug in slugs], cards,
        )
        return picture_file(webp, "codex-choices")

    async def side_file(self, game: CodexGame, match, asked: int,
                        seat: Optional[int]) -> discord.File:
        """`seat`'s side of the table pictured alone, upright
        (`render_side`), or with `seat` `None` both sides stacked as
        `asked` looks at them, their own nearer (`render_board`'s
        `near`) -- off the event loop."""
        names = self.seat_names(game)
        if seat is None:
            webp = await asyncio.to_thread(
                render_board, match, "stacked", names, self.engine.catalog, asked,
            )
            return picture_file(webp, "codex-sides")
        webp = await asyncio.to_thread(
            render_side, match, seat, names[seat], self.engine.catalog,
        )
        return picture_file(webp, "codex-side")

    async def show_panel(self, interaction: discord.Interaction, game: CodexGame, match,
                         seat: int, *, edit: bool, standing: bool = False, note: str = "",
                         replace: bool = False, open_tech: bool = False) -> None:
        """
        Put up what `seat` is asked: **made afresh** as an ephemeral
        message (`edit=False` -- My hand, Tech, `/codex resume`) -- for a
        turn that waits on a tech choice its player never made, the hand
        pictured with **Tech** alone under it (`TechGateView`) until it
        is opened, or the picker at once where **Tech** was pressed
        (`open_tech`); saved picks open on their confirmation either way
        (the author, 2026-10-10) -- in
        place of the panel clicked (`edit=True`), or **in its stead,
        under the turn message just posted again** (`replace=True`,
        `put_panel`). The cog never looks for an old panel: an ephemeral
        message dies with the client's session, and every entry point
        makes a new one.
        """
        prompt = self.prompt_for(game, match, seat, standing)
        if prompt is None:
            if edit or replace:
                await self.put_panel(interaction, NOTHING_ASKED, edit=edit, replace=replace)
            elif owed_step(self.engine, game, match) is not None:
                await send_ephemeral(interaction, STEP_OWED)
            else:
                await self.send_hand(interaction, game, match, seat)
            return
        fresh = not edit and not replace
        gate = fresh and not standing and not open_tech and prompt.kind is PromptKind.TECH_CHOICE
        started = time.perf_counter()
        content, files, view = await self.panel_parts(game, match, prompt, note, gate=gate)
        drawn = elapsed_ms(started)
        started = time.perf_counter()
        await self.put_panel(interaction, content, files, view, edit=edit, replace=replace)
        LOGGER.info(
            "Codex game #%s: the panel's picture drawn in %d ms (%d KB); the panel %s in %d ms",
            game.game_number, drawn, pictures_size(files) // 1024,
            "sent afresh" if replace else "edited in place" if edit else "sent",
            elapsed_ms(started),
        )

    async def put_panel(self, interaction: discord.Interaction, content: str,
                        files: Optional[list[discord.File]] = None,
                        view: Optional[discord.ui.View] = None, *,
                        edit: bool, replace: bool = False) -> None:
        """
        The panel's one write, three ways. `replace`: the click was
        deferred and the turn message has just been posted again at the
        foot of the channel, so the panel is **sent afresh under it**, a
        follow-up of the click's, and the panel clicked deleted -- the
        interaction's own message, which is the one way an ephemeral
        message can be deleted. Both go through the click's webhook. An
        ephemeral message is always drawn as an answer to something --
        Discord ties every message an interaction makes to it -- so the
        new panel is drawn as a reply to the one it replaces, never to
        the turn message. `edit`: in place of the panel clicked.
        Otherwise a new ephemeral message, the click's answer or its
        follow-up.
        """
        files = list(files or [])
        if edit and not replace:
            await interaction.response.edit_message(
                content=content, attachments=kept_pictures(files, interaction.message), view=view,
            )
            return
        if replace and not interaction.response.is_done():
            # Deferred first, so the message deleted below is the panel
            # clicked and never the answer about to be sent.
            await interaction.response.defer()
        kwargs: dict = {"ephemeral": True}
        if files:
            kwargs["files"] = files
        if view is not None:
            kwargs["view"] = view
        if interaction.response.is_done():
            await interaction.followup.send(content, **kwargs)
        else:
            await interaction.response.send_message(content, **kwargs)
        if replace:
            try:
                await interaction.delete_original_response()
            except discord.HTTPException as error:
                LOGGER.warning("Could not delete a Codex panel: %s", error)

    async def answer_panel(self, interaction: discord.Interaction, game: CodexGame,
                           seat: int, result: GameResult,
                           answered: Optional[PromptKind] = None,
                           replace: bool = False) -> None:
        """
        The panel after its own click, with what is asked next: the next
        action, the defender, the patrol lock, the turn's actions once
        the tech is confirmed -- **edited in place**, or, where the click
        put something in public (`replace`), sent afresh under the turn
        message posted again and the panel clicked deleted (`put_panel`).
        A tech save stays on the picker, saved -- or, in a test game,
        where the save is the ready phase's and the turn begins on it,
        becomes the turn's actions. The Lock that ends the turn becomes
        the tech picker, saying the turn is over; in a test game nothing
        stands to pick (`codex.prompts.tech_stands`), so the panel closes
        naming the side whose turn it is now, and the one person plays on
        from My hand.
        """
        match = result.match
        prompt = result.prompt if result.prompt is not None and result.prompt.asked_player == seat else None
        standing = next((one for one in result.standing if one.asked_player == seat), None)
        if prompt is not None:
            await self.show_panel(interaction, game, match, seat, edit=True, replace=replace)
            return
        if standing is not None and answered is PromptKind.TECH_CHOICE:
            await self.show_panel(interaction, game, match, seat, edit=True, standing=True,
                                  note="**Saved.** You may change it until your turn begins.",
                                  replace=replace)
            return
        if standing is not None:
            await self.show_panel(interaction, game, match, seat, edit=True, standing=True,
                                  note=TURN_OVER, replace=replace)
            return
        if answered is PromptKind.PATROL and match is not None and match.active != seat and match.winner is None:
            closing = self.turn_over_text(game, match, seat, result.prompt)
        elif match is not None and match.winner is not None:
            closing = "The game is over."
        else:
            closing = NOTHING_ASKED
        await self.put_panel(interaction, closing, edit=True, replace=replace)

    def turn_over_text(self, game: CodexGame, match, seat: int,
                       prompt: Optional[PendingPrompt]) -> str:
        """What the Lock's panel closes on where no tech picker follows
        it: in a test game, the side that ended and the side My hand
        opens, with its tech choice first where `prompt` is one."""
        if not game.test_game:
            return TURN_OVER_NOTHING_OWED
        tech = ", its tech choice first" if prompt is not None and prompt.kind is PromptKind.TECH_CHOICE else ""
        return TURN_OVER_TEST.format(
            ended=team_name(match.player(seat).specs), begins=team_name(match.active_player.specs), tech=tech,
        )

    # -- The presenter ---------------------------------------------------------

    def goes_public(self, result: GameResult) -> bool:
        """Whether `present` puts anything in the channel for `result`:
        the turn ended, a base fell, or something was said or moved. A
        click that does is answered with its panel under it
        (`answer_panel`'s `replace`)."""
        match = result.match
        if match is not None and (split_at_turn_end(result)[3] or match.winner is not None):
            return True
        return bool(result.lines or result.board_changed)

    async def present(self, game: CodexGame, result: GameResult,
                      before: Optional[tuple[int, str]] = None) -> None:
        """
        **The whole of the Discord side of a result.** What it said joins
        the turn's lines and the turn message is posted again at the foot
        of the channel with them and the board, the one it replaces
        deleted -- or, where the model's end-of-turn step ran,
        the turn's message stands with
        its last lines and board and the next turn's goes up; or, where
        a base fell, the game's last line. Hidden information never
        reaches here: a result's lines are public (docs/design/codex.md,
        "What the narration may say"), and its prompts go to their asked
        player through the panel. `before` is the turn and phase the click
        found, which says whether the turn's main phase has just opened.
        """
        match = result.match
        # The turn ended where the model's own end-of-turn step closed a
        # group (`split_at_turn_end`), not where the cog sees the turn
        # number move.
        if match is not None and split_at_turn_end(result)[3]:
            await self.roll_over(game, result)
            return
        self.note_lines(game, result)
        if match is not None and match.winner is not None:
            await self.finish_game(game, result)
            return
        if match is not None and match.phase == "main" and before is not None and before[1] != "main":
            self.note_turn_head(game, match)
        if result.lines or result.board_changed:
            await self.repost_turn_message(game, match)

    async def stand_turn_message(self, channel, game: CodexGame, message_id: int,
                                 png: bytes, text: Optional[str]) -> None:
        """
        A turn message's last edit: its lines and its board, **without
        its buttons**, so it stands as that turn's summary -- and **it is
        pinned** (the author, 2026-10-09), so the pins are the game's
        history turn by turn. Written under the gate's lock, so no write
        of the gate's lands on it after, and the gate is forgotten: the
        next write is the next message's. Called before the next turn's
        message is posted, so the pin's own notice lands above that
        message rather than under the board.
        """
        state = self.boards.state(game.game_id)
        async with state.lock:
            message = channel.get_partial_message(message_id)
            try:
                await message.edit(
                    attachments=[self.match_file_from_png(game, png)], view=None,
                    **({} if text is None else {"content": text}),
                )
            except discord.HTTPException as error:
                LOGGER.warning("Could not close the turn message of Codex game %s: %s",
                               game.game_id, error)
            try:
                await message.pin(reason="A finished turn of a Codex game")
            except discord.HTTPException as error:
                # Discord caps a channel's pins; past the cap the turn
                # still stands, unpinned.
                LOGGER.warning("Could not pin the turn summary of Codex game %s: %s",
                               game.game_id, error)
        self.boards.forget(game)

    async def roll_over(self, game: CodexGame, result: GameResult) -> None:
        """
        The turn ended in this result: its message is edited a last time
        with the turn's closing lines and its own last board, stands and
        is pinned; the next turn's message is posted under it with what
        the next turn has said.
        """
        match = result.match
        closing, board, opening, _ = split_at_turn_end(result)
        channel = self.bot.get_channel(game.channel_id) if game.channel_id else None
        if channel is None:
            return
        ended = MatchState.from_dict(board) if board is not None else MatchState.from_dict(match.to_dict())
        # The standing picture lights the player whose turn it was: the
        # position is the one the turn handed over on.
        # The heading is the turn that ended, too.
        ended.active = 2 if match.active == 1 else 1
        ended.turn = match.turn - 1
        if game.turn_message_id is not None:
            png = await self.render_match_png(game, ended)
            text = None
            if game.game_id in self.turn_lines:
                text = self.turn_text(
                    game, ended, [*self.turn_lines[game.game_id], *closing], footer=False,
                )
            await self.stand_turn_message(channel, game, game.turn_message_id, png, text)
        self.turn_lines[game.game_id] = opening
        if match.phase == "main":
            self.note_turn_head(game, match)
        await self.post_turn_message(channel, game, match)

    async def finish_game(self, game: CodexGame, result: GameResult) -> None:
        """
        The game is over -- a base fell, or a player conceded: the turn
        message's last edit, without its buttons, pinned as every
        finished turn is, and **a public line naming the winner with the
        final board** -- rendered once, uploaded twice -- with **Rematch**
        under it (`RematchView`), whose message the record keeps so a
        restart re-arms it. Then the channel is moved to Codex Archive
        and left as it is (`archive_channel`): nothing is exported from
        it and no statistics are read from it.
        """
        match = result.match
        channel = self.bot.get_channel(game.channel_id) if game.channel_id else None
        if channel is None:
            return
        png = await self.render_match_png(game, match)
        if game.turn_message_id is not None:
            await self.stand_turn_message(channel, game, game.turn_message_id, png,
                                          self.turn_text(game, match))
        line = result.prompt.ask if result.prompt is not None else ""
        try:
            message = await channel.send(
                self.render_text(f"**{line}**", game) if line else None,
                file=self.match_file_from_png(game, png),
                view=RematchView(self, game.game_id),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as error:
            LOGGER.warning("Could not post the final board of Codex game %s: %s", game.game_id, error)
        else:
            game.final_message_id = message.id
            self.service.save()
        self.turn_lines.pop(game.game_id, None)
        self.turn_heads.pop(game.game_id, None)
        await self.archive_channel(channel, game)

    # -- The undos ---------------------------------------------------------------

    async def undo_to_turn_start(self, interaction: discord.Interaction, game: CodexGame,
                                 seat: int) -> None:
        """
        The active player's own undo: the turn's snapshot restored, the
        turn message posted again with its first lines and "undone to the
        start of the turn" and the restored board, the panel sent under it
        from the new prompt. Nobody's consent is asked.
        """
        match = self.service.load(game)
        if seat != match.active:
            await send_ephemeral(interaction, "Only the player whose turn it is can undo it.")
            return
        try:
            result = self.service.undo_to_turn_start(game.game_id)
        except RuleRefusal as refused:
            await send_ephemeral(interaction, str(refused))
            return
        restored = result.match
        head = self.turn_heads.get(game.game_id, {}).get(restored.turn, [])
        self.turn_lines[game.game_id] = [*head, *result.lines]
        # The acknowledgement goes out beside the board, not before it
        # (`TurnPanelView.act`).
        await asyncio.gather(interaction.response.defer(), self.repost_turn_message(game, restored))
        await self.show_panel(interaction, game, restored, seat, edit=True, replace=True)

    async def ask_undo_to_previous_turn(self, interaction: discord.Interaction, game: CodexGame,
                                        seat: int, turn: int) -> None:
        """
        An undo to the start of the previous turn unwinds the opponent's
        turn too, so it is asked of them: a public message with their
        **Agree** (or a helper's) and **Refuse**. The panel goes back to
        the actions, saying it was asked.
        """
        match = self.service.load(game)
        if seat != match.active:
            await send_ephemeral(interaction, "Only the player whose turn it is can ask for that.")
            return
        opponent = 2 if seat == 1 else 1
        opponent_id = game.player_1_id if opponent == 1 else game.player_2_id
        asker = game.seat_name(seat) or f"Player {seat}"
        await self.show_panel(interaction, game, match, seat, edit=True,
                              note="Your opponent has been asked to agree to the undo.")
        mention = f"<@{opponent_id}>" if opponent_id else (game.seat_name(opponent) or "Opponent")
        await send_new_prompt(
            interaction,
            f"{mention}, {asker} asks to undo to the start of turn {turn - 1} -- your turn -- "
            "which takes back this turn and the end of yours. Do you agree?",
            view=UndoConfirmView(self, game.game_id, seat, turn),
            allowed_mentions=discord.AllowedMentions(
                users=[discord.Object(id=opponent_id)] if opponent_id else False,
            ),
        )

    async def undo_to_previous_turn(self, interaction: discord.Interaction, game: CodexGame,
                                    seat: Optional[int]) -> None:
        """
        The opponent agreed (or a helper did): the older snapshot is
        restored; the restored turn's message is posted at the foot of
        the channel with its first lines and "undone to the start of the
        turn", the restored board and its buttons; the current turn's
        message and the previous turn's standing one are deleted, since
        the restored turn is current again; and the restored turn's
        player, where they clicked, gets a fresh panel under it.
        """
        try:
            result = self.service.undo_to_previous_turn(game.game_id)
        except RuleRefusal as refused:
            await interaction.response.edit_message(content=str(refused), view=None)
            return
        restored = result.match
        who = game.seat_name(seat) if seat is not None else interaction.user.display_name
        await interaction.response.edit_message(
            content=f"Undone to the start of turn {restored.turn}: agreed by {who}.", view=None,
        )
        channel = interaction.channel or (self.bot.get_channel(game.channel_id) if game.channel_id else None)
        previous = game.previous_turn_message_id
        self.boards.forget(game)
        head = self.turn_heads.get(game.game_id, {}).get(restored.turn, [])
        self.turn_lines[game.game_id] = [*head, *result.lines]
        # The turn before the restored one has no message the record
        # knows, so a second such undo in a row has nothing to delete.
        game.previous_turn_message_id = None
        await self.post_turn_message(channel, game, restored, replace=True)
        if previous is not None and previous != game.turn_message_id:
            await self.delete_table_message(channel, game, previous)
        if seat is not None and seat == restored.active:
            await self.show_panel(interaction, game, restored, seat, edit=False)

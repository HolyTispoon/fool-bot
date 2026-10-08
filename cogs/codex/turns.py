"""
A turn on Discord (docs/codex-bot.md, step 4; docs/design/codex.md,
"The turn on Discord"): the panel shown to whoever is asked, `present`
-- the one presenter over a `GameResult` -- the turn's message rolled
over when a turn ends, the finished game's last line, and the two undos.

**Two messages are written per click at most, and only one of them is
the channel's**: the panel, an ephemeral message edited through the
click's own response (the interaction's webhook, which spends nothing
from the channel's bucket), and the turn message, edited through the
gate (`BoardRefresher`). A turn's end adds the old message's last edit,
the new one's post, its pin and the old one's unpin -- the rollover
D12 Ball's board does. Nothing here decides a rule: what is asked, what
may be chosen and which undos are open are the model's answers.
"""

from __future__ import annotations

import logging
from typing import Optional

import discord

from codex.components import MatchState
from codex.flow.result import FollowOnStep
from codex.game import CodexGame, RuleRefusal
from codex.prompts import PendingPrompt, PromptKind, owed_step, pending_prompt, standing_prompts
from cogs.codex_views import UndoConfirmView, hand_file, send_ephemeral
from cogs.game_auth import send_new_prompt
from gamesaves.codex.service import GameResult

LOGGER = logging.getLogger(__name__)

PANEL_NOTE = "*Only you can see this.*"
NOTHING_ASKED = "Nothing is asked of you now."
STEP_OWED = (
    "The game has a step of its own to run before anybody is asked anything: "
    "`/codex resume` runs it."
)
TURN_OVER = (
    "Patrol locked: your turn is over. Choose your tech below -- or later, from "
    "**Tech** on the turn message, until your next turn begins."
)


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


class TurnsMixin:
    # -- Who is asked what -----------------------------------------------------

    def standing_for(self, game: CodexGame, match, seat: int) -> Optional[PendingPrompt]:
        """The standing prompt `seat` may answer meanwhile -- the tech
        choice -- or `None`."""
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
                          note: str = "") -> tuple[str, list[discord.File], Optional[discord.ui.View]]:
        """The panel for `prompt`: its text, its picture -- the hand,
        numbered, for the main phase and the defender; the prompt's own
        (`render_prompt`) for the rest -- and its view (`view_for_prompt`)."""
        view = self.view_for_prompt(game, prompt, match)
        caption = getattr(view, "caption", None)
        extra = [note] if note else []
        if callable(caption):
            extra.append(caption())
        if prompt.kind is PromptKind.MAIN_ACTION:
            files = [await hand_file(self.engine, match, prompt.asked_player, prompt.options.hand)]
        elif prompt.kind is PromptKind.CHOOSE_DEFENDER:
            files = [await hand_file(self.engine, match, prompt.asked_player)]
        else:
            picture = await self.render_prompt(game, prompt)
            files = [] if picture is None else [picture]
        return self.panel_caption(game, prompt, "\n".join(extra)), files, view

    async def show_panel(self, interaction: discord.Interaction, game: CodexGame, match,
                         seat: int, *, edit: bool, standing: bool = False, note: str = "") -> None:
        """
        Put up what `seat` is asked: **made afresh** as an ephemeral
        message (`edit=False` -- My hand, Tech, `/codex resume`), or in
        place of the panel clicked (`edit=True`). The cog never looks
        for an old panel: an ephemeral message dies with the client's
        session, and every entry point makes a new one.
        """
        prompt = self.prompt_for(game, match, seat, standing)
        if prompt is None:
            if edit:
                await interaction.response.edit_message(content=NOTHING_ASKED, attachments=[], view=None)
            elif owed_step(self.engine, game, match) is not None:
                await send_ephemeral(interaction, STEP_OWED)
            else:
                await self.send_hand(interaction, game, match, seat)
            return
        content, files, view = await self.panel_parts(game, match, prompt, note)
        if edit:
            await interaction.response.edit_message(content=content, attachments=files, view=view)
            return
        kwargs: dict = {"ephemeral": True}
        if files:
            kwargs["files"] = files
        if view is not None:
            kwargs["view"] = view
        if interaction.response.is_done():
            await interaction.followup.send(content, **kwargs)
        else:
            await interaction.response.send_message(content, **kwargs)

    async def answer_panel(self, interaction: discord.Interaction, game: CodexGame,
                           seat: int, result: GameResult,
                           answered: Optional[PromptKind] = None) -> None:
        """
        The panel after its own click, **edited in place** with what is
        asked next: the next action, the defender, the patrol lock, the
        turn's actions once the tech is confirmed. A tech save stays on
        the picker, saved. The Lock that ends the turn closes the panel
        and sends the tech picker as an ephemeral follow-up.
        """
        match = result.match
        prompt = result.prompt if result.prompt is not None and result.prompt.asked_player == seat else None
        standing = next((one for one in result.standing if one.asked_player == seat), None)
        if prompt is not None:
            await self.show_panel(interaction, game, match, seat, edit=True)
            return
        if standing is not None and answered is PromptKind.TECH_CHOICE:
            await self.show_panel(interaction, game, match, seat, edit=True, standing=True,
                                  note="**Saved.** You may change it until your turn begins.")
            return
        if standing is not None:
            await interaction.response.edit_message(content=TURN_OVER, attachments=[], view=None)
            await self.show_panel(interaction, game, match, seat, edit=False, standing=True)
            return
        if match is not None and match.winner is not None:
            await interaction.response.edit_message(content="The game is over.", attachments=[], view=None)
            return
        await interaction.response.edit_message(content=NOTHING_ASKED, attachments=[], view=None)

    # -- The presenter ---------------------------------------------------------

    async def present(self, game: CodexGame, result: GameResult,
                      before: Optional[tuple[int, str]] = None) -> None:
        """
        **The whole of the Discord side of a result.** What it said joins
        the turn's lines and the board and the lines are written once
        through the gate -- or, where the model's end-of-turn step ran,
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
            await self.refresh_match_image(game)

    async def stand_turn_message(self, channel, game: CodexGame, message_id: int,
                                 png: bytes, text: Optional[str]) -> None:
        """
        A turn message's last edit: its lines and its board, **without
        its buttons**, so it stands as that turn's summary. Written under
        the gate's lock, so no write of the gate's lands on it after, and
        the gate is forgotten: the next write is the next message's.
        """
        state = self.boards.state(game.game_id)
        async with state.lock:
            try:
                await channel.get_partial_message(message_id).edit(
                    attachments=[self.match_file_from_png(game, png)], view=None,
                    **({} if text is None else {"content": text}),
                )
            except discord.HTTPException as error:
                LOGGER.warning("Could not close the turn message of Codex game %s: %s",
                               game.game_id, error)
        self.boards.forget(game)

    async def roll_over(self, game: CodexGame, result: GameResult) -> None:
        """
        The turn ended in this result: its message is edited a last time
        with the turn's closing lines and its own last board and stands;
        the next turn's message is posted with what the next turn has
        said, pinned, and the old one unpinned.
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
        A base fell: the turn message's last edit, without its buttons,
        and **a public line naming the winner with the final board** --
        rendered once, uploaded twice. Step 7 adds the rematch.
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
            await channel.send(
                self.render_text(f"**{line}**", game) if line else None,
                file=self.match_file_from_png(game, png),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as error:
            LOGGER.warning("Could not post the final board of Codex game %s: %s", game.game_id, error)

    # -- The undos ---------------------------------------------------------------

    async def undo_to_turn_start(self, interaction: discord.Interaction, game: CodexGame,
                                 seat: int) -> None:
        """
        The active player's own undo: the turn's snapshot restored, the
        turn message back to its first lines and "undone to the start of
        the turn", the board through the gate, the panel re-rendered from
        the new prompt. Nobody's consent is asked.
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
        await self.show_panel(interaction, game, restored, seat, edit=True)
        await self.refresh_match_image(game)

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
        restored; the previous turn's message is edited back to its
        first lines and "undone to the start of the turn" with the
        restored board and its buttons, and pinned again; the current
        turn's message is deleted -- the one deletion in the flow -- and
        the restored turn's player, where they clicked, gets a fresh
        panel.
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
        current, previous = game.turn_message_id, game.previous_turn_message_id
        self.boards.forget(game)
        head = self.turn_heads.get(game.game_id, {}).get(restored.turn, [])
        self.turn_lines[game.game_id] = [*head, *result.lines]
        if previous is not None:
            game.turn_message_id, game.previous_turn_message_id = previous, None
            self.service.save()
            await self.refresh_match_image(game)
            try:
                await channel.get_partial_message(previous).pin(reason="The current turn of a Codex game")
            except discord.HTTPException as error:
                LOGGER.warning("Could not pin the restored turn of Codex game %s: %s", game.game_id, error)
        else:
            game.turn_message_id = None
            self.service.save()
            await self.post_turn_message(channel, game, restored)
        if current is not None and current != game.turn_message_id:
            try:
                await channel.get_partial_message(current).delete()
            except discord.HTTPException as error:
                LOGGER.warning("Could not delete the undone turn of Codex game %s: %s", game.game_id, error)
        if seat is not None and seat == restored.active:
            await self.show_panel(interaction, game, restored, seat, edit=False)

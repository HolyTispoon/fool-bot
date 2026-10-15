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
from typing import Callable, Optional

import discord

from codex.formatting import team_name
from codex.components import MatchState
from codex.flow.result import FollowOnStep
from codex import history
from codex.game import CodexGame, RuleRefusal
from codex.render import render_board, render_hand, render_side
from codex.prompts import (
    PendingPrompt, PromptKind, owed_step, pending, pending_prompt, pending_prompts, standing_prompts,
)
from cogs.codex_views import (
    RematchView, TeamConcedeView, UndoConfirmView, WaitingView, hand_files, kept_pictures, opponent_started,
    picture_file, revealed_caption, revealed_files, acknowledge, edit_clicked, send_answer, send_ephemeral,
)
from cogs.codex.core import TECH_GATE_KINDS
from cogs.codex_helpers import elapsed_ms, pictures_size
from cogs.game_auth import send_new_prompt
from gamesaves.codex.service import GameResult

LOGGER = logging.getLogger(__name__)

#: What the fine undo's menu calls an action that said nothing, by the
#: answer that began it (`UndoPoint.choice`): its button's own name.
SILENT_ACTIONS = {"end_main": "End main phase"}

PANEL_NOTE = "*Only you can see this.*"

#: The prompts whose panel is pictured with the asked player's hand, as
#: the main phase's is: Appel Stomp's place, which is about their own
#: draw pile, and the card a stash keeps (step 13) -- its owner's alone.
PANEL_HAND_KINDS = (
    PromptKind.APPEL_STOMP_TOP,
    PromptKind.STASH,
)
#: The prompts whose panel is the hand message -- pictured with the
#: asked player's hand -- and so opens on the turn's lines
#: (`with_turn_log`): the main phase and `PANEL_HAND_KINDS`. No other
#: ephemeral message carries the lines (the author, 2026-10-12: "only in
#: the hand message and the public turn message") -- the tech
#: confirmation pictures the picks alone.
TURN_LOG_KINDS = (
    PromptKind.MAIN_ACTION,
    *PANEL_HAND_KINDS,
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


def side_shown(prompt: PendingPrompt, opponents: tuple[int, ...]) -> Optional[int]:
    """The side a target prompt's panel pictures: the one seat every
    target the prompt offers is on -- the asked player's own, or an
    opponent's -- or `None`, the table stacked, where the targets lie on
    several seats (the author, 2026-10-09; a table of several, 2026-10-14).
    A prompt with no rows of its own pictures the opponent's side, the
    only one a duel has, and the table where there are several."""
    kind = prompt.kind
    if kind is PromptKind.TARGET:
        found = {row.seat for row in prompt.options.targets}
    elif kind is PromptKind.DIVIDE_DAMAGE:
        found = {int(key.split(":", 1)[0]) for key, _ in prompt.options.split}
    else:
        found = set()
    if len(found) == 1:
        return next(iter(found))
    if len(found) > 1 or len(opponents) != 1:
        return None
    return opponents[0]


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
        or with `standing`, their standing one. In a two-headed dragon
        each acting seat has its own (`pending`'s `seat`; decision 8),
        and nothing reads one teammate's for the team's."""
        if standing:
            return self.standing_for(game, match, seat)
        if match.dragons:
            found = pending(self.engine, game, match, seat)
            return found if isinstance(found, PendingPrompt) else None
        prompt = pending_prompt(self.engine, game, match)
        return prompt if prompt is not None and prompt.asked_player == seat else None

    def questions(self, game: CodexGame, match) -> tuple[PendingPrompt, ...]:
        """Every question the acting seats are asked now: one, or a
        dragon's one per acting seat (`pending_prompts`)."""
        return pending_prompts(self.engine, game, match)

    def acting_seat_for(self, game: CodexGame, match, user_id: int) -> Optional[int]:
        """
        The seat a click of `user_id`'s on the turn message acts for: the
        record's `seat_for` -- their seat, or in a test game the one whose
        turn it is -- except where a test game's one person holds both
        acting seats of a dragon: then **the first unlocked teammate's**
        with a question (decision 13), the other reached by its panel's
        **Switch to** button.
        """
        held = game.seats_of(user_id)
        if match.dragons and match.winner is None and len(held) > 1:
            for seat in self.engine.acting_seats(match):
                if seat in held and self.prompt_for(game, match, seat) is not None:
                    return seat
        return game.seat_for(user_id, match.active)

    def switch_target(self, game: CodexGame, match, seat: int, user_id: int) -> Optional[int]:
        """The other acting seat the same person holds in a dragon's test
        game, where it has a question of its own -- what the panel's
        **Switch to** button sends -- or `None`."""
        if not match.dragons or match.winner is not None:
            return None
        held = game.seats_of(user_id)
        for other in self.engine.acting_seats(match):
            if other != seat and other in held and self.prompt_for(game, match, other) is not None:
                return other
        return None

    def tech_asked(self, game: CodexGame, match, seat: int) -> bool:
        """Whether `seat`'s turn waits on their tech -- the confirmation,
        or the picker where nothing was picked -- which **Tech** opens
        and **My hand** puts behind a Tech button (`TECH_GATE_KINDS`)."""
        prompt = self.prompt_for(game, match, seat)
        return prompt is not None and prompt.kind in TECH_GATE_KINDS

    # -- The panel -------------------------------------------------------------

    def panel_caption(self, game: CodexGame, prompt: PendingPrompt, extra: str = "",
                      hand: Optional[bool] = None) -> str:
        """The panel's text: the model's ask, rendered, what it tells
        the asked player alone (`PendingPrompt.told` -- the cards an
        effect discarded from their hand), what the view adds beneath
        it, and that it is the clicker's alone -- under the turn's lines
        so far (`with_turn_log`) where the panel pictures the hand:
        `hand`, or where not given, the prompt's kind (`TURN_LOG_KINDS`)."""
        lines = [self.render_text(prompt.ask, game)]
        lines.extend(self.render_text(line, game) for line in prompt.told)
        if extra:
            lines.append(extra)
        lines.append(PANEL_NOTE)
        text = "\n".join(lines)
        if hand is None:
            hand = prompt.kind in TURN_LOG_KINDS
        return self.with_turn_log(game, text) if hand else text

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
        # Whether the picture is the hand: the turn's lines go over it.
        hand = not private and (prompt.kind in TURN_LOG_KINDS
                                or (gate and prompt.kind not in PANEL_SIDE_KINDS))
        if private:
            files = [await self.choices_file(private)]
        elif prompt.kind is PromptKind.MAIN_ACTION:
            # The opponent's hand under one's own where Eyes of the
            # Chancellor reveals it -- to this player alone (step 13) --
            # and a dragon's teammate's, always (decision 13).
            files = [*await hand_files(self.engine, match, prompt.asked_player, prompt.options.hand),
                     *await revealed_files(self.engine, match, prompt.asked_player)]
            revealed = revealed_caption(self.engine, match, prompt.asked_player, game)
            if revealed:
                extra.append(revealed)
        elif prompt.kind in PANEL_SIDE_KINDS:
            files = [await self.side_file(game, match, prompt.asked_player, side_shown(prompt, self.engine.opponents(match, prompt.asked_player)))]
        elif prompt.kind in PANEL_HAND_KINDS or gate:
            files = await hand_files(self.engine, match, prompt.asked_player)
            if match.dragons:
                # The teammate's hand under one's own wherever the hand is
                # pictured (decision 13); a duel's reveal stays the main
                # phase's.
                files = [*files, *await revealed_files(self.engine, match, prompt.asked_player)]
                revealed = revealed_caption(self.engine, match, prompt.asked_player, game)
                if revealed:
                    extra.append(revealed)
        else:
            # The tech confirmation among them: the picks alone, so what
            # is confirmed is what is seen (the author, 2026-10-12: "remove
            # the hand from the 'confirm tech' view").
            picture = await self.render_prompt(game, prompt)
            files = [] if picture is None else [picture]
        return self.panel_caption(game, prompt, "\n".join(extra), hand=hand), files, view

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
                self.engine.board_reading,
            )
            return picture_file(webp, "codex-sides")
        webp = await asyncio.to_thread(
            render_side, match, seat, names[seat], self.engine.catalog, self.engine.board_reading,
        )
        return picture_file(webp, "codex-side")

    async def show_panel(self, interaction: discord.Interaction, game: CodexGame, match,
                         seat: int, *, edit: bool, standing: bool = False, note: str = "",
                         open_tech: bool = False) -> None:
        """
        Put up what `seat` is asked: **made afresh** as an ephemeral
        message (`edit=False` -- My hand, Tech, `/codex resume`) -- for a
        turn that waits on a tech choice its player never made, the hand
        pictured with **Tech** alone under it (`TechGateView`) until it
        is opened, or the picker at once where **Tech** was pressed
        (`open_tech`); saved picks open on their confirmation either way
        (the author, 2026-10-10) -- or **in place of the panel clicked**
        (`edit=True`, `put_panel`). The cog never looks for an old
        panel: an ephemeral message dies with the client's session, and
        every entry point makes a new one.
        """
        prompt = self.prompt_for(game, match, seat, standing)
        if prompt is None:
            if edit and match.dragons and seat in self.engine.turn_seats(match) and match.winner is None:
                # A teammate's panel the team has moved past -- their
                # teammate's action stands part-way, or they have locked:
                # the hand, why, and **Back to my turn** (decision 13).
                await self.put_waiting(interaction, game, match, seat, note)
            elif edit:
                await self.put_panel(interaction, NOTHING_ASKED, edit=True)
            elif owed_step(self.engine, game, match) is not None:
                await send_ephemeral(interaction, STEP_OWED)
            else:
                await self.send_hand(interaction, game, match, seat)
            return
        gate = not edit and not standing and not open_tech and prompt.kind is PromptKind.TECH_CHOICE
        started = time.perf_counter()
        content, files, view = await self.panel_parts(game, match, prompt, note, gate=gate)
        if not standing and view is not None and game.test_game:
            self.add_switch(view, game, match, seat, interaction.user.id)
        drawn = elapsed_ms(started)
        started = time.perf_counter()
        await self.put_panel(interaction, content, files, view, edit=edit)
        LOGGER.info(
            "Codex game #%s: the panel's picture drawn in %d ms (%d KB); the panel %s in %d ms",
            game.game_number, drawn, pictures_size(files) // 1024,
            "edited in place" if edit else "sent",
            elapsed_ms(started),
        )

    def add_switch(self, view: discord.ui.View, game: CodexGame, match, seat: int,
                   user_id: int) -> None:
        """
        **Switch to <name>** on a dragon test game's panel, where its one
        person holds the other acting seat too and it has a question of
        its own (decision 13): the panel edited in place to the other
        seat's (the author, 2026-10-15), with a Switch back. Named
        by the seat's player and, since every seat of a test game is the
        one person's, its team. Left off a panel with no room for it.
        """
        other = self.switch_target(game, match, seat, user_id)
        if other is None:
            return
        name = game.seat_name(other) or f"Player {other}"
        button = discord.ui.Button(
            label=f"Switch to {name} ({team_name(match.player(other).specs)})"[:80],
            style=discord.ButtonStyle.secondary,
        )

        async def switch(interaction: discord.Interaction) -> None:
            fresh = self.service.load(game)
            if self.prompt_for(game, fresh, other) is None:
                await send_ephemeral(interaction, NOTHING_ASKED)
                return
            await self.show_panel(interaction, game, fresh, other, edit=True)

        button.callback = switch
        try:
            view.add_item(button)
        except ValueError:
            # Five rows full: the other seat is still a My hand away.
            pass

    async def put_waiting(self, interaction: discord.Interaction, game: CodexGame, match,
                          seat: int, note: str = "") -> None:
        """
        A dragon seat's panel edited in place where the team's turn asks
        it nothing now -- the teammate's attack or effect stands part-way,
        or this seat has locked: its hand pictured, the teammate's under
        it, the reason, and **Back to my turn**, which asks again
        (`WaitingView`). The other seat's click is never lost: the driver
        refused it against the options as they stand.
        """
        mate_seat = self.engine.teammate(match, seat)
        mate = self.mate_name(game, mate_seat)
        theirs = self.prompt_for(game, match, mate_seat) if mate_seat is not None else None
        lines = [note] if note else []
        if match.player(seat).locked:
            lines.append(f"Your patrol is locked: your main phase is over. {mate} is still "
                         "playing, and your tech choice opens from **Tech** on the turn "
                         "message once the team's turn ends.")
        elif theirs is not None and theirs.kind in TECH_GATE_KINDS:
            lines.append(f"Waiting on {mate} to confirm their tech: the team's turn begins "
                         "once both of you have.")
        elif not note:
            what = "attack" if match.attacking is not None or match.combat is not None else "action"
            lines.append(f"Waiting on {mate}'s {what}.")
        files = [*await hand_files(self.engine, match, seat),
                 *await revealed_files(self.engine, match, seat)]
        revealed = revealed_caption(self.engine, match, seat, game)
        text = self.with_turn_log(game, "\n".join([*lines, *([revealed] if revealed else []), PANEL_NOTE]))
        await self.put_panel(interaction, text, files, WaitingView(self, game.game_id, seat), edit=True)

    @staticmethod
    def mate_name(game: CodexGame, seat: Optional[int]) -> str:
        """A teammate as the panel names them: the seat's player."""
        if seat is None:
            return "Your teammate"
        return game.seat_name(seat) or f"Player {seat}"

    async def put_panel(self, interaction: discord.Interaction, content: str,
                        files: Optional[list[discord.File]] = None,
                        view: Optional[discord.ui.View] = None, *,
                        edit: bool) -> None:
        """
        The panel's one write, two ways, both through the click's own
        webhook and none through the channel's bucket. `edit`: in place
        of the panel clicked -- the click's response, or, on a click
        deferred while the turn message was brought up to date, its
        original message (`edit_clicked`). Otherwise a new ephemeral
        message, the click's answer or its follow-up.
        """
        files = list(files or [])
        if edit:
            await edit_clicked(
                interaction, content=content, attachments=kept_pictures(files, interaction.message), view=view,
            )
            return
        kwargs: dict = {"ephemeral": True}
        if files:
            kwargs["files"] = files
        if view is not None:
            kwargs["view"] = view
        await send_answer(interaction, content, **kwargs)

    async def answer_panel(self, interaction: discord.Interaction, game: CodexGame,
                           seat: int, result: GameResult,
                           answered: Optional[PromptKind] = None) -> None:
        """
        The panel after its own click, with what is asked next: the next
        action, the defender, the patrol lock, the turn's actions once
        the tech is confirmed -- **edited in place** (`put_panel`).
        A tech save stays on the picker, saved -- or, in a test game,
        where the save is the ready phase's and the turn begins on it,
        becomes the turn's actions. The Lock that ends the turn becomes
        the tech picker, with no note above it; in a test game nothing
        stands to pick (`codex.prompts.tech_stands`), so the panel closes
        naming the side whose turn it is now, and the one person plays on
        from My hand.
        """
        match = result.match
        asked = result.prompts or ((result.prompt,) if result.prompt is not None else ())
        prompt = next((one for one in asked if one.asked_player == seat), None)
        standing = next((one for one in result.standing if one.asked_player == seat), None)
        if prompt is not None:
            await self.show_panel(interaction, game, match, seat, edit=True)
            return
        if match is not None and match.dragons and match.winner is None \
                and seat in self.engine.turn_seats(match):
            # The team's turn goes on without this seat for now: in a test
            # game, the one person's other seat, where it is asked
            # something; otherwise why it waits, the hand under it.
            other = self.switch_target(game, match, seat, interaction.user.id) if game.test_game else None
            await self.show_panel(interaction, game, match, seat if other is None else other, edit=True)
            return
        if standing is not None and answered is PromptKind.TECH_CHOICE:
            await self.show_panel(interaction, game, match, seat, edit=True, standing=True,
                                  note="**Saved.** You may change it until your turn begins.")
            return
        if standing is not None:
            await self.show_panel(interaction, game, match, seat, edit=True, standing=True)
            return
        if answered is PromptKind.PATROL and match is not None and seat not in self.engine.turn_seats(match) and match.winner is None:
            closing = self.turn_over_text(game, match, seat, result.prompt)
        elif match is not None and match.winner is not None:
            closing = "The game is over."
        else:
            closing = NOTHING_ASKED
        await self.put_panel(interaction, closing, edit=True)

    def turn_over_text(self, game: CodexGame, match, seat: int,
                       prompt: Optional[PendingPrompt]) -> str:
        """What the Lock's panel closes on where no tech picker follows
        it: in a test game, the side that ended and the side My hand
        opens, with its tech choice first where `prompt` is one."""
        if not game.test_game:
            return TURN_OVER_NOTHING_OWED
        tech = ", its tech choice first" if prompt is not None and prompt.kind is PromptKind.TECH_CHOICE else ""

        def sides(seats) -> str:
            # A dragon's team names both its seats' teams.
            return " and ".join(team_name(match.player(one).specs) for one in seats)

        return TURN_OVER_TEST.format(
            ended=sides(self.engine.dragon_of(match, seat)), begins=sides(self.engine.turn_seats(match)), tech=tech,
        )

    # -- The presenter ---------------------------------------------------------

    def goes_public(self, result: GameResult) -> bool:
        """Whether `present` puts anything in the channel for `result`:
        the turn ended, a base fell, or something was said or moved. A
        click that does is deferred while the turn message is brought up
        to date, and its panel edited after (`TurnPanelView.act`)."""
        match = result.match
        if match is not None and (split_at_turn_end(result)[3] or match.winner is not None):
            return True
        return bool(result.lines or result.board_changed)

    async def present(self, game: CodexGame, result: GameResult) -> None:
        """
        **The whole of the Discord side of a result.** What it said joins
        the turn's lines and the turn message is edited with them and the
        board, through the gate (`refresh_match_image`) -- or, where the
        model's end-of-turn step ran,
        the turn's message stands with
        its last lines and board and the next turn's goes up; or, where
        a base fell, the game's last line. Hidden information never
        reaches here: a result's lines are public (docs/design/codex.md,
        "What the narration may say"), and its prompts go to their asked
        player through the panel.
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
        if result.lines or result.board_changed:
            await self.refresh_match_image(game)

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
        ended.active = self.service.previous_turn_owner(game.game_id) or ended.active
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
        # The turn's first lines: what it said before its snapshot, which
        # the journal does not hold -- the ready phase's where no tech
        # was owed, nothing where the turn waits on its tech.
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
        self.boards_drawn.pop(game.game_id, None)
        await self.archive_channel(channel, game)

    # -- The undos ---------------------------------------------------------------

    def undo_choices(self, game: CodexGame) -> list[tuple[history.UndoPoint, str]]:
        """
        The points of this turn the fine undo may go back to
        (`GameService.undo_points`), oldest first, each with the label
        its menu option carries: the action's number and the first line
        it said, its tokens as words since a select's option carries no
        markup (`plain_text`) -- or, for an action that said nothing,
        what its button is called (`SILENT_ACTIONS`).
        """
        choices = []
        for point in self.service.undo_points(game.game_id):
            said = next((line for line in point.said if line), "")
            text = self.plain_text(said, game) if said else SILENT_ACTIONS.get(point.choice, "An action")
            choices.append((point, f"{point.number}. {text}"))
        return choices

    async def undo_to_turn_start(self, interaction: discord.Interaction, game: CodexGame,
                                 seat: int) -> None:
        """
        The active player's own undo: the turn's snapshot restored, the
        turn message edited with its first lines and "undone to the start
        of the turn" and the restored board, the panel edited in place
        from the new prompt. Nobody's consent is asked.
        """
        await self._own_undo(interaction, game, seat, lambda: self.service.undo_to_turn_start(game.game_id))

    async def undo_to(self, interaction: discord.Interaction, game: CodexGame, seat: int,
                      index: int, of: int) -> None:
        """
        The fine undo, the active player's own as the turn's start is:
        the match replayed to before one of this turn's actions
        (`GameService.undo_to`, a point `undo_choices` offered), the turn
        message edited with its first lines, the kept actions' lines and
        the undone line, and the restored board, the panel edited in
        place. Refused in the model's words for a point no
        longer offered.
        """
        await self._own_undo(interaction, game, seat, lambda: self.service.undo_to(game.game_id, index, of=of))

    async def _own_undo(self, interaction: discord.Interaction, game: CodexGame, seat: int,
                        undo: Callable[[], GameResult]) -> None:
        """An undo of the active player's own: `undo` through the
        service, then the turn message and the panel from the result."""
        match = self.service.load(game)
        if seat not in self.engine.turn_seats(match):
            await send_ephemeral(interaction, "Only the player whose turn it is can undo it.")
            return
        try:
            result = undo()
        except RuleRefusal as refused:
            await send_ephemeral(interaction, str(refused))
            return
        restored = result.match
        head = self.turn_heads.get(game.game_id, {}).get(restored.turn, [])
        self.turn_lines[game.game_id] = [*head, *result.lines]
        # The acknowledgement goes out beside the board, not before it
        # (`TurnPanelView.act`).
        await asyncio.gather(acknowledge(interaction), self.refresh_match_image(game))
        await self.show_panel(interaction, game, restored, seat, edit=True)

    async def ask_undo_to_previous_turn(self, interaction: discord.Interaction, game: CodexGame,
                                        seat: int, turn: int) -> None:
        """
        An undo to the start of the previous turn unwinds the opponent's
        turn too, so it is asked of them: a public message with their
        **Agree** (or a helper's) and **Refuse**. The panel goes back to
        the actions, saying it was asked.
        """
        match = self.service.load(game)
        if seat not in self.engine.turn_seats(match):
            await send_ephemeral(interaction, "Only the player whose turn it is can ask for that.")
            return
        # The seat whose turn is unwound: the previous turn's owner, off
        # its snapshot -- a duel's one opponent, a table's seat before.
        opponent = self.service.previous_turn_owner(game.game_id)
        if opponent is None:
            await self.show_panel(interaction, game, match, seat, edit=True,
                                  note="There is no previous turn to go back to.")
            return
        asker = game.seat_name(seat) or f"Player {seat}"
        duel = match.variant == "duel"
        # In a dragon the turn unwound was the other team's: either of its
        # players may agree (decision 15).
        agreeing = self.engine.dragon_of(match, opponent)
        ids = list(dict.fromkeys(one for one in (game.seat_user_id(other) for other in agreeing) if one))
        names = " and ".join(game.seat_name(other) or f"Player {other}" for other in agreeing)
        note = ("Your opponent has been asked to agree to the undo." if duel else
                "The other team has been asked to agree to the undo." if match.dragons else
                f"{names} has been asked to agree to the undo.")
        await self.show_panel(interaction, game, match, seat, edit=True, note=note)
        mention = ", ".join(f"<@{one}>" for one in ids) if ids else (names or "Opponent")
        whose, yours = ("your team's turn", "the end of it") if match.dragons else ("your turn", "the end of yours")
        await send_new_prompt(
            interaction,
            f"{mention}, {asker} asks to undo to the start of turn {turn - 1} -- {whose} -- "
            f"which takes back this turn and {yours}. Do you agree?",
            view=UndoConfirmView(self, game.game_id, seat, turn, opponent, agreeing),
            allowed_mentions=discord.AllowedMentions(
                users=[discord.Object(id=one) for one in ids] if ids else False,
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
            await edit_clicked(interaction, content=str(refused), view=None)
            return
        restored = result.match
        who = game.seat_name(seat) if seat is not None else interaction.user.display_name
        await edit_clicked(
            interaction, content=f"Undone to the start of turn {restored.turn}: agreed by {who}.", view=None,
        )
        await self._previous_turn_back(interaction, game, result, seat)

    async def undo_end_of_turn(self, interaction: discord.Interaction, game: CodexGame,
                               seat: int) -> None:
        """
        The player who ended the turn before this one takes its end back,
        with nobody's consent, while this turn has done nothing but open
        (`GameService.end_of_turn_owner`; the author, 2026-10-13): the
        ended turn replayed to its patrol, before the lock, and made
        current again as the undo to the previous turn makes it -- its
        message posted at the foot of the channel with its lines and the
        undone line, this turn's message and the ended turn's standing
        one deleted -- and the panel put up for them, on the patrol.
        """
        if seat not in self.service.end_of_turn_owners(game.game_id):
            await edit_clicked(
                interaction, content=opponent_started(game, self.service.load(game)), view=None,
            )
            return
        try:
            result = self.service.undo_end_of_turn(game.game_id)
        except RuleRefusal as refused:
            await edit_clicked(interaction, content=str(refused), view=None)
            return
        await edit_clicked(
            interaction, content=f"The end of turn {result.match.turn} is taken back.", view=None,
        )
        await self._previous_turn_back(interaction, game, result, seat)

    async def _previous_turn_back(self, interaction: discord.Interaction, game: CodexGame,
                                  result: GameResult, seat: Optional[int]) -> None:
        """The turn before the one that was current made current again by
        an undo: its message posted at the foot of the channel with its
        first lines and `result.lines`, the restored board and its
        buttons; the current turn's message deleted, and the restored
        turn's standing one; and the restored turn's player, where they
        clicked, a fresh panel under it."""
        restored = result.match
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
        if seat is not None and seat in self.engine.turn_seats(restored) and restored.winner is None:
            await self.show_panel(interaction, game, restored, seat, edit=False)

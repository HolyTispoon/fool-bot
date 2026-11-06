"""
The turn on Discord (docs/design/tnp.md, "The turn on Discord"): each
seat's panel, the answers it sends, and what a turn puts in the channel.

- **A panel** is one seat's, ephemeral, to its player alone: the seat's
  player board, the panel's words (`tnp.formatting`'s, off the prompt's
  options) and its controls (`cogs.tnp_views.panel_view`). A click is
  answered by redrawing the panel in place through the click's own
  response, which spends nothing from the channel's bucket; the board
  is drawn again only where the turn or the phase has moved since.
- **The table** is edited through the write gate (`BoardRefresher`,
  docs/design/rate-limits.md) as a seat locks in and as the map moves:
  who has locked in, and nothing of either plan.
- **What a turn posts** is the model's lines, one message an attack
  spot in March -- A, then B -- each with the map as that spot left it,
  and one for what follows; a lone lock-in posts nothing, the table
  saying it. A battle met in March is fought on its own message
  (`cogs/tnp/battles.py`), and a round's record is posted as it ends.

Every picture is drawn off the event loop (`asyncio.to_thread`).
Nothing here decides a rule.
"""

from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass, field, replace
from typing import Any, Optional, Sequence

import discord

from cogs.tnp.battles import ROUND_FILENAME, battle_key, fighting
from cogs.tnp_views import BATTLE_VIEWS, PanelState, panel_view, send_ephemeral
from tnp import tokens
from tnp.briefs import board_brief, map_brief
from tnp.catalog import Cost
from tnp.formatting import (
    battle_heading, board_caption, card_trade_lines, cards_lines, cost_text, map_caption,
    phase_heading, plan_lines, plan_offer_lines, pool_text, token_text, trade_lines,
)
from tnp.flow.result import FollowOnStep
from tnp.game import GameStatus, RuleRefusal, TnpGame
from tnp.prompts import SIMULTANEOUS, Action, PendingPrompt, PromptKind, prompt_for
from tnp.render import render_attack, render_board, render_map

LOGGER = logging.getLogger(__name__)

#: The map's file, and a board's: one name each, so an edit in place of
#: the table replaces the picture rather than adding one.
MAP_FILENAME = "tnp-map.png"
BOARD_FILENAME = "tnp-board-{seat}.png"

#: Discord's limits on a message: its text, and the files it carries.
MESSAGE_LENGTH = 2000
MESSAGE_FILES = 10
#: An attack's picture's name (`render_attack`).
ATTACK_FILENAME = "tnp-attack-{spot}-{area}.png"

#: What a seat's panel says while its seat is asked a battle's question.
BATTLE_ELSEWHERE = "Your battle question is on the battle message in the channel"


@dataclass
class Post:
    """One message a result posts (`plan_posts`): a March attack spot's
    ("part"), a battle round's record ("round", with the battle as the
    round left it and which battle), or the rest ("rest")."""

    kind: str
    lines: list
    part: Optional[str] = None
    battle: Any = None
    key: Optional[str] = None
    #: The attacks pictured on it, by area: `(spot, area, map brief)`.
    pictures: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PostPlan:
    """What a result posts, and the battle around it: `battle` the
    battle being fought at the end, `(key, its round's lines so far)`;
    `ended` the battle the record held that is over now; `settled`
    whether a battle's outcome went on the map."""

    posts: list
    battle: Optional[tuple] = None
    ended: Optional[str] = None
    settled: bool = False

#: Under a plan's controls.
PLAN_HINT = (
    "Choose what to change below. Every change is saved as you make it, and nobody sees "
    "any of it until both of you have locked in."
)


class TurnMixin:
    # -- Words the views ask for -----------------------------------------

    def area_words(self, area: str) -> str:
        return tokens.plain(tokens.area(area), self.catalog)

    def cost_words(self, materials: int, gold: int) -> str:
        return cost_text(Cost(materials, gold))

    def token_words(self, kind: str, count: int) -> str:
        return token_text(kind, int(count))

    # -- The table, through the gate ---------------------------------------

    def map_picture(self, match):
        """The map's brief where a run stops (`Batching.picture`): public
        by construction, so it may be drawn under a post."""
        return map_brief(match, map_caption(match))

    async def draw_map(self, brief) -> bytes:
        return await asyncio.to_thread(render_map, self.catalog, brief)

    async def render_match_png(self, game: TnpGame) -> bytes:
        """The table's map as it stands -- the gate's render, drawn when
        the gate writes."""
        return await self.draw_map(self.map_picture(self.service.load(game)))

    def match_file_from_png(self, game: TnpGame, png: bytes) -> discord.File:
        return discord.File(io.BytesIO(png), filename=MAP_FILENAME)

    def table_text_or_none(self, game: TnpGame) -> Optional[str]:
        """The table's words for the gate, or `None` -- the text left
        as it is -- where the match no longer loads."""
        try:
            return self.table_text(game, self.service.load(game))
        except Exception:
            LOGGER.exception("TNP game %s: the table's text could not be read.", game.game_id)
            return None

    def game_channel(self, game: TnpGame, fallback=None):
        return self.bot.get_channel(game.channel_id) or fallback

    def table_link(self, game: TnpGame) -> Optional[str]:
        if game.guild_id is None or game.channel_id is None or game.table_message_id is None:
            return None
        return f"https://discord.com/channels/{game.guild_id}/{game.channel_id}/{game.table_message_id}"

    # -- A seat's panel ------------------------------------------------------

    async def send_panels(self, interaction: discord.Interaction, game: TnpGame,
                          seats: Sequence[str]) -> None:
        """
        Each seat the clicker holds -- both, in a test game -- as an
        ephemeral message of its own: the seat's board, drawn for that
        seat alone, the panel's words and its controls. The click is
        acknowledged privately first, since a board drawn and uploaded
        can outlast Discord's three seconds.
        """
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
        match = self.service.load(game)
        for seat in seats:
            prompt = prompt_for(self.engine, game, match, seat)
            state = PanelState(drawn=(match.turn, match.phase))
            await interaction.followup.send(
                self.panel_text(game, match, seat, prompt, state),
                file=await self.board_file(match, seat),
                view=panel_view(self, game.game_id, seat, prompt, state) or discord.utils.MISSING,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    async def board_file(self, match, seat: str) -> discord.File:
        brief = board_brief(self.engine, match, seat, board_caption(match))
        png = await asyncio.to_thread(render_board, self.catalog, brief)
        return discord.File(io.BytesIO(png), filename=BOARD_FILENAME.format(seat=seat))

    def panel_text(self, game: TnpGame, match, seat: str, prompt: Optional[PendingPrompt],
                   state: PanelState = PanelState()) -> str:
        """
        A seat's panel in words: a refusal first where the last click
        was refused, whose board it is, its pool, and what it is asked
        -- the prompt's ask and its options in words, a plan's or a
        trade's as saved so far. **That seat's alone**: it reads the
        seat's own prompt and nothing of the other seat's.
        """
        lines = []
        if state.notice:
            lines.append(f"**Not done:** {state.notice}")
        lines += [
            self.render_text(f"{phase_heading(match)} -- your board, {tokens.seat(seat)}.", game),
            f"Pool: {pool_text(match.seat(seat).pool)}.",
        ]
        if prompt is None:
            if match.seat(seat).locked:
                lines.append("You have locked in. Nothing is shown to anyone until both of you have.")
            elif fighting(match):
                lines.append("A battle is being fought; the other seat is asked on its message.")
            else:
                lines.append("Nothing is asked of you now.")
            return "\n".join(lines)
        lines.append(self.render_text(prompt.ask, game))
        said: list[str] = []
        if prompt.kind is PromptKind.PLAN:
            said = (plan_lines(prompt.options) + plan_offer_lines(prompt.options)
                    + cards_lines(prompt.options) + [PLAN_HINT])
        elif prompt.kind is PromptKind.TRADE:
            said = card_trade_lines(prompt.options) if prompt.options.advanced else trade_lines(prompt.options)
        elif prompt.kind is PromptKind.TACTIC:
            said = [
                "Your tactic cards: " + ", ".join(
                    tokens.card(one.card) + ("" if one.card in prompt.options.applies else " (its units are not here)")
                    for one in prompt.options.cards
                ) + ".",
                "Nothing of your choice is shown until both seats have chosen.",
            ]
        elif prompt.kind in BATTLE_VIEWS:
            link = self.battle_link(game)
            said = [f"{BATTLE_ELSEWHERE}" + (f": {link}" if link else ".")]
        lines += [self.render_text(line, game) for line in said]
        return fit("\n".join(lines))

    async def answer_panel(self, interaction: discord.Interaction, view, action: Optional[Action],
                           state: PanelState) -> None:
        """
        A panel's click: `action` answered through the service, or with
        none the panel shown again in `state`; then the panel redrawn in
        place by the click's own response -- a refusal at its head --
        and, where the answer did something in public, that posted and
        the table edited (`present`).
        """
        game = view.game()
        if game is None or game.status is not GameStatus.PLAYING:
            await send_ephemeral(interaction, "This game is not being played.")
            return
        result = None
        if action is not None:
            try:
                result = self.service.apply_action(game.game_id, action)
            except RuleRefusal as refused:
                state = replace(state, notice=str(refused))
            else:
                if result.refused:
                    notice = result.refusal + (f" ({result.cite})" if result.cite else "")
                    state = replace(state, notice=notice)
        match = self.service.load(game) if result is None or result.refused else result.match
        seat = view.seat
        prompt = prompt_for(self.engine, game, match, seat)
        if prompt is not None and prompt.kind is not view.prompt.kind:
            # A new question: nothing of the last one's choices carries.
            state = PanelState(notice=state.notice, drawn=state.drawn)
        now = (match.turn, match.phase)
        new_view = panel_view(self, game.game_id, seat, prompt, replace(state, drawn=now))
        text = self.panel_text(game, match, seat, prompt, state)
        fields = dict(content=text, view=new_view, allowed_mentions=discord.AllowedMentions.none())
        if state.drawn != now:
            # The turn or the phase has moved: the board under the panel
            # is drawn again, through the click's own webhook.
            await interaction.response.defer()
            await interaction.edit_original_response(
                attachments=[await self.board_file(match, seat)], **fields,
            )
        else:
            await interaction.response.edit_message(**fields)
        if result is not None and not result.refused:
            await self.present(self.game_channel(game, interaction.channel), game, result, action)

    # -- What a turn posts ----------------------------------------------------

    def plan_posts(self, game: TnpGame, result) -> "PostPlan":
        """
        A result's lines as the messages they are posted in, and where a
        battle's round stands:

        - the groups a March attack spot closed (`Narration.part`, "A"
          then "B") one message a spot, with a picture for each attack in
          it -- the map around the area it resolved at (`Narration.area`),
          as the spot left it, with the piles revealed there;
        - **a battle round's record** where a round ended (a group closed
          at `END_ROUND`): what the round said before this click, kept on
          the record, and what it said in it, with the battle as the round
          left it -- the battle's outcome on the map (`SETTLE_BATTLE`'s
          own group) joined to its last round;
        - everything else -- March's end, Production, the trades, Cleanup
          -- one message after them with no picture, the table carrying
          the map;
        - and **while a battle is on at the end**, the lines of its round
          so far, for the battle message, rather than a post.
        """
        prior = game.battle_post or {}
        log_key, log = prior.get("key"), list(prior.get("lines") or [])
        posts: list[Post] = []
        settled = False
        for group in result.groups:
            lines = [line for line in group.lines if line]
            picture = group.picture
            if group.step is FollowOnStep.END_ROUND and picture is not None and picture.battle is not None:
                if picture.key != log_key:
                    log_key, log = picture.key, []
                posts.append(Post(
                    "round", [battle_heading(picture.battle), *log, *lines],
                    battle=picture.battle, key=picture.key,
                ))
                log = []
                continue
            if group.step is FollowOnStep.SETTLE_BATTLE:
                settled = True
                if posts:
                    posts[-1].lines += lines
                elif lines:
                    posts.append(Post("rest", lines))
                continue
            last = posts[-1] if posts else None
            if last is None or last.kind == "round" or last.part != group.part:
                last = Post("part" if group.part is not None else "rest", [], part=group.part)
                posts.append(last)
            last.lines += lines
            if group.part is not None and group.area is not None and picture is not None:
                # The latest picture of each area the spot resolved at,
                # in the order the spot first reached it.
                last.pictures[group.area] = (group.part, group.area, picture.map)
        tail = [line for line in result.narration if line]
        match = result.match
        battle = None
        if fighting(match):
            key = battle_key(match)
            battle = (key, (log if key == log_key else []) + tail)
        elif tail:
            if posts and posts[-1].kind == "rest":
                posts[-1].lines += tail
            else:
                posts.append(Post("rest", tail))
        ended = prior.get("key") if prior.get("key") and (battle is None or battle[0] != prior.get("key")) else None
        return PostPlan([post for post in posts if post.lines], battle, ended, settled)

    def lone_lock(self, result, action: Optional[Action]) -> bool:
        """A seat locking in while the other is still asked the same: the
        table says so, and nothing is posted."""
        return (
            action is not None and action.kind in SIMULTANEOUS and action.choice == "lock"
            and not result.groups
            and any(prompt.kind is action.kind for prompt in result.prompts)
        )

    def closing_lines(self, game: TnpGame, result) -> list[str]:
        """What a post ends on: where the questions now asked are
        answered -- **My board** on the table, or for a battle's, the
        battle message."""
        if not result.prompts:
            return []
        ping = " ".join(f"<@{user_id}>" for user_id in self.asked_players(game, result))
        ping = f"{ping} " if ping else ""
        if fighting(result.match):
            link = self.battle_link(game)
            where = f"the battle message ({link})" if link else "the battle message"
            return [f"{ping}{self.render_text(result.prompts[0].ask, game)} Answer on {where}."]
        link = self.table_link(game)
        where = f"**My board** on the table ({link})" if link else "**My board** on the table"
        if len(result.prompts) == 1 and result.prompts[0].kind not in SIMULTANEOUS:
            return [self.render_text(result.prompts[0].ask, game), f"{ping}Answer from {where}."]
        return [f"{ping}Open {where} to answer."]

    def handed_over(self, game: TnpGame, result, asked_before: Optional[str]) -> bool:
        """Whether a battle click passed the question to another person:
        the seat asked now is held by somebody other than whoever held
        the seat asked before -- never in a test game, one person in both
        seats."""
        if asked_before is None or not result.prompts:
            return False
        before = game.seats.get(asked_before, {}).get("id")
        return any(one != before for one in self.asked_players(game, result))

    def asked_players(self, game: TnpGame, result) -> list[int]:
        """The people asked something now, each once -- one person in both
        seats of a test game pinged once. The only mentions TNP makes: a
        post that ends on a question pings whoever must answer it (the
        author, 2026-11-06), and nothing else pings anyone."""
        found: list[int] = []
        for prompt in result.prompts:
            user_id = game.seats.get(prompt.asked_seat, {}).get("id")
            if user_id is not None and user_id not in found:
                found.append(user_id)
        return found

    async def present(self, channel, game: TnpGame, result, action: Optional[Action] = None, *,
                      clicked=None, fresh_battle: bool = False,
                      asked_before: Optional[str] = None) -> None:
        """
        What a result puts in public, in order: the battle message clicked
        redrawn through the click's own webhook (`clicked`); the posts,
        A then B, a round's record, then the rest (`plan_posts`), each its
        own send with its pictures; a battle that has just opened -- or,
        with `fresh_battle`, one being fought -- posted as its own
        message; the questions now asked named at the foot, whoever must
        answer pinged; and the table edited through the gate, unless only
        a battle moved. A save says nothing and moves nothing. A failed
        send is logged and the rest goes on -- the turn is saved.
        """
        if channel is None or result.refused:
            return
        quiet = self.lone_lock(result, action)
        plan = self.plan_posts(game, result)
        posts = [] if quiet else plan.posts
        match = result.match
        prior = game.battle_post or {}
        # The round records' pictures, drawn once each: the last of a
        # battle's is also its message's final picture.
        pngs: dict[int, bytes] = {}
        for index, post in enumerate(posts):
            if post.kind == "round":
                pngs[index] = await self.battle_png(post.battle)
        final = None
        if plan.ended is not None:
            for index, post in enumerate(posts):
                if post.kind == "round" and post.key == plan.ended:
                    final = (post, pngs[index])
        # The battle message: the clicked one redrawn, or a battle's end
        # put on it; a new battle's posted after the posts.
        new_battle = plan.battle is not None and (
            fresh_battle or prior.get("key") != plan.battle[0] or prior.get("id") is None
        )
        if plan.battle is not None:
            self.note_battle(game, key=plan.battle[0], lines=plan.battle[1])
        elif prior.get("key"):
            self.note_battle(game, key=None, lines=())
        if final is not None:
            post, png = final
            if clicked is not None:
                # The record's lines less its heading, which the
                # battle message has of its own.
                await self.edit_clicked_battle(clicked, game, match, post.lines[1:], picture=True,
                                               battle=post.battle, png=png)
            else:
                await self.edit_battle_message(channel, game, match, post.lines[1:], post.battle, png,
                                               message_id=prior.get("id"))
        elif plan.ended is not None:
            # Over with no round's end -- a base nobody defended once its
            # emergency defense was declined: its controls taken off.
            await self.close_battle_message(channel, clicked, game, prior.get("id"))
        elif plan.battle is not None and not new_battle:
            if clicked is not None:
                await self.edit_clicked_battle(clicked, game, match, plan.battle[1],
                                               picture=result.board_changed or bool(posts))
            else:
                await self.edit_battle_message(channel, game, match, plan.battle[1])
        pinged: list[int] = []
        if posts and not new_battle:
            closing = self.closing_lines(game, result)
            if closing:
                posts[-1].lines += closing
                pinged = self.asked_players(game, result)
        for index, post in enumerate(posts):
            text = "\n".join(self.render_text(line, game) for line in post.lines)
            last = index == len(posts) - 1
            files = []
            if post.kind == "round":
                files = [self.battle_file(pngs[index], ROUND_FILENAME.format(round=post.battle.round))]
            await self.post(channel, game, text, list(post.pictures.values())[:MESSAGE_FILES],
                            pinged if last else (), files=files)
        if new_battle:
            await self.post_battle_message(channel, game, match, plan.battle[1],
                                           self.asked_players(game, result))
        elif plan.battle is not None and not posts and self.handed_over(game, result, asked_before):
            # The battle's question passed to somebody else inside the
            # round, and no post of this click pings them already.
            await self.ping_the_asked(channel, game, result)
        table_moved = quiet or plan.settled or any(post.kind != "round" for post in posts) or (
            result.board_changed and plan.battle is None and plan.ended is None
        )
        if match is not None and match.winner is not None:
            # The win was announced in the lines above, once: the table
            # becomes the final message, and the channel is archived.
            await self.finish_game(channel, game)
        elif table_moved:
            await self.boards.refresh(channel, game)

    async def attack_file(self, spot: str, area: str, brief) -> discord.File:
        """One attack's picture: the map around `area`, with the piles
        revealed there (`render_attack`), drawn off the event loop."""
        png = await asyncio.to_thread(render_attack, self.catalog, brief, area, spot)
        return discord.File(io.BytesIO(png), filename=ATTACK_FILENAME.format(spot=spot, area=area))

    async def post(self, channel, game: TnpGame, text: str, pictures=(), pinged=(), files=()) -> None:
        """One message, with its attacks' pictures where it has any, and
        `files` drawn already (a round's battle) -- and where the text is
        longer than Discord takes, the rest in the messages after it, the
        pictures on the last. `pinged` are the users its mentions may
        ping; every other mention is inert."""
        chunks = split_text(text)
        drawn = list(files)
        for index, chunk in enumerate(chunks):
            files = []
            if index == len(chunks) - 1:
                files = drawn + [await self.attack_file(*picture) for picture in pictures]
            mentions = discord.AllowedMentions.none()
            if pinged:
                mentions = discord.AllowedMentions(
                    everyone=False, roles=False,
                    users=[discord.Object(id=user_id) for user_id in pinged],
                )
            try:
                await channel.send(chunk, allowed_mentions=mentions, **({"files": files} if files else {}))
            except discord.HTTPException as error:
                LOGGER.error("Could not post a turn's lines in TNP game %s: %s", game.game_id, error)
                return


def fit(text: str) -> str:
    """A panel's text cut to Discord's length."""
    return text if len(text) <= MESSAGE_LENGTH else text[: MESSAGE_LENGTH - 1] + "…"


def split_text(text: str) -> list[str]:
    """Text in messages of at most Discord's length, split at lines."""
    chunks, current = [], ""
    for line in text.split("\n"):
        while len(line) > MESSAGE_LENGTH:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:MESSAGE_LENGTH])
            line = line[MESSAGE_LENGTH:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > MESSAGE_LENGTH:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [""]


__all__ = ["BATTLE_ELSEWHERE", "BOARD_FILENAME", "MAP_FILENAME", "Post", "PostPlan", "TurnMixin", "split_text"]

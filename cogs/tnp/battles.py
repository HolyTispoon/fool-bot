"""
Battles on Discord (docs/design/tnp.md, "Battles on Discord"): a battle
met in March gets **its own message** -- the battle's picture, its
heading, what its round has said so far, and the question it is asking,
with the controls under it (`cogs.tnp_views.battle_view`).

- **The question is public, the controls the asked seat's.** A battle
  reveals every unit in it (TNP 6.1), so nothing on its message is
  hidden; only the asked seat's player may click.
- **A click redraws the message through the click's own response** --
  deferred, then edited through the click's webhook, the picture drawn
  again where the battle moved -- which spends nothing from the
  channel's bucket (docs/design/rate-limits.md). No other request
  edits it, except the rare battle a `/tnp resume` moves on.
- **A round is posted once, as its record**, when it ends: everything
  the round said, every roll whole, with the battle as the round left
  it. That send is the round's one request on the channel; the table is
  left alone until the battle's outcome moves the map.
- **What the round has said so far** is kept on the record
  (`TnpGame.battle_post`), since each click hands back only its own
  lines, so a restart loses none of it.

Every picture is drawn off the event loop (`asyncio.to_thread`).
Nothing here decides a rule.
"""

from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass
from typing import Any, Optional

import discord

from cogs.tnp_views import BATTLE_VIEWS, BattleHeld, battle_view, send_ephemeral
from tnp import tokens
from tnp.battle import ROUND, BattleState
from tnp.formatting import battle_heading, battle_offer_lines
from tnp.game import GameStatus, RuleRefusal, TnpGame
from tnp.prompts import PendingPrompt
from tnp.render import render_battle

LOGGER = logging.getLogger(__name__)

#: The battle message's picture, and a round record's: one name each,
#: so an edit in place replaces the picture rather than adding one.
BATTLE_FILENAME = "tnp-battle.png"
ROUND_FILENAME = "tnp-battle-round-{round}.png"

#: Discord's limit on a message's text.
MESSAGE_LENGTH = 2000


@dataclass(frozen=True)
class Picture:
    """What the cog keeps of a position where a run stops
    (`Batching.picture`): the map's brief, public by construction, and,
    while a battle is on, a copy of the battle there and which battle it
    is (`battle_key`) -- a run goes on past the round it pictures."""

    map: Any
    battle: Optional[BattleState] = None
    key: Optional[str] = None


def battle_key(match) -> Optional[str]:
    """Which battle the match is fighting: the turn, the attack spot and
    the area -- one attack a spot at an area, so one battle. `None`
    where none is."""
    battle = match.battle if match is not None else None
    if battle is None:
        return None
    spot = (match.resolving or {}).get("spot") or "-"
    return f"{match.turn}:{spot}:{battle.territory}"


def fighting(match) -> bool:
    """Whether the match is in a battle that is not over."""
    return match is not None and match.battle is not None and match.battle.outcome is None


class BattleMixin:
    # -- Pictures and words ------------------------------------------------

    def position_picture(self, match) -> Picture:
        """
        The picture kept where a run stops (`Batching.picture`). At a
        round's end the round track has already moved up for the next
        round (TNP 6.10), so the copy kept of the battle is put back on
        the round that ended: the picture under a round's record is the
        line as that round left it, numbered as that round. A copy, and
        drawn only -- the match is not touched.
        """
        battle = None
        if match.battle is not None:
            battle = BattleState.from_dict(match.battle.to_dict())
            if battle.outcome is None and battle.phase == ROUND and battle.round > 1:
                battle.round -= 1
        return Picture(self.map_picture(match), battle, battle_key(match))

    def plain_words(self, text: str) -> str:
        """A token string in plain words, for a control's label: "Blue",
        never a player's name."""
        return tokens.plain(text, self.catalog)

    async def battle_png(self, battle: BattleState) -> bytes:
        return await asyncio.to_thread(render_battle, self.catalog, battle)

    @staticmethod
    def battle_file(png: bytes, name: str = BATTLE_FILENAME) -> discord.File:
        return discord.File(io.BytesIO(png), filename=name)

    def battle_link(self, game: TnpGame) -> Optional[str]:
        post = game.battle_post or {}
        if game.guild_id is None or game.channel_id is None or post.get("id") is None:
            return None
        return f"https://discord.com/channels/{game.guild_id}/{game.channel_id}/{post['id']}"

    def battle_prompt(self, game: TnpGame, match) -> Optional[PendingPrompt]:
        """The battle's one question now, or `None` -- one seat at a time,
        so never two (docs/design/tnp.md, "The battle")."""
        if not fighting(match):
            return None
        for prompt in self.service.prompts(game, match):
            if prompt.kind in BATTLE_VIEWS:
                return prompt
        return None

    def battle_lines(self, game: TnpGame, match) -> list[str]:
        """What the battle's round has said so far, as kept on the record,
        where it is this battle's."""
        post = game.battle_post or {}
        if post.get("key") != battle_key(match):
            return []
        return list(post.get("lines") or [])

    def battle_text(self, game: TnpGame, battle: BattleState, lines, prompt: Optional[PendingPrompt],
                    notice: Optional[str] = None) -> str:
        """
        The battle message's words: a notice once, the heading, what the
        round has said so far -- its latest lines where they are more than
        a message holds, the round's record carrying them all -- and the
        question, with what its options offer beyond the controls.
        """
        head = [f"**Not done:** {notice}"] if notice else []
        head.append(self.render_text(battle_heading(battle), game))
        foot: list[str] = []
        if prompt is not None:
            foot.append(f"**Now:** {self.render_text(prompt.ask, game)}")
            foot += [self.render_text(line, game) for line in battle_offer_lines(prompt)]
        elif battle.outcome is not None:
            foot.append("The battle is over; March goes on below.")
        body = [self.render_text(line, game) for line in lines if line]
        room = MESSAGE_LENGTH - len("\n".join(head + foot)) - 2
        kept: list[str] = []
        for line in reversed(body):
            if len(line) + 1 + sum(len(one) + 1 for one in kept) > room - 2:
                kept.insert(0, "…")
                break
            kept.insert(0, line)
        text = "\n".join(head + kept + foot)
        return text if len(text) <= MESSAGE_LENGTH else text[: MESSAGE_LENGTH - 1] + "…"

    def battle_controls(self, game: TnpGame, battle: BattleState, prompt: Optional[PendingPrompt],
                        held: BattleHeld = BattleHeld()):
        """The controls under the battle message, or `discord.utils.MISSING`
        for an edit's `view=None` where it asks nothing."""
        return battle_view(self, game.game_id, prompt, battle, held)

    # -- The record of the battle message ---------------------------------------

    def note_battle(self, game: TnpGame, *, key: Optional[str], lines, message_id: Optional[int] = None) -> None:
        """What the record keeps of the battle message: its id, which
        battle, and the round's lines so far; `key` `None` forgets it
        between battles. Saved, as `post_table` saves the table's id."""
        if key is None:
            game.battle_post = None
        else:
            post = dict(game.battle_post or {})
            if post.get("key") != key:
                post = {"id": None}
            post.update(key=key, lines=list(lines))
            if message_id is not None:
                post["id"] = message_id
            game.battle_post = post
        self.service.save()

    def restore_battle_view(self, game: TnpGame) -> None:
        """The startup sweep's part: a battle being fought has its controls
        re-armed on its message by id, built from the question as it
        stands, `restored` so a button that would send what a view held
        shows the question afresh."""
        post = game.battle_post or {}
        if post.get("id") is None or self.service is None:
            return
        match = self.service.load(game)
        if battle_key(match) != post.get("key"):
            return
        view = battle_view(self, game.game_id, self.battle_prompt(game, match), match.battle,
                           restored=True)
        if view is not None:
            self.bot.add_view(view, message_id=post["id"])

    # -- A click on the battle message ------------------------------------------------

    async def answer_battle(self, interaction: discord.Interaction, view, action) -> None:
        """
        A battle click: acknowledged first (a picture drawn and uploaded
        can outlast Discord's three seconds), answered through the
        service, and then the battle message redrawn through the click's
        own webhook and whatever the answer did in public posted
        (`present`). A refusal is told to the clicker alone and the
        message put back to the question as it stands.
        """
        game = view.game()
        if game is None or game.status is not GameStatus.PLAYING:
            await send_ephemeral(interaction, "This game is not being played.")
            return
        await interaction.response.defer()
        try:
            result = self.service.apply_action(game.game_id, action)
        except RuleRefusal as refused:
            notice, result = str(refused), None
        else:
            notice = None
            if result.refused:
                notice = result.refusal + (f" ({result.cite})" if result.cite else "")
        if notice is not None:
            await send_ephemeral(interaction, f"Not done: {notice}")
            match = self.service.load(game)
            await self.edit_clicked_battle(interaction, game, match, self.battle_lines(game, match),
                                           picture=False)
            return
        await self.present(self.game_channel(game, interaction.channel), game, result, action,
                           clicked=interaction)

    async def redraw_battle(self, interaction: discord.Interaction, view, held: BattleHeld) -> None:
        """The same question shown with what the view holds changed -- a
        force chosen, a count -- through the click's own response. Where
        the question has moved on since the view was drawn, it is shown as
        it now stands."""
        game = view.game()
        if game is None or game.status is not GameStatus.PLAYING:
            await send_ephemeral(interaction, "This game is not being played.")
            return
        match = self.service.load(game)
        prompt = self.battle_prompt(game, match)
        if prompt is None or prompt.kind is not view.prompt.kind or prompt.asked_seat != view.prompt.asked_seat:
            held = BattleHeld()
        battle = match.battle
        if battle is None:
            await send_ephemeral(interaction, "That battle is over.")
            return
        await interaction.response.edit_message(
            content=self.battle_text(game, battle, self.battle_lines(game, match), prompt, held.notice),
            view=self.battle_controls(game, battle, prompt, held),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def edit_clicked_battle(self, interaction, game: TnpGame, match, lines, *,
                                  picture: bool, battle: Optional[BattleState] = None,
                                  png: Optional[bytes] = None) -> None:
        """The clicked battle message edited through the click's webhook:
        the battle `battle` (the match's by default), its lines and its
        question; the picture uploaded again where `picture` says it
        moved. A failure is logged; the answer is saved."""
        battle = battle if battle is not None else match.battle
        if battle is None:
            return
        prompt = self.battle_prompt(game, match) if battle is match.battle else None
        fields: dict = dict(
            content=self.battle_text(game, battle, lines, prompt),
            view=self.battle_controls(game, battle, prompt),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        if picture:
            fields["attachments"] = [self.battle_file(png if png is not None else await self.battle_png(battle))]
        try:
            await interaction.edit_original_response(**fields)
        except discord.HTTPException as error:
            LOGGER.error("Could not redraw the battle message of TNP game %s: %s", game.game_id, error)

    async def post_battle_message(self, channel, game: TnpGame, match, lines, pinged=()) -> None:
        """A battle's own message sent: its picture, its words and its
        controls, pinging whoever is asked (the author, 2026-11-06, on
        PR #712); its id kept on the record so a restart re-arms it. One
        send."""
        battle = match.battle
        prompt = self.battle_prompt(game, match)
        text = self.battle_text(game, battle, lines, prompt)
        if pinged:
            text = " ".join(f"<@{user_id}>" for user_id in pinged) + "\n" + text
            text = text if len(text) <= MESSAGE_LENGTH else text[: MESSAGE_LENGTH - 1] + "…"
        mentions = discord.AllowedMentions.none()
        if pinged:
            mentions = discord.AllowedMentions(
                everyone=False, roles=False, users=[discord.Object(id=one) for one in pinged],
            )
        view = self.battle_controls(game, battle, prompt)
        try:
            message = await channel.send(
                text, file=self.battle_file(await self.battle_png(battle)),
                allowed_mentions=mentions, **({"view": view} if view is not None else {}),
            )
        except discord.HTTPException as error:
            LOGGER.error("Could not post the battle of TNP game %s; it needs /tnp resume: %s",
                         game.game_id, error)
            self.note_battle(game, key=battle_key(match), lines=lines)
            return
        self.note_battle(game, key=battle_key(match), lines=lines, message_id=message.id)

    async def close_battle_message(self, channel, clicked, game: TnpGame,
                                   message_id: Optional[int]) -> None:
        """A battle that ended with no round's record to picture it: its
        message told so and its controls taken off -- through the click's
        webhook where it was clicked, else the channel."""
        fields = dict(content="**This battle is over.** What it came to is posted below.",
                      view=None, allowed_mentions=discord.AllowedMentions.none())
        try:
            if clicked is not None:
                await clicked.edit_original_response(**fields)
            elif message_id is not None and channel is not None:
                await channel.get_partial_message(message_id).edit(**fields)
        except discord.HTTPException as error:
            LOGGER.error("Could not close the battle message of TNP game %s: %s", game.game_id, error)

    async def edit_battle_message(self, channel, game: TnpGame, match, lines, battle=None,
                                  png: Optional[bytes] = None, message_id: Optional[int] = None) -> None:
        """The battle message edited through the channel -- one request
        from its bucket, made only where a battle moved without a click on
        its message (a `/tnp resume` that ran an owed step)."""
        post = dict(game.battle_post or {})
        if message_id is not None:
            post["id"] = message_id
        battle = battle if battle is not None else match.battle
        if post.get("id") is None or channel is None or battle is None:
            return
        prompt = self.battle_prompt(game, match) if battle is match.battle else None
        view = self.battle_controls(game, battle, prompt)
        try:
            await channel.get_partial_message(post["id"]).edit(
                content=self.battle_text(game, battle, lines, prompt),
                attachments=[self.battle_file(png if png is not None else await self.battle_png(battle))],
                view=view, allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as error:
            LOGGER.error("Could not edit the battle message of TNP game %s: %s", game.game_id, error)


__all__ = ["BATTLE_FILENAME", "BattleMixin", "Picture", "ROUND_FILENAME", "battle_key", "fighting"]

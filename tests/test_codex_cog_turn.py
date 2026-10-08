"""
A Codex turn through the cog, with Discord faked (docs/codex-bot.md,
step 4): the active player's panel, opened from **My hand** and edited
in place by its own clicks; the turn message edited once per action
through the gate; the turn's end -- the old message standing without
its buttons, the new one posted and pinned, the tech picker sent to the
player whose turn ended; the tech choice answered while the other
player's panel is open; a stale panel refused with the driver's words;
and the two undos.

**The requests per click are counted here** (`tests/codex_cog_fakes.py`
logs every request by route): the channel's bucket against the
interaction's own webhook, which spends nothing from it
(docs/design/rate-limits.md; docs/design/codex.md, "The turn on
Discord").
"""

from __future__ import annotations

import unittest
from unittest import mock

from codex import history
from codex.flow.driver import STALE_CLICK
from codex.prompts import PromptKind
from codex_cog_fakes import Table
from codex_positions import put
from cogs.codex_views import (
    NOT_YOUR_PANEL,
    PatrolView,
    TechChoiceView,
    TechConfirmView,
    TurnMessageView,
    TurnPanelView,
    UndoConfirmView,
)

CHANNEL_REQUESTS = ("send", "edit", "pin", "unpin", "delete")


def channel_requests(table: Table, mark: int) -> list[tuple[str, int]]:
    return [(kind, message_id) for kind, message_id, _ in table.game_channel.since(mark)
            if kind in CHANNEL_REQUESTS]


def playable(view) -> list[str]:
    return [row.slug for row in view.prompt.options.playable if row.allowed]


class TurnTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.table = Table()
        self.addCleanup(self.table.close)
        self.game = await self.table.started()

    def assertNothingWentWrong(self, call) -> None:
        for kind, args, kwargs in call.answers:
            text = kwargs.get("content") or (args[0] if args else "") or ""
            self.assertNotIn("Something went wrong", text)

    async def end_turn(self, patrol: str | None = None):
        """End the active player's main phase and lock the patrol --
        `patrol`, a ref, as squad leader -- from a fresh panel."""
        _, view = await self.table.panel()
        call = await self.table.press(view, "End main phase")
        view = call.view()
        if patrol is not None:
            view = (await self.table.choose(view, "Who patrols", patrol)).view()
        lock = await self.table.press(view, "Lock patrol")
        self.assertNothingWentWrong(lock)
        return lock


class PanelTests(TurnTestCase):
    async def test_my_hand_opens_the_panel_for_the_active_player(self) -> None:
        call, view = await self.table.panel()
        kind, _, kwargs = call.last()
        self.assertEqual(kind, "response.send")
        self.assertTrue(kwargs["ephemeral"])
        self.assertIsInstance(view, TurnPanelView)
        self.assertEqual(kwargs["files"][0].filename, "codex-hand.png")
        # The other player's My hand is their hand, with nothing to press.
        theirs = await self.table.turn_button("hand", self.table.waiting)
        self.assertNotIn("view", theirs.last()[2])
        self.assertEqual(theirs.last()[2]["file"].filename, "codex-hand.png")

    async def test_an_action_is_one_panel_edit_and_one_turn_message_edit(self) -> None:
        """**The count per click**: the panel's edit through the click's
        own response, and one edit of the turn message through the gate
        -- nothing else, and no channel send."""
        _, view = await self.table.panel()
        mark = len(self.table.game_channel.requests)
        call = await self.table.choose(view, "Play a card", playable(view)[0])
        self.assertNothingWentWrong(call)
        self.assertEqual([answer[0] for answer in call.answers], ["response.edit"])
        self.assertIsInstance(call.view(), TurnPanelView)
        self.assertEqual(
            channel_requests(self.table, mark), [("edit", self.game.turn_message_id)],
        )

    async def test_a_choice_that_changes_nothing_public_spends_nothing(self) -> None:
        """Ending the main phase moves nothing a board draws and says
        nothing: the panel turns to the patrol lock, and the channel
        hears nothing."""
        _, view = await self.table.panel()
        mark = len(self.table.game_channel.requests)
        call = await self.table.press(view, "End main phase")
        self.assertIsInstance(call.view(), PatrolView)
        self.assertEqual(channel_requests(self.table, mark), [])

    async def test_a_click_by_anybody_else_is_refused_privately(self) -> None:
        _, view = await self.table.panel()
        before = self.table.match.to_dict()
        call = await self.table.press(view, "End main phase", who=self.table.waiting)
        kind, args, kwargs = call.last()
        self.assertEqual(kind, "response.send")
        self.assertTrue(kwargs["ephemeral"])
        self.assertEqual(args[0], NOT_YOUR_PANEL)
        self.assertEqual(self.table.match.to_dict(), before)

    async def test_a_stale_panel_is_refused_with_the_drivers_words(self) -> None:
        _, first = await self.table.panel()
        _, second = await self.table.panel()
        await self.table.press(first, "End main phase")
        call = await self.table.choose(second, "Play a card", playable(second)[0])
        kind, args, kwargs = call.last()
        self.assertTrue(kwargs["ephemeral"])
        self.assertEqual(args[0], STALE_CLICK[PromptKind.MAIN_ACTION])
        self.assertEqual(self.table.match.phase, "patrol")

    async def test_an_attack_asks_its_defender_in_the_same_panel(self) -> None:
        """The attacker first, then the legal defenders, each with why it
        is legal; Cancel takes the attacker back."""
        match = self.table.match
        seat = match.active
        attacker = put(match, seat, "older_brother")
        self.table.cog.service.persist(self.game, match)
        _, view = await self.table.panel()
        call = await self.table.choose(view, "Attack with", attacker.ref)
        defending = call.view()
        self.assertIsInstance(defending, TurnPanelView)
        self.assertIs(defending.prompt.kind, PromptKind.CHOOSE_DEFENDER)
        labels = [option.label for option in defending.children[0].options]
        self.assertTrue(labels)
        self.assertTrue(all(label.endswith("-- nothing is patrolling") for label in labels))
        cancelled = await self.table.press(defending, "Cancel the attack")
        self.assertIs(cancelled.view().prompt.kind, PromptKind.MAIN_ACTION)
        self.assertIsNone(self.table.match.attacking)

    async def test_the_hand_never_reaches_the_channel(self) -> None:
        """Every line the channel is sent or edited to is the header, the
        cog's caption, or a line of the model's narration -- which is
        public (docs/design/codex.md, "What the narration may say"):
        nothing of a hand, a hire's card or a tech choice. The lobby, in
        the same channel since the game is played where it was opened,
        is the lobby's own text."""
        _, view = await self.table.panel()
        view = (await self.table.choose(view, "Play a card", playable(view)[0])).view()
        view = (await self.table.press(view, "Hire worker")).view()
        hire = await self.table.choose(view, "Hire a worker", view.prompt.options.hand[0].slug)
        self.assertNothingWentWrong(hire)
        await self.end_turn()
        tech = await self.table.turn_button("tech", self.table.waiting)
        picker = tech.view()
        values = [option.value for option in picker.select.options[:2]]
        await self.table.choose(picker, "Choose", *values)
        rendered = {self.table.cog.render_text(line, self.game) for line in self.table.said}
        lobby = self.game.message_id
        texts = [kwargs["content"] for kind, message_id, kwargs in self.table.game_channel.requests
                 if kind in ("send", "edit") and kwargs.get("content") and message_id != lobby]
        for text in texts:
            for line in text.split("\n"):
                with self.subTest(line=line):
                    self.assertTrue(
                        line.startswith("**Turn ") or line.startswith("*") or line in rendered,
                        line,
                    )


class TurnEndTests(TurnTestCase):
    async def test_the_lock_ends_the_turn_and_rolls_the_message_over(self) -> None:
        old = self.game.turn_message_id
        ending = self.table.active
        mark = len(self.table.game_channel.requests)
        lock = await self.end_turn()

        # The panel closes, and the tech picker follows, to them alone.
        kinds = [answer[0] for answer in lock.answers]
        self.assertEqual(kinds, ["response.edit", "followup.send"])
        self.assertIsNone(lock.answers[0][2]["view"])
        followup = lock.answers[1][2]
        self.assertTrue(followup["ephemeral"])
        self.assertIsInstance(followup["view"], TechChoiceView)
        self.assertEqual(followup["view"].seat, self.game.seat_of(ending.id))

        # The channel: the old message's last edit, without its buttons;
        # the new one posted, pinned, the old one unpinned. Four requests.
        new = self.game.turn_message_id
        self.assertNotEqual(new, old)
        self.assertEqual(
            channel_requests(self.table, mark),
            [("edit", old), ("send", new), ("pin", new), ("unpin", old)],
        )
        last_edit = self.table.game_channel.since(mark)[0][2]
        self.assertIsNone(last_edit["view"])
        self.assertIn("draws", last_edit["content"])
        self.assertIn("**Turn 1**", last_edit["content"])
        self.assertIsInstance(self.table.game_channel.views[new], TurnMessageView)
        # The model's heading, rendered: the turn, its player as a
        # mention -- which the post pings -- and their deck.
        match = self.table.match
        player_id = self.game.player_1_id if match.active == 1 else self.game.player_2_id
        heading = f"**Turn 2** -- <@{player_id}> ({match.active_player.spec.title()})"
        self.assertTrue(self.table.game_channel.texts[new].startswith(heading + "\n"))
        self.assertEqual(self.table.game_channel.texts[new].count("**Turn 2**"), 1)
        mentioned = self.table.game_channel.since(mark)[1][2]["allowed_mentions"].users
        self.assertEqual([user.id for user in mentioned], [player_id])
        self.assertEqual(self.game.previous_turn_message_id, old)
        self.assertEqual(self.table.game_channel.pinned, {new})

    async def test_a_turn_that_waits_on_its_tech_says_so_and_confirms_from_my_hand(self) -> None:
        """From turn 3 on, the new turn opens on its player's tech
        confirmation: the turn message says it waits on them, and My hand
        is the confirmation; Confirm runs the ready phase and turns the
        panel into the turn's actions."""
        first = self.table.active
        lock = await self.end_turn()
        picker = lock.answers[1][2]["view"]
        values = [option.value for option in picker.select.options[:2]]
        picked = await self.table.choose(picker, "Choose", *values)
        saved = await self.table.press(picked.view(), "Save tech")
        self.assertNothingWentWrong(saved)
        self.assertIn("Saved", saved.text())

        await self.end_turn()
        self.assertIs(self.table.active, first)
        self.assertEqual(self.table.match.phase, "ready")
        text = self.table.game_channel.texts[self.game.turn_message_id]
        self.assertIn("waits on", text)
        self.assertIn("**Turn 3**", text)

        call, view = await self.table.panel(first)
        self.assertIsInstance(view, TechConfirmView)
        confirmed = await self.table.press(view, "Confirm")
        self.assertNothingWentWrong(confirmed)
        self.assertIsInstance(confirmed.view(), TurnPanelView)
        self.assertEqual(self.table.match.phase, "main")
        text = self.table.game_channel.texts[self.game.turn_message_id]
        self.assertNotIn("waits on", text)
        self.assertIn("2 tech cards", text)

    async def test_the_tech_choice_is_answerable_while_the_other_panel_is_open(self) -> None:
        await self.end_turn()
        _, active_panel = await self.table.panel()
        tech = await self.table.turn_button("tech", self.table.waiting)
        picker = tech.view()
        self.assertIsInstance(picker, TechChoiceView)
        values = [option.value for option in picker.select.options[:2]]
        picked = await self.table.choose(picker, "Choose", *values)
        mark = len(self.table.game_channel.requests)
        saved = await self.table.press(picked.view(), "Save tech")
        self.assertNothingWentWrong(saved)
        self.assertIsNotNone(self.table.match.player(picker.seat).tech_choice)
        # Saved privately and said nowhere: a tech choice is announced in
        # its owner's ready phase alone (the author, 2026-10-08).
        self.assertEqual(channel_requests(self.table, mark), [])
        # The active player's panel, opened before, still acts.
        played = await self.table.choose(active_panel, "Play a card", playable(active_panel)[0])
        self.assertNothingWentWrong(played)
        self.assertEqual([answer[0] for answer in played.answers], ["response.edit"])

    async def test_tech_is_the_other_players_alone(self) -> None:
        call = await self.table.turn_button("tech", self.table.active)
        self.assertTrue(call.last()[2]["ephemeral"])
        self.assertNotIn("view", call.last()[2])


class WholeGameTests(TurnTestCase):
    async def test_two_players_finish_a_game_through_the_panel(self) -> None:
        """
        A whole game of the vanilla engine, every click a panel's or the
        turn message's, under a simple policy -- summon, play the first
        playable card, build the next tech building, attack the first
        legal defender, lock an empty patrol, tech the first two -- to a
        destroyed base. **Every click is held to the budget**: one
        channel request at most, none for a tech choice, four at the
        turn's end (the old
        message's last edit, the new one's post, pin and unpin), two at
        the game's end (the last edit and the winner's line). The
        panel's pictures are stood in for; drawing them is not the
        subject here.
        """
        table = self.table
        budget = {"click": 1, "turn": 4, "end": 2}
        with mock.patch("cogs.codex_views.turn_message.render_hand", return_value=b"hand"), \
                mock.patch("cogs.codex.core.render_codex", return_value=b"codex"), \
                mock.patch("cogs.codex.core.render_hand", return_value=b"hand"):
            for _ in range(200):
                if table.match.winner is not None:
                    break
                call, view = await table.panel()
                while table.match.winner is None:
                    turn = table.match.turn
                    mark = len(table.game_channel.requests)
                    call = await self.policy(view)
                    self.assertNothingWentWrong(call)
                    spent = len(channel_requests(table, mark))
                    match = table.match
                    allowed = budget["end"] if match.winner else budget["turn"] if match.turn != turn else budget["click"]
                    self.assertLessEqual(spent, allowed)
                    if match.turn != turn:
                        # The tech picker the Lock sent: its owner's
                        # clicks, each held to the click's budget.
                        picker = call.view()
                        if isinstance(picker, TechChoiceView) and match.winner is None:
                            mark = len(table.game_channel.requests)
                            await self.policy(picker)
                            self.assertEqual(channel_requests(table, mark), [])
                        break
                    view = call.view()
        self.assertIsNotNone(table.match.winner)
        self.assertIn("wins", table.game_channel.requests[-1][2]["content"])

    async def policy(self, view):
        table = self.table
        if isinstance(view, TechConfirmView):
            return await table.press(view, "Confirm")
        if isinstance(view, TechChoiceView):
            # Choosing redraws the picker in place and spends nothing
            # public; only the save is said.
            who = table.seated(view.seat)
            values = [option.value for option in view.select.options[:view.prompt.options.maximum]]
            picked = (await table.choose(view, "Choose", *values, who=who)).view()
            return await table.press(picked, "Save tech", who=who)
        if isinstance(view, PatrolView):
            return await table.press(view, "Lock patrol")
        options = view.prompt.options
        if view.prompt.kind is PromptKind.CHOOSE_DEFENDER:
            return await table.choose(view, "", options.defenders[0])
        if options.hero.action == "summon" and not options.hero.why_not:
            return await table.press(view, "Summon")
        cards = [row for row in options.playable if row.allowed]
        if cards:
            return await table.choose(view, "Play a card", cards[0].slug)
        tech = [row for row in options.buildings if row.allowed and row.building.startswith("tech")]
        if tech:
            return await table.choose(view, "Build", tech[0].building)
        if options.attackers:
            return await table.choose(view, "Attack with", options.attackers[0])
        return await table.press(view, "End main phase")


class TestGameTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_person_plays_both_sides_from_the_panel(self) -> None:
        """A test game seats one person in both seats: the panel is the
        active side's either way, across the turn's end, and Tech is the
        other side's."""
        from cogs.codex_views import LobbyView

        table = Table()
        self.addCleanup(table.close)
        call = table.interaction(table.basher, table.lobby_channel)
        await table.cog.lobby.callback(table.cog, call, test_game=True)
        (game,) = table.cog.games.values()
        table.game = game
        lobby = LobbyView(table.cog, game.game_id)
        for action in ("bashing", "finesse", "start"):
            click = table.interaction(table.basher)
            await next(item for item in lobby.children if f":{action}:" in item.custom_id).callback(click)
        table.fencer = table.basher
        for _ in range(2):
            seat = table.match.active
            _, view = await table.panel(table.basher)
            self.assertEqual(view.seat, seat)
            ended = await table.press((await table.press(view, "End main phase", who=table.basher)).view(),
                                      "Lock patrol", who=table.basher)
            self.assertIsInstance(ended.answers[-1][2]["view"], TechChoiceView)
            self.assertNotEqual(table.match.active, seat)
        tech = await table.turn_button("tech", table.basher)
        self.assertIsInstance(tech.view(), TechChoiceView)
        self.assertNotEqual(tech.view().seat, table.match.active)


class GameOverTests(TurnTestCase):
    async def test_a_destroyed_base_ends_the_game_in_public(self) -> None:
        """The turn message's last edit, without its buttons, and one
        public line naming the winner with the final board."""
        match = self.table.match
        seat = match.active
        match.opponent(seat).base_hp = 1
        attacker = put(match, seat, "older_brother")
        self.table.cog.service.persist(self.game, match)
        _, view = await self.table.panel()
        defending = (await self.table.choose(view, "Attack with", attacker.ref)).view()
        mark = len(self.table.game_channel.requests)
        call = await self.table.choose(defending, "", "base")
        self.assertNothingWentWrong(call)
        self.assertEqual(self.table.match.winner, seat)
        requests = self.table.game_channel.since(mark)
        self.assertEqual([kind for kind, _, _ in requests], ["edit", "send"])
        self.assertIsNone(requests[0][2]["view"])
        self.assertIn("wins", requests[1][2]["content"])
        self.assertTrue(requests[1][2]["file"].filename.startswith("codex-"))


class UndoTests(TurnTestCase):
    async def test_undo_to_the_start_of_the_turn_puts_everything_back(self) -> None:
        start = history.position(self.table.match)
        message = self.game.turn_message_id
        before_text = self.table.game_channel.texts[message]
        _, view = await self.table.panel()
        view = (await self.table.choose(view, "Play a card", playable(view)[0])).view()
        view = (await self.table.press(view, "Undo")).view()
        mark = len(self.table.game_channel.requests)
        call = await self.table.press(view, "To the start of my turn")
        self.assertNothingWentWrong(call)

        # The position, the panel and the turn message, all restored.
        self.assertEqual(history.position(self.table.match), start)
        self.assertEqual(call.last()[0], "response.edit")
        panel = call.view()
        self.assertIsInstance(panel, TurnPanelView)
        self.assertEqual(
            [row.slug for row in panel.prompt.options.hand],
            self.table.match.active_player.hand,
        )
        self.assertEqual(channel_requests(self.table, mark), [("edit", message)])
        self.assertEqual(
            self.table.game_channel.texts[message],
            before_text + "\n" + history.UNDONE,
        )

    async def test_the_previous_turn_undo_waits_for_the_opponent(self) -> None:
        first = self.table.active
        old = self.game.turn_message_id
        await self.end_turn()
        second = self.table.active
        current = self.game.turn_message_id
        _, view = await self.table.panel()
        view = (await self.table.press(view, "Undo")).view()
        mark = len(self.table.game_channel.requests)
        asked = await self.table.press(view, "To the start of the previous turn")
        self.assertNothingWentWrong(asked)

        # A public question for the opponent; nothing undone yet.
        (kind, confirm_id, kwargs), = self.table.game_channel.since(mark)
        self.assertEqual(kind, "send")
        confirmation = kwargs["view"]
        self.assertIsInstance(confirmation, UndoConfirmView)
        self.assertIn(f"<@{first.id}>", kwargs["content"])
        self.assertEqual(self.table.match.turn, 2)

        # The asker cannot agree for their opponent.
        own = await self.table.press(confirmation, "Agree", who=second)
        self.assertTrue(own.last()[2]["ephemeral"])
        self.assertEqual(self.table.match.turn, 2)

        mark = len(self.table.game_channel.requests)
        agreed = await self.table.press(confirmation, "Agree", who=first)
        self.assertNothingWentWrong(agreed)
        match = self.table.match
        self.assertEqual((match.turn, match.active), (1, self.game.seat_of(first.id)))
        # The question answered in place; the previous turn's message
        # back up with its buttons and pinned; this turn's deleted; a
        # fresh panel for the player whose turn it is again.
        self.assertEqual(agreed.answers[0][0], "response.edit")
        self.assertIsNone(agreed.answers[0][2]["view"])
        self.assertEqual(
            channel_requests(self.table, mark),
            [("edit", old), ("pin", old), ("delete", current)],
        )
        self.assertEqual(self.game.turn_message_id, old)
        self.assertIsInstance(self.table.game_channel.views[old], TurnMessageView)
        self.assertTrue(self.table.game_channel.texts[old].endswith(history.UNDONE))
        self.assertEqual(agreed.answers[-1][0], "followup.send")
        self.assertIsInstance(agreed.answers[-1][2]["view"], TurnPanelView)

    async def test_a_helper_agrees_behind_a_confirmation(self) -> None:
        from codex_cog_fakes import user

        await self.end_turn()
        _, view = await self.table.panel()
        view = (await self.table.press(view, "Undo")).view()
        mark = len(self.table.game_channel.requests)
        await self.table.press(view, "To the start of the previous turn")
        confirmation = self.table.game_channel.since(mark)[0][2]["view"]
        helper = user(909, "helper", helper=True)
        asked = await self.table.press(confirmation, "Agree", who=helper)
        self.assertEqual(self.table.match.turn, 2)
        confirm_view = asked.answers[0][2]["view"]
        confirmed = await self.table.press(confirm_view, "Confirm", who=helper)
        self.assertNothingWentWrong(confirmed)
        self.assertEqual(self.table.match.turn, 1)

    async def test_the_undo_choices_are_the_models(self) -> None:
        """On the first turn only the start of this turn is open."""
        _, view = await self.table.panel()
        undo = (await self.table.press(view, "Undo")).view()
        labels = [item.label for item in undo.children]
        self.assertIn("To the start of my turn", labels)
        self.assertFalse(any(label.startswith("To the start of the previous") for label in labels))
        self.assertEqual(set(self.table.cog.service.undo_targets(self.game.game_id)), {history.TURN_START})


if __name__ == "__main__":
    unittest.main()

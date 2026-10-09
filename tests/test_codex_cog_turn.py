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

import discord

from codex import history
from codex.flow.driver import STALE_CLICK
from codex.game import GameStatus
from codex.prompts import PromptKind
from codex_cog_fakes import Table
from codex_positions import hero_in_play, put
from cogs.codex_views import (
    NOT_YOUR_PANEL,
    PatrolView,
    RematchView,
    TechChoiceView,
    TechConfirmView,
    TurnMessageView,
    TurnPanelView,
    UndoConfirmView,
    hand_numbers,
)

CHANNEL_REQUESTS = ("send", "edit", "pin", "unpin", "delete")


def channel_requests(table: Table, mark: int) -> list[tuple[str, int]]:
    return [(kind, message_id) for kind, message_id, _ in table.game_channel.since(mark)
            if kind in CHANNEL_REQUESTS]


def playable(view) -> list[str]:
    return [row.slug for row in view.prompt.options.playable if row.allowed]


def cards_pictured(call) -> int:
    """How many cards the codex picture a panel edit carries lays out:
    its columns, one per card up to `CODEX_COLUMNS` (never reached by a
    narrowed view of the basic game's codex)."""
    from PIL import Image

    from codex.render import CODEX_CARD

    (picture,) = call.last("response.edit")[2]["attachments"]
    picture.fp.seek(0)
    with Image.open(picture.fp) as image:
        width = image.size[0]
    picture.fp.seek(0)
    return (width - 14) // (CODEX_CARD[0] + 14)


class TurnTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.table = Table()
        self.addCleanup(self.table.close)
        self.game = await self.table.started()

    def assertNothingWentWrong(self, call) -> None:
        for kind, args, kwargs in call.answers:
            text = kwargs.get("content") or (args[0] if args else "") or ""
            self.assertNotIn("Something went wrong", text)

    async def attack(self, view, ref: str):
        """**Attack...** turns the panel into what may attack; then the
        attacker's own button."""
        opened = (await self.table.press(view, "Attack...")).view()
        return await self.table.press(opened, ("attack", ref))

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
        self.assertEqual(kwargs["files"][0].filename, "codex-hand.webp")
        # The other player's My hand is their hand, with nothing to press.
        theirs = await self.table.turn_button("hand", self.table.waiting)
        self.assertNotIn("view", theirs.last()[2])
        self.assertEqual(theirs.last()[2]["file"].filename, "codex-hand.webp")

    async def test_an_action_is_one_panel_edit_and_one_turn_message_edit(self) -> None:
        """**The count per click**: the panel's edit through the click's
        own response, and one edit of the turn message through the gate
        -- nothing else, and no channel send."""
        _, view = await self.table.panel()
        mark = len(self.table.game_channel.requests)
        call = await self.table.press(view, ("play", playable(view)[0]))
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
        call = await self.table.press(second, ("play", playable(second)[0]))
        kind, args, kwargs = call.last()
        self.assertTrue(kwargs["ephemeral"])
        self.assertEqual(args[0], STALE_CLICK[PromptKind.MAIN_ACTION])
        self.assertEqual(self.table.match.phase, "patrol")

    async def test_the_main_phase_is_rows_of_buttons(self) -> None:
        """No menu in the main phase (the author, 2026-10-09): the hand a
        button per card, numbered as the picture numbers it and disabled
        where it may not be played; a building a button; **Attack...**
        turning the panel into what may attack, one button each, with
        **Back** -- and spending nothing public to open."""
        match = self.table.match
        seat = match.active
        attacker = put(match, seat, "older_brother")
        self.table.cog.service.persist(self.game, match)
        _, view = await self.table.panel()
        self.assertFalse([item for item in view.children if isinstance(item, discord.ui.Select)])
        options = view.prompt.options
        numbers = hand_numbers(options)
        cards = [item for item in view.children if (item.choice or ("",))[0] == "play"]
        self.assertEqual([item.choice[1] for item in cards], [row.slug for row in options.playable])
        self.assertEqual([item.disabled for item in cards],
                         [not row.allowed for row in options.playable])
        for item in cards:
            self.assertTrue(item.label.startswith(f"{numbers[item.choice[1]]}. "), item.label)
        builds = [item.choice[1] for item in view.children if (item.choice or ("",))[0] == "build"]
        self.assertEqual(builds, [row.building for row in options.buildings if row.allowed])
        mark = len(self.table.game_channel.requests)
        opened = await self.table.press(view, "Attack...")
        self.assertEqual([answer[0] for answer in opened.answers], ["response.edit"])
        self.assertEqual(channel_requests(self.table, mark), [])
        attacking = opened.view()
        self.assertEqual([item.choice for item in attacking.children if item.choice],
                         [("attack", attacker.ref)])
        back = (await self.table.press(attacking, "Back")).view()
        self.assertIs(back.prompt.kind, PromptKind.MAIN_ACTION)
        self.assertTrue([item for item in back.children if (item.choice or ("",))[0] == "play"])

    async def test_hire_offers_the_hand_as_buttons(self) -> None:
        """**Hire worker** turns the panel into the hand, a button per
        card numbered as the picture, under the question the menu's
        placeholder used to carry, with **Back**."""
        _, view = await self.table.panel()
        opened = await self.table.press(view, "Hire worker")
        self.assertEqual([answer[0] for answer in opened.answers], ["response.edit"])
        self.assertIn("which card goes", opened.last()[2]["content"])
        hiring = opened.view()
        options = view.prompt.options
        numbers = hand_numbers(options)
        cards = [item for item in hiring.children if getattr(item, "choice", None)]
        self.assertEqual([item.choice for item in cards],
                         [("hire", row.slug) for row in options.playable])
        for item in cards:
            self.assertTrue(item.label.startswith(f"{numbers[item.choice[1]]}. "), item.label)
        back = (await self.table.press(hiring, "Back")).view()
        self.assertIs(back.prompt.kind, PromptKind.MAIN_ACTION)

    async def test_level_up_buys_one_level_a_click(self) -> None:
        """One button per hero, a level a click (the author, 2026-10-09)."""
        match = self.table.match
        seat = match.active
        hero_in_play(match, seat)
        match.player(seat).gold = 3
        self.table.cog.service.persist(self.game, match)
        _, view = await self.table.panel()
        call = await self.table.press(view, ("level",))
        self.assertNothingWentWrong(call)
        self.assertEqual(self.table.match.player(seat).hero.level, 2)
        self.assertEqual(self.table.match.player(seat).gold, 2)
        call = await self.table.press(call.view(), ("level",))
        self.assertNothingWentWrong(call)
        self.assertEqual(self.table.match.player(seat).hero.level, 3)
        self.assertEqual(self.table.match.player(seat).gold, 1)

    async def test_a_big_hand_leaves_the_boards_row(self) -> None:
        """Five rows of five: the hand takes three rows at most, so what
        may be built is still on the panel under a hand of more cards
        than fit, and no row holds more than five."""
        match = self.table.match
        seat = match.active
        match.player(seat).hand = list(self.table.cog.engine.catalog.cards)[:18]
        self.table.cog.service.persist(self.game, match)
        _, view = await self.table.panel()
        rows: dict[int, list] = {}
        for item in view.children:
            rows.setdefault(item.row, []).append(item)
        self.assertLessEqual(max(rows), 4)
        self.assertTrue(all(len(items) <= 5 for items in rows.values()), {r: len(i) for r, i in rows.items()})
        cards = [item for item in view.children if (item.choice or ("",))[0] == "play"]
        self.assertEqual(len(cards), 15)
        self.assertTrue([item for item in view.children
                         if item.label.startswith(("Build ", "Nothing can be built"))])

    async def test_an_attack_asks_its_defender_in_the_same_panel(self) -> None:
        """The attacker first, then the legal defenders, each with why it
        is legal; Cancel takes the attacker back."""
        match = self.table.match
        seat = match.active
        attacker = put(match, seat, "older_brother")
        self.table.cog.service.persist(self.game, match)
        _, view = await self.table.panel()
        call = await self.attack(view, attacker.ref)
        defending = call.view()
        self.assertIsInstance(defending, TurnPanelView)
        self.assertIs(defending.prompt.kind, PromptKind.CHOOSE_DEFENDER)
        labels = [item.label for item in defending.children if getattr(item, "choice", None)]
        self.assertTrue(labels)
        self.assertFalse([item for item in defending.children if isinstance(item, discord.ui.Select)])
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
        view = (await self.table.press(view, ("play", playable(view)[0]))).view()
        view = (await self.table.press(view, "Hire worker")).view()
        hire = await self.table.press(view, ("hire", view.prompt.options.hand[0].slug))
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
        played = await self.table.press(active_panel, ("play", playable(active_panel)[0]))
        self.assertNothingWentWrong(played)
        self.assertEqual([answer[0] for answer in played.answers], ["response.edit"])

    async def test_the_tech_picker_is_narrowed_by_its_show_menu(self) -> None:
        """
        **Show...** on the picker narrows the menu and the picture to one
        view -- a tech level, the spells -- and the picks are kept across
        views: one picked under Tech I stays picked while Tech II is
        shown, both are saved. Each change of view is the picker's own
        edit and spends nothing public (the author, 2026-10-09: the
        whole codex at once is too much to pick from).
        """
        await self.end_turn()
        engine = self.table.cog.engine
        mark = len(self.table.game_channel.requests)
        tech = await self.table.turn_button("tech", self.table.waiting)
        picker = tech.view()
        self.assertIsInstance(picker, TechChoiceView)
        self.assertEqual(picker.view, "everything")
        codex = picker.prompt.options.codex
        self.assertEqual(len(picker.select.options), sum(left for _, left in codex))

        # The picture is drawn for real here, and its width counts the
        # cards shown (`render_codex` lays one column per card, up to
        # `CODEX_COLUMNS`): a mock by the module's dotted name would miss
        # the cog once a bot test has closed its bot, which unloads the
        # extension and evicts `cogs.codex` from `sys.modules`.
        shown = await self.table.choose(picker, "Show", "tech1", who=self.table.waiting)
        self.assertNothingWentWrong(shown)
        self.assertEqual([answer[0] for answer in shown.answers], ["response.edit"])
        narrowed = shown.view()
        tech1 = engine.codex_view_rows(codex, "tech1")
        self.assertEqual({option.value.split("#")[0] for option in narrowed.select.options},
                         {slug for slug, _ in tech1})
        self.assertEqual(narrowed.select.min_values, 0)
        self.assertEqual(cards_pictured(shown), len(tech1))
        self.assertLess(len(tech1), len(codex))
        self.assertIn("Showing: Tech I.", shown.text())

        first = narrowed.select.options[0].value
        picked = (await self.table.choose(narrowed, "Choose", first, who=self.table.waiting)).view()
        self.assertEqual(picked.picks, [first.split("#")[0]])

        # Tech II shown: the Tech I pick is kept, unseen, and leaves one
        # place in the menu.
        switched = await self.table.choose(picked, "Show", "tech2", who=self.table.waiting)
        later = switched.view()
        self.assertEqual(later.picks, picked.picks)
        self.assertEqual(later.hidden, picked.picks)
        self.assertEqual(later.select.max_values, later.prompt.options.maximum - 1)
        self.assertEqual(cards_pictured(switched), len(engine.codex_view_rows(codex, "tech2")))
        self.assertIn("Picked so far: " + engine.catalog.name(picked.picks[0]), switched.text())
        second = later.select.options[0].value
        both = (await self.table.choose(later, "Choose", second, who=self.table.waiting)).view()
        self.assertEqual(both.picks, [first.split("#")[0], second.split("#")[0]])

        # Every pick elsewhere: the spells' menu is closed, and says so.
        full = (await self.table.choose(both, "Show", "spells", who=self.table.waiting)).view()
        self.assertIsNone(full.select)
        self.assertTrue(any(getattr(item, "disabled", False) and "other views" in (item.placeholder or "")
                            for item in full.children))
        self.assertEqual(full.picks, both.picks)

        saved = await self.table.press(full, "Save tech", who=self.table.waiting)
        self.assertNothingWentWrong(saved)
        self.assertEqual(self.table.match.player(picker.seat).tech_choice, both.picks)
        self.assertEqual(channel_requests(self.table, mark), [])

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
        sent = [kwargs for kind, _, kwargs in table.game_channel.requests if kind == "send"]
        self.assertIn("wins", sent[-1]["content"])

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
            return await table.press(view, ("defend", options.defenders[0]))
        # The three questions an attack asks inside itself: the panel's
        # buttons, whichever it is.
        if view.prompt.kind is PromptKind.OBLITERATE_CHOICE:
            return await table.press(view, ("obliterate", options.units[0]))
        if view.prompt.kind is PromptKind.SPARKSHOT_TARGET:
            return await table.press(view, ("sparkshot", options.patrollers[0]))
        if view.prompt.kind is PromptKind.OVERPOWER_TARGET:
            return await table.press(view, ("overpower", options.targets[0]))
        # The questions an effect asks as it resolves (step 6).
        if view.prompt.kind is PromptKind.TARGET:
            return await table.press(view, ("target", options.targets[0].key))
        if view.prompt.kind is PromptKind.APPEL_STOMP_TOP:
            return await table.press(view, "Into my discard pile")
        if view.prompt.kind is PromptKind.UPKEEP_ORDER:
            return await table.press(view, "Heal first")
        if options.hero.action == "summon" and not options.hero.why_not:
            return await table.press(view, "Summon")
        cards = [row for row in options.playable if row.allowed]
        if cards:
            return await table.press(view, ("play", cards[0].slug))
        tech = [row for row in options.buildings if row.allowed and row.building.startswith("tech")]
        if tech:
            return await table.press(view, ("build", tech[0].building))
        if options.attackers:
            return await self.attack(view, options.attackers[0])
        return await table.press(view, "End main phase")


class EffectPanelTests(TurnTestCase):
    """The questions an effect asks, in the same panel (step 6): a
    target, Appel Stomp's place and the upkeep's order as buttons, and
    the abilities as buttons on the board's row."""

    def stage(self):
        match = self.table.match
        seat = match.active
        return match, seat, 2 if seat == 1 else 1

    async def test_a_target_is_a_button_in_the_panel(self) -> None:
        match, seat, other = self.stage()
        hero_in_play(match, seat)
        first = put(match, other, "older_brother", patrol="elite")
        put(match, other, "iron_man", patrol="squad_leader")
        match.player(seat).hand = ["spark"]
        match.player(seat).gold = 1
        self.table.cog.service.persist(self.game, match)
        _, view = await self.table.panel()
        call = await self.table.press(view, ("play", "spark"))
        self.assertNothingWentWrong(call)
        asking = call.view()
        self.assertIs(asking.prompt.kind, PromptKind.TARGET)
        # The ask says what the part does; the buttons are the targets.
        self.assertIn("deal 1 damage to a patroller", call.last()[2]["content"].lower())
        self.assertFalse([item for item in asking.children if isinstance(item, discord.ui.Select)])
        mark = len(self.table.game_channel.requests)
        call = await self.table.press(asking, ("target", f"{other}:{first.ref}"))
        self.assertNothingWentWrong(call)
        self.assertIs(call.view().prompt.kind, PromptKind.MAIN_ACTION)
        self.assertEqual(self.table.match.player(other).instance(first.id).damage, 1)
        self.assertEqual(channel_requests(self.table, mark), [("edit", self.game.turn_message_id)])

    async def test_a_spell_is_cancelled_from_its_targets(self) -> None:
        match, seat, other = self.stage()
        hero_in_play(match, seat)
        put(match, other, "older_brother", patrol="elite")
        put(match, other, "iron_man", patrol="squad_leader")
        match.player(seat).hand = ["spark"]
        match.player(seat).gold = 1
        match.turn_snapshots[-1] = history.position(match)
        match.journal = []
        self.table.cog.service.persist(self.game, match)
        _, view = await self.table.panel()
        asking = (await self.table.press(view, ("play", "spark"))).view()
        call = await self.table.press(asking, "Cancel")
        self.assertNothingWentWrong(call)
        self.assertIs(call.view().prompt.kind, PromptKind.MAIN_ACTION)
        self.assertEqual(self.table.match.player(seat).hand, ["spark"])
        self.assertEqual(self.table.match.player(seat).gold, 1)

    async def test_an_ability_is_a_button_on_the_boards_row(self) -> None:
        match, seat, _ = self.stage()
        song = put(match, seat, "harmony")
        put(match, seat, "dancer")
        self.table.cog.service.persist(self.game, match)
        _, view = await self.table.panel()
        call = await self.table.press(view, ("ability", "stop_the_music", song.ref))
        self.assertNothingWentWrong(call)
        slugs = [card.slug for card in self.table.match.player(seat).play]
        self.assertEqual(slugs, ["angry_dancer"])

    async def test_the_combat_choices_and_the_detection_are_buttons(self) -> None:
        """The three questions an attack asks inside itself, and the
        tower's detection, as buttons carrying their choice, with what
        the menus' placeholders said as the panel's caption."""
        from dataclasses import replace

        from codex.engine import DetectOption
        from codex.prompts import (
            ObliterateOptions, OverpowerOptions, PendingPrompt, SparkshotOptions,
        )

        match, seat, other = self.stage()
        mine = put(match, seat, "older_brother")
        first = put(match, other, "iron_man", patrol="squad_leader")
        second = put(match, other, "granfalloon_flagbearer", patrol="elite")
        self.table.cog.service.persist(self.game, match)
        cog, game_id = self.table.cog, self.game.game_id

        def built(kind, options):
            return TurnPanelView(cog, game_id, PendingPrompt(kind, "", seat, options), match)

        def choices(view):
            return [item.choice for item in view.children if getattr(item, "choice", None)]

        view = built(PromptKind.OBLITERATE_CHOICE,
                     ObliterateOptions(mine.ref, (first.ref, second.ref), left=2))
        self.assertEqual(choices(view), [("obliterate", first.ref), ("obliterate", second.ref)])
        self.assertEqual(view.caption(), "**Obliterate 2**: which unit goes?")
        view = built(PromptKind.SPARKSHOT_TARGET,
                     SparkshotOptions(mine.ref, first.ref, (second.ref,), left=2))
        self.assertEqual(choices(view), [("sparkshot", second.ref)])
        self.assertIn("2 of its damage left", view.caption())
        view = built(PromptKind.OVERPOWER_TARGET,
                     OverpowerOptions(mine.ref, first.ref, 3, (second.ref, "base")))
        self.assertEqual(choices(view), [("overpower", second.ref), ("overpower", "base")])
        self.assertEqual(view.caption(), "**Overpower** carries 3 over.")
        self.assertFalse([item for item in view.children if isinstance(item, discord.ui.Select)])
        # Detect... turns the panel into what the tower may detect, one
        # button each, with Back and the question in the text.
        _, panel = await self.table.panel()
        options = replace(panel.prompt.options, detect=DetectOption(True, (first.ref,), "", True))
        panel = TurnPanelView(cog, game_id, replace(panel.prompt, options=options), match)
        opened = await self.table.press(panel, "Detect...")
        self.assertIn("Detect with your tower", opened.last()[2]["content"])
        self.assertEqual(choices(opened.view()), [("detect", first.ref)])
        self.assertIn("Back", [item.label for item in opened.view().children])

    async def test_appel_stomp_and_the_upkeep_are_buttons(self) -> None:
        match, seat, _ = self.stage()
        match.resolving = [{"kind": "appel_top", "seat": seat}]
        self.table.cog.service.persist(self.game, match)
        _, view = await self.table.panel()
        call = await self.table.press(view, "On top of my draw pile")
        self.assertNothingWentWrong(call)
        self.assertEqual(self.table.match.player(seat).deck[-1], "appel_stomp")

        match = self.table.match
        put(match, seat, "helpful_turtle")
        put(match, seat, "starcrossed_starlet", damage=1)
        match.enter_phase("upkeep")
        match.resolving = [{"kind": "upkeep_order", "seat": seat}]
        self.table.cog.service.persist(self.game, match)
        _, view = await self.table.panel()
        self.assertIs(view.prompt.kind, PromptKind.UPKEEP_ORDER)
        call = await self.table.press(view, "Heal first")
        self.assertNothingWentWrong(call)
        self.assertEqual(self.table.match.phase, "main")


class TestGameTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        """A test game: one person in both seats, through the real lobby."""
        from cogs.codex_views import LobbyView

        self.table = Table()
        self.addCleanup(self.table.close)
        call = self.table.interaction(self.table.basher, self.table.lobby_channel)
        await self.table.cog.lobby.callback(self.table.cog, call, test_game=True)
        (self.game,) = self.table.cog.games.values()
        self.table.game = self.game
        lobby = LobbyView(self.table.cog, self.game.game_id)
        for action in ("bashing", "finesse", "start"):
            click = self.table.interaction(self.table.basher)
            await next(item for item in lobby.children if f":{action}:" in item.custom_id).callback(click)
        # Both seats are the one person's: a press defaulting to the
        # panel's seat finds them either way.
        self.table.fencer = self.table.basher

    async def lock(self, view):
        ended = await self.table.press(view, "End main phase", who=self.table.basher)
        return await self.table.press(ended.view(), "Lock patrol", who=self.table.basher)

    async def test_one_person_plays_both_sides_from_the_panel(self) -> None:
        """A test game seats one person in both seats, and its tech is
        chosen in each side's own ready phase (the author, 2026-10-09):
        the Lock closes the panel naming the side My hand opens next and
        sends no picker, Tech says where the choice is made, the second
        side's first turn opens on its actions with no tech to choose,
        and from a side's second turn on My hand is its picker, whose
        Save runs the ready phase and becomes the turn's actions."""
        table, game = self.table, self.game
        # The engine picks who goes first (UMR p. 3); the sides are
        # named by their decks, since both are the one person.
        first = table.match.active
        second = 2 if first == 1 else 1
        side = {seat: table.match.player(seat).spec.title() for seat in (1, 2)}

        # Turn 1: the Lock closes the panel; nothing follows it.
        _, view = await table.panel(table.basher)
        self.assertEqual(view.seat, first)
        ended = await self.lock(view)
        self.assertEqual([answer[0] for answer in ended.answers], ["response.edit"])
        self.assertIsNone(ended.answers[0][2]["view"])
        self.assertIn(f"{side[first]}'s turn is over", ended.text())
        self.assertIn(f"**My hand** opens {side[second]}'s turn.", ended.text())
        self.assertTrue(table.match.player(first).tech_owed)
        self.assertEqual(table.cog.service.standing(game, table.match), ())

        # Tech is not where a test game's choice is made.
        tech = await table.turn_button("tech", table.basher)
        self.assertTrue(tech.last()[2]["ephemeral"])
        self.assertNotIn("view", tech.last()[2])
        self.assertIn("My hand", tech.text())

        # Turn 2, the second side's first: no tech to choose, the
        # actions at once.
        self.assertEqual((table.match.active, table.match.phase), (second, "main"))
        _, view = await table.panel(table.basher)
        self.assertIsInstance(view, TurnPanelView)
        self.assertEqual(view.seat, second)
        ended = await self.lock(view)
        self.assertIn(f"{side[second]}'s turn is over", ended.text())
        self.assertIn(f"opens {side[first]}'s turn, its tech choice first.", ended.text())

        # Turn 3, the first side's second: the picker is the pending
        # prompt, in the ready phase; the turn message says so.
        self.assertEqual((table.match.active, table.match.phase), (first, "ready"))
        text = table.game_channel.texts[game.turn_message_id]
        self.assertIn("**Turn 3**", text)
        self.assertIn("to choose their tech", text)
        _, picker = await table.panel(table.basher)
        self.assertIsInstance(picker, TechChoiceView)
        self.assertEqual(picker.seat, first)
        values = [option.value for option in picker.select.options[:2]]
        picked = await table.choose(picker, "Choose", *values)
        mark = len(table.game_channel.requests)
        saved = await table.press(picked.view(), "Save tech")
        for kind, args, kwargs in saved.answers:
            self.assertNotIn("Something went wrong", kwargs.get("content") or (args[0] if args else "") or "")
        # The pick is the choice: the ready phase ran, and the panel is
        # the turn's actions, in place.
        self.assertIsInstance(saved.view(), TurnPanelView)
        self.assertEqual((table.match.active, table.match.phase), (first, "main"))
        text = table.game_channel.texts[game.turn_message_id]
        self.assertIn("2 tech cards", text)
        self.assertNotIn("waits on", text)
        # One panel edit, one turn message edit through the gate.
        self.assertEqual([answer[0] for answer in saved.answers], ["response.edit"])
        self.assertEqual(channel_requests(table, mark), [("edit", game.turn_message_id)])


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
        defending = (await self.attack(view, attacker.ref)).view()
        mark = len(self.table.game_channel.requests)
        call = await self.table.press(defending, ("defend", "base"))
        self.assertNothingWentWrong(call)
        self.assertEqual(self.table.match.winner, seat)
        requests = self.table.game_channel.since(mark)
        # The two message requests the end spends, then the channel's own
        # move to Codex Archive -- a request of the channel's route, not
        # of the messages' edit bucket.
        self.assertEqual([kind for kind, _, _ in requests], ["edit", "send", "channel.edit"])
        self.assertIsNone(requests[0][2]["view"])
        self.assertIn("wins", requests[1][2]["content"])
        self.assertTrue(requests[1][2]["file"].filename.startswith("codex-"))
        self.assertIsInstance(requests[1][2]["view"], RematchView)
        self.assertIn("category", requests[2][2])
        self.assertIs(self.game.status, GameStatus.FINISHED)
        self.assertEqual(self.game.final_message_id, requests[1][1])


class UndoTests(TurnTestCase):
    async def test_undo_to_the_start_of_the_turn_puts_everything_back(self) -> None:
        start = history.position(self.table.match)
        message = self.game.turn_message_id
        before_text = self.table.game_channel.texts[message]
        _, view = await self.table.panel()
        view = (await self.table.press(view, ("play", playable(view)[0]))).view()
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

"""
`LobbyView`: the lobby `/codex lobby` posts, rebuilt from the record on
every change (docs/design/codex.md, "The standard game"):

- **Basic game** / **Standard game** -- one hero a side or three (UMR
  p. 3) -- **Leave** and **Start**, and in a rematch's lobby **Keep
  heroes**;
- a menu of the heroes this bot plays (`CardCatalog.landed_heroes`),
  one pick in a basic game and three in a standard one, which seats the
  clicker with those heroes -- two menus in a test game, one per side,
  since one person plays both;
- for each seat whose heroes span more than one colour, a button per
  colour for its starting deck.

A menu because twenty heroes do not fit two rows of buttons. Persistent,
so a restart re-arms it (docs/codex-bot.md, decision 10). Every move is
a service method over the record's rule; the view changes nothing itself
and saves nothing.
"""

from typing import Optional

import discord

from codex.cards import catalog
from codex.game import MODES, CodexGame, GameStatus, RuleRefusal
from cogs.codex_views.base import SafeView, send_ephemeral

#: The mode buttons' labels.
MODE_LABELS = {"basic": "Basic game", "standard": "Standard game"}


def hero_options(game: CodexGame, seat: Optional[int]) -> list[discord.SelectOption]:
    """Every landed hero as a menu option -- "Jaina Stormborne (Fire)",
    its colour beneath -- marked as chosen where `seat` holds it."""
    chosen = set(game.player_specs.get(seat, ())) if seat is not None else set()
    options = []
    for hero in catalog().landed_heroes():
        spec = (hero.spec or "").lower()
        options.append(discord.SelectOption(
            label=f"{hero.name} ({hero.spec})",
            value=spec,
            description=f"{hero.color} hero",
            default=spec in chosen,
        ))
    return options


class LobbyView(SafeView):
    """
    The lobby's buttons and menus, custom_ids fixed and carrying the
    game id. Start is either seated player's -- or a game helper's: a
    lobby is where a helper is expected to press things for people, so
    nothing here asks for a confirmation. The mode is either seated
    player's, or anyone's while nobody sits.
    """

    confirms_helper_clicks = False

    def __init__(self, cog, game_id: str) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        game = cog.games.get(game_id)
        mode = game.mode if game is not None else "basic"
        buttons = [
            *(
                (MODE_LABELS[name], f"mode_{name}",
                 discord.ButtonStyle.primary if name == mode else discord.ButtonStyle.secondary)
                for name in MODES
            ),
            ("Leave", "leave", discord.ButtonStyle.secondary),
            ("Start", "start", discord.ButtonStyle.success),
        ]
        if game is not None and game.rematch_specs:
            # A rematch's lobby: the teams are swapped unless both
            # players ask to keep them.
            buttons.insert(3, ("Keep heroes", "keep", discord.ButtonStyle.secondary))
        for label, action, style in buttons:
            button = discord.ui.Button(
                label=label, style=style, custom_id=f"codex:lobby:{action}:{game_id}", row=0,
            )
            button.callback = self._callback(action)
            self.add_item(button)
        if game is None:
            return
        count = game.heroes_per_seat
        menus = [(None, "heroes")] if not game.test_game else [(1, "heroes1"), (2, "heroes2")]
        for row, (seat, key) in enumerate(menus, start=1):
            if seat is None:
                placeholder = "Choose your hero" if count == 1 else f"Choose your {count} heroes"
            else:
                placeholder = (
                    f"Player {seat}'s hero" if count == 1 else f"Player {seat}'s {count} heroes"
                )
            select = discord.ui.Select(
                custom_id=f"codex:lobby:{key}:{game_id}",
                placeholder=placeholder,
                min_values=count, max_values=count,
                options=hero_options(game, seat),
                row=row,
            )
            select.callback = self._pick(select, seat)
            self.add_item(select)
        row = len(menus) + 1
        for seat in (1, 2):
            choices = game.deck_choices(seat)
            if len(choices) < 2:
                continue
            who = game.seat_name(seat) or f"Player {seat}"
            for color in choices:
                chosen = game.player_decks.get(seat) == color
                button = discord.ui.Button(
                    label=f"{who}: {color.title()} deck"[:80],
                    style=discord.ButtonStyle.success if chosen else discord.ButtonStyle.secondary,
                    custom_id=f"codex:lobby:deck{seat}_{color}:{game_id}",
                    row=row,
                )
                button.callback = self._deck(seat, color)
                self.add_item(button)
            row += 1

    def _callback(self, action: str):
        async def callback(interaction: discord.Interaction) -> None:
            if action == "start":
                await self.start(interaction)
            elif action.startswith("mode_"):
                await self.set_mode(interaction, action[len("mode_"):])
            elif action == "keep":
                await self.move(interaction, lambda: self.cog.service.keep_heroes(
                    self.game_id, interaction.user.id))
            elif action == "leave":
                await self.move(interaction, lambda: self.cog.service.leave(
                    self.game_id, interaction.user.id))
        return callback

    def _pick(self, select: discord.ui.Select, seat: Optional[int]):
        async def callback(interaction: discord.Interaction) -> None:
            specs = list(select.values)
            await self.move(interaction, lambda: self.cog.service.take_seat(
                self.game_id, interaction.user.id, interaction.user.display_name, specs, seat))
        return callback

    def _deck(self, seat: int, color: str):
        async def callback(interaction: discord.Interaction) -> None:
            await self.move(interaction, lambda: self.cog.service.choose_deck(
                self.game_id, interaction.user.id, color, seat))
        return callback

    async def set_mode(self, interaction: discord.Interaction, mode: str) -> None:
        """The basic game or the standard one: either seated player's, a
        helper's, or anyone's while nobody sits."""
        game = self.cog.games.get(self.game_id)
        seated = game is not None and (game.player_1_id is not None or game.player_2_id is not None)
        if seated and not self.may_act_in_game(interaction, game):
            await send_ephemeral(interaction, "Only a seated player can change the game.")
            return
        await self.move(interaction, lambda: self.cog.service.set_mode(self.game_id, mode))

    async def move(self, interaction: discord.Interaction, change) -> None:
        """A seat, a team, a deck or the mode changed: the service's,
        then the lobby edited in place -- the click's own response, which
        costs nothing out of the channel's edit bucket."""
        game = self.cog.games.get(self.game_id)
        if game is None or game.status is not GameStatus.LOBBY:
            await send_ephemeral(interaction, "This lobby is closed.")
            return
        try:
            change()
        except RuleRefusal as refused:
            await send_ephemeral(interaction, str(refused))
            return
        await interaction.response.edit_message(
            content=self.cog.lobby_text(game), view=LobbyView(self.cog, self.game_id),
        )

    async def start(self, interaction: discord.Interaction) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.status is not GameStatus.LOBBY:
            await send_ephemeral(interaction, "This lobby is closed.")
            return
        if not self.may_act_in_game(interaction, game):
            await send_ephemeral(interaction, "Only a seated player can start the game.")
            return
        if not game.may_start():
            await send_ephemeral(
                interaction,
                "Both seats have to be taken, each with its heroes and its deck, "
                "before the game can start.",
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog.start_game(interaction, game)

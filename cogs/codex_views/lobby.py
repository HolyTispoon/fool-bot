"""
`LobbyView`: the lobby `/codex lobby` posts, rebuilt from the record on
every change (docs/design/codex.md, "The standard game"):

- **Basic game** / **Standard game** -- one hero a side or three (UMR
  p. 3) -- **Leave** and **Start**, and in a rematch's lobby **Keep
  heroes**;
- in a basic game, a menu of the heroes this bot plays
  (`CardCatalog.landed_heroes`), one pick, which seats the clicker with
  that hero;
- in a standard game, a button per colour's deck by its name --
  **Blood Anarchs**, the colour's three heroes (`CardCatalog.color_decks`)
  -- which seats the clicker with that team, and **Mixed colours**, which
  opens `MixedTeamView` for them alone: the first hero, whose colour is
  the starting deck, and the other two;
- a test game's picks twice, one set per side, since one person plays
  both.

A menu for the heroes because twenty do not fit two rows of buttons.
Persistent, so a restart re-arms it (docs/codex-bot.md, decision 10);
`MixedTeamView` is ephemeral and is not. Every move is a service method
over the record's rule; the view changes nothing itself and saves
nothing.
"""

from typing import Optional

import discord

from codex.cards import COLOR_DECK_NAMES, catalog
from codex.formatting import team_name
from codex.game import MODES, CodexGame, GameStatus, RuleRefusal
from cogs.codex_views.base import SafeView, send_ephemeral

#: The mode buttons' labels.
MODE_LABELS = {"basic": "Basic game", "standard": "Standard game"}

#: A row of buttons, as Discord allows.
ROW_WIDTH = 5

#: How long the ephemeral mixed-team picker waits for its two menus.
MIXED_TEAM_TIMEOUT = 600


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
        seats = (None,) if not game.test_game else (1, 2)
        if game.mode == "basic":
            self._hero_menus(game, seats)
        else:
            self._team_buttons(game, seats)

    def _hero_menus(self, game: CodexGame, seats) -> None:
        """The basic game's pick: a menu of the heroes, one a side."""
        for row, seat in enumerate(seats, start=1):
            key = "heroes" if seat is None else f"heroes{seat}"
            select = discord.ui.Select(
                custom_id=f"codex:lobby:{key}:{self.game_id}",
                placeholder="Choose your hero" if seat is None else f"Player {seat}'s hero",
                min_values=1, max_values=1,
                options=hero_options(game, seat),
                row=row,
            )
            select.callback = self._pick(select, seat)
            self.add_item(select)

    def _team_buttons(self, game: CodexGame, seats) -> None:
        """
        The standard game's picks: a button per colour's deck, named,
        and **Mixed colours** -- for each side in a test game, the side
        written in front and its team lit.
        """
        row = 1
        for seat in seats:
            suffix = "" if seat is None else str(seat)
            prefix = "" if seat is None else f"P{seat}: "
            chosen = game.player_specs.get(seat) if seat is not None else None
            chosen_color = catalog().color_deck_of(chosen) if chosen else None
            items = []
            for color in catalog().color_decks(game.heroes_per_seat):
                button = discord.ui.Button(
                    label=f"{prefix}{COLOR_DECK_NAMES[color]}"[:80],
                    style=(discord.ButtonStyle.success if color == chosen_color
                           else discord.ButtonStyle.secondary),
                    custom_id=f"codex:lobby:team{suffix}_{color}:{self.game_id}",
                )
                button.callback = self._team(color, seat)
                items.append(button)
            mixed = discord.ui.Button(
                label=f"{prefix}Mixed colours",
                style=(discord.ButtonStyle.success if chosen and chosen_color is None
                       else discord.ButtonStyle.primary),
                custom_id=f"codex:lobby:mixed{suffix}:{self.game_id}",
            )
            mixed.callback = self._mixed(seat)
            items.append(mixed)
            for start in range(0, len(items), ROW_WIDTH):
                for item in items[start:start + ROW_WIDTH]:
                    item.row = row
                    self.add_item(item)
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

    def _team(self, color: str, seat: Optional[int]):
        """A colour's deck: its three heroes, the seat's team."""
        async def callback(interaction: discord.Interaction) -> None:
            specs = list(catalog().color_decks()[color])
            await self.move(interaction, lambda: self.cog.service.take_seat(
                self.game_id, interaction.user.id, interaction.user.display_name, specs, seat))
        return callback

    def _mixed(self, seat: Optional[int]):
        """**Mixed colours**: the two menus, for the clicker alone."""
        async def callback(interaction: discord.Interaction) -> None:
            game = self.cog.games.get(self.game_id)
            if game is None or game.status is not GameStatus.LOBBY:
                await send_ephemeral(interaction, "This lobby is closed.")
                return
            picker = MixedTeamView(self.cog, self.game_id, seat,
                                   game.player_specs.get(self._seat_for(game, interaction, seat)))
            await interaction.response.send_message(picker.text(), view=picker, ephemeral=True)
        return callback

    @staticmethod
    def _seat_for(game: CodexGame, interaction: discord.Interaction,
                  seat: Optional[int]) -> Optional[int]:
        """The seat a pick is for: the one named, in a test game, or the
        clicker's own."""
        return seat if seat is not None else game.seat_of(interaction.user.id)

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


class MixedTeamView(discord.ui.View):
    """
    **Mixed colours**, for the one who clicked it, ephemeral: a menu
    for the first hero -- **its colour is the starting deck** (UMR p. 3;
    `CodexGame._settle_deck`) -- and one for the other two. Both filled,
    the seat is taken through the service as the lobby's buttons take
    it, and the lobby is edited to show it -- through the channel, since
    the click answered is the picker's (`refresh_lobby`). Each menu starts on the
    seat's team where it has one, so changing the first hero alone is
    one pick.
    """

    def __init__(self, cog, game_id: str, seat: Optional[int],
                 team: Optional[list[str]] = None) -> None:
        super().__init__(timeout=MIXED_TEAM_TIMEOUT)
        self.cog = cog
        self.game_id = game_id
        self.seat = seat
        team = list(team or ())
        self.first: Optional[str] = team[0] if len(team) == 3 else None
        self.others: list[str] = team[1:] if len(team) == 3 else []
        self.refusal: Optional[str] = None
        heroes = catalog().landed_heroes()
        self.first_menu = discord.ui.Select(
            placeholder="First hero: its colour is your starting deck",
            min_values=1, max_values=1, row=0,
            options=[
                discord.SelectOption(
                    label=f"{hero.name} ({hero.spec})",
                    value=(hero.spec or "").lower(),
                    description=f"{hero.color} hero: the {hero.color} starting deck",
                    default=(hero.spec or "").lower() == self.first,
                )
                for hero in heroes
            ],
        )
        self.first_menu.callback = self.pick_first
        self.add_item(self.first_menu)
        self.others_menu = discord.ui.Select(
            placeholder="Your other two heroes",
            min_values=2, max_values=2, row=1,
            options=[
                discord.SelectOption(
                    label=f"{hero.name} ({hero.spec})",
                    value=(hero.spec or "").lower(),
                    description=f"{hero.color} hero",
                    default=(hero.spec or "").lower() in self.others,
                )
                for hero in heroes
            ],
        )
        self.others_menu.callback = self.pick_others
        self.add_item(self.others_menu)

    def text(self) -> str:
        """What the picker says: the team so far, the first hero and the
        deck it names, and what is still to choose."""
        cards = catalog()
        lines = ["**Mixed colours**: your first hero's colour is your starting deck."]
        if self.first is not None:
            hero = cards.hero_for(self.first)
            lines.append(f"First: **{hero.name}** ({hero.spec}) -- the {hero.color} starting deck.")
        if self.others:
            lines.append("Then: " + ", ".join(
                f"{cards.hero_for(spec).name} ({cards.hero_for(spec).spec})" for spec in self.others
            ) + ".")
        if self.refusal:
            lines.append(self.refusal)
        elif self.first is None or not self.others:
            lines.append("Choose " + " and ".join(
                part for part, missing in (("your first hero", self.first is None),
                                           ("the other two", not self.others)) if missing
            ) + ".")
        return "\n".join(lines)

    async def pick_first(self, interaction: discord.Interaction) -> None:
        self.first = self.first_menu.values[0]
        await self.settle(interaction)

    async def pick_others(self, interaction: discord.Interaction) -> None:
        self.others = list(self.others_menu.values)
        await self.settle(interaction)

    async def settle(self, interaction: discord.Interaction) -> None:
        """Either menu picked: once both are, the seat is taken -- or
        the record's refusal shown -- and the lobby edited."""
        for menu, picked in ((self.first_menu, {self.first}), (self.others_menu, set(self.others))):
            for option in menu.options:
                option.default = option.value in picked
        self.refusal = None
        if self.first is None or not self.others:
            await interaction.response.edit_message(content=self.text(), view=self)
            return
        game = self.cog.games.get(self.game_id)
        if game is None or game.status is not GameStatus.LOBBY:
            await interaction.response.edit_message(content="This lobby is closed.", view=None)
            return
        specs = [self.first, *self.others]
        try:
            self.cog.service.take_seat(
                self.game_id, interaction.user.id, interaction.user.display_name, specs, self.seat,
            )
        except RuleRefusal as refused:
            self.refusal = str(refused)
            await interaction.response.edit_message(content=self.text(), view=self)
            return
        first = catalog().hero_for(self.first)
        await interaction.response.edit_message(
            content=(f"Seated as **{team_name(specs)}**: {first.name} first, "
                     f"so the {first.color} starting deck."),
            view=None,
        )
        self.stop()
        await self.cog.refresh_lobby(game)

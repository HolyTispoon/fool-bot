# The game-creation hub and the lobby

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## The game-creation hub and the lobby

The friendly front door to a new game, alongside `/d12ball create_game` (which
stays, for anyone who prefers the command; the lobby now covers everything it
does bar naming specific opponents up front). Two pieces:

- **The hub** is one locked channel per server carrying two persistent
  messages: the **games message**, with a **D12 Ball** button
  (`NewGameHubView`, in `cogs/d12ball_views/lobby.py`), and under it the
  **roles message**, with a toggle button per role (`HubRolesView`, same
  module). An admin registers both by running `/d12ball setup_hub` **in the
  channel** -- the command sets `@everyone send_messages=False` (keeping the
  bot's own send), posts or edits each message, and records
  `{channel_id, message_id, roles_message_id}` per guild in
  `data/d12ball_hubs.json` via `gamesaves/d12ball/hub.py`. Re-runnable to move
  the hub or repair either deleted message; `post_or_edit_hub_message` is the
  one edit-or-send for both. The games button's custom_id names no game and
  no guild (the interaction carries the guild, and there is no lobby yet).
  - **The roles are a table, `HUB_ROLES` in `cogs/d12ball_helpers.py`**, one
    `HubRole` per button: a `key` (what the custom_id carries,
    `d12ball:hub:role:<key>` -- the one field that cannot change once a
    message is posted), the server role's `role_name`, the button `label` and
    a `description` for the message. One entry today, the **D12ball
    playtester** role. Adding a role is adding an entry: the view builds a
    button per entry, `build_hub_roles_message` lists a line per entry, and
    `D12Ball.toggle_hub_role` looks a click up by key -- add, or remove if
    the member already has it, answered ephemerally. A click from an entry
    since removed is refused rather than crashing.
  - **The bot finds a role by name and creates none.** `find_guild_role`
    matches `role_name` case-insensitively against `guild.roles`, so an admin
    makes the role in the server settings with whatever colour and position
    they want; `setup_hub`'s reply names any role the server is missing, and
    that role's button says so until it exists. A `Forbidden` on the change
    (no Manage Roles, or the role above the bot's own) is explained to the
    clicker rather than raised.
  - **Two messages rather than one so a change to either leaves the other
    alone**, and because the games message already carries a button and
    a paragraph per game -- a row of role buttons under it would read as
    part of D12 Ball. `roles_message_id` is optional on load: a hub file
    written before the roles message re-arms its games button alone until
    `setup_hub` is run again, which is what an admin does to get the second
    message anyway.
  `build_hub_message` is a welcome plus one titled block per game -- name,
  button, and **the game's own description, which is the author's copy and kept
  verbatim** (D12 Ball's came back in review as the one to use). The **only image
  that ever accompanies "D12 Ball"** is a d12, and there are **two cuts of it**,
  both uploaded through the Developer Portal: `d12dice` (light blue ink) rides
  `build_hub_message(...)` and the lobby heading -- message text on the channel
  background -- and `d12dicecream` (cream ink) rides the **hub buttons alone**,
  because a button's coloured fill swallowed the blue die. `load_d12_emoji(name=)`
  resolves either to a `<:name:id>` string; `load_d12_button_emoji` is the
  buttons', `d12dicecream` **or nothing -- it does not fall back to
  `d12dice`**, since a blue die on a green button is the thing the cream cut
  exists to avoid, and a bare button with an INFO line naming the missing
  upload is the better failure.
  Both load in `cog_load` onto `self.d12_emoji` / `self.d12_button_emoji` and are
  **re-fetched by `/d12ball setup_hub`** so a fresh upload takes without a
  restart. Never a 🎲/🏈/🎮 -- a d6, a gridiron or a video-game pad, none of
  which this is.
  `data/d12ball_hubs.json` is untracked runtime state like the saved games, and
  local to each machine -- the message lives in Discord, this is only a pointer.

- **The lobby** is an ordinary `SETUP` game with `in_lobby=True` on the record
  (`d12ball/game.py`). `D12Ball.open_lobby` creates its channel through the
  existing `create_private_game_channel` (named `d12ball-pbdN-lobby`), builds
  the game with `player_2_id`/`ai_opponent` **both None**, and posts a
  `LobbyView` -- Join / Observe / Leave / Start Game, the Test game and Tutorial
  toggles, a **Name** button (opening `LobbyNameModal`, the one text field in
  the flow), and the mode / board-size / opponent settings -- plus, while
  Advanced is on, the two module toggles beside the mode buttons (see
  [Species abilities in the bot](species-abilities.md#species-abilities-in-the-bot)).
  **Nothing may read
  `is_solo_game` off a lobby**: a two-human game also starts with `player_2_id`
  None, and who the opponent is (a second human, Dinky, the creator on both
  sides, or the tutorial's Dinky) is only settled when Start Game is pressed.
  - **The lobby channel is visible to the whole server**
    (`lobby_channel_overwrites` -- `@everyone` view+send), so anyone can look in
    and decide to join or observe. `lobby_start` swaps that for
    `game_channel_lockdown_overwrites` (`@everyone` no view; the two players full;
    every `observer_id` read-only), in the **same `channel.edit`** as the rename,
    so it is one request and best-effort. Observer overwrites are keyed by
    `discord.Object(id=..., type=Member)` -- `TextChannel.edit(overwrites=...)`
    accepts them and an observer may not be in the member cache.
  - **Join** fills `player_2_id` (and clears any AI pick, and drops the user
    from `observer_ids`). **Observe** appends to `game.observer_ids` -- a list
    field, `field(default_factory=list)`, persisted; a player may not observe.
    **Leave** removes you from whichever list you are on.
  - **A lobby is never abandoned just because it emptied out.** The creator
    leaving with a Player 2 present promotes them; the creator leaving alone is
    **refused** -- the lobby stays up for them to invite someone or start solo.
    `abandon_and_archive_game` is only reached through `/d12ball abandon_game`
    now.
  - **Test game** and **Tutorial** are mutually exclusive with each other and
    with a second human -- each is a different answer to "who takes the other
    side". Test game toggles `game.test_game` (one person both sides); while a
    lobby carries it `player_2_id` is still None, so
    `D12BallGame.__post_init__`'s "same user for both sides" check is **relaxed
    while `in_lobby`** and holds again once `lobby_start` sets
    `player_2_id = player_1_id`. Tutorial toggles `game.tutorial` and **pins
    Basic mode on a 7-space board against Dinky** -- the only shape
    `d12ball/tutorial.py`'s script is written for -- greying the mode and board
    rows; `tutorial_step` stays None and the kickoff arms it, exactly as the
    `create_game` path does.
  - **Name** sets `game.game_name` through a modal (players, or a game
    helper -- as with every other setting on this message). It decides
    only the channel name at Start -- `game_name` beats the test/tutorial/
    players-derived name.
  - **Every setting on the lobby message, Start Game included, is open to a
    game helper as well as to the two players**, which is the case the gate
    was built for: somebody walking a new player through their first game
    turns Tutorial on in a lobby they are not playing in. Join, Observe and
    Leave are deliberately not widened -- those are about the clicker
    themselves, and a helper joining would make them a player. See
    [Who may act on a game](permissions.md#who-may-act-on-a-game).
  - **Start Game** (`lobby_start`, any player) finalises the record, does the
    **one-time best-effort** `channel.edit` (rename + lockdown -- the deliberate
    exception to "Archiving ... never renames it" under "Game channels" in [channels-and-archive.md](channels-and-archive.md)), then
    `post_game_setup_message`, the same `TeamSelectionView` the rest of setup
    drives (test games included -- Player 1 then Player 2 in turn).
    `game.message_id` is re-pointed at it, as `CoinFlipView` does for the
    home/visiting message.

- **`restore_saved_views` re-arms all three.** The two hub messages per
  stored guild (`NewGameHubView`, and `HubRolesView` when the entry has a
  `roles_message_id`), and `LobbyView` on an `in_lobby` game's `message_id`
  ahead of the team-picker branch -- without that a lobby would come back as
  the team picker. `LobbyNameModal` is opened fresh per click and needs no
  persistence.

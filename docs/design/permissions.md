# Who may act on a game

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Who may act on a game

**The coach a button belongs to, or a game helper** -- and a game helper is
anyone the server trusts with `manage_channels`. That is the whole rule, and
it is answered in one place: `is_game_helper`, `may_act_for_coach` and
`may_act_in_game` in `cogs/d12ball_helpers.py`, with `SafeView.may_act_in_game`
/ `may_act_for` / `may_act_for_possession` / `may_act_for_defense` as the
interaction-shaped front door every view uses.

It exists because somebody organising playtests is not playing in the games
they are helping people into: a lobby's Tutorial toggle refused them for not
being a player, while `/d12ball abandon_game` -- gated on `manage_channels`
since long before -- would happily let the same person end the game outright.
Two readings of "may this person touch this game" is how that happens, so
there is now one.

- **`manage_channels`, and no second kind of helper.** It is the permission
  `/d12ball resume`, `/d12ball abandon_game`, the full-time Archive button
  and `/debug reset_channels` were already gated on, so nothing new has to be
  set up on a server and nobody gains anything they could not already reach
  the long way round. A role of its own was the alternative and would have to
  be created per server and found by name -- and self-assignable from the hub
  it would be no gate at all.
- **`may_administer_game` is that predicate under its old name**, kept
  because that is what the recovery commands read as. **Don't re-inline the
  permission check into it**: it was the first gate to let somebody act on a
  game they are not in, and the whole point is that it is no longer the only
  one.
- **`is_game_participant` is a fact about the game, not the authorization
  check.** It still answers "is this one of the two coaches", which is what
  `game_participant_ids` is for and what a display or a mention wants. A
  helper is not a participant and may still press the button, so a *gate*
  that asks it is a gate that has stopped being the rule.
- **A helper holds no side, which is the only thing that needed deciding
  anywhere.** Almost every gate names the coach it belongs to
  (`side_controller_id`, `controlling_user_id`, `possession_user_id`,
  `defending_user_id`) and `may_act_for` simply widens it, so a helper acts
  for either side and the flow is untouched. Three places had to answer
  *which* side instead, because they read it off the clicker:
  - **The team picker.** A normal game's two sides share one row, so a
    helper's pick fills the side that has not chosen yet, Player 1 first
    (`D12BallGame.team_pick_lands_on`) -- the same order
    `picking_player_number` puts a test game's sequential screens in. The
    `else` branch would otherwise have given every helper's pick to Player
    2, silently. The view still decides *that* it is a helper's pick; the
    record decides where it lands.
  - **The coin flip.** The coin is read from the flipping player's point of
    view, so it has to be flipped *as* somebody; a helper flips on Player 1's
    behalf. The coin is fair either way, so this changes the wording and
    nothing else.
  - **The shootout's order menus.** A coach gets their own side -- **and only
    their own, whether or not they also hold the permission** -- and a helper
    outside the game gets both, so `owes` picks whichever still needs one.
    That does show a helper both coaches' orders, which is the price of being
    able to set one for somebody. `claim` read the permission ahead of the
    side until 2026-09-18, which handed a visiting coach with
    `manage_channels` the *home* order to set; see the next two bullets.
- **A coach who holds the permission is a coach first.** Every gate answers
  "is this the coach it belongs to" before it asks "is this a helper", so a
  coach with `manage_channels` presses their own buttons exactly as anybody
  else does and is only a helper's click for the *other* side.
  `SafeView.may_act_for` does that by construction; the three sites above
  that derive a side had to be read the same way, and the shootout's was
  not. Anything new that derives a side from the clicker has to try their
  own side first.
- **A helper's click for somebody else is confirmed first, past the lobby.**
  `SafeView.may_act_for` and `may_act_in_game` raise
  `HelperConfirmationRequired` for a helper acting for a coach who is not
  them, unless the click already carries `HELPER_CONFIRMED_EXTRA` on its
  `interaction.extras`; `SafeView.on_error` catches it and swaps the
  prompt's buttons for a `HelperConfirmationView` -- Confirm (the helper
  alone) and Cancel (anyone in the game), with an ephemeral line saying
  who the click would act for. Confirm re-runs the button that asked with
  the confirming click marked, so the callback runs exactly as it would
  have. It is asked every click, and not remembered: "for now", the
  author, 2026-09-18 -- it may later narrow to helpers who are coaches in
  the game.
  - **It is an exception rather than a third return value** because the
    gates are called from fifty-odd callbacks as `if not
    self.may_act_for(...)`, each of which has neither responded nor changed
    anything when it asks -- which is what makes raising there safe, and is
    a property every new gate site has to keep. The raise leaves the
    callback untouched and reaches `on_error`, the one place that knows the
    button it came from.
  - **The confirmation replaces the prompt's view in place**, the way
    `TimeOutConfirmView` does, so the click that confirms is a click *on
    the prompt* and a callback that answers with `edit_message` -- nearly
    all of them -- edits the message it always did. An ephemeral
    confirmation would hand the callback an interaction on the ephemeral
    message, and a coaching flow or a run back would carry on inside a
    message only the helper can see. A callback that answers with a message
    of its own (the maneuver pick) leaves Confirm/Cancel up, so the view
    puts the prompt's own buttons back by hand -- the one channel-route
    edit in it. A timeout does the same, so a helper who walked away does
    not leave a coach without their buttons.
  - **The lobby is exempt** (`LobbyView.confirms_helper_clicks = False`):
    turning Tutorial on and pressing Start for somebody is what the gate was
    widened for, and nothing there is a move made for a coach. The slash
    commands (`resume`, `abandon_game`, `skip_tutorial`) read the free
    functions in `cogs/d12ball_helpers.py`, which stay plain booleans, so
    they ask nothing either -- they were `manage_channels`-gated before any
    of this.
  - **Not restart-safe, deliberately.** A restart re-arms the prompt's own
    view on the message, so the Confirm/Cancel a coach sees are answered by
    nothing; `/d12ball resume` puts the prompt back, the same as any other
    stuck prompt.
- **`is True`, not truthiness, is what reads the permission**, and that is
  about the suite rather than about Discord. Nearly every person in `tests/`
  is a `MagicMock(spec=discord.Member)`, whose
  `guild_permissions.manage_channels` is a Mock and so truthy -- under a plain
  `bool(...)` every mocked click in the game would read as a helper's, which
  turns every gate here into a no-op **and does it silently**, since a gate
  that lets everyone through fails no test about refusing somebody. A test
  that means to grant it says `SimpleNamespace(manage_channels=True)`.
  `tests/test_d12ball_game_helpers.py` asserts the mock case directly.
- **A helper's click is attributed to the coach, never to them.** Every
  message about a pick, a toss or a choice is worded from the *side*
  (`format_player_with_team` off the side's own player number), so nothing
  had to change for this and nothing should: the pick is that side's however
  it was entered. What a helper gets of their own is the ephemeral reply.
- **What is deliberately not widened**: Join, Observe and Leave, which are
  about the clicker themselves rather than authority over somebody's game --
  a helper joining would make them a player, which is the opposite of the
  point; and `/d12ball coach` and the score adjuster, which derive a side
  from `side_for_user` and already send anyone without one to `/d12ball ref`,
  where the team is an argument. A helper is a person with no side, so that
  is the command that already fits them.

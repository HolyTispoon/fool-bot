# Naming a player, and what a message says

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Naming a player

**A player is never named without their role.** Nine of them are on the field
at once and a coach is choosing between them on what they do, so a bare name
is the one thing a label can say that does not help -- the role initials are
what the meeple, the card on the board and the printed card all carry, so the
name a coach reads is the one they can match to what they are looking at.

**Outside a button, a player also carries their team emoji.** Two things make
that the split. A message can be about either side, and since the 2026-08-17
reshuffle a card's own definition cannot say which of its two rosters it is
being fielded as (see [One player, both sides](teams-and-players.md#one-player-both-sides)) -- so
a message has to say. A button is the clicking coach's own side by
construction, and the room the emoji would take is better spent on the
position, which is what the choice usually turns on.

| Where | Form | Built by |
| --- | --- | --- |
| A message | `🟠 Hellguard [FB]` -- and once the role emoji are uploaded, `🟠 Hellguard <:role_fullback_orange:id>`, the badge edged in that side's own colour | `RulesEngine.format_player_label`, via `D12Ball.player_label` / `player_id_label`; `RulesEngine.format_roster_player_for_message` inside the engine's own two message builders |
| A button | `Hellguard [FB]`, plus the position or the price the choice turns on | `player_with_role` |
| Anywhere holding a card id rather than a definition | `Hellguard [FB]` | `RulesEngine.format_roster_player` |
| The two both-sides autocompletes | `Hellguard [FB] (Orange)` | `RulesEngine.format_roster_player_with_team` |
| A coach, in a message | `🟠 @coach` | `format_player_with_team`, which takes the emoji dict |

- **A coach is named the same way: their side's emoji in front, and
  the team never in words.** `format_player_with_team` read
  `@coach (Purple)` until 2026-09-16 -- the turn prompt, the maneuver
  picks, the coin toss, the loose-ball send, the setup message all
  spelled the team out in parentheses while every card beside them
  carried the emoji. The emoji is the mark the board draws that side's
  meeples in, so a coach and their cards now read as one side at a
  glance, and the position is the player label's for the same reason
  the emoji is: one rule for "whose is this", not two. A coach with no
  team yet (setup, before the picker) is named bare -- "(Unknown team)"
  answered a question nobody asked. `format_player_with_team` writes
  the team's mark as a token, `{team:purple}`, and the coach as
  `{coach:1}` where it addresses them; the cog draws both once, at
  its door (`D12Ball.render_text`, `DiscordTokens`) -- see "Tokens"
  in [model-discord-split.md](model-discord-split.md), and "The dict
  lives on the engine" below for how it got there. The two both-sides
  autocompletes are the deliberate exception -- an autocomplete choice
  is plain text and cannot render an emoji.
- **`player_with_role` in `d12ball/formatting.py` is the whole of the
  bracket spelling**, and the message form is it with the mark in front --
  `RulesEngine.format_player_label` builds on it rather than beside it, so
  "outside a button, also the emoji" is one rule and not two formatters
  agreeing by hand. (`format_role_bracket`, the cog's copy of that form,
  went with step 9; `D12Ball.player_label` renders the engine's.)
- **`role_initials` is the one reader of `ROLE_INITIALS`** outside the modules
  that *draw* it (`render.py`, `cards.py`, `player_cards.py`, `boards.py`,
  `species_cards.py`), which index it for a glyph rather than for a name.
  `NamingAPlayerTests` in `tests/test_d12ball_package_shape.py` fails on
  anything else that reads it.
- **The brackets are the *only* spelling.** The coaching flow, the halftime
  buttons and `/ref`'s roster printed `Hellguard (FB)` until 2026-09-16, on
  the reasoning that parentheses read better inside prose. What that missed is
  that those labels all put something else in parentheses straight after --
  the halftime buttons came out `Hellguard (FB) (3)` and the roster listing
  `Hellguard (FB) (M2)`, where the two pairs of brackets mean different things
  and nothing says which. One spelling for the role leaves parentheses free to
  mean one thing, and it is what the rule reduces to: a player looks the same
  everywhere.
- **The rule was written down because the run back broke it.**
  `RunBackPlayerChoiceView`'s buttons read `Hellguard — M2` -- the one place
  in the game that named a card and left the role off. It was invisible
  precisely because every *other* site spelled the brackets out for itself,
  nine copies of `f"{player.name} [{ROLE_INITIALS[...]}]"`, so no one of them
  looked like the odd one out. The sweep that fixed it is only permanent
  because there is now one place left to change.
- **A label is cut to Discord's 80 characters** (`[:80]`), which is a hard
  limit rather than a style: a longer one is a 400 on the send, and the
  prompt is what the turn is waiting on.
- **The brackets have an emoji form, and it goes only where custom emoji
  render.** `d12ball/images/emoji/role_<role>.png` is one badge a role --
  the two initials in a white rounded square, drawn by
  `scripts/render_role_emoji.py` -- uploaded to the application under
  `ROLE_EMOJI_NAMES` (`role_fullback`, ...) exactly as the team emoji are,
  and `load_role_emojis` looks them up on startup. `role_badge` in
  `d12ball/formatting.py` writes the token, `{role:fullback:orange}`, for
  a message and `[FB]` for a button; `DiscordTokens` in
  `cogs/d12ball_helpers.py` is the whole of the substitution: given an
  upload it draws the emoji, and for a role the application has none
  for it draws `[FB]` (`role_brackets`, the one spelling) -- so an
  application with three of the six is three badges and three bracketed
  roles, and a fresh bot reads exactly as it did before.
  - **A message asks for the badge and a button does not**, which is the
    same split the team emoji already made and for a harder reason:
    custom emoji markup in a button label or an autocomplete choice
    renders as the raw `<:role_fullback:123>`. So `player_with_role(player)`
    is the plain form every button and autocomplete builds from, and
    `player_with_role(player, badge=True, team=...)` -- through
    `format_player_label` and `player_label` -- is the form a message
    takes.
    **The plain form is the default on purpose** -- a `[FB]` in a message
    is the old look, where a `<:...:>` in a button is a visible bug -- which
    is why the engine has two methods rather than a flag:
    `format_roster_player` for a label and `format_roster_player_for_message`
    for the turn prompt and `apply_formation`'s summary, the only two
    messages the engine words itself.
  - **The dict lived on the engine** from 2026-09-20 until step 9 of
    [../architecture-migration.md](../architecture-migration.md), and
    lives on the cog again -- the history below is kept because it
    records why the model had to be able to *name* the badge, which
    is still true; what changed is that it names it with a token and
    the cog draws it. (`RulesEngine.role_emojis`, empty until
    `cog_load`, with `D12Ball.role_emojis` a property over it, not a
    second dict: `cog_load` *replaces* the dict, so a reference handed
    to the engine at construction would go stale the moment the fetch
    landed. It was a Discord-shaped thing the engine held, and it was
    on the architecture's remove list by name. The four dicts are
    read-only class defaults on `CoreMixin` now, so a test fixture
    that builds a cog with `object.__new__` reads "nothing fetched".)
    - **`RulesEngine.team_emojis` joined it the same way (2026-09-20),
      ahead of the `PendingPrompt` move.** `player_label`'s two `ask`
      lines (Mind Pull, an injury test) need a player named with both
      dicts, and `pending_prompt`'s single chain has to answer them
      from the model side of the seam -- so the reasoning above, which
      had applied to `role_emojis` alone, now applies to both:
      `D12Ball.team_emojis` is the second property over the engine's
      dict, `build_turn_prompt` and `build_loose_ball_prompt` read
      `self.team_emojis` instead of taking it as a parameter, and
      `RulesEngine.format_player_label` is `format_role_bracket`'s body
      moved onto the engine to read both dicts off itself, with
      `D12Ball.player_label` forwarding to it so no call site moved.
    - **`RulesEngine.condition_emojis` was the third and last of them
      (2026-09-20), with rank O2 of the split.** A Dribble Burst
      charges a token a space and a beaten Clear charges two, and both
      sentences are written by `describe_exhaustion_gain` -- so a flow
      step that charges exhaustion would have had to hand its own
      wording back to the cog to find out what an exhaustion token
      looks like. `apply_exhaustion` and `describe_exhaustion_gain`
      moved onto the engine with the dict; `D12Ball` keeps a
      forwarding method for each, so none of the nineteen call sites
      moved, and `D12Ball.condition_emojis` is the third property over
      an engine dict. The five `get_*_emoji` fallback lookups went to
      `d12ball/formatting.py` beside `get_team_emoji` for the same
      reason; the *names* the uploads are fetched by stayed in
      `cogs/d12ball_helpers.py` beside `load_condition_emojis`, which
      is the half that needs discord.py.
  - **A square, not a ring.** The team emoji is a white circle with a
    coloured ring and a letter, so `🟠 Hellguard [FB]` as two rings would
    read as two teams; the badge is a rounded square in ink for that
    reason, and a *white* one because that is what reads on Discord's dark
    and light themes alike. Everything about it is tuned for the 22px it is
    shown at inline: the first draft's thicker edge and smaller initials
    were legible at 256px and a smudge in a message.
  - **There are five cuts of each badge, and the colour is on the edge
    alone.** `role_fullback_orange` and its twenty-three siblings are the
    same badge with the edge in a team's hex -- the face stays white and
    the initials stay ink, which is the whole of the design (2026-09-17).
    The alternatives were drawn and looked at first: filling the *face*
    with the colour and knocking the initials out in `high_contrast_ink`,
    which is the board's own recipe for a meeple token, reads strongest at
    256px and worst at 22, where two letters out of orange or slime green
    are a smudge and black on white is still two letters. Putting the
    colour on the initials as well, which is what the *team* emoji does
    with its one big glyph, loses the same way for the same reason. So the
    colour goes on the one part of the badge carrying no information.
    - **One geometry for all five cuts.** The edge stays at `EDGE_WIDTH`,
      which is already the thickest line that survives the downscale as a
      line rather than a shadow -- a wider edge would read the colour
      better and cost the letters, which is the trade that settled the
      badge in the first place and is settled the same way again.
    - **Four files a role, not eight.** A species team shares its colour
      team's hex, so Orange and Fire Demons are one upload.
      `ROLE_TEAM_EMOJI_NAMES` keys every team and fills from four names,
      resolving the pairing once the way `TEAM_COLORS` does -- so nothing
      downstream has to know that a Cyborg is drawn teal.
  - **One dict for both cuts, keyed `(role, team)`.** The plain badge is
    filed under `(role, None)` and each colour cut under both teams
    sharing it, so a caller with a side and a caller with none ask the
    same dict. Two dicts threaded through ninety call sites was the
    alternative. `get_role_emoji` (behind `DiscordTokens`) falls back in
    three steps -- the colour cut, then the plain badge, then the
    brackets -- so an application holding
    the six and none of the twenty-four reads exactly as it did before the
    colours existed, which is what it does until somebody uploads them.
  - **Passing the team is what asks for the colour, and every message
    already had one.** `format_player_label` takes a team for the mark it
    puts in front, so the same argument now answers the badge as well --
    which is what stops the ring and the badge on one line ever naming two
    different sides. It is `match.team_for_player`'s answer, not the
    definition's, so a player fielded on both sides carries each side's
    colour on the right card (see "One player, both sides" in [teams-and-players.md](teams-and-players.md)).
  - **The goal log is the one message that passes no team, deliberately.**
    Every line of it is under the heading of the side the goal counted
    for, which for an own goal is not the scorer's -- so it keeps the
    *plain* cut. A badge in the scorer's own colour would say exactly what
    the team emoji is left off that line for saying, and contradict the
    heading in exactly the same way. See `format_goal_scorer`.
  - **The dice image's detail lines, the matchup image and the stats
    tables keep the brackets**: they are drawn, or set in a code block,
    and an emoji goes in neither. The goal log does take the badge -- the
    role says nothing about which side a goal counted for, which is the
    reason the *team* emoji is kept off that line -- but the plain cut of
    it only, since a coloured edge would say a side after all.

## What a message says

Three rules the author gave on 2026-08-27, after reading a turn back out of
a channel. They are about every message the bot posts, not only the ones that
produced them.

- **Say what the position is, never what it is not.** A ball coming down where
  one side is standing was announced "**Not loose.** ... so the ball is simply
  theirs" -- a sentence fragment that defines the position by the two it is
  not, in front of a coach who has to act on it. It reads "The ball comes down
  to a space where {team} has a player, so they get the ball." The other two
  arrivals were reworded with it; see
  [Where the ball comes to rest](loose-balls.md#where-the-ball-comes-to-rest).
- **Don't answer a question nobody asked.** That same message closed with
  "nobody may be sent after it", and the contest's with "and nobody else may
  be sent" -- both denying an offer neither message had made. A coach reading
  a result is not owed a list of what the rules did not do.
- **A move that costs nothing says nothing.** `describe_exhaustion_gain`
  returns `""` for a charge of zero, where it used to say "was already there --
  no exhaustion cost", and "free of exhaustion" is gone from the new-play
  reset, the halftime restore and Double Team's second defender. Every move
  that *does* cost a token says so in that same line, so silence already
  carries the fact -- and "free" left a coach to work out what was free about
  it. **Callers join on the parts that are there** (`"\n".join(filter(None,
  ...))`) rather than interpolating, or the empty string shows as a blank line.

The subject is spelled out for a related reason: "It comes down on an empty
space" followed a sentence about a maneuver, so the pronoun read as the
maneuver. Nothing in a result message should have to be resolved backwards
through the message above it.

# D12 Ball 2.0: the maneuver deck

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are
[rules-2.0.md](../rules-2.0.md) over [living-rules.md](../living-rules.md).

## An edition beside the mode

`D12BallGame.edition` (`Edition.ONE`, `Edition.TWO`) is a setting of its own, not a fourth
mode (the author, 2026-10-16: "keep d12ball 1.0 as is"; each mode keeps its abilities and
every mode can play the deck). **Nothing reads it to decide a rule**:
`RulesEngine.maneuver_deck_applies` is the answer, and it is never true for a tutorial, whose
beats rail cards a shuffled hand may not hold (`configure` refuses 2.0 there and
`pin_tutorial` sets 1.0).

- **`gambits_apply` answers yes in 2.0**, whatever the mode, because the deck holds the six
  advanced maneuvers and their successful and failed outcomes are rules of the cards. What 2.0
  drops is the coin, so **`coin_applies`** is the new gate over everything Law 19.3 adds:
  `coin_holder`, `may_declare_gambit`, `may_answer_gambit` (and with it `gambit_answer_owed`),
  `describe_gambit_access`, `withheld_gambits`, the declaration's refusal. Volatile's tier
  rider and the special abilities that raise a tier still ask `gambits_apply`: the advanced
  card exists in a 2.0 standard game.
- **The record leaves the field out of `to_dict` while it is 1.0**, as it does `ai_seats`, so a
  1.0 save is written byte for byte as before.
- **The rematch carries it**, in the service's `rematch` and the cog's.
- **Discord alone offers it**: two buttons on the mode's row of the lobby and the setup
  screen (`EDITION_BUTTONS`). The web table names the settings it shows and does not name this
  one, and `webapp.server` refuses it outright (`DISCORD_ONLY_SETTINGS`): the page has no
  secret hand. A web game is never 2.0.

## The deck is data on the match

`MatchState.maneuver_decks` is `{"home": deck, "visiting": deck}`, each deck `{"draw",
"hand", "discard"}` lists of **card ids**, saved as it stands. It is one of
`MATCH_EXPLICIT_FIELDS` rather than a row of the table, because **a match with no decks writes
no key**: every row of the table is in every save, and a 1.0 match has to be saved exactly as it
was before 2.0 -- the four goldens pin that byte for byte. An absent key reads as no decks,
which is 1.0 and every save before the field. `d12ball/maneuver_deck.py` is the cards and the three
moves made on them -- `new_deck`, `draw_cards`, `play_card` -- with the engine's `rng` handed
in, so a seeded game deals and reshuffles the same way every time.

- **A card is an id, not a maneuver.** A two-headed card is `basic_<rank>`, an advanced card
  its maneuver key. What a card plays is `plays_as(catalog, card, side)`, because a two-headed
  card is two maneuvers and the side decides which.
- **The deck belongs to a team, the pick to a maneuver side.** The engine maps one onto the
  other with `maneuver_side_team`, the reading every other per-side question already uses.
- **The reshuffle is at the last card drawn**, not at a draw from an empty pile -- the
  author's wording -- so a deck between turns is never empty while there is a discard.
- **Eighteen cards and five in hand since 2026-10-20** (`BASIC_COPIES`, `HAND_SIZE`; it was
  fifteen and four). A 2.0 game saved before that keeps the fifteen cards its save lists --
  nothing rebuilds a saved deck -- and draws up to five at its next card played, since a draw
  fills the hand to `HAND_SIZE` whatever it held. No migration, as for every saved field.
- **The picks are still maneuver keys** on `offense_maneuver` / `defense_maneuver`; nothing in
  the effect pipeline knew there was a deck.

## Who holds what

**`RulesEngine.maneuver_hand` is still the only answer to which cards a coach may play.** In
2.0 it reads the side's team's hand through `plays_as` -- one entry a maneuver however many
copies are held -- and `maneuver_tiers` is read off it rather than the other way round. The
prompt's `ManeuverHand` keeps `maneuver_keys` as the answer, and grows `held` (the five card
ids) with `deck_count` and `discard_count`, which the AI and the pick refusal do not read. The
AI needed nothing: Dinky already picks among the keys on a rolled rank, and from the whole
hand where it holds nothing on that rank.

**An advanced card against no challenge resolves as its basic counterpart** (the author). It
is recorded as played, and `resolving_maneuver` downgrades it with no change, since
`cards_outcome` answers `None` with no opposing card; the uncontested narration says so.

## Played at the reveal

`d12ball.flow.turn.play_maneuver_cards`, at the end of `maneuver_pick_step` once
`maneuver_selections_complete`: the card behind each pick goes to the discard and the coach
draws to five. It is the reveal rather than `begin_effect_resolution` because that is when a
card is down for good -- until then the pick may change -- and the step where both picks
become complete is the one place every maneuver passes (an AI's pick goes through the same
answer). A reshuffle is said, since it is public.

## On Discord: the hand is secret

1.0's prompt puts both hands' buttons on one public message, which works because every coach
holds the same three cards. A 2.0 hand is a secret, so **the public prompt carries one
**My hand** button and no card** (`d12ball:maneuver_hand:<game>`, `HAND_BUTTON_LABEL`), and no
hand image. One button rather than one a side (the author, 2026-10-17): who presses it says
whose hand it is. It answers ephemerally with the hand of each side the clicker coaches --
both, named by side, for somebody coaching themselves -- as the five cards
(`render_deck_hand`, one row of five past `HAND_MAX_COLUMNS`, because a wrap at four leaves
one card alone on a row of its own) and `ManeuverHandView`, one button a playable maneuver. Somebody coaching
neither side is put through the pick's own gate a side at a time, so a helper is confirmed and
then shown every hand on the prompt, and anybody else is refused. A pick from there is the 1.0 pick exactly
(`ManeuverPicking`, the mixin both views share): the same action, the same ephemeral "You
chose", the prompt deleted once both are in. The public message is never edited, as in 1.0,
and a restart re-arms it from the custom ids; the ephemeral hand is not persistent, and
pressing the public button again sends a fresh one.

**A two-headed card is its own face, built from the printed card's parts**
(`render_two_headed_card`, the author, 2026-10-16). Each half is the printed card's header,
strip diagram and effect sentence (`render_two_headed_half`), **drawn at full width into half
the card** rather than drawn at the printed size and shrunk -- which made every half narrower
than the card, the author asked why -- so its header is shorter (`TWO_HEADED_HEADER`, with the
badge and time chip moved in off the rounded corner), its diagram panel is as tall as its own
diagram (`strip_block_height`) and its effect is one size for all six
(`two_headed_effect_size`). The printed card's header and strip take those as parameters whose
defaults are the printed card's, so the 1.0 faces and hands are byte-identical (hashed before
and after). And **nothing about roles**: no
ability box, and the strip drawn with `draw_strip(roles=False)`, which drops the role's dashed
moves (`ROLE_MOVE_LABELS`) and the tokens they land. **The matchups are one band across the
middle** (`render_two_headed_band`): two rows in the printed card's matchup layout
(`draw_matchups`) at a size two fit, each read from its own end -- BEATS / TIES / LOSES TO over
the other side's rank badge (D3 under the offensive half, O3 under the defensive one) and the
basic maneuver on it -- not its advanced one -- the author asking on 2026-10-17 for O1/D1 rather than R1 and
for the band to look like the 1.0 card's row. One band serves both halves because a
rank's offensive and defensive maneuvers beat, tie and lose to the same ranks
(`two_headed_ranks`; a test holds the defensive half to the offensive one's). The band is the
row once for the half above it and the same row turned for the half below, so the card is one
picture through 180 degrees; the side being played is upright on top. An advanced card is the
printed one, veiled where its side cannot play it. Each of the thirty faces is drawn once and
kept.

**The discard piles are face up** (the author): the public 2.0 prompt carries both coaches'
piles as one picture (`render_discard_piles`, `D12Ball.build_discard_file`) once either has
discarded anything -- the upload the 1.0 hand image made, so no extra request. **A discarded
card is a chip, not the card** (the author, 2026-10-18, asking for a more condensed discard
view; the whole cards made two piles 1534 x 1298 px): the rank badge and the name in the card's own colour, a two-headed
card's two halves both upright, offense over defense, an advanced card one block in its gambit
colour with its "ADVANCED ..." line (`discard_chip`). The pile is read for what has gone, and a
coach knows the eighteen cards, so nothing a card spells out for playing it is on the chip. Copies
of a card are one chip with the count on it -- only a two-headed card has copies -- so a pile is
at most nine chips. **Each pile is a column, the two side by side**, home's first, with 4 px
between chips and 20 px between the columns (the author, 2026-10-20: "stack discard piles
vertically side by side and make it closer together"; they had been two blocks of rows, one
above the other). The model's reading is
`RulesEngine.maneuver_discards`; a picture is not a button, so it is read off the match, as the
field strip is.

**Halftime reshuffles** (the author): `begin_halftime` asks
`RulesEngine.reshuffle_maneuver_decks`, which puts each coach's hand and discard back into the
deck, shuffles and deals five (`maneuver_deck.reshuffled`), and says so in halftime's opening
message. A 1.0 halftime is unchanged, which the windows golden pins.

## The coin

**2.0's coin settles a tied roll** (rules-2.0 section 5; the author, 2026-10-20) -- a skill
test's and a contest for the ball's, never the cards' and never a shot's. It is not 1.0's gambit
coin, which `coin_applies` still gates and 2.0 still has none of; it is
**`MatchState.tie_coin`**, the face it shows, with **`tie_coin_owed`** beside it. Both are
`MATCH_EXPLICIT_FIELDS`, written only once the coin has been flipped, so a 1.0 match is saved
byte for byte as before. `RulesEngine.tie_coin_applies` is the gate (2.0's, so the deck's
answer under its own name) and `tie_coin_winner` the one reading of whom the face favours.

- **A tie is settled where 1.0 re-rolls it.** `skill_test_step` and `loose_ball_test_step` ask
  `coin_settles_tie` in place of `pay_contest_tie`: the winner is the coin's side, nothing is
  charged, and the tie is said above the winner's line. The contest's offense is
  `ball.possession`, the side that last held the ball, which is already the side adding its
  offensive skill there.
- **Flipped and tossed at the start of a turn** (`settle_tie_coin`, in `start_turn`). The rules
  toss it once the advanced maneuver is fully resolved, every contest it leads to included, and
  only a maneuver leads to a tied roll, so the next turn's start is the first point after which
  the new face can matter -- and one place reaches every ending, a goal and a period's end
  included, where the maneuver's own finish has several. The reveal marks the toss owed
  (`owe_coin_toss`), which is why the flag is saved: a restart between the two must not lose
  it. An unflipped coin is flipped the same way, which is both the game's first flip and a 2.0
  game saved before the coin; a tie met with no coin at all (such a save, mid-maneuver) flips it
  there and says so.
- **The face is always in view** (the author, 2026-10-20): every turn message carries it
  (`build_turn_prompt`, "Doom: defense wins ties.") and the board draws the game's own coin
  showing it on the jumbotron, between the visiting side and the clock, with the same words
  under it (`draw_jumbotron_coin`). The engine answers both -- `tie_coin_face` and
  `tie_coin_caption` -- and the cog hands the renderer the picture's name and the caption
  (`D12Ball.tie_coin_brief`), so the renderer reads no rule. With no coin the jumbotron is
  drawn exactly as before, byte for byte; the web page has no 2.0 and passes none.

## Moving costs

**In 2.0 a move on the board costs a token a space, and a card costs nothing** (rules-2.0 5.4;
the author, 2026-10-21, replacing the rank cost of 2026-10-20, which had each player pay their
card's rank at the reveal). `RulesEngine.moving_costs` is the gate -- the deck's answer under its
own name, like `tie_coin_applies` -- and `pay_for_move(game, match, player_id, tokens)` the one
charge, "" in 1.0 or for a move that went nowhere.

- **Charged where the move is made, off what it came to.** The Charter already charges a send and
  a run back a space in both editions (`choose_challenger`, `walk_in_contestants`,
  `run_back_space_step`, the pickup), so those never reach `pay_for_move`. What does is every move
  1.0 makes free during play: a won Dribble's handler (`dribble_advance_step`, at
  `dribble_burst_cost`, so Emberdash's free Burst covers their Dribble), the passer's step
  (`answer_passer_advance`, whose ask names the token -- `passer_advance_prompt`), Pressure's
  shove, the challenger who follows it and a Double Team's partner who joins them (`pressure_step`,
  each measured from where they stood -- the partner too, though Law 19.10.2 makes their join free
  in 1.0; the author on PR #665), a Steal's or an Intercept's carry (`steal_step`), and a beaten Double Team's two
  (`pay_double_team_cost`). Each reads the distance `move_player_relative` hands back, never the
  one asked for, because a clamped move pays for where it got to.
- **What stays free** (5.4a, 5.4b): the reset after a new play and every Coaching Choice move,
  which rearrange a formation rather than play; and the moves an ability prices -- Strider's run back,
  Quantor's run, Glompex's step -- which keep their price.
- **Entering a skill test stays free** (5.4c, the author's answer): `skill_test_tokens` answers 0
  in 2.0 but for the 2 Scorchit pays to force a test, which is the ability's price.
- **The Dribble menu does not price its buttons yet**; a Playmaker choosing 1 or 2 spaces reads
  the cost in the narration. Pricing them is an option field on `DRIBBLE_ADVANCE_CHOICE`, both
  sides reading it, as the Burst's `dribble_burst_note` does.

## No shooting range

**2.0 has no shooting range: a shot may be taken from anywhere** (rules-2.0 section 6; the
author, 2026-10-25). `RulesEngine.shooting_range_applies` is the gate -- the deck's answer the
other way round, under its own name -- and two engine readings carry it to every site:
`can_attempt_score(game, match, side)` and `may_call_time_out(game, match)`, over the
`MatchState` methods of the same names, which take `range_applies` because the match cannot see
the edition. Every rule site asks the engine (the turn's options and refusal, the turn prompt,
a 2-space High Ball's and Vorix's set-up, the Winger's, Zytheris's shot); a 1.0 caller of the
`MatchState` methods gets the range by default.

- **The time out is offered on any turn** (6.2, the author's answer when asked): the Charter's
  "out of range" condition would never hold in 2.0, so it is dropped, and once a half and not
  after last possession stay. So a 2.0 turn offers all three actions at once.
- **The bot's board draws no range bracket** in a 2.0 game (`shooting_range` on
  `render_match_image`, `render_field_image` and `draw_board`, from `shooting_range_applies`),
  and the printed 2.0 field board puts the standard roles where 1.0 brackets the ranges
  ([printed-boards.md](printed-boards.md), "The 2.0 boards").
- **Dinky needs nothing**: it shoots only from the scoring space, so it does not start shooting
  from its own end, and calls a time out only for an injured player on the field.
- **A long shot is still harder**: every defender between the ball and the goal adds half their
  skill (Law 5.3.2), which is what makes a range unnecessary rather than the shot free.

## Roles

**`RulesEngine.role_of(match, player_id)` is the one reading of which role a card is
playing**, and `has_role_ability(match, player_id, role)` the one question every role-ability
site asks (the Fullback's distances, the Defender's steal, the Midfielder's +3, the Playmaker's
space, the Winger's set-up, the Striker's +3) -- the twin of `has_species_ability`. 2.0 moves a
role off the player and onto the formation (rules-2.0 section 4), so the two editions can only
be told apart where the role is read, and that has to be one place. They ask the match rather
than the game because every one of the sixteen sites is handed the match and nothing else.
`tests/test_role_reading.py` holds the rule modules (`engine.py`, `flow/`,
`prompts.py`, `ai.py`, `dice_brief.py`) to reading no `.role` outside `role_of` and Dinky's
`role_rank`, which ranks the bench by each card's printed skill profile rather than by a role
anybody is playing.

**A 2.0 match carries its roles: `MatchState.formation_roles`**, per side `{card id: role}` for
the six fielded cards, a bench card holding none. It is one of `MATCH_EXPLICIT_FIELDS`, written
only where a match has roles, for the reason `maneuver_decks` is: a 1.0 match is saved byte for
byte as before. `role_of` reads it where it is there and each card's own role where it is not,
so a 2.0 game saved before the field plays on with its cards' roles -- and its role abilities,
since `has_role_ability` answers no only for a match whose roles are the formation's
(rules-2.0 4.7). Who holds what:

- **The deal** is `RulesEngine.deal_formation_roles`, beside the decks at kickoff and gated the
  same way (`maneuver_deck_applies`, so never a tutorial): the six 1.0 deals, each in the role
  their card names (the author, 2026-10-18). Each unique role has a space (rules-2.0 4.3a,
  `MatchState.unique_role_space`), and on boards 7 and 9 the 1.0 deal already stands them there;
  on board 10 it puts the Midfielder on the kickoff space (Law 3.2.2), so the 2.0 deal moves the
  Playmaker onto it and the Midfielder behind, and records that as the first arrangement.
- **`MatchState.assign_formation_roles`** reads a freshly dealt side: in each zone the card on
  the unique role's space (the nearest, where nobody is) takes it and the rest the standard role
  (`FORMATION_ZONE_ROLES`). It is asked only where nobody shares a space -- after the deal, and
  after a re-deal by hand (`apply_formation`, which no 2.0 hub offers) -- since an Ooze may
  share a unique role's space and the space would then not say who holds it. An arrangement
  (below) gives its roles rather than reading them back.
- **A substitute takes the outgoing card's role** (`substitute`). **A 2.0 Coaching Choice has no
  zone assignment and no space positioning** (rules-2.0 4.6c, the author, 2026-10-25: *"drop
  them"*): a rearrangement's trades and moves (below) do both, so the hub offers a 2.0 side no
  `swaps` and no `repositions`, the driver refuses `swap` and `reposition` for it, and Discord
  builds neither button. The model's own readings stay -- `exchange_field_players` still trades
  two 2.0 roles, two in the same zone included, and `positioning_targets` still says where a 2.0
  card may be moved -- because a sharer stepping off a unique role's space goes by the second,
  and a test or an admin edit may call the first.
- **The Playmaker takes the kickoff** (rules-2.0 4.4): `RulesEngine.hand_kickoff_to_playmaker`
  makes them the carrier just before a restart from the kickoff space is played -- at the end
  of setup (`finish_setup_coaching`), of halftime (`finish_halftime`) and of a goal's restart
  (`run_back_kickoff_fill`), once every arrangement and window has settled. A carrier rather
  than a new reading of who may handle, because "the ball was left with somebody" is already
  what a carrier says (Law 4.2.2) and `turn_handler_candidates` already honours it. It only
  changes anything where somebody shares the Playmaker's space -- an Ooze (rules-2.0 4.6e) --
  since nobody else's arrangement puts them on the kickoff space.
- **Where a card may be moved reads the role** (rules-2.0 4.6d): `MatchState.positioning_targets`
  is the one reading of where a card may be moved and whom it trades with, and `position_meeple`
  refuses against it. A unique role goes nowhere; a standard role goes to an empty space, or
  trades with a teammate in a standard role, never onto a space a unique role holds. In 1.0 it is
  every other space of the zone, the hub's `repositions` are built from it, and
  `position_meeple`'s own trade rule decides, as before. **An Ooze bends it** (4.6e): one in a
  standard role may go anywhere in its zone and shares rather than trades, and one in a unique
  role is still locked but lets a standard teammate share its space. Which cards are Spreadable
  is the engine's (`spread_exempt_ids`), handed in, since the match knows no species -- so in
  training mode, which plays no species abilities, nobody bends it.
- **Moving off a unique role's space** (rules-2.0 4.6e, the author, 2026-10-18): a teammate
  sharing an Ooze's unique space is left sharing it with somebody who is not an Ooze when a
  substitution puts them in the role. The substitution stands; `MatchState.unique_space_sharers`
  names who has to move, `settle_unique_space_sharers` moves each who has one empty space of
  their zone to go to (`windows.settle_moves`, which says so), and one with a choice is the
  coach's, by rearranging (the author, 2026-10-25): the arrangement as it stands would not be
  allowed (`arrangement_refusal`), but `ArrangementOptions.edits` keeps every change whose result
  would be, so the sharer is offered a move to any space with room, in any zone, and the other
  five only what also moves the sharer off. `coaching_finish_refusal` holds the window until they
  have moved, and the hub's options name them (`must_move`), so Dinky sends the first move their
  edits offer before it is done. A zone never holds more players than spaces, so with two on one
  there is always an empty one.
- **There are no formations: a side is arranged by its roles** (rules-2.0 4.2, 4.3; the author,
  2026-10-24, replacing the formation change of 2026-10-18). An arrangement is the three unique
  roles' holders, each stood on their space, and three placements anywhere on the field, each
  taking its zone's standard role. `MatchState.arrange_side` puts a side in one, checking it
  whole before anybody moves, and `RulesEngine.apply_arrangement` words it. The shape is whatever
  that makes, so a 2.0 side is named by its counts (`RulesEngine.shape_name`, "3-1-2" as readily
  as "2-2-2") rather than by `current_formation`, which knows only the five 1.0 shapes; the hub's
  title and the window's summary both ask it.
- **One reading of whether an arrangement may stand**: `arrangement_refusal`, a pure function
  over every fact it needs, with `arrangement_space_open` under it -- an empty space, or a shared
  one where either is an Ooze, in a zone with room. **No zone holds more players than spaces,
  Oozes included** (the author, 2026-10-24): besides being the rule, it is what keeps an empty
  space for a unique role's sharer to step off to. `arrange_side` refuses on it, and the
  prompt's `ArrangementOptions.refusal` and `edits` read the same function, so nothing is offered
  that the match would refuse.
- **A rearrangement starts from the side as it stands** (the author, 2026-10-24: *"it should
  already be set up the way it is currently set up, and then they can make changes on the basis
  of the current setup"*). The deal still sets every side up (`deal_formation_roles`);
  `MatchState.current_arrangement` reads it back, the options carry it (`holders`, `placed`), and
  `ArrangementOptions.edits(player)` is every change that starts with one of the six -- a move to
  a space with room, a trade of places and roles with one of the other five, and before kickoff a
  bench player in their place -- each the whole arrangement it leaves, kept only if
  `arrangement_refusal` lets it stand. The hub's `arrange` answer takes that whole arrangement,
  so the driver's door is one and the same however the frontend builds it.
- **Before kickoff the pool is the squad** (rules-2.0 4.3c): `MatchState.arrangement_pool` is the
  six on the field, and the bench too where the window's substitutions have no limit -- setup's
  -- so whoever on the field is left out goes off through `substitute` and is recorded as the
  window's substitution. After kickoff a substitution is counted, so an arrangement rearranges
  the six playing. Who among the pool is Spreadable is `RulesEngine.spreadable_among`, since a
  bench Ooze is not among `spread_exempt_ids`' fielded six.
- **The hub offers Arrange team in place of Formation** for a 2.0 side (`CoachingHubOptions.
  arrangement`, with `formations` empty, and the driver's `arrange` answer refusing a 1.0 side
  as `formation` refuses a 2.0 one). On Discord `CoachingArrangeView` lists the six as they stand,
  role and space on each button, and `CoachingArrangePlayerView` one player's edits; a click
  applies the change at once and the side comes back up with the half-field redrawn, one
  `edit_message` a click as every hub step is. Zone Assignment and Space Positioning are not
  built beside it. Dinky never arranges for its own sake -- the deal's recommended arrangement is
  its -- and sends `arrange` only to move a sharer off a unique role's space, or, where the
  window is held while a unique role stands off their space, the side as it stands again, which
  puts the Playmaker back on the kickoff space (`DinkyAI._rearrangement`). The web app plays no
  2.0, so it shows neither control.

Decided for the step still to come (the author, 2026-10-18): **a 2.0 bench player is named by
their skills** rather than a role, since they hold none.

What is not done yet: a 2.0 hand on the web page; a printed two-headed card for the
print-and-play kit; the Learn to Play; and the rest of **the roles of rules-2.0 section 4** (the
author, 2026-10-18): roles in the labels and pictures, a bench player named by their skills.

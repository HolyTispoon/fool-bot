# D12 Ball 2.1: the maneuver deck

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are
[rules-2.1.md](../rules-2.1.md) over [living-rules.md](../living-rules.md).

**2.1 replaced 2.0's cards on 2026-10-31** (the author): twenty-four single-faced cards, four
for each basic maneuver, each with a role special, any card playable as the other side's
maneuver of its rank for an extra card, and no advanced maneuvers. 2.0's two-headed cards and
their importer are filed away in [archive/maneuvers-2.0/](../../archive/maneuvers-2.0/README.md);
nothing deals them, and no saved 2.0 game is carried over -- the three games in progress on the
live bot were abandoned (the author: *"we don't need any legacy"*). Everything else 2.0 built --
the roles, the moving costs, no range, the secret hand -- is 2.1's as it stood.

## An edition beside the mode

`D12BallGame.edition` (`Edition.ONE`, `Edition.TWO`) is a setting of its own, not a fourth
mode (the author, 2026-10-16: "keep d12ball 1.0 as is"; each mode keeps its abilities and
every mode can play the deck). **`Edition.TWO` is 2.1**: its saved value is still "2.0", since
2.1 is the same setting with new cards, and only what a person reads says 2.1
(`formatting.EDITION_NAMES`). **Nothing reads it to decide a rule**:
`RulesEngine.maneuver_deck_applies` is the answer, and it is never true for a tutorial, whose
beats rail cards a shuffled hand may not hold (`configure` refuses 2.x there and
`pin_tutorial` sets 1.0).

- **`gambits_apply` answers no in 2.1**, whatever the mode: there are no advanced maneuvers.
  `coin_applies` -- the gate over everything Law 19.3 adds -- is the same answer, 1.0's
  advanced mode alone.
- **The record leaves the field out of `to_dict` while it is 1.0**, as it does `ai_seats`, so a
  1.0 save is written byte for byte as before.
- **The rematch carries it**, in the service's `rematch` and the cog's.
- **Discord alone offers it**: two buttons on the mode's row of the lobby and the setup
  screen (`EDITION_BUTTONS`). The web table names the settings it shows and does not name this
  one, and `webapp.server` refuses it outright (`DISCORD_ONLY_SETTINGS`): the page has no
  secret hand. A web game is never 2.x.

## The deck is data on the match

`MatchState.maneuver_decks` is `{"home": deck, "visiting": deck}`, each deck `{"draw",
"hand", "discard"}` lists of **card ids**, saved as it stands. It is one of
`MATCH_EXPLICIT_FIELDS` rather than a row of the table, because **a match with no decks writes
no key**: every row of the table is in every save, and a 1.0 match has to be saved exactly as it
was before 2.0 -- the four goldens pin that byte for byte. An absent key reads as no decks,
which is 1.0 and every save before the field. `d12ball/maneuver_deck.py` is the cards and the three
moves made on them -- `new_deck`, `draw_cards`, `play_cards` -- with the engine's `rng` handed
in, so a seeded game deals and reshuffles the same way every time.

- **A card is its sheet index, not a maneuver or a name**: "P1" to "R4". Two of 2.1's names
  are 1.0 cards' names -- P3 is "Pinpoint", P4 "Reset" -- so a slug of the name would collide
  with the catalog's keys; the index is what the tab, the deck, the save and the rules read.
  What a card plays is `plays_as(catalog, card, side)`: its own maneuver on its own side, and on
  the other side, flipped, the maneuver of the same rank there.
- **The deck belongs to a team, the pick to a maneuver side.** The engine maps one onto the
  other with `maneuver_side_team`, the reading every other per-side question already uses.
- **The reshuffle is at the last card drawn**, not at a draw from an empty pile -- the
  author's wording -- so a deck between turns is never empty while there is a discard.
- **Twenty-four cards and five in hand** (`deck_cards`, `HAND_SIZE`).
- **The picks are still maneuver keys** on `offense_maneuver` / `defense_maneuver` -- always
  one of the six basic keys -- and **the cards behind them are `MatchState.maneuver_cards`**,
  `{side: [card]}` or `[card, extra]` for a flip. One of `MATCH_EXPLICIT_FIELDS`, written only
  while there are any, and cleared with the picks in `reset_maneuver`, since the effect reads it
  until the maneuver is over.

## The 2.1 cards

**The deck is the `maneuvers 2.1` tab** (gid 1310773351 -- the tab 2.0 read, renamed and
rewritten in place), imported by `scripts/import_d12ball_maneuver_cards.py` into
`d12ball/data/maneuver_cards.json` and read into `ManeuverCatalog.deck_cards`, a `DeckCard` an
index ([rules-and-data.md](rules-and-data.md)). The importer skips the tab's Advanced rows and
says so, fills a blank `Mode` or `Time` with Basic and 1 and says so, refuses a card whose
`Maneuver` is not 1.0's basic card on its rank or whose `Effect` differs from its rank's, and
**refuses a rank whose four specials do not name each of the six roles exactly once** -- the
property that makes a role tell which card's special a player plays. It strips the spaces at a
cell's ends and nothing else: a typo on the tab is the author's to fix there.

- **Not a catalog of maneuvers.** A `DeckCard` plays one of the six `ManeuverDefinition`s, so
  the matchups, the clock, the stats, the bearings and every effect table see 1.0's keys, and
  the cards sit beside the catalog's sides rather than in them. The 2.0 catalog's variant tier,
  `deck_side`, `effect_two` and `merge_edition_two` are gone with the cards they read.
- **A special is a role interaction, read once.** `RulesEngine.card_special(match, side)` is
  the one reading: the index of the side's card where it was played as itself and the player
  making the maneuver -- the handler on offense, the challenger on defense
  (`maneuver_actor`) -- holds a role it names, through `role_of` (`special_names_role`). Every
  site a special changes asks `card_special(match, side) == maneuver_deck.PINPOINT` and so on,
  by the named indexes in `maneuver_deck.py`, as a site asks a maneuver by its key; nothing else
  reads a role for one. It is the 2.x twin of `has_role_ability`, which still answers no for the
  Charter's six abilities in a match whose roles are the formation's (rules-2.1 4.7). Where a
  special is a Charter ability on one card -- P1 the Winger's set-up, F1 the Fullback's deflect
  -- the site asks both.
- **A special runs in its maneuver's step**, mostly where 2.0's variant of the same shape ran:

  | Card | Where |
  | --- | --- |
  | P1, P2 | `low_pass_tail`'s set-up; `offer_passer_advance` |
  | P3, P4 | `RulesEngine.pass_candidates` adds the teammates within 2, or the Playmaker (`playmaker_pass`) |
  | B1, B3, B4 | `dribble_two_tail`: a scoring opportunity; the speed choice by defensive skill; no carrier, so the turn's handler choice offers a teammate on the space (Law 4.2.3) |
  | B2 | `dribble_advance_asked`, Dribble's distance prompt |
  | H1, H3, H4 | `high_pass_distance_options`: 3 or 4, 2 or 3, 0/1 or 3; under 2 is `vertical_ball_step` |
  | H2 | the `"long_shot"` choice on `HIGH_PASS_CHOICE` (`DistanceOptions.long_shot`), `long_shot_step` |
  | F1, F2, F3, F4 | `deflection_numbers`; `deflection_step`'s follow, set-up anywhere, and `contest_on_the_spot` |
  | S1 | the run back's speed choice by offensive skill (`finish_run_back`, `effect_choice_prompt`) |
  | S2, S4 | `steal_step`'s turnover in place, and `toss_ball` |
  | S3 | `skill_test_step`'s +3 |
  | R1, R2, R3, R4 | `pressure_step`: `turnover_in_place`, `control_step`, the handler's extra token, `contest_on_the_spot` |

  2.0's Spin question (`SPIN_MOVE`) went with its card.
- **Every special that asks something asks a prompt the game already had**, so the restart
  reading (`effect_choice_prompt`) reads it off `card_special` and the position: B3's and S1's
  speed choice carry their skill type, B2's distance is Dribble's, H1 to H4 are High Ball's
  distance prompt with more distances and H2's choice, P2 is the passer's step.
- **What the readings are** -- each the plainest reading of the tab, listed in the PR for the
  author to confirm: a "may" that replaces the card's own throw or pass is offered beside it;
  F2's follow and R2's are always made, as 2.0's Follow and Stress were; F3's set-up is the
  deflection's own, taken by the player who played it from where the ball lies; F4 and R4 are a
  contest between handler and challenger on the ball's space, the speed left alone; B1's shot is
  a scoring opportunity (Law 8); B4's teammate is the turn's own handler choice.

## The flip

**On their turn a coach may discard an extra card to play any card as the same rank's maneuver
on the other side, without its special** (rules-2.1 2.3; the author, 2026-10-31). The pick
therefore names a card, and a flip the extra card: `Action(MANEUVER_ACTION, "", {"side",
"maneuver_key", "card_id", "extra_card_id"})`. `maneuver_key` is still the required argument --
1.0's pick is a key alone -- and the driver refuses a 2.1 pick without a card, a card not in the
hand, a card that does not play that key, and a flip without an extra card from the hand
(`turn._card_pick_refusal`). **`RulesEngine.card_plays` is the one list**: every card in the hand
as a `CardPlay` (`maneuver_deck.py`) -- its maneuver on the side, whether it is a flip, the
cards a flip may discard (every other card in the hand) and whether its special is live. The
prompt carries it (`ManeuverHand.cards`), the Discord hand builds its buttons off it, the refusal
reads it, and the AI picks from it. A hand of one card cannot flip.

**Dinky** rolls its rank as before, plays a card of its own side on it where it holds one -- a
live special first -- and plays another of its own ranks rather than flip; it flips only a hand
with nothing of its own side, discarding the first other card (`DinkyAI._card_for`).

## Who holds what

**`RulesEngine.maneuver_hand` is still the only answer to which maneuvers a coach may play.** In
2.1 it is every key `card_plays` reaches -- a coach holding any card of the other side and
another to discard can play every rank. The prompt's `ManeuverHand` keeps `maneuver_keys` and
`held` (the five card ids) with `deck_count` and `discard_count`, and grows `cards`.

**An unchallenged maneuver plays its card**, and its special applies to the handler.

## Played at the reveal

`d12ball.flow.turn.play_maneuver_cards`, at the end of `maneuver_pick_step` once
`maneuver_selections_complete`: each side's cards on `maneuver_cards` -- the card, and a flip's
extra -- go to the discard and the coach draws back to five. It is the reveal rather than
`begin_effect_resolution` because that is when a card is down for good -- until then the pick
may change -- and the step where both picks become complete is the one place every maneuver
passes (an AI's pick goes through the same answer). A reshuffle is said, since it is public. The
reveal names each card -- "Pinpoint (P3), a Pass, its special in play", "Pass and Run (P2)
played as Deflect" (`RulesEngine.played_card_label`).

## On Discord: the hand is secret

1.0's prompt puts both hands' buttons on one public message, which works because every coach
holds the same three cards. A 2.x hand is a secret, so **the public prompt carries one
**My hand** button and no card** (`d12ball:maneuver_hand:<game>`, `HAND_BUTTON_LABEL`), and no
hand image. One button rather than one a side (the author, 2026-10-17): who presses it says
whose hand it is. It answers ephemerally with the hand of each side the clicker coaches --
both, named by side, for somebody coaching themselves -- as the five cards
(`deck_faces.render_deck_hand`, one row, the side's own cards first) and `ManeuverHandView`,
**one button a `CardPlay`**: "P3 Pinpoint", starred where its special is live, in the side's
colour; and "⇅ F1 Deflect as Pass" for a flip, grey, which answers with `FlipExtraView` -- one
button a card the flip may discard -- before it is a pick. Somebody coaching neither side is put
through the pick's own gate a side at a time, so a helper is confirmed and then shown every hand
on the prompt, and anybody else is refused. A pick from there is the 1.0 pick exactly
(`ManeuverPicking`, the mixin the views share): the same action, an ephemeral "You chose P3
Pinpoint" (or "... as Pass, discarding ..."), the prompt deleted once both are in. The public
message is never edited, as in 1.0, and a restart re-arms it from the custom ids; the ephemeral
hand is not persistent, and pressing the public button again sends a fresh one.

## The faces

**A 2.1 card is drawn from scratch** (`d12ball/deck_faces.py`, the author, 2026-10-31), not
from the printed 1.0 card's parts -- the 2.0 two-headed card and its band went with the cards.
Top to bottom: the header, the card's name beside its rank badge (O1, D2), with its index, its
maneuver and its time under the name; **the main effect**, the rank's wording, largest; **the
role interaction** in a box tinted with the card's colour, headed with the roles it names in
full ("IF FULLBACK OR DEFENDER"); **an empty, labelled space for the spec ability** advanced
mode will add, with the tab's `Spec` name small in its corner where it gives one; and **a green
strip along the bottom**, "Discard an extra card: play as Deflect", the same rank's maneuver on
the other side. Offense is 1.0's red; **defense is navy, #0B2545** (the author) -- on the 2.1
face alone, so the 1.0 cards are byte-identical (hashed before and after, every face, back and
hand). Each face is drawn once and kept (`lru_cache`). The print run is
`scripts/render_maneuver_cards.py --edition 2.0`, into `maneuver-cards-2.1/`, every card on the
2.x back (`EDITION_TWO_BACK`). **The matchup row sits above the flip strip** (the author,
2026-10-31: "Need the matchup row"): BEATS / TIES / LOSES TO over the other side's rank badge in
that side's colour and the basic maneuver on it, read off the rank as 1.0's row is
(`matchup_rank_groups`, `draw_matchup_row`) -- every card of a rank reads the same row, and no
advanced card is named, since 2.1 has none.

**The discard piles are face up** (the author): the public 2.x prompt carries both coaches'
piles as one picture (`deck_faces.render_discard_piles`, `D12Ball.build_discard_file`) once
either has discarded anything -- the upload the 1.0 hand image made, so no extra request. **A
discarded card is a chip, not the card** (the author, 2026-10-18): its rank badge and its index
and name, in the new face's colours (`discard_chip`), in the order they went down. **Each pile
is a column, the two side by side**, home's first (the author, 2026-10-20). The model's reading
is `RulesEngine.maneuver_discards`; a picture is not a button, so it is read off the match, as
the field strip is.

**Halftime reshuffles** (the author): `begin_halftime` asks
`RulesEngine.reshuffle_maneuver_decks`, which puts each coach's hand and discard back into the
deck, shuffles and deals five (`maneuver_deck.reshuffled`), and says so in halftime's opening
message. A 1.0 halftime is unchanged, which the windows golden pins.

## The coin

**2.1's coin settles every tie, and is tossed again after it** (rules-2.1 section 5; the author,
2026-10-20 and 2026-10-31: *"The coin is tossed after any tie so players always know how it'll be
resolved next and it has to be presented in turn messages"*). A skill test's, a contest for the
ball's and, new in 2.1, a score attempt's tie goes to the face the coin shows -- Fortune to the
offense (at a shot, the attack scores), Doom to the defense -- and then the coin is tossed, and
its new face holds until the next tie. A tied shootout test scores for nobody and leaves the coin
alone. It is not 1.0's gambit coin, which `coin_applies` gates and 2.1 has none of.

- **`MatchState.tie_coin` is the face it shows**, saved only once flipped (`MATCH_EXPLICIT_FIELDS`),
  so a 1.0 match is written as before. `RulesEngine.tie_coin_applies` is the gate, the deck's
  answer under its own name, and `tie_coin_winner` the one reading of whom the face favours.
- **Flipped at the first turn** (`turn.settle_tie_coin`, in `start_turn`), before anybody is
  asked anything, and never again there: 2.0 tossed it at a turn's start after an advanced card,
  and with no advanced cards the turn-start toss and `tie_coin_owed` are gone.
- **Settled and tossed in one place**, `rolls.coin_settles_tie`: it reads the face, says who wins
  and why, tosses (`engine.flip_coin`, the engine's `rng`) and says the new face and what it means
  -- asked where 1.0 re-rolls a tied test or contest (`skill_test_step`, `loose_ball_test_step`)
  and where 1.0 scores a tied shot (`score_attempt_step`). A tie met before any flip flips it
  first, and says so.
- **The face is always in view** (the author, 2026-10-20 and 2026-10-31): every turn message
  carries it (`build_turn_prompt`, "Doom: defense wins ties.") and the board draws the game's own
  coin showing it on the jumbotron, with the same words under it (`draw_jumbotron_coin`). The
  engine answers both -- `tie_coin_face` and `tie_coin_caption` -- and the cog hands the renderer
  the picture's name and the caption (`D12Ball.tie_coin_brief`), so the renderer reads no rule.
  With no coin the jumbotron is drawn exactly as before, byte for byte.

## Moving costs

**In 2.x a move on the board costs a token a space, and a card costs nothing** (rules-2.1 5.4;
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

**2.0 has no shooting range: a shot may be taken from anywhere** (rules-2.1 section 6; the
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
role off the player and onto the formation (rules-2.1 section 4), so the two editions can only
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
(rules-2.1 4.7). Who holds what:

- **The deal** is `RulesEngine.deal_formation_roles`, beside the decks at kickoff and gated the
  same way (`maneuver_deck_applies`, so never a tutorial): the six 1.0 deals, each in the role
  their card names (the author, 2026-10-18). Each unique role has a space (rules-2.1 4.3a,
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
  zone assignment and no space positioning** (rules-2.1 4.6c, the author, 2026-10-25: *"drop
  them"*): a rearrangement's trades and moves (below) do both, so the hub offers a 2.0 side no
  `swaps` and no `repositions`, the driver refuses `swap` and `reposition` for it, and Discord
  builds neither button. The model's own readings stay -- `exchange_field_players` still trades
  two 2.0 roles, two in the same zone included, and `positioning_targets` still says where a 2.0
  card may be moved -- because a sharer stepping off a unique role's space goes by the second,
  and a test or an admin edit may call the first.
- **The Playmaker takes the kickoff** (rules-2.1 4.4): `RulesEngine.hand_kickoff_to_playmaker`
  makes them the carrier just before a restart from the kickoff space is played -- at the end
  of setup (`finish_setup_coaching`), of halftime (`finish_halftime`) and of a goal's restart
  (`run_back_kickoff_fill`), once every arrangement and window has settled. A carrier rather
  than a new reading of who may handle, because "the ball was left with somebody" is already
  what a carrier says (Law 4.2.2) and `turn_handler_candidates` already honours it. It only
  changes anything where somebody shares the Playmaker's space -- an Ooze (rules-2.1 4.6e) --
  since nobody else's arrangement puts them on the kickoff space.
- **Where a card may be moved reads the role** (rules-2.1 4.6d): `MatchState.positioning_targets`
  is the one reading of where a card may be moved and whom it trades with, and `position_meeple`
  refuses against it. A unique role goes nowhere; a standard role goes to an empty space, or
  trades with a teammate in a standard role, never onto a space a unique role holds. In 1.0 it is
  every other space of the zone, the hub's `repositions` are built from it, and
  `position_meeple`'s own trade rule decides, as before. **An Ooze bends it** (4.6e): one in a
  standard role may go anywhere in its zone and shares rather than trades, and one in a unique
  role is still locked but lets a standard teammate share its space. Which cards are Spreadable
  is the engine's (`spread_exempt_ids`), handed in, since the match knows no species -- so in
  training mode, which plays no species abilities, nobody bends it.
- **Moving off a unique role's space** (rules-2.1 4.6e, the author, 2026-10-18): a teammate
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
- **There are no formations: a side is arranged by its roles** (rules-2.1 4.2, 4.3; the author,
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
- **Before kickoff the pool is the squad** (rules-2.1 4.3c): `MatchState.arrangement_pool` is the
  six on the field, and the bench too where the window's substitutions have no limit -- setup's
  -- so whoever on the field is left out goes off through `substitute` and is recorded as the
  window's substitution. After kickoff a substitution is counted, so an arrangement rearranges
  the six playing. Who among the pool is Spreadable is `RulesEngine.spreadable_among`, since a
  bench Ooze is not among `spread_exempt_ids`' fielded six.
- **The hub offers Arrange team in place of Formation** for a 2.0 side (`CoachingHubOptions.
  arrangement`, with `formations` empty, and the driver's `arrange` answer refusing a 1.0 side
  as `formation` refuses a 2.0 one). On Discord `CoachingArrangeView` lists the six as they stand,
  role first, then the player and their space, on each button, and `CoachingArrangePlayerView` one
  player's edits -- "Move to space −2 as Defender", "Stay here as Winger", "Trade places and roles
  with ...", "Bring on ... in this role"; a click applies the change at once and the side comes back
  up with the picture redrawn, one `edit_message` a click as every hub step is. **Its message says
  what Arrange team is** (the author, 2026-10-28: after the deal's recommended arrangement, make it
  clear the coach now assigns players to roles by zone): "Assign your players to roles.", then
  the side zone by zone -- each zone's unique role, its space and who holds it, and its standard
  role and who holds it, "nobody" where nobody does -- and the bench, holding no role. **The
  picture is the 2.0 board** (below), both sides' slots and benches, at 1x, in place of 1.0's
  half-field. Zone Assignment and Space Positioning are not
  built beside it. Dinky never arranges for its own sake -- the deal's recommended arrangement is
  its -- and sends `arrange` only to move a sharer off a unique role's space, or, where the
  window is held while a unique role stands off their space, the side as it stands again, which
  puts the Playmaker back on the kickoff space (`DinkyAI._rearrangement`). The web app plays no
  2.0, so it shows neither control.

- **A new play is a run back** (rules-2.1 4.9, the author, 2026-10-24): every player is placed
  again in their own zone, free -- the unique roles on their spaces -- and the Coaching Choice
  comes after; a time out's and halftime's window sends the unique roles back as it opens and
  the coach puts everybody else right by rearranging, a change at a time -- each stray back in
  their zone or given a new role -- and a steal's run back is
  the Charter's. The machinery is the run back's: "2.0: a new play is a run back" in
  [possession-and-turnovers.md](possession-and-turnovers.md).

**At the table** a role is a loose piece: the print-and-play kit's role tokens, a zone's unique
role on one side and its standard role on the other, laid on the card holding it -- a 2.0 card,
which prints none -- and the players
on the field are standees, since a meeple can no longer be told apart by role (the author,
2026-10-24) -- [printed-tokens.md](printed-tokens.md), "Role tokens", and
[standees.md](standees.md). The 2.0 field and zone boards show which role goes where, on boards 9
and 10 -- [printed-boards.md](printed-boards.md), "The 2.0 boards".

Decided for the step still to come (the author, 2026-10-18): **a 2.0 bench player is named by
their skills** rather than a role, since they hold none.

**The printed players have a 2.0 piece**, a tile smaller than a card that names no role (the
author, 2026-10-24 and 2026-10-25), and
`/d12ball team_reference` posts it in a 2.0 game -- [cards.md](cards.md), "The 2.0 player tiles".

**The bot's 2.0 board is a zone board** (the author, 2026-10-28: "a version of the zone board for
the discord bot that would house the players of each team above and below the board ... use the
player tiles for 2.0, make it clear which sits on each role"). `zone_board_image.render_zone_board`
draws the field and the jumbotron the 1.0 board does, and round them each side's players as 2.0
tiles in slots -- a zone's slots over or under that zone of the field, the visitors' over and
home's under, each with its role on a pill between the tile and the field, every pill the same dark outline and a unique
role's marked in words -- a star before its name and a heavier border -- since gold (the printed
board's) read as Orange's and white was no better (the author, 2026-10-28); an OPEN slot for a
role of the zone nobody holds. The benches are tiles with no slot. The meeples carry the role the match gives them
(`render.draw_board`'s `roles`), so the field and the slots agree. Who holds what is
`RulesEngine.board_roles`, handed in; the renderer asks no rule. It is the board message's picture
in a 2.0 game, the Coaching Choice's (at 1x, since it is re-uploaded with every change), and the
field strip under a prompt carries the roles on its meeples -- [board-image.md](board-image.md),
"The 2.0 board".

**Every name in a 2.0 game carries the role the card holds**, and a bench card its skills --
[naming-and-wording.md](naming-and-wording.md), "Naming a player".

What is not done yet: a 2.1 hand on the web page; the 2.1 cards in the print-and-play kit; the
spec abilities the face leaves room for; the Learn to Play's 2.x cards; and of **the roles of
rules-2.1 section 4**, the matchup image's ability line, which still prints the card's own role
ability though 2.0 plays none (4.7), and the goal log, which names a scorer by the card's role.

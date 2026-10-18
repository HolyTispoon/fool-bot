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
- **The picks are still maneuver keys** on `offense_maneuver` / `defense_maneuver`; nothing in
  the effect pipeline knew there was a deck.

## Who holds what

**`RulesEngine.maneuver_hand` is still the only answer to which cards a coach may play.** In
2.0 it reads the side's team's hand through `plays_as` -- one entry a maneuver however many
copies are held -- and `maneuver_tiers` is read off it rather than the other way round. The
prompt's `ManeuverHand` keeps `maneuver_keys` as the answer, and grows `held` (the four card
ids) with `deck_count` and `discard_count`, which the AI and the pick refusal do not read. The
AI needed nothing: Dinky already picks among the keys on a rolled rank, and from the whole
hand where it holds nothing on that rank.

**An advanced card against no challenge resolves as its basic counterpart** (the author). It
is recorded as played, and `resolving_maneuver` downgrades it with no change, since
`cards_outcome` answers `None` with no opposing card; the uncontested narration says so.

## Played at the reveal

`d12ball.flow.turn.play_maneuver_cards`, at the end of `maneuver_pick_step` once
`maneuver_selections_complete`: the card behind each pick goes to the discard and the coach
draws to four. It is the reveal rather than `begin_effect_resolution` because that is when a
card is down for good -- until then the pick may change -- and the step where both picks
become complete is the one place every maneuver passes (an AI's pick goes through the same
answer). A reshuffle is said, since it is public.

## On Discord: the hand is secret

1.0's prompt puts both hands' buttons on one public message, which works because every coach
holds the same three cards. A 2.0 hand is a secret, so **the public prompt carries one
**My hand** button and no card** (`d12ball:maneuver_hand:<game>`, `HAND_BUTTON_LABEL`), and no
hand image. One button rather than one a side (the author, 2026-10-17): who presses it says
whose hand it is. It answers ephemerally with the hand of each side the clicker coaches --
both, named by side, for somebody coaching themselves -- as the four cards
(`render_deck_hand`) and `ManeuverHandView`, one button a playable maneuver. Somebody coaching
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
discarded anything -- the upload the 1.0 hand image made, so no extra request. Copies of a card
are drawn once with a count under them. The model's reading is
`RulesEngine.maneuver_discards`; a picture is not a button, so it is read off the match, as the
field strip is.

**Halftime reshuffles** (the author): `begin_halftime` asks
`RulesEngine.reshuffle_maneuver_decks`, which puts each coach's hand and discard back into the
deck, shuffles and deals four (`maneuver_deck.reshuffled`), and says so in halftime's opening
message. A 1.0 halftime is unchanged, which the windows golden pins.

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
  their card names (the author, 2026-10-18). Each unique role has a space (rules-2.0 4.3b,
  `MatchState.unique_role_space`), and on boards 7 and 9 the 1.0 deal already stands them there;
  on board 10 it puts the Midfielder on the kickoff space (Law 3.2.2), so the 2.0 deal moves the
  Playmaker onto it and the Midfielder behind, and records that as the first arrangement.
- **`MatchState.assign_formation_roles`** reads a freshly dealt side: in each zone the card on
  the unique role's space (the nearest, where nobody is) takes it and the rest the standard role
  (`FORMATION_ZONE_ROLES`). It is asked only where nobody shares a space -- after the deal and
  after a formation change -- since an Ooze may share a unique role's space and the space would
  then not say who holds it.
- **A substitute takes the outgoing card's role** (`substitute`), and **a zone assignment trades
  the two roles** (`exchange_field_players`).
- **The Playmaker takes the kickoff** (rules-2.0 4.4): `RulesEngine.hand_kickoff_to_playmaker`
  makes them the carrier just before a restart from the kickoff space is played -- at the end
  of setup (`finish_setup_coaching`), of halftime (`finish_halftime`) and of a goal's restart
  (`run_back_kickoff_fill`), once every arrangement and window has settled. A carrier rather
  than a new reading of who may handle, because "the ball was left with somebody" is already
  what a carrier says (Law 4.2.2) and `turn_handler_candidates` already honours it. It only
  changes anything where somebody shares the Playmaker's space -- an Ooze (rules-2.0 4.6e) --
  since nobody else's arrangement puts them on the kickoff space.
- **A formation change** re-deals by defensive skill as in 1.0 (`deploy_side`) and then reads
  the roles off the new shape. That is a stand-in: the change that keeps the Fullback, the
  Playmaker and the Striker on their spaces is the next step.

Decided for the steps still to come (the author, 2026-10-18): **a 2.0 bench player is named by
their skills** rather than a role, since they hold none; and **a formation change keeps the
Fullback, the Playmaker and the Striker** and fills the new standard roles by defensive skill,
leaving the coach to change anything with role trades and space positioning, which between them
reach every assignment the rules allow.

What is not done yet: a 2.0 hand on the web page; a printed two-headed card for the
print-and-play kit; the Learn to Play; and the rest of **the roles of rules-2.0 section 4** (the
author, 2026-10-18): a formation change that keeps the three unique roles on their spaces, the
Coaching Choice's movement rules (4.6), and roles in the labels and pictures -- a bench player
named by their skills.

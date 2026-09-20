# Species abilities in the bot

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Species abilities in the bot

The four abilities as the engine plays them. The rules are
[Species abilities](../living-rules.md#species-abilities) and are settled;
what is here is how they are wired, and the reasoning the rules do not carry.

**Advanced mode is one switch over two modules** -- the advanced maneuvers
and these (the author, PR #177 review). Turning it on brings both, and a game
may then take just one.

- **`GameMode` stays BASIC/ADVANCED and the opt-out is two bools on the game
  record**, `advanced_maneuvers` and `species_abilities`, both defaulting
  True. They are opt-*outs*, not opt-ins: a game is basic or advanced (one
  switch, which is what a coach picks and what every existing save carries)
  and these two say what an advanced game left behind. Defaulting True is
  what makes every advanced game played before them read as both modules on,
  which is what those games were. A third `GameMode` value would have made
  "advanced" three things a coach has to tell apart.
- **A coach picks them in setup, as two toggles beside the mode buttons**,
  and both screens build them out of one table: `ADVANCED_MODULES` in
  `cogs/d12ball_helpers.py`, keyed by the word the button carries in its
  custom_id and naming the field it toggles. `toggle_advanced_module` is the
  click, shared by `GameConfigurationView.select_module` (the settings block
  on `CoinFlipView`) and the lobby's `change_setting`, so the two screens
  cannot come to offer different modules or disagree about which may be
  turned off.
  - **They are offered only while Advanced is on**, on the mode row itself --
    four buttons of Discord's five -- because they are what narrows the
    switch beside them. A basic game plays neither, and two dead buttons say
    nothing a coach can act on.
  - **The last module still on is refused, not silently ignored.** Both off
    is a basic game reached the long way round, and the mode buttons are
    right there. That refusal is the reason the two bools need no third
    state.
  - **Picking Basic leaves them as they are.** They mean nothing in a basic
    game (`advanced_maneuvers_apply` folds the mode in), so undoing them
    would only cost a coach their pick to a mis-click on the mode.
  - **A rematch carries them**, alongside the mode and board size, which is
    why `open_new_game` takes them at all -- `/d12ball create_game` settles
    everything else in setup and settles these there too.
- **Nothing may read either bool to decide a rule.**
  `RulesEngine.advanced_maneuvers_apply` and `species_abilities_apply` are
  the two answers, and each folds `mode` in so a caller cannot check the
  opt-out and forget the mode. `maneuver_tiers` reads the first -- it used to
  ask `game.mode` directly, which would have dealt six cards to a game that
  opted the maneuvers out, and `D12Ball.reference_tier` was the same reading
  one step removed: the hexagon a coach is posted is the six-card one only
  when the game is actually playing those six.
- **What a coach reads about the mode is read off the modules too.**
  `describe_game_mode` words both the setup and the lobby message -- "six
  maneuvers a side, species abilities", or one of them alone -- where the
  lobby used to say "six maneuvers a side" for every advanced game. A screen
  that advertises a module the game left behind is the same bug as a rule
  site that plays it.
- **`RulesEngine.has_species_ability` is the one question every ability site
  asks**: this card, this game, this species. It folds the module gate and
  the species check together for the reason `settled_maneuver_winner` is one
  predicate over three call sites -- the two are always asked in the same
  breath, and a site that checks the species and forgets the module plays a
  basic game by advanced rules. **Don't read `PlayerDefinition.species` to
  decide a rule anywhere else.**
  - **A player fielded on both sides carries it on both cards**, and that is
    free rather than handled: `species_of` goes through
    `PlayerCatalog.player_by_id`, which resolves a duplicate card id to the
    same person. See "One player, both sides" in [teams-and-players.md](teams-and-players.md).
  - It is tolerant of an id the catalog does not know (`species_of` answers
    `""`), because every caller is a predicate asking whether an ability
    fires -- the same tolerance `turn_handler_candidates` shows a stale
    carrier.

### Volatile, and the roll funnel

**`RulesEngine.ignite` is the funnel every d12 in the game comes through**,
and it is what stops the next ability that reads a die being written at six
call sites. Volatile is the only one that reads one today.

- **It takes the face rather than rolling it.** Each site already knows how
  to get its own dice -- `random.randint(1, 12)`, or the tutorial's scripted
  faces through `tutorial_dice` -- and taking that over would have meant
  threading the script through the engine for nothing. What the funnel owns
  is the *reading*, which is the part that was going to be duplicated.
- **An ignite is reported as a modifier, not as a new total.**
  `IgnitedRoll.modifier` and `.detail` are added to what each site was
  already building, exactly like the Midfielder's +3 or the ball speed
  modifier -- which is why all six sites took this without changing how they
  roll, display or total anything, and why the dice image explains itself
  with no new drawing code.
- **The six sites, and what each passes**: the maneuver skill test and the
  loose-ball/High-Pass contest pass each side's own player (so two Fire
  Demons each check their own); the score attempt passes **only the
  shooter** -- its second die is the defensive wall's and belongs to no card,
  which is why `ignite` takes an optional player and answers "no ignite" for
  None; the own goal passes **the die that is kept**, since it is rolled at
  an advantage and the rules name "the die kept"; the injury check and the
  shootout test pass their one roller.
- **Injury does not withhold it.** What an injured contestant loses is their
  own skill modifier and only that; an ignite is the die, not a modifier the
  player brings -- the same reading that leaves the ball speed modifier
  alone.
- **A backfire on an injury check injures the Fire Demon**, which falls out
  of applying the modifier to the check rather than being special-cased. The
  die image draws the natural face, so `run_injury_test` says the ignite in
  words -- otherwise the number a coach reads and the verdict they are given
  would not add up.
- **Volatile's two numbers live in `d12ball/components.py`**, beside the
  other three species', rather than in the engine that reads them:
  `d12ball/render.py` cannot import the engine (the engine imports it) and
  the ignition die's own explainer reads them too. `engine.py` re-exports
  both, so nothing that already asked it moved.

### The ignition die

**The second die is a die a coach watches, not a number in a total.**
`render_volatile_die` draws it and `D12Ball.post_volatile_ignition` posts
it -- one message per ignited roll, between the roll's own dice image and
the result.

- **It was a line in the totals column and nothing else**, which is what
  the modifier shape above bought and where it fell short: the face on the
  image and the total under it disagreed by up to 12, with one grey line of
  arithmetic to explain a die nobody saw thrown. Every other modifier in
  the game is checkable against the board or a card; this one is a roll.
- **`IgnitedRoll.detail` and `.explain` are one ignite said twice, and they
  sit together.** `detail` is the arithmetic in the totals column, which
  has to add up; `explain` is the sentence over the second die's own image,
  which has to say why there is a second die at all. Written apart they
  come to disagree about which way a roll went.
- **One helper for all seven call sites**, which is `ignite` read from the
  other end: the funnel owns what a die means and this owns what a coach is
  shown of it. Each site hands over the pairs it has -- a contest both
  sides, a score attempt only the shooter -- and a roll that did not ignite
  posts nothing, so no caller branches on it. That is also what lets
  `run_mind_pull` pass its Telekinetic's roll through: it cannot ignite
  today, and the day a card carries both abilities this is not the one roll
  in the game that swallows the die.
- **Between the dice and the result, at every site including a tie.** The
  ignite happened to the die a coach has just watched and before the
  verdict they are about to read; a message's attachments render below its
  content, so nothing else reads as what happened. See `SkillTestView.roll`
  for the same reasoning about a result.
- **The sentence is above its own die**, unlike every result in the game.
  It is not a verdict the picture is about to reveal, it is the caption
  explaining why a second die exists -- and the alternative is two messages
  an ignite.
- **The image is the Mind Pull die's layout with the Fire Demons' flame**
  (die, portrait, verdict, with a halo and a ring), for the reason that one
  follows the injury test's: a coach should not have to learn a layout per
  ability. The face keeps the *roller's team* colour, since a Fire Demon
  plays for any of the eight teams. What it adds is an explainer line under
  the title -- "a natural 6 or 7 ignites — the second d12 adds on 5-12,
  subtracts on 1-4", read off the constants like the Mind Pull die's target
  band -- and it is what sizes the canvas, being both the widest thing on
  the image and the half a coach meeting their first ignite needs.
- **It borrows that layout's shape and not its proportions** (the author,
  2026-09-16), because the explainer is what makes this image wider than
  the row under it and the other two have no such line. Three things
  follow, and all three are the same instruction -- spend the space rather
  than leave it black. The **portrait is 168** and not the 96 the other two
  draw, so it is the tallest thing in the row. The **flame fills that row
  and does not grow it** -- a halo up to the portrait's height costs
  nothing, and past it the flame is what makes the canvas taller than its
  own content, which is what the Mind Pull's 2.9 did here. It cannot be
  that number either way, since the two shapes are not alike: a spiral is
  mostly the gaps between its arms and needs room to read as one, where a
  flame is solid. Both ends of that are real -- 1.85 was tried and reads as
  a smudge behind the die. And the slack the
  explainer creates is spread **between** the three columns instead of
  around them, so the row reads as the sentence's own rather than a narrow
  thing centred under it.
- **What ignites is the ball, not the die** (the author, 2026-09-16), in
  `IgnitedRoll.explain` and nowhere else. The rules state the trigger as a
  property of the die because that is what a player has to *check*; what a
  coach watches is a Fire Demon setting the ball alight. The image keeps
  the mechanic -- "ignited on 6" under the face -- since that band is what
  ties this die to the roll it came out of.
- **A roll site may not swallow its die**, which is a claim about all of
  them and so cannot be made by a test that drives one:
  `IgnitionIsShownEverywhereTests` fails any module that calls `ignite`
  without posting one. A new roll site is written by copying an old one and
  the arithmetic works perfectly well with the image left out.

**The tier rider is one flag, not a side.** The rules name two cases -- a
surge on the winning side raises that side's maneuver, a backfire on the
losing side raises "the opponent's" -- and the opponent of the losing side
*is* the winning side, so both raise the winner's card.
`MatchState.volatile_tier_upgrade` is that, and
`RulesEngine.volatile_raises_tier` is the reading.

- **It is gated where it is set, not where it is read.**
  `volatile_raises_tier` asks `advanced_maneuvers_apply` (a game with the
  abilities but not the maneuvers has no tier to change), so
  `resolving_maneuver` needs no `game` and stays a question about the match
  alone.
- **It is persisted**, because the injury tests run between the roll that
  sets it and the effect that reads it: a restart in that window has to
  resolve the maneuver at the tier the dice decided, and nothing else on the
  match records it. `reset_maneuver` clears it with the rest of the turn.
- **It beats the tie downgrade**, which is the case the rules call out
  ("even where the cards tied and the basic card would otherwise resolve"),
  and it only ever raises -- a card already resolving at advanced gains
  nothing, which falls out of an advanced card's counterpart being itself.

**The rider has a second half: the losing side's own ignite decides their
advanced cost** (the author, 2026-09-07). `MatchState.volatile_loser_cost`
is that, and `RulesEngine.volatile_loser_cost` is the reading.

- **It is a nullable bool because there are three states.** `False` is a
  **surge that lost** -- they pay no cost even where the cards would have
  charged one. `True` is a **backfire that lost** -- they pay theirs even
  where the cards alone would not, which makes a backfire the one thing in
  the game that puts a cost in force off the dice. `None` is every other
  roll, leaving `advanced_cost_applies` the whole answer it always was.
- **It is read off the loser's own die, not the matchup**, which is why it
  is a separate field rather than derivable from `volatile_tier_upgrade`.
  A surge that loses suppresses a cost *and* raises nothing; a backfire
  that loses charges one *and* raises the opponent's card. The two halves
  agree only by coincidence.
- **`advanced_cost` asks it before `advanced_cost_applies`**, because that
  is precisely what it overrides -- in both directions. The card checks
  stay above both: the override decides *whether* an advanced cost applies,
  not whether there is one to apply, and a basic losing card has none.
- **The first build had the tier half and not this one.** It read "resolves
  that side's maneuver as its advanced version" as a sentence about the
  card that resolves and nothing else, and left `advanced_cost` asking only
  the cards.

### Lithium Powered

Three things sharing one ability, and they touch three different parts of the
codebase.

**The Drained line made the Exhausted threshold a question.** It used to be
"the player's defensive skill" and was read straight off the profile at each
site; a Cyborg's is a flat 7, so `RulesEngine.exhaustion_threshold` is now the
one answer and `retest_exhausted`, `apply_exhaustion`,
`describe_exhaustion_gain`, `recover_exhaustion` and `apply_substitution` all
ask it.

- **That is why so many methods grew a `game`.** The threshold depends on which
  modules the game is playing, and the modules are the *game record's* -- so
  the game had to reach every site that charges or removes a token. Seventeen
  call sites took it; almost all already had one in scope.
- **A copy of the modules on `MatchState` would have avoided that and was not
  worth it.** It is a second thing that can disagree with the game record,
  which is the failure this codebase keeps writing down (see the team colours,
  and the formations living in two places *checked against each other*).
- **`recover_exhaustion`'s parameter is `threshold`, not `defense_skill`.**
  Renamed rather than left: it is now sometimes a Cyborg's 7, and a parameter
  named for one of its two meanings is how the next reader gets it wrong.
- **`mark_exhausted_if_needed` marks on *greater than*, so "Drained at 7 or
  more" is a threshold of 6.** The arithmetic is done once, inside
  `exhaustion_threshold`, rather than at the sites -- `CYBORG_DRAINED_AT - 1`
  appears exactly once.
- **A Cyborg's tokens are called drain wherever a coach reads them**, which is
  `describe_exhaustion_gain` branching on the same predicate. The mechanic is
  identical and the word is the ability.

**A Cyborg who fails an injury check is Damaged, not Injured** (the author,
2026-09-19), the same extension one level down: *"the cyborgs use Drain rather
than exhausted [...] this is only in advanced mode when the spec ability is
turned on"* -- Drained already existed for Exhausted, and Damaged is the
missing other half for Injured, scoped the same way.

- **Cyborgs only, not a rename of Injured itself.** Every other species stays
  Exhausted/Injured; only a Cyborg with the ability active (`has_species_ability`,
  never `PlayerDefinition.species` read bare) reads Drained/Damaged. A global
  rename was considered and dropped -- Drained already means something
  narrower than "Exhausted" (the flat-7 threshold), so reusing it as a generic
  replacement would have made the Lithium Powered rules text self-contradictory.
- **One word, not a new mechanic.** Nothing about the injury check, the
  disadvantage or a substitution differs for a Damaged Cyborg; `match.injured`
  is untouched; `mark_injured`/`run_injury_test` ask no species question at
  all. Every site that already branched Exhausted/Drained on
  `has_species_ability` picked up the matching Injured/Damaged branch beside
  it -- `CoreMixin.injured_word_and_emoji` is the shared word+emoji answer for
  the cog's own message-building sites (mirroring the inline `drain = ...`
  branch `describe_exhaustion_gain` already used for Exhausted/Drained), and
  the handful of sites the cog doesn't reach -- `RulesEngine.shootout_button_label`,
  the contest dice images' `contestant_detail` -- ask `has_species_ability`
  directly, since a button label and a drawn die face carry no emoji to look
  up.
- **The board badge is a fourth argument, not a fourth boolean pair.**
  `render.py` already drew Exhausted/Injured as mutually exclusive badges in
  one card-stats slot; `draw_card`'s new `cyborg` flag only ever picks which
  *icon* fills that slot (Drained instead of Exhausted, Damaged instead of
  Injured), never whether one is drawn. The flag is threaded down from
  `render_match_image`/`render_coaching_image` as a `cyborg_ids` set the same
  way `species_icons` already threads a bool -- this module still never reads
  a player's species or the game's own bools to decide it (see the
  `species_icons` comment in `render.py`). `D12Ball.cyborg_condition_ids`
  answers it once, off `match.exhausted | match.injured` filtered through
  `has_species_ability`, for both render entry points to share.
- **New art, not a recolour.** `drained.png`/`damaged.png`
  (`scripts/render_condition_tokens.py`) are their own icons and application
  emoji (`DRAINED_EMOJI_NAME`/`DAMAGED_EMOJI_NAME`), teal/amber rather than the
  human pair's blue/red -- teal because it is the Cyborgs' own team colour,
  amber because a card carrying an amber Damaged badge and a red Injured
  badge in the same slot would otherwise be the same picture with new words
  stapled on. The teal is a shade brighter than a literal `TEAM_COLORS` teal:
  the author's read on a first draft using the exact team hex was that the
  lettering got lost in the sunburst behind it at the 26px the board actually
  draws it.

**Overdrive is the only thing in the game declared before a roll**, which is
what it cost to build. Every roll already sits behind a button any coach may
press, so the declaration is a **second button on that same prompt** rather
than a step of its own -- `SafeView.add_overdrive_buttons` builds it and
`SafeView.declare_overdrive` answers it, shared by all six roll prompts so a
seventh gets it in one line.

- **`MatchState.pending_overdrive` is a list, not a flag**, because a contest
  has two rollers and both may be Cyborgs -- and because the ids are what say
  whose total the +5 goes on. Membership is also the "once per roll" check.
- **It is persisted**, since declaring and rolling are two clicks with a save
  between them. That *is* declaring blind: a coach commits, and only then does
  somebody press Roll.
- **Every roll site clears it**, win, lose or tie. A tie that is re-rolled is a
  fresh roll and has to be Overdriven again, which the rules say outright and
  which falls out of consuming rather than being special-cased.
- **The declaration is the Cyborg's own coach's, unlike the roll.** Either
  coach may throw a die (see "Every roll is a coach's" in [maneuvers.md](maneuvers.md)); nobody else may spend
  another coach's tokens. The button carries the player in its custom_id for
  the reason the injury test's does -- an older prompt in the channel must not
  declare for somebody else's roll.
- **A Drained Cyborg may still Overdrive, and a Damaged one may not.** The
  first is the rules ("the drain stacks"); the second is not a rule about
  Overdrive at all -- a Damaged player carries no tokens and cannot gain any,
  so the price cannot be paid. Overdrive itself survives Damaged, being a flat
  bonus rather than the withheld skill modifier.

**Charge-up is about movement, not about being obliged to move** (the author,
2026-09-07): *"any player that moves is running back. Charging up only occurs
when a player does not move during run-back."* So it reads
`MatchState.run_back_moved`, which `run_back_player` fills in as it places
people, and **not** who was displaced.

- **That is why it is settled at the *end* of the run back**, in
  `finish_run_back`, rather than at `begin_run_back` where it was first
  built. Who actually moved is only known once the cascade has run, because
  **a stack is a real decision**: where several share a space and one must
  go, the one the coach sends loses their token and the one left keeps
  theirs. Holding a Cyborg still is a reason to send somebody else. The
  first build read "not moved by it" as "not *required* to move" and charged
  up both.
- **`run_back_player` is where the move is recorded**, not the three callers
  (the forced pass, the AI's placement, the coach's click), because it is
  the one method a run back moves anybody through -- the same reasoning as
  `add_exhaustion` owning attribution.
- **`pending_run_back_charge_up` is what keeps a new play out of it.** "A
  new-play reset is not a run back and triggers no Charge-up", and by the
  time the cascade finds nothing to do it can no longer tell a reset from a
  steal that scattered nobody -- `new_play` is not persisted. So
  `begin_run_back` arms the flag and `finish_run_back` spends it.
- **The line rides on `lead_in`** rather than being sent on its own: this is
  the tail of a cascade that has been batching its messages all the way
  down, and drain tokens do not earn a message. See "Discord's rate limits" in [rate-limits.md](rate-limits.md).
- **It goes through `recover_exhaustion` rather than decrementing.** A Cyborg
  on exactly 7 is Drained and dropping to 6 clears it, so the removal has to
  re-test.

### Slimey

**Slip in declines to narrow; it adds nobody.** An Ooze standing on the ball
for the side in possession is *already* an eligible ball handler -- what
`turn_handler_candidates` does is cut that list down to the carrier when a
resolution named one, and Slimey is the rule that keeps the Oozes in it.

- **`MatchState.turn_handler_candidates` takes the ids rather than asking.**
  `slip_in_ids` is a parameter for the reason `mark_exhausted_if_needed` takes
  a threshold: `MatchState` does not know what a species is, let alone which
  modules the game is playing. `RulesEngine.slip_in_candidates` computes them
  and `RulesEngine.turn_handler_candidates` is the wrapper every prompt, the
  click and the AI should ask.
- **"Of the same side" is `eligible_ball_handlers`' own answer**, which is what
  makes this safe on a space both sides are standing on -- that helper is
  already "everyone of the possessing team on the ball", so an opponent's Ooze
  is never in the list to be filtered out.
- **The carrier stays first**, so a coach reads who actually won the ball ahead
  of who may take it off them.
- **Dinky never slips in**, which is why `DinkyAI.choose_ball_handler` still
  asks the *match* rather than the engine. Weighing whether to hand the ball to
  a different player is a judgement call, and Dinky makes none -- the same call
  as never declining a challenge and never leaving a loose ball
  uncontested. In a solo game the option is the human's alone.
- **It is the one thing that can add a click to a turn.** Everywhere else a
  single candidate is selected without asking; a carrier with an Ooze beside
  them is two buttons where there was none.

**Merge is a sum, not a pick.** "Every such Ooze adds -- two of them add
twice", so `RulesEngine.merge_bonus` totals them and returns the detail lines
with it.

- **The skill is the side of the contest, not anything about the Ooze** --
  offensive on the attacking side, defensive on the defending one -- so the
  caller passes which it wants. That is also what lets the score attempt ask
  for the attack alone.
- **A score attempt gets the attack and nothing else**, because defenders on
  and beyond the ball are already counted by [what the defense
  adds](shooting.md#what-a-shot-is-up-against) and an Ooze among them must not be counted
  twice.
- **An injured Ooze adds nothing**, which is the ordinary rule about an injured
  player's skill modifier reaching here rather than an exception to it.
- **`rolling` is passed in** because who is contesting differs by site: two
  players in a skill test or a contest, one shooter in a score attempt. Their
  own skill is already in the total, so they are struck out rather than
  double-counted.

**Spreadable is fully passive -- every fielded Ooze, always, nothing to
declare.** "It counts as 0 [toward occupancy]" (the author, 2026-09-16) is not
something a coach turns on: `RulesEngine.spread_exempt_ids(game, match, side)`
is every one of that side's fielded Oozes whenever the game plays species
abilities, full stop. There is no second space, no per-card state, and no
Coaching Choice action for it -- the two earlier readings (an Ooze holding a
second declared space; a coach picking one from a "Spread" button) were both
tried and dropped in the same conversation that settled this one, which is
why there is no `spread_link` on `MatchState` and no `CoachingSpreadView`.

- **The exemption is an id set threaded through three readings, never a fact
  `MatchState` looks up itself.** Same split as `slip_in_candidates` and
  `merge_bonus`: this module does not know what a species is, so
  `open_spaces_in_zone`, `placement_spaces_in_zone` and `crowded_candidates`
  each take a `spread_exempt_ids` collection and simply subtract it from the
  team-membership set before intersecting it against a space's occupants --
  the same shape the moved player's own exclusion already had in
  `placement_spaces_in_zone`. `RulesEngine` supplies the set at every call
  site that has a `game` in scope; nothing calls the bare `MatchState` methods
  without it except `move_card` (the `/coach`/`/ref` manual override, which is
  deliberately left asking no rules question at all).
- **An exempt Ooze's own space reads as uncovered, even standing on it.**
  That is the whole of "counts as 0" -- there is no second space to also
  exempt, so this is the entire effect on `open_spaces_in_zone` and
  `placement_spaces_in_zone`.
- **The one place the exemption reaches past occupancy is `crowded_candidates`
  (run-back-out-of-a-stack).** It takes the same `spread_exempt_ids` and
  applies it to the same `team_players` set it already builds `zone_native`
  from: a stack of an exempt Ooze plus one zone-native teammate becomes a
  stack of one once the Ooze is disregarded, so `len(zone_native) < 2` and
  neither of them is ever offered. That is a deliberate, narrow reading (the
  author, confirmed in the same conversation) -- it is *only* the
  stack-breaking question. `run_back_displaced` (a player genuinely outside
  their own zone) is untouched, so a displaced Ooze still runs back like
  anyone else; the exemption never grows into a full run-back exemption the
  way the ball carrier's does.
- **`run_back_player` re-validates against the same set the prompt was built
  from.** It calls `placement_spaces_in_zone` again to check the click, so a
  caller that built its buttons with `spread_exempt_ids` and then calls
  `run_back_player` without them would have the re-check reject a space it
  had just legitimately offered -- see
  `RunBackChoiceView`/`run_back_ai_placement`/`apply_forced_run_backs` for the
  three places that thread the same set through both halves.
- **`positioning_swap_candidates` (Space Positioning's own trade-or-stack
  question) is deliberately untouched.** "Can stack with other players in
  assignments" reads as a plausible extension of the same primitive, but it
  was never reconfirmed once the design turned passive and it needs the
  furthest plumbing (`position_meeple` has no `game` today) for the least
  certain payoff -- worth revisiting if the author confirms it, not
  inferred.
- **Neither the formation's zone headcount nor kickoff-space coverage reads
  the exemption.** `current_formation` and `kickoff_space_occupied_by` are
  untouched: an exempt Ooze still counts once toward its zone's shape, and
  still has to be the one covering its side's kickoff space if it is the one
  standing there. Both are named explicitly in
  `docs/rules-log.md` as scope this landed without, not scope it ruled out.

### Mind Pull, and the arrival gate

**The only ability that interrupts a maneuver rather than modifying one.**
"Mind Pull resolves before the ball settles: a pull that lands pre-empts
whatever the movement would have led to -- a reception, a scoring
opportunity, a contest, a loose ball." So the ball has to be able to stop
mid-flight, which is a change to the spine of a turn and not an addition
beside one.

**`set_ball_space` records the path; three arrival points read it.** That
split is the whole design.

- **Recording is one place** because `set_ball_space` is the funnel every
  maneuver's ball movement comes through, `move_ball_relative` included --
  eleven effect sites, one method. `MatchState.ball_path_to` is the geometry:
  **excluding where the ball starts and including where it lands**, which is
  exactly "to or through" plus "the ball's own starting space does not count
  as moved to". A move that goes nowhere is an empty path, so a clamped pass
  offers nobody a pull.
- **Reading is three places**, and they are the functions that settle an
  arrival: `finish_maneuver_resolution` (the tail of every ordinary path,
  receptions included), `begin_loose_ball` (a Deflect, which calls it
  directly, and the High Pass contest, which comes through it), and
  `offer_scoring_attempt_choice` (a set-up). Between them they are every one
  of the four things the rules say a pull pre-empts.
- **`check_for_mind_pull` returns True when it took over**, exactly the shape
  `check_for_loose_ball` has, so a gate is one `if ...: return` at the top of
  each. It sits *above* the loose-ball check in
  `finish_maneuver_resolution`: whether the possessing side has anybody where
  the maneuver would have left the ball is a question that must not be asked
  while a pull could still move it somewhere else.
- **The path is spent whether or not anybody may pull**, before the early
  return. That is what stops one movement being offered twice when two gates
  run in a row -- `finish_maneuver_resolution` gates and then calls
  `check_for_loose_ball`, which reaches the second gate with the path already
  empty.

**A restart goes through `restart_ball_at`, not `set_ball_space`, and that
distinction is the caller's to make.** A dead ball being brought back into
play -- the kickoff after a goal, the ball put out again after a shot that
missed, a second-half kickoff -- is carried to where play starts again rather
than travelling over the spaces in between, so it crosses nobody (the author,
2026-09-07). `restart_ball_at` is `set_ball_space` with the path *cleared*,
which is both halves of that: no pull is offered on the restart, and the
restart cannot hand the last live movement on to the next arrival gate
either.

- **The readers cannot make this call, which is why the recorder no longer
  tries to let them.** The three arrival points spend the path as they pass
  it, and a restart's movement never reaches one: a goal's leads into
  `begin_run_back(new_play=True)`, whose reset, coaching window and empty run
  back all sit between the placement and `finish_maneuver_resolution` at the
  tail of the new play. Recording it there and reading selectively was the
  first build, and it offered the **scoring** side's Telekinetics a pull on
  the ball's way back to the middle of the field.
- **The halftime kickoff was accidentally safe**, because `end_period` calls
  `reset_maneuver` immediately after it and that clears the path. It uses
  `restart_ball_at` too, so the ordering there is no longer load-bearing.
- **Three placements are restarts and no others.** `restart_after_goal` (an
  ordinary goal and a conceded own goal), `restart_after_missed_score`, and
  the second-half kickoff in `end_period`. Every other dead-ball path in the
  game -- an out-of-bounds Setup Pass or High Pass, an avoided own goal --
  leaves the ball where it lies and moves it not at all, so there is nothing
  to record either way.

**The queue and the resume are `pending_injury_tests`' shape**, and for the
same reasons. `pending_mind_pull` is ordered because "each may try in the
order the ball reaches them; the first to succeed stops the ball there and
the rest get no roll"; `pending_mind_pull_resume` is the arrival that was
interrupted, because between the interrupt and the answer nothing else on the
match says what the ball was about to do. `continue_mind_pull` is the one
exit, so a coach who declines and a Telekinetic who was never asked leave by
the same door.

- **A pull that lands drops the resume rather than dispatching it** -- the
  arrival it pre-empted never happens. What it does not drop is that
  maneuver's clock cost, which rides into `begin_run_back` as
  `distance_moved`: "the maneuver that moved the ball still costs its space
  minute".
- **A pull is a steal**, so `apply_mind_pull` sets `ball_carrier_id` and the
  caller runs an ordinary turnover. Setting the carrier *is* the whole of
  arranging the exemption, since `begin_run_back` reads it off there -- see
  "The ball carrier" in [possession-and-turnovers.md](possession-and-turnovers.md).
- **The roll is shown, on a die of its own.** `render_mind_pull_die` is the
  image, and the offer message is edited into it exactly as an injury test's
  prompt becomes its die -- same three-column row (die, portrait, verdict), so
  a coach reads it without learning a second layout. **What makes it distinct
  is the aura, not a different shape**: the Telekinetics' own spiral drawn
  faint behind the face and a ring of the same purple around it. The face
  stays the *roller's team* colour, because a Telekinetic plays for any of the
  eight teams (see "One player, both sides" in [teams-and-players.md](teams-and-players.md)) and whose roll it is still has to
  be legible.
  - **The target band is on the image** -- "pulls on 1-2", off
    `MIND_PULL_SUCCESS_FACES` rather than written down -- for the reason the
    injury test draws the token count: a bare face means nothing until you
    know what it was chasing, and two in twelve is the whole of why a coach
    might let the ball go instead.
  - **The face drawn is the natural one**, so an ignite is said in words
    beside it, the same as `run_injury_test`.
- **A landed pull is announced as a turnover, at the skill test's own size.**
  `## {player} grabs the ball with their telekinetic powers!` and
  **Turnover!** under it -- the author's wording, 2026-09-07. It replaced
  "**They pull it in!**", which named the mechanic rather than what happened
  and buried a change of possession mid-paragraph. The heading rides in
  `begin_run_back`'s `lead_in`, so it lands *after* the die: a message's
  attachments render below its content, and a result written above the roll
  would be read before it.
- **Dinky never pulls**, so an AI side's Telekinetics are skipped rather than
  prompted. Paying a token for a one-in-six steal is a judgement call and
  Dinky makes none; it is also what keeps this flow free of an AI branch.
- **The token is paid whether or not the pull lands**, so the charge is above
  the roll rather than in the winning branch. It is **not a skill test and
  owes no injury check**, which the rules state outright -- nothing here goes
  through `begin_injury_tests`.
- **An injured Telekinetic is skipped, not refused**, in both
  `mind_pull_candidates` and `run_mind_pull`. They cannot pay the token, and
  `add_exhaustion` would refuse it silently and hand them a free roll.
- **`pending_mind_pull` is checked first in `pending_turn_view`**, ahead even
  of the injury tests, for a stronger version of their reason: a pull
  interrupts an arrival that has *not happened yet*, so the maneuver's state
  is still exactly as it was and every branch below would resolve the arrival
  this is holding back.

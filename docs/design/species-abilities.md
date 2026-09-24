# Species abilities in the bot

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Species abilities in the bot

The four abilities as the engine plays them. The rules are
[Species abilities](../living-rules.md#species-abilities) and are settled;
what is here is how they are wired, and the reasoning the rules do not carry.

**Advanced mode is one switch over two modules** -- the gambits
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
  `d12ball/game.py` (re-exported by `cogs/d12ball_helpers.py`), keyed by
  the word the button carries in its custom_id and naming the field it
  toggles. `D12BallGame.toggle_advanced_module` is the click, reached
  through `GameService.configure` by `GameConfigurationView.select_module`
  (the settings block on `CoinFlipView`) and the lobby's `change_setting`
  alike, so the two screens cannot come to offer different modules or
  disagree about which may be turned off.
  - **They are offered only while Advanced is on**, on the mode row itself --
    four buttons of Discord's five -- because they are what narrows the
    switch beside them. A basic game plays neither, and two dead buttons say
    nothing a coach can act on.
  - **The last module still on is refused, not silently ignored.** Both off
    is a basic game reached the long way round, and the mode buttons are
    right there. That refusal is the reason the two bools need no third
    state.
  - **Picking Basic leaves them as they are.** They mean nothing in a basic
    game (`gambits_apply` folds the mode in), so undoing them
    would only cost a coach their pick to a mis-click on the mode.
  - **A rematch carries them**, alongside the mode and board size, which is
    why `open_new_game` takes them at all -- `/d12ball create_game` settles
    everything else in setup and settles these there too.
- **Nothing may read either bool to decide a rule.**
  `RulesEngine.gambits_apply` and `species_abilities_apply` are
  the two answers, and each folds `mode` in so a caller cannot check the
  opt-out and forget the mode. `maneuver_tiers` reads the first -- it used to
  ask `game.mode` directly, which would have dealt the gambits to a game that
  opted the maneuvers out, and `D12Ball.reference_tier` was the same reading
  one step removed: the hexagon a coach is posted is the six-card one only
  when the game is actually playing those six.
- **What a coach reads about the mode is read off the modules too.**
  `describe_game_mode` words both the setup and the lobby message -- "a
  gambit on every rank, species abilities", or one of them alone -- where the
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
  to get its own dice -- `scripted_or_random`, the tutorial's scripted
  faces or the engine's `rng` -- and taking that over would have meant
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
- **A burn on an injury check injures the Fire Demon**, which falls out
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
blaze on the winning side raises that side's maneuver, a burn on the
losing side raises "the opponent's" -- and the opponent of the losing side
*is* the winning side, so both raise the winner's card.
`MatchState.volatile_tier_upgrade` is that, and
`RulesEngine.volatile_raises_tier` is the reading.

- **It is gated where it is set, not where it is read.**
  `volatile_raises_tier` asks `gambits_apply` (a game with the
  abilities but not the maneuvers has no tier to change), so
  `resolving_maneuver` needs no `game` and stays a question about the match
  alone.
- **It is persisted**, because the injury tests run between the roll that
  sets it and the effect that reads it: a restart in that window has to
  resolve the maneuver at the tier the dice decided, and nothing else on the
  match records it. `reset_maneuver` clears it with the rest of the turn.
- **It beats the tie downgrade**, which is the case the rules call out
  ("even where the cards tied and the basic card would otherwise resolve"),
  and it only ever raises -- a card already resolving as a gambit gains
  nothing, which falls out of a gambit's counterpart being itself.

**The rider has a second half: the losing side's own ignite decides their
gambit's cost** (the author, 2026-09-07). `MatchState.volatile_loser_cost`
is that, and `RulesEngine.volatile_loser_cost` is the reading.

- **It is a nullable bool because there are three states.** `False` is a
  **blaze that lost** -- they pay no cost even where the cards would have
  charged one. `True` is a **burn that lost** -- they pay theirs even
  where the cards alone would not, which makes a burn the one thing in
  the game that puts a cost in force off the dice. `None` is every other
  roll, leaving `gambit_cost_applies` the whole answer it always was.
- **It is read off the loser's own die, not the matchup**, which is why it
  is a separate field rather than derivable from `volatile_tier_upgrade`.
  A blaze that loses suppresses a cost *and* raises nothing; a burn
  that loses charges one *and* raises the opponent's card. The two halves
  agree only by coincidence.
- **`gambit_cost` asks it before `gambit_cost_applies`**, because that
  is precisely what it overrides -- in both directions. The card checks
  stay above both: the override decides *whether* an advanced cost applies,
  not whether there is one to apply, and a basic losing card has none.
- **The first build had the tier half and not this one.** It read "resolves
  that side's maneuver as the gambit on its rank" as a sentence about the
  card that resolves and nothing else, and left `gambit_cost` asking only
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
  `species_icons` comment in `render.py`). `RulesEngine.cyborg_condition_ids`
  answers it once, off `match.exhausted | match.injured` filtered through
  `has_species_ability`, for both render entry points to share. It was
  `D12Ball.cyborg_condition_ids` until step 10 of
  docs/architecture-migration.md, when the web app came to draw the same
  board: which players carry a Cyborg's own marks is a rule, and a rule on
  the cog is one a second frontend would have to copy.
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
- **The exhaustion-token counter got a Cyborg variant the same way,
  2026-09-19** -- `exhaust_cyborg.png`, in the same teal as Drained, so a
  Cyborg's own tally and their Drained badge read as one colour rather than
  an amber count sitting beside a teal condition. Unlike the four condition
  tokens above, this one is a **recolour, not a redraw**:
  `exhaust.png` (the amber triangle `draw_exhaustion_badge` draws on any
  card carrying tokens at all) predates `render_condition_tokens.py` and has
  no generator of its own, so `scripts/recolor_exhaust_token.py` reads the
  source's two flat colours (a warm near-black ink and the amber fill,
  sampled off the art rather than assumed) and re-expresses every pixel at
  the same position on the ink-to-teal line -- which carries every
  anti-aliased edge across exactly, rather than risking a redrawn triangle
  that doesn't quite match the one it sits beside on the card.
  `draw_card`'s `cyborg` flag now also picks this icon in
  `draw_exhaustion_badge`, the same "which icon, never whether one is
  drawn" rule as Drained/Damaged above. That meant widening what
  `cyborg_condition_ids` answers: it used to be "currently
  Exhausted or Injured", which left a Cyborg mid-count (tokens above zero
  but below `CYBORG_DRAINED_AT`) drawing the amber triangle, so it now
  unions in `match.exhaustion.keys()` too.
  - **And it became an application emoji too, 2026-09-23**, because the
    board was the only place it ever reached: `describe_exhaustion_gain`
    already said "gains 2 drain tokens" and then counted them out in the
    amber `{condition:exhaust}`, so the card showed a teal tally and the
    sentence beside it an amber one -- the same cost in two colours (the
    author, reading a run back out of a channel). The mark the model
    writes is **`{condition:drain}`**, a sixth member of
    `tokens.CONDITIONS` standing to `drained` exactly as `exhaust`
    stands to `exhausted`: the token, and the condition it leads to.
    The upload it is fetched by is named `exhaust_cyborg` after the art,
    the way every upload is -- **the one mark whose token spelling and
    emoji name differ**, which is why `CONDITION_EMOJI_NAMES` is a table
    rather than an identity, and a test in
    `tests/test_d12ball_coin_toss.py` pins both that pairing and the
    rule that every mark in `tokens.CONDITIONS` has an upload name and a
    fallback. The plain fallback is ⚡ rather than Exhausted's 😮‍💨 or
    Drained's 🪫: a drain token is charge spent, and a coach counting
    three of them has to be able to tell the tally from the condition it
    is heading for.
    **The three words moved onto the engine at the same time**, because
    the roster line needed all of them and a frontend may not decide
    which. `RulesEngine.token_word_and_mark`,
    `exhausted_word_and_mark` and `injured_word_and_mark` each answer a
    word and its token, all three off one `drain_wording` reading --
    one question rather than a `has_species_ability` call per site,
    since a player counting drain tokens is a player who becomes
    Drained, and a line taking one word from this reading and another
    from its own would word one player two ways.
    `d12ball.flow.turn.injured_word_and_emoji` is now a forwarder,
    kept because a dozen steps call it by that name;
    `describe_exhaustion_gain` and the two substitution sentences in
    `d12ball/flow/windows.py` lost their inline branches to it, which
    is the duplication the earlier note beside
    `CoreMixin.injured_word_and_emoji` predicted.
    `format_team_roster_entry` reads all three through the cog's
    forwarders (`token_word_and_emoji`, `exhausted_word_and_emoji`,
    `injured_word_and_emoji`) and so takes the `game` now, as does
    `build_team_roster_section` above it -- both callers had one in
    hand. That line was the last place calling a Cyborg exhausted and
    drawing them an amber triangle, which is what
    `/d12ball team_roster` exists to answer.
- **`exhaust.png`'s content got its own redraw, same day.** The pill and its
  small "ZZZ" (black ink on an amber pill, both at the same tiny scale that
  read as an unbroken bar at 26px) are gone; `scripts/redraw_exhaust_zs.py`
  erases the pill back to the face's own ink and draws three bold "Z"s
  straight onto the face in the ring's own amber, stepped down in size
  top-right to bottom-left, the largest tucked into the triangle's own
  corner. **The triangle itself is still not regenerated** -- the edge,
  ring and face are the same pixels they always were, only the content
  inside the ring changed, for the same "don't risk a shape that doesn't
  match" reason `recolor_exhaust_token.py` never redraws it either. That
  leaves `exhaust_cyborg.png` still exactly the **recolour, not a redraw**
  described above: it is derived from whatever `exhaust.png` currently
  holds, so `recolor_exhaust_token.py --in-place` has to run again after
  any change to the amber art, including this one, or the two drift apart.
  - **The first draft placed each glyph by eye and let them overlap** into
    one interlocking zigzag, with the biggest Z well short of the corner.
    The second draft placed every glyph by search instead, scoring the
    biggest Z's spot by how far a plain "maximise x, minimise y" reading
    pushed it into the corner -- and still fell short, since that score
    can't find a position further in along a path other than straight up
    and right. **The author moved it the rest of the way by hand**
    (2026-09-19), and the other two Zs are built out from that spot rather
    than the search's: the smallest as close as it can get to the first
    draft's own position, the middle roughly between its neighbours, both
    while keeping a 10px gap from every other glyph's actual ink, not just
    its bounding box, so a glyph's own diagonal stroke still can't touch
    its neighbour.

**A Cyborg's injury check is a damage test, and "drain" is a verb** (the
author, 2026-09-23). The third and fourth words of the same set: a Drained
Cyborg takes a damage test and, failing it, is Damaged; a Cyborg *drains 2*
where anybody else gains 2 exhaustion tokens.

- **`RulesEngine.injury_test_name` is the one answer to what the check is
  called**, beside `token_word_and_mark` and the other `drain_wording`
  readers. The narration, the pending prompt, the button and the title drawn
  on the die (`render_injury_test_die`'s `title`, passed by the cog, since
  `render.py` decides no wording) all ask it. The code keeps its own name --
  `PromptKind.INJURY_TEST`, `pending_injury_tests`, the custom_id -- because
  those are saved or shared with the web app and name the mechanic, not what
  a coach reads.
- **The verb is only for gaining.** `describe_exhaustion_gain`, Overdrive's
  line and button, and the Dribble Burst prompt say *drain N*; a line that
  *removes* drain (Charge-up, halftime) or counts it (the check's target)
  still says drain tokens, because "drains 1" there would read as the
  opposite of what happened.

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
  (the forced pass, and a coach's or the AI's answer to the prompt), because it is
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
  `MatchState` looks up itself.** Same split as `smooth_candidates` and
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

**Where the code is.** Since **Phase 4** of the model/Discord split the
gate and every arrival it guards are flow steps in
[`d12ball/flow/arrivals.py`](../../d12ball/flow/arrivals.py) --
`check_for_ball_arrival`, `check_for_smooth`, `check_for_mind_pull`,
`continue_smooth`, `continue_mind_pull`, `dispatch_arrival_resume`,
`check_for_loose_ball`, and the five arrival points themselves. They moved
**together**, because the ordering between them is what this section is
about and half an ordering on each side of the seam is worse than none.
A gate returns `Optional[StepResult]` -- a result when it took over, None
when it did not -- so every caller stays the one `if ...: return` it has
always been. `run_smooth` and `run_mind_pull` are still the cog's: they
are dice and a dice image.

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
- **Reading is five places, through one gate.** Each arrival point calls
  `check_for_ball_arrival`, which asks Smooth and then Mind Pull -- see
  "Smooth" below for why that order is load-bearing and why only the second
  of the two spends the path. The five are the functions that settle an
  arrival: `finish_maneuver_resolution` (the tail of every ordinary path,
  receptions included), `begin_loose_ball` (a Deflect, which calls it
  directly, and the High Pass contest, which comes through it),
  `offer_scoring_attempt_choice` (a set-up), `begin_run_back` (a
  turnover a maneuver settles for itself -- Steal, Intercept, a Defender's
  pressure steal, an own goal avoided -- and hands straight to run-back
  without passing through any of the other three), and
  `begin_own_goal_roll` (the shove that overshot into an own-goal risk). Between them they are every one of the four things
  the rules say a pull pre-empts, plus the two the first three don't reach
  on their own: a steal's own carry, and a shove that ends in an own-goal
  roll.
  - **The fourth was missing until 2026-09-20** (the author, from a bot
    transcript): Steal/Intercept, a Defender's pressure steal, and an own
    goal avoided all move the ball with `set_ball_space` and then call
    `begin_run_back` directly, so `last_ball_path` sat unread through the
    whole run-back cascade and was only finally checked from
    `finish_run_back`'s own tail call into `finish_maneuver_resolution` --
    by which point run-back had already repositioned players onto those
    spaces. `mind_pull_candidates` reads *current* board occupancy of the
    path, not who was standing there when the ball actually crossed, so a
    Telekinetic who merely ran back onto one of those spaces was wrongly
    offered a pull that belonged to whoever the ball had actually passed.
    Gating `begin_run_back` itself, before any run-back state is set up,
    is the one place every turnover-driven run-back funnels through
    regardless of which maneuver produced it -- patching each maneuver
    individually would have left the same trap for the next one that
    settles its own turnover this way. For every ordinary maneuver the
    gate has already run (and spent the path) by the time `begin_run_back`
    is reached, so this reading is a no-op there, the same as the existing
    "second gate reached with the path already spent" case.
  - **The fifth was missing until 2026-09-20 as well**, and for a reason
    the fourth did not cover: an overshot shove is neither a settling nor
    a turnover. `shove_pressured_handler` drives the ball back through
    `set_ball_space` like every other effect, so the shove has a path;
    `apply_pressure` then handed straight to `begin_own_goal_roll`
    without reading it. That put the pull in the wrong place **both**
    ways the roll can go. An own goal *avoided* eventually reaches
    `begin_run_back` with the path still intact, so the offer did come --
    after the roll, which is too late for "a pull that lands pre-empts
    whatever the movement would have led to", and after the handler had
    already paid the roll's exhaustion token. An own goal *conceded* never
    reaches it at all: `restart_after_goal` clears `last_ball_path` on the
    way to the kickoff, exactly as it should, and the pull was simply lost.
    Gating before `begin_own_goal_roll` is what makes the own-goal risk
    one of the things a pull can pre-empt rather than a hole beside them.
    - **Only a Double Team can reach the branch with a path at all.** The
      overshoot is read before anything moves, as `abs(target - origin) <
      push`, so a 1-space Pressure overshoots only from the space closest
      to the offense's own goal -- where the handler does not move, and
      `ball_path_to` answers empty for a move that goes nowhere. A Double
      Team pushing 2 from one space short of it shoves them a real space
      and clamps on the second. So the gate is a no-op for the ordinary
      Pressure and is asked there anyway, the way every other arrival asks
      it rather than deciding for itself that it has nothing to offer.
    - **It gates inside `begin_own_goal_roll`, not at the call site.**
      The Phase 3d lift made Pressure and Double Team a pure
      `pressure_step` that returns
      `FollowOn(FollowOnStep.BEGIN_OWN_GOAL_ROLL)`, and a model step
      cannot ask a gate -- so the arrival gates itself the way the other
      four do, and any later caller gets it for free. The gate was
      briefly at the call site, before the lift landed; there is nothing
      to regret in that, but the lift is what settled where it belongs.
    - **`pending_own_goal` is not set yet when the gate runs**, because
      `begin_own_goal_roll` is what sets it. That is what keeps a restart
      mid-offer unambiguous: `pending_prompt` reads `pending_mind_pull`
      before `pending_own_goal`, and here there is no second flag for it to
      read. A pull that lands leaves no own-goal state behind to clean up;
      one that is declined reaches the roll through the `"own_goal"` resume
      kind, which sets the flag then.
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

**The path says where the ball went; `last_ball_movers` says who went with
it, and a candidate has to fail the second test as well as pass the first.**
"They move with the ball, while Mind Pull only works when the ball moves
after" (the author, 2026-09-20). A player the resolution carried never had the
ball move *to or through* their space, because they and it arrived together --
so reading occupancy alone was wrong in a way the path could not see.

- **It was a live bug on every Pressure and Double Team.**
  `shove_pressured_handler` places the challenger on the handler's *new*
  space, which is exactly what the card says ("the challenger moves 1 space
  forward onto the same space"), and `mind_pull_candidates` read current
  occupancy -- so a Telekinetic who challenged a Pressure was offered a pull
  on the ball they had just shoved, every time. It is the same shape as the
  bug the fourth gate fixed, except that here the step that moves them is
  part of the maneuver rather than the run-back afterwards, which is why the
  fourth gate's answer (gate earlier) could not reach it.
- **Smooth made it worse before it made it visible.** The shoved handler is
  on the *possessing* side and ends up standing on the ball, so the moment
  Smooth existed they would have been offered a Smooth on a ball they were
  already holding -- as would the handler of every dribble. One exclusion
  answers all of it.
- **Recorded at the two ways a player moves during play**, `move_meeple` and
  `move_player_relative`, both of which call `MatchState.note_mover`. The
  deal, a substitution and the run-back reset reach
  `BoardState.place_meeple` directly and are deliberately *not* recorded:
  none of them happens while a movement is waiting on a gate, and noting
  them would disqualify players for having been dealt onto a space.
- **A move that goes nowhere is not a move**, the same reading `ball_path_to`
  makes of a ball that does not travel. A 1-space Pressure against the goal
  clamps to nothing, and that handler is offered whatever standing still
  would have offered them.
- **Spent with the path, not with the turn.** The disqualification belongs to
  the movement that caused it, so a second movement in the same turn finds
  everyone eligible again -- which is why the gate clears both together and
  `reset_maneuver` clears both as well.

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
- **Dinky never pulls.** An AI side's Telekinetics are asked like a coach's
  and Dinky answers `decline` (`DinkyAI._let_it_pass`, through the service --
  step 7 of docs/architecture-migration.md); until then the queue skipped
  them. Paying a token for a one-in-six steal is a judgement call and Dinky
  makes none.
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

### Smooth

**Smooth is Mind Pull with the price taken off, and it lives on the same
gate.** "When your team has possession and the ball moves to or through your
space, you may take it over instead" (the sheet's `spec_abilities` tab,
2026-09-20). Free, no roll, cannot fail. It replaced **Slip in**, which had
moved to the Telekinetics from the Oozes only days earlier -- see both
2026-09-20 entries in [rules-log.md](../rules-log.md). **Since 2026-09-24 it
reads only the space the ball arrives at**, not the ones it passes through --
see "Only where the ball arrives" below.

**The replacement changed the shape, not just the name, and that is the whole
of this section.** Slip in asked *after* the fact: a resolution had already
left the ball with somebody, and Slip in widened `turn_handler_candidates`
so a Telekinetic standing there could take the turn instead. Smooth asks of
the ball's **path**, in Mind Pull's own words, and answers by stopping the
ball. Three consequences, and each one deleted code rather than adding it:

- **`slip_in_ids` is gone from `MatchState.turn_handler_candidates` and
  `select_ball_handler`.** A carrier is now always the whole list, because by
  the time the turn is handed out the arrival gate has already settled who
  holds the ball. Both production callers dropped their second argument.
- **`build_turn_prompt`'s slip-in line is gone**, and could not have fired
  anyway: it keyed on `carrier_id in candidates and len(candidates) > 1`,
  which the paragraph above makes unreachable. The prompt it used to
  replace -- "Choose which player in the ball's space will take an action" --
  is once again the only one, because the case it distinguished now happens
  a step earlier, in a message of its own.
- **The three cases the rules used to list for Slip in** (a dribble onto a
  teammate, a handler shoved back onto one, a Setup Pass received into a
  group) stopped needing a list. They are three movements that end on a
  Telekinetic, and the path sees all three the same way.

**Two queues, not one, and they can never both be owed to the same player.**
A pull needs the ball to be the opponents'; a Smooth needs it to be yours.
`smooth_candidates` reads `match.ball.possession` exactly where
`mind_pull_candidates` reads `defending_side()`, and that single difference is
what makes the two lists disjoint on any one movement. They stay separate
queues because the offer a coach is shown is a different offer -- one button
that spends a token on a 1-in-6, or one that simply takes the ball.

- **Injured players are in Smooth's list and out of the pull's.** Not an
  inconsistency: the pull excludes them because it costs a token an injured
  player cannot gain, so `add_exhaustion` would silently hand them a free
  roll. Smooth costs nothing, so the reasoning does not reach it, and an
  injured player is still playing.
- **`ball_carrier_id` is out of Smooth's list, and the pull needs no such
  clause.** The author, on a Low Pass aimed at a Telekinetic that then
  offered its own receiver a Smooth (2026-09-20): *"Dravox was already the
  recipient of the ball so it doesn't make sense"*. Taking it over means
  taking it off somebody, and a receiver, a thief and the shooter a set-up
  hands it to each end the movement holding it either way -- so the offer
  changes nothing and reads as a mechanic firing for its own sake. It is the
  **same sentence as `last_ball_movers`, read at the other end**: that one
  disqualifies a player the ball arrived *with*, this one the player the ball
  is arriving *for*, and between them a Telekinetic can no longer be offered
  a ball that was already theirs. The pull is exempt for a structural reason
  rather than by oversight -- a carrier is on the side in possession by
  definition, and the pull is only ever offered to the side that is not.
  - **It needed no new state**, which is why it is one `continue`: every
    effect that completes a delivery sets the carrier *before* the arrival
    gate is asked (`send_low_pass`, the Setup Pass, the two High Pass set-up
    branches, the steal and the intercept), and `select_ball_handler` clears
    it at the top of the turn, so nothing stale reaches the gate.
  - **What it does not take away is the whole point of the ability**: a
    Telekinetic standing on the landing space beside the player the pass was
    aimed at. That is Slip in's own case, and since 2026-09-24 it is the
    only one (below).

**Only where the ball arrives (the author, 2026-09-24).** *"Smooth only
works when the ball gets to the space, not through. So the gate is
different from Mind Pull, it's just like the old ability Slip-In."* So
`smooth_candidates` walks `last_ball_path[-1:]` where
`mind_pull_candidates` walks the whole path. The last entry is always where
the ball lands -- `ball_path_to` excludes the start and includes the end,
and `set_ball_space` overwrites the path on every move, so a movement made
of two calls still ends on the space the ball is standing on -- and an
empty path (a clamped move, a restart) has no last entry and offers
nobody anything.

- **It stayed on the arrival gate rather than going back to
  `turn_handler_candidates`**, although the author named Slip in. What the
  ruling changed is *which spaces count*, and the rest of what Smooth
  became on 2026-09-20 -- the prompt, the keeper, the two exclusions, the
  pre-emption, the restart recovery through `pending_smooth` -- answers
  the same on the last space as on any other. Moving it back would have
  been a second change the ruling did not ask for.
- **The own-goal case is gone rather than guarded.** The only own-goal
  risk is a Pressure against a handler already on the last space, which
  moves the ball nowhere, so the path is empty and nobody is asked.
- **Smooth-then-pull still holds on one movement**, and now the two read
  different spaces of it: a ball that crosses an opposing Telekinetic and
  lands on a friendly one asks the Smooth first. The 2026-09-20 ruling
  (*"smooth goes first"*) was made when both read the whole path; it was
  kept rather than reinterpreted, and whether the pull on an earlier space
  should now go first is a question for the author.

**`check_for_ball_arrival` is the single gate the five arrival points call**,
and it runs Smooth then Mind Pull. Two things about that order are
load-bearing:

- **Smooth does not spend `last_ball_path`; the pull does.** The pull is the
  last reader, so it keeps the unconditional `last_ball_path = []` it always
  had, and Smooth deliberately leaves the path alone -- a Smooth that nobody
  wanted must still leave the pull its movement. This is the one mechanical
  difference between the two gate functions and the reason they are not one
  function with a side argument.
- **Smooth first is a rules decision, not an ordering convenience**, because
  either one taken stops the ball and ends the movement. It is written down
  in three places that must agree -- `check_for_ball_arrival`,
  `continue_smooth`'s hand-off, and `pending_prompt`'s branch order, which is
  what a restart comes back to. The sheet does not say; the author
  settled it on 2026-09-20 (*"smooth goes first"*), and the cost that
  buys -- an opposing Telekinetic gets no roll at all whenever one of
  the possessing side's is also on the path -- is recorded with the
  ruling in [rules-log.md](../rules-log.md).

**A landed Smooth ends the maneuver; it does not run a turnover.** That is
the one place it parts company with a landed pull, and it falls straight out
of possession never having changed: no speed reset, no run back, no
`set_possession`. `apply_smooth` is `apply_mind_pull` minus the possession
line, and it clears `pending_mind_pull` along with the path -- the opposing
side's pulls were owed on a movement that no longer ends where it was going.

- **The arrival it pre-empted does not happen**, which is the pull's rule
  reaching Smooth unchanged. `run_smooth` has no `"own_goal"` branch to
  read: on 2026-09-20 that was because "the roll never happens" is just what
  pre-emption already means (the author), and since 2026-09-24 an own-goal
  shove moves the ball nowhere and so is never offered a Smooth at all.
- **`"run_back"` is the one kind it cannot pre-empt**, and the one branch
  `run_smooth` does carry. `begin_run_back` is not a question about where the
  ball settles -- it is the consequence of a turnover that already happened --
  so a Smooth there only changes who is standing on the ball when everyone
  runs back, and the carrier it sets is the one who stays.
- **The clock is not dropped**, the same as a pull: the maneuver that moved
  the ball still costs its space minute, carried out in `distance_moved`.

**The offer names the ability and the decline names a player**
(the author, 2026-09-22). Two wordings were wrong at once and they
were wrong for one reason -- the offer said what the mechanic *was*
without saying what the buttons *did*:

- **"can still take the ball over" never named Smooth.** It is
  `pending_prompt`'s branch rather than `continue_smooth`'s live
  offer, so it is what a coach comes back to after a restart or a
  `/d12ball resume` -- with none of the lines that opened the
  question. The live offer had carried the `{species:telekinetic}`
  banner and the bold **Smooth** since the ability landed; the
  restored one now carries both as well, and "still" is the only
  thing left telling the two apart. Both say "can take the ball to
  become the ball handler", which is the rule's own sentence ("the
  ball stops on their space and they become the carrier"), where
  "pull to become handler" read as Mind Pull's word for a thing that
  is not a pull.
- **"Leave it" said what declining did not do.** A Smooth is a choice
  between two players holding the ball, so the decline names the one
  it leaves it with: "Gearclaw [PM] keeps the ball".

**Who that is is a rule, so it is `RulesEngine.smooth_keeper` and it
rides on the prompt.** `SmoothOptions` is `DecisionOptions`' shape
with `keeper_id` added rather than that shape with a nullable field
on it -- a pull declined leaves the ball with the other side, which
the pull's own wording already says, and a coaching offer has no ball
in it. A view and a web page read the one field, which is the rule a
frontend's buttons are held to (CLAUDE.md, "State and saves").

The answer is `ball_carrier_id` -- every effect that completes a
delivery sets it before the gate is asked, and a dribble or a shove
sets it on the handler who carried the ball -- with **two arrivals
excepted, and both are about to clear it**: a loose ball comes down
free (`begin_loose_ball` clears the carrier the moment the gate lets
it through) and a new play sends the ball back to the kickoff space
with nobody on it, so the receiver a goal has just made a former
carrier is not keeping anything. Both are read off
`pending_smooth_resume`, the arrival the offer is holding back, which
is the only thing that knows what declining leads to. Where there is
no keeper the button has nothing to name and says "Leave it" -- the
one place the old wording was the right wording.

**Dinky never takes a Smooth.** An AI side's Telekinetics are asked the
same `SMOOTH` prompt a coach's are and Dinky answers `decline`
(`DinkyAI._let_it_pass`), the way it lets a Mind Pull go; until step 7 of
docs/architecture-migration.md `continue_smooth` skipped them instead.
Taking the ball over moves who plays the next turn, which is a judgement, and
Dinky makes none -- the same call as never ceding, never declining a challenge
and never pulling. In a solo game the ability is the human's alone.

**The take-over line names a space, not a sentence** (2026-09-20).
`run_smooth` and `run_mind_pull` each built their narration around
`ball_location_line`, which is a whole sentence -- so a coach read "takes the
ball over on The ball is at **V1** (Visitors Third)..". `ball_space_phrase` in
`cogs/d12ball_helpers.py` is the phrase half and `ball_location_line` is now a
sentence around it, so the two cannot come to name a space differently. It is
the split `travel_space_label` and `travel_space_phrase` already make, for the
same reason: a label and the prose around it are one wording in two shapes.

### Application emoji for the four abilities (2026-09-20)

Each species' own ink icon, uploaded to the application in colour under the
name its file already carries (`telekinetic_color`, `cyborg_color`,
`fire_demon_color`, `ooze_color`, from `d12ball/images/species/`), is looked
up the same way the team, role and condition emoji are:
`load_species_ability_emojis` in `cogs/d12ball_helpers.py` fetches it once in
`cog_load` off the one `fetch_application_emojis` call the others share, and
`get_species_ability_emoji(species_ability_emojis, species)` beside it
answers the lookup, falling back to that species' own team badge
(`TEAM_EMOJI_FALLBACKS`) until an upload exists. The banner itself names
the ability with a token, `{species:telekinetic}`, which `DiscordTokens`
draws through that lookup (step 9 of
[../architecture-migration.md](../architecture-migration.md)).

**It is an ability's banner that gets one, not a player.** A player is already
named with their team emoji and role badge (see
[naming-and-wording.md](naming-and-wording.md)); this is the mark at the head
of the line that says *which ability just fired* -- Mind Pull's offer and its
resolution, and Smooth's offer and its take-over, four lines in
`cogs/d12ball/effects.py` that each opened with a bare 🔮 literal before this
landed. 🔮 was `TEAM_EMOJI_FALLBACKS[Team.TELEKINETICS]` spelled out by hand,
so a coach with the uploads in place still read the crystal ball where every
other mention of a Telekinetic had become the spiral.

- **The dict lived on the engine, not the cog**, beside `team_emojis`,
  `role_emojis` and `condition_emojis`, from 2026-09-20 until step 9 --
  so the wording kept it when Mind Pull's and Smooth's narration lifted
  into `d12ball/flow/`, and so there was one dict rather than two that
  could disagree about which upload exists. Step 9 answered the same
  need the other way round: the flow writes `{species:telekinetic}` and
  knows no emoji, the dict is the cog's again, and one resolver draws
  every mark (see "Tokens" in
  [model-discord-split.md](model-discord-split.md)).
- **The fallback is per species, not one shared default**, so an application
  with three of the four uploaded draws the fourth as its own team badge
  rather than as one anonymous mark. Nothing fails when an upload is missing
  -- `fetch_application_emojis` already swallows its errors, because the
  emoji are decoration.
- **Volatile's own banners still spell 🔥 by hand**, at five sites across
  `d12ball/engine.py` and `cogs/d12ball_views/rolls.py`. Two of those are
  `IgniteResult.explain`, a dataclass method with no engine to read the dict
  off, so wiring them is a change to its signature and its callers rather
  than a lookup swapped for a literal -- kept apart from the Telekinetic
  swap deliberately. Overdrive's ⚡ is not the same case: it is a mark chosen
  for that ability, not a team badge standing in for a missing upload.

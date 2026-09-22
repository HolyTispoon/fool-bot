# The cards: maneuvers, players, species, and their icons

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## The maneuver cards

`d12ball/cards.py` draws the twelve maneuvers as cards. They exist because the
selection d6 they replaced made a coach hold the rules in their head: the die
said "3-4" and the coach had to remember that was Dribble Advance if they had
the ball and Steal Intercept if they did not, what it beat, and which role
changed it. The cards won outright on 2026-08-17 -- the die is off the rules
altogether now.

**One layout serves two things, on purpose.** `render_maneuver_card` is the
print-ready face for the tabletop game -- 2.5 x 3.5in at 300dpi, plus one
shared back -- and `render_maneuver_hands` puts every hand in play side by
side, which is what rides on the maneuver prompt. A coach who has played at the
table and a coach playing by Discord should be reading the same card, so neither
gets a design of its own.

```bash
python3 scripts/render_maneuver_cards.py --out cards/ --sheet  # print-sheet.png
python3 scripts/render_maneuver_cards.py --bleed   # 1/8in for a print shop
python3 scripts/render_maneuver_cards.py --hands   # every prompt image the bot sends
```

- **The hand replaced a paragraph per maneuver.** `build_maneuver_choice_text`
  listed each maneuver's effect and matchups next to the buttons; every word of
  it is on a card and in the same place on each one, so a coach now compares
  three cards instead of reading three sentences. It went with the change --
  don't reintroduce it alongside the image.
- **The hand is a side's cards, laid out a tier to a row**, and the "Maneuver
  Reference" button is beside them. A basic hand is one row of three; a
  hand holding gambits is two, the basic three above the gambit of each rank
  (the author), so every gambit sits under the basic one it shares a
  rank with -- which is the relation that decides the matchup, and the thing a
  hand wrapped at four and three split down the middle. `hand_card_rows` is the
  split and `lay_out_hand` takes each block's rows as given rather than
  chopping a flat run of cards up; `HAND_MAX_COLUMNS` stays as the ceiling, so
  a seventh card on a rank lands on a row of its own instead of shrinking every
  card on the image. The hexagon is what the shared back
  carries, and since the hand only carries a back in one case (below) the
  button is how most prompts reach it at all.
  `ManeuverActionPromptView.show_reference` posts it ephemerally, so the cost
  is a click and an upload only when somebody wants one. Both it and `/d12ball maneuver_reference`, which posts the same image to
  the channel, go through `build_maneuver_reference_file`.
  - **Ephemeral for the pick's reason, not its own.** The hexagon hides
    nothing -- answering in the channel would just tell the other side that
    this coach is still choosing.
  - **One button for a prompt holding both sides.** Its custom_id carries the
    game and no side, since the hexagon is the same picture for either coach.
- **Every hand is drawn once in `D12Ball.__init__`**, like the maneuver
  reference image and for the same two reasons: startup is the one place a
  render can block the loop harmlessly, and the alternative is drawing up to
  thirteen cards on every maneuver. Nothing about a card depends on the match,
  so they cannot go stale. `build_maneuver_hand_file` re-wraps the bytes per
  send, because uploading a `discord.File` consumes the stream inside it.
  - **Eight images, not four**, keyed by the hands on the prompt -- one
    `(side, tiers)` pair each: offense alone, defense alone, or both, against
    the basic three or all six. Which sides is
    `RulesEngine.maneuver_pick_sides` and which tiers is
    `RulesEngine.maneuver_tiers`, the same two questions the buttons under the
    image ask, and `maneuver_hand_combinations` is the enumeration the cog
    draws at startup. **The tiers are each side's own, which is what makes it
    eight**: since 2026-09-20 a gambit is held only by a coach whose team is
    behind, so a contested prompt can carry six cards for one side and three
    for the other. **The reference hexagon is keyed by tier the same way** (see
    below): the button posts the hexagon for the tiers the game is actually
    playing, so what a coach reads a matchup off cannot show cards their hand
    does not hold.
  - **Both hands on one image, not one per side.** Discord lays two attachments
    on a message out side by side, which would halve the width of both. Nothing
    is given away: the twelve cards and the defeat cycle are public information
    either coach may ask for at any time. Where the back is drawn it rides on
    the end of that hand's own row rather than starting one of its own, or it
    would be a second row holding one card.
  - **Each side's block is captioned -- "OFFENSE HAND" / "DEFENSE HAND", in that
    side's own colour** (`HAND_HEADINGS`, `OFFENSE_COLOR`/`DEFENSE_COLOR`). The
    two rows sitting one above the other read as one grid of cards otherwise,
    and a coach has to find *their* row before reading a label. `lay_out_hand`
    takes a `headings` list parallel to `blocks` and reserves a band above each
    captioned block's first row; a block with no heading reserves nothing. An
    a hand holding gambits is two rows under one caption, which is the other
    half of why
    the tier split lives in `hand_card_rows` rather than in the layout: a
    block is a side, however many rows it takes. The player's name and team are deliberately *not*
    on the image -- the mention line right above the prompt already names both
    coaches, and putting names on the cards would make the hand depend on the
    match, which is exactly what the `__init__`-time render avoids.
  - **The back is a lone basic hand's alone** (the author). Two things drop
    it. A basic *contested* prompt: both basic hands together *are* the whole
    game -- all six cards, each carrying its own beats/ties/loses row -- so the
    hexagon is the same six relations drawn a second time, for the width of a
    card, and dropping it leaves two clean rows of three instead of a ragged
    four and three. A prompt with a **gambit** on it anywhere, one hand or
    two: a back on the end of the basic row makes the image four columns wide
    to hold rows of three, so every card is drawn narrower for a card that is
    not part of the pairing the layout exists to show. Anywhere rather than in
    the hand the back would ride on, since the image is one canvas and its
    widest row sizes every card on it. What is left is the unchallenged
    maneuver and the solo basic game against Dinky -- half a cycle, and the one
    hand that cannot read the relations off the cards in front of it. The
    "Maneuver Reference" button is still there for anyone who wants the
    hexagon, which is why dropping it costs nothing.
  - **Four across is still the ceiling.** Discord scales an inline image to the
    message's width, so a row of seven arrives at about 75px a card against
    131px for a row of four. Nothing reaches `HAND_MAX_COLUMNS` today -- a tier
    is three cards, and only the back makes a fourth -- but it stays as the
    wrap, so a card added to a rank costs a row rather than every card's
    width.
- **The hand is drawn at a third of the print card's width.** Discord scales an
  inline image down whatever it is sent, so the extra pixels would only be
  payload -- and this send is once per maneuver, not once per coach. The
  abilities are small print at that size, which is what the full-image link on
  the message is for. That link is the webhook route, not the channel's edit
  bucket; see "Discord's rate limits" in [rate-limits.md](rate-limits.md).
- **The field goes under the hands**, drawn by `render_field_image` and sent by
  `D12Ball.post_field_image`. What a maneuver would do depends on where
  everybody is standing, and the persistent board has usually scrolled up the
  channel by the time a turn resolves.
  - **A message of its own, not a second attachment on the prompt.** Discord
    lays two images on one message out side by side, which would show a field
    the width of the whole board at half the width of a phone. It also keeps
    the prompt's link pointing at the cards -- `build_full_image_button` reads
    the *first* attachment, and "View full image" under a hand means the hand.
    Both sends are the webhook route, so neither competes with the board for
    the channel's edit bucket.
  - **It is rendered per maneuver, unlike the hand**, because it is the position
    and so is different every time. It carries a full-image link of its own for
    a stronger version of the hand's reason: a field is the whole width of the
    board in a strip a fifth as tall, which is the smallest thing the bot sends
    inline.
  - **Losing it must not lose the pick**, which is already up and clickable by
    then, so the send is wrapped the way `add_full_image_button`'s is.
  - **Every distance prompt carries one too**, as an attachment on the prompt
    rather than a message of its own -- the High Pass, the Setup Pass, both
    dribbles, the Low Pass and the run back. There is no second image on those
    messages for Discord to lay it out beside, and riding on the prompt is
    what lets the click take it away again. See
    [Choosing a distance, and the field under it](maneuver-prompt.md#choosing-a-distance-and-the-field-under-it).

- **Nothing on a face is written in the script.** The effect, the time cost and
  the beats/ties/loses row come from `maneuvers.json` through
  `load_maneuver_catalog` and `cards.matchup_rank_groups`; the abilities come
  from `players.json`. So a card cannot claim a rule the bot does not play, and
  an import is carried onto the cards by re-running this rather than by
  editing them.
  - **Each column names the rank it faces, not one maneuver.** Every column
    used to narrow to the card's own tier -- naming only the basic opponent on
    a basic card and only the gambit on its counterpart -- on the
    reasoning that rank decides and each rank carries one card per tier, so
    the second name was the same relation read twice. That reads backwards on
    a gambit: naming only its own tier's opponent makes the twelve
    maneuvers look like two cycles with no relation between them, which is
    exactly wrong when a tie on the cards resolves as the basic pair (see
    `tie_note` below). `matchup_rank_groups` names the rank instead --
    `O2`/`D1`/etc, coloured the opposing side's colour -- with **both** tiers'
    names under it, basic in ink and the gambit in its own colour. This is
    true of a basic card as well as of a gambit: what a basic card beats is
    still a rank, and that rank still has a gambit on it once advanced mode is
    in play.
  - **The row's own height is measured, not a fixed constant.** It used to be
    sized for a name long enough to wrap to two lines, which left every card
    whose names were shorter than that -- almost all of them -- a band of
    blank space under its own column. `matchup_content_height` counts the
    actual wrapped lines at the row's own name size (22, large enough that
    every maneuver name in the game still fits one line in a column this
    wide) and `render_maneuver_card` sizes the row to that, the same way it
    already sizes the abilities band to `laid_out_abilities`' measured
    height. The room either measurement frees goes to the effect band
    between them.
- **Which roles a card lists is mostly matched, not tabulated.** A role is on
  the card when its ability sentence names that maneuver, which is why the
  Fullback is on both High Pass and Deflect, carrying its whole sentence
  to each. The sentence is never cut down here -- see "Every ability is
  imported twice". A new ability that mentions a maneuver reaches its card
  without anything in the script being touched.
  - **The match is on whole words, not substrings.** It was a substring while
    every maneuver name was two words; the author renamed the basic D2 card to
    "Steal" on 2026-08-18, and "steal" is inside "Steals the ball when
    resolving Pressure" -- so the Defender's ability, which is Pressure's,
    silently appeared on Steal's card as well.
  - **No role ability names a gambit**, and that is the data being
    honest rather than a gap: the sheet's `Advanced` ability column is empty
    for all thirty-six. What a gambit carries instead is the one thing
    settled about how it resolves -- `tie_note`, which says a tie resolves it
    as the basic card on its rank with no gambit's effect, and that a skill
    test forced by injury still carries them. The counterpart it names is
    looked up by rank rather than written down.
  - **Two things the match cannot find are listed explicitly**, and both are
    the author's call rather than an oversight in the data. `EXTRA_ROLES` puts
    the **Striker** on High Pass: its +3 is for scoring off a set-up, one step
    removed from the maneuver, and three maneuvers can produce a set-up -- a
    High Pass is much the most common way, so it goes there and nowhere else.
    `EXTRA_NOTES` gives **Steal Intercept** the ball speed modifier its
    defender adds to the skill test, which decides the maneuver and which no
    role ability names, so its card would otherwise be the only blank one.
  - **Neither can live in `maneuvers.json`**: `scripts/import_d12ball_maneuvers.py`
    rewrites that file whole from the sheet, so a field added to it survives
    until the next import and no longer.
  - **`EXTRA_NOTES` is keyed by rank in practice**: the ball speed modifier is
    on Steal *and* Intercept, since the sheet lists it against both rows and it
    is what decides that rank's skill test either way.
- **The strip diagram is what a card can say that a die face cannot**, so it
  carries the geometry and the effect text carries the wording. A basic card is
  drawn on the standard seven-space board with the ball on the third space,
  which is the only position from which every basic maneuver fits: a High Pass
  of 4 lands on the last space and a Fullback's Deflect of 2 on the
  first. **A gambit is drawn on the nine-space board** with the ball on
  the fourth, because Clear drives the ball back 3 and Dribble Burst runs it 4
  forward -- 4 either way once a Fullback is near a Clear, which the seven-space
  strip has no room for. `STRIP_GEOMETRY` is the pair, per tier, and the nine-space board is a
  real board rather than a strip invented to fit.
  - **A dashed arc is a role's variant and a solid one is the ordinary move.**
    That is the only thing the dashes mean, which is why Low Pass's backward
    option is solid -- it is a choice any passer has, not an ability.
  - **A move's offset is along the offense's attacking direction, never
    "forward" or "back".** Those two words mean opposite things to the two
    sides and are what got Pressure and Steal Intercept drawn mirrored:
    a challenger's forward is toward the goal *they* attack, so Pressure moves
    the handler and the challenger onto the **same** space (which is how a
    Defender's won Pressure can steal at all); and a steal's back is toward the
    new possessor's own goal, which is the goal the offense was attacking, so
    the ball travels the way the offense was going. Both are verified against
    `move_player_relative` rather than reasoned about -- run it and read the
    flat indices before redrawing an arrow.
  - **Distances are labelled under the space they land on.** High Pass throws
    three arcs out of one space, and labelling those at their peaks stacked
    three captions on top of each other. A caption's font is sized to the gap
    to the next caption on its row, and ability variants get a second row.
- **The offense red and defense green are the maneuver reference image's**, so
  a coach reading a card and a coach reading the bot's hexagon are looking at
  the same two colours. **A gambit is a distinct shade, not a tint of
  the basic one** -- a darker red/green rather than a lighter or darker version
  of the same hue, since a basic and its gambit sit side by side
  in the reference image and back to back in the print run, and two cards that
  read as the same colour under different lighting is exactly what a coach
  must not confuse.
- **A card is white, and the colour is its edge and its header.** It used to
  be a saturated frame edge to edge on a cream face, with a near-black back --
  which is a page of ink per sheet of nine and the first thing a home printer
  runs out of. The face and the back are now `CARD_FACE` white, the maneuver's
  colour is a `EDGE_WIDTH` outline, and `BACK_COLOR` is white with a grey
  edge. **`FACE_COLOR` is still the boards' cream** and is deliberately not
  the cards': a board is one sheet a game, where cards are printed by the
  page.
- **The rounded outline is the cut line.** With the face and the sheet both
  white there is nothing else to say where a card ends, which is why the
  corner radius is drawn rather than implied and why `FRAME` is small enough
  that the outline is the card's own edge.
- **The back is keyed by tier -- `render_maneuver_card_back(catalog, bleed,
  tier=...)`.** `MANEUVER_TIER_GAMBIT` (the default) is one back for all
  twelve: a coach holding both sets must not show which side
  of the ball -- or which tier -- they are reading, and the offense there
  holds six. `MANEUVER_TIER_BASIC` draws six nodes with one name apiece
  instead: a basic-mode coach's hand is never anything but the three basic
  cards, so there is no tier to hide, and a name with no counterpart stacked
  under it reads larger in the same circle. `render_maneuver_hands` picks
  between them off its own `tiers` argument -- `MANEUVER_TIER_GAMBIT` in it
  or not -- so a hand and the back riding along with it can't disagree about
  which a coach is holding.
  - **A node is a rank**, and in advanced mode carries the two cards on it,
    the basic name over the gambit, split by a hairline. Rank alone decides who
    beats whom, so the hexagon is six nodes however many cards there are -- a
    second back was never available, and two cycles laid on top of each other
    is not a hexagon.
  - **The rank itself (O1, D2, ...) sits outside the circle, straight above
    or below the node** -- whichever side faces away from the ellipse's own
    centre -- in the node's own green/red. A node already carries two names;
    putting the rank inside it as well would be a fifth line in a circle
    sized for four. Outside it, the badge is what tells a coach the two
    tiers resolve by rank rather than as twelve maneuvers with no relation
    between them -- the same reason `render_maneuver_reference_image`
    carries one now (see below). **It used to sit out along the spoke from
    the ellipse's centre through the node instead**, which for the four
    off-axis nodes pushed it toward the card's corners -- close enough to
    the edge that the label's own width ran past it. Vertical is the
    direction every node has clear room in, since the hexagon already
    clears the header above and the caption below. The two caption lines at
    the foot of the card were pushed lower to clear the D1 badge below the
    bottom node, which still sits on this same vertical line.
  - **One size for all six nodes, and it is the tightest of them.** With one
    name to a node the tightest fit was a single long word and capping there
    shrank every other node for nothing; with both tiers on a node all six are
    four lines of much the same length, so the tightest is a real constraint.
    `CYCLE_LABEL_MARGIN` went from 8 to 24 for the same reason: the outer two
    of four lines sit where the circle curves away hardest, and at 8 the
    longest cleared the chord by under two pixels a side.
  - **The cycle draws both relations: a solid arrow to what a maneuver beats,
    a dashed line to what it ties with.** The ties were left to the caption
    ("same rank ties"), which made them the one thing on the card a coach had
    to work out rather than look up -- and a tie is the branch that costs a
    skill test and a token each. `tie_pairs` asks `ManeuverCatalog.resolve`
    rather than pairing equal ranks or joining opposite nodes: on six
    maneuvers the ties happen to be the hexagon's three diagonals, but that
    is a property of a six-node cycle, so a seventh would move the lines
    without moving what they mean.
- **`print_sheet` is an exact grid, because splitters cut by dividing.**
  Every cell is one card plus `SHEET_MARGIN_X` either side and
  `SHEET_MARGIN_Y` above and below, the sheet is `SHEET_COLUMNS` cells wide
  and whole rows deep, and a short last row is padded with spare backs. So
  dividing the image into quarters across gives a card dead centre in each
  piece. The old `contact_sheet` put a gutter between the cards *and* around
  the outside, which made a quarter of its width a card plus a quarter of a
  gutter -- every cut but the first came out off-centre.
  `D12BallManeuverTests` divides a rendered sheet and checks the pieces,
  since nothing else would notice.
  - **The two margins are different numbers because only one of them is
    under pressure.** Four poker cards across is 10in of card before any
    gutter at all, and a letter page turned landscape has about 10.5in of
    printable width -- so every horizontal pixel comes off what a home
    printer can fit, and at the old shared 24 the sheet was 10.64in and lost
    its outside columns at 100%. The cut is lined up on the card's own
    rounded outline rather than on the space around it, so the gutter can go
    narrow without costing anything. Height is under no such pressure: a
    thirteen-card sheet is 14.6in whatever the gutter, and is tiled or
    printed a page at a time either way.
    `test_a_print_sheet_fits_a_letter_page_across` is the guard -- nothing
    about the image says how wide it is meant to be, so the arithmetic is
    asserted rather than looked at.
- **The header's corner names the tier, not the die faces.** It printed
  "die 1-2" while the cards and the selection die had to coexist, then "BASIC
  MANEUVER" while there was only one set; it now reads the card's own tier,
  and is **the one thing on a card that tells the two sets apart** -- the back
  cannot, and must not.
- **A gambit's header also says, in words, which basic maneuver it is
  the advanced version of** (the author, 2026-09-20) -- a line under
  the title reading "ADVANCED VERSION OF PRESSURE", the same phrase the
  living rules' own gambit table uses. The matchup band already carried
  this once, by naming the rank both cards share (see "Each column
  names the rank it faces" above), but that asks a coach to notice two
  cards on the same rank badge and infer the relation; the header states
  it outright, for a coach who has just picked the card up and read no
  further. `draw_card_header` computes it from `catalog.counterpart`
  rather than a second table, so it cannot drift from the pairing the
  matchup band already reads off the same call. Drawn only on a
  gambit's face -- a basic card is not the advanced version of
  anything, and keeps the title centred alone at its old, larger size.
  `fitted_title` takes a lower `max_size` on a gambit's card for the
  same reason `matchup_content_height` is measured rather than fixed:
  the subtitle has to fit in the room the title leaves, not the other
  way round.
- **The effect text's size is searched, not set.** The effects run from Block
  Deflect's twenty words to Double Team's seventy against a band that is
  whatever the strip, the matchups and the abilities leave behind. A fixed size
  fitted the short cards and ran Double Team's paragraph straight over three
  bands at once, silently, because nothing measured what it had been given.
- `cards/` is generated output and is gitignored, like `board.png`.

## The player cards

`d12ball/player_cards.py` draws the roster as cards -- one a player, poker
size at 300dpi, the same as a maneuver's and out of the same `Pen`, palette
and `print_sheet`.

```bash
python3 scripts/render_player_cards.py --out cards/players --sheet
python3 scripts/render_player_cards.py --team orange --bleed
python3 scripts/render_player_cards.py --fronts-only   # the old one-sided run
```

- **It follows the bot's own card, not a design of its own.** Name, the two
  skills in `CARD_OFFENSE_COLOR` and `CARD_DEFENSE_COLOR`, the role, the
  portrait, inside the team's colour -- `build_player_card` in `render.py` is
  what a coach playing by Discord is looking at, and a coach at the table
  should be reading the same card. `ROLE_INITIALS` is shared for the same
  reason: the two letters in the badge are the two letters on the meeple's
  card in the channel.
- **What the print adds is the ability, and it is the full sentence.** The
  bot has the roster and the rules commands a click away; a card on a table is
  the whole of what its coach has, so the sentence goes under the portrait.
  Never `ability_short` -- see "Every ability is imported twice" --
  and `D12BallPlayerCardTests` greps the module to keep it that way.
- **The ability is measured before anything is drawn, and the portrait takes
  what is left.** Its length is the one thing on the card the layout does not
  choose, so the header and stats are pinned to the top, the ability band to
  the bottom, and the picture gets the middle. That is silent when it goes
  wrong -- a longer ability squeezes the portrait rather than overflowing --
  which is why the suite asserts a floor on the slot rather than only that a
  card renders.
- **A portrait prints at about 190dpi and that is deliberate.** The art is the
  bot's own, around 400px, and there is no larger source, so `PORTRAIT_MAX_SCALE`
  lets it up to 1.6x and no further: kept to its native size it would print
  smaller on a 2.5in card than the bot draws it on a phone.
- **A portrait in `d12ball/images/player_images/` is a cut-out, and new art has
  to be one.** These are JPEG paintings on a white studio background, and a
  cut-out that leaves any of it behind shows twice over: as a pale box behind
  the player on the dark images (`render_matchup`, and anywhere a portrait is
  posted on its own), and as a faint checkerboard on the printed card, because
  the background is not flat white but the JPEG's 8x8 blocks.
  `scripts/recut_player_portraits.py` is the cut, and the roster was put
  through it on 2026-08-12: background goes wherever it is light and
  *colourless*, which is what keeps the white jersey numbers and the white net
  a goalkeeper stands in -- paint carries a tint, a studio wall does not.
  Reaching the edge of the image is not the test, since most of what was left
  behind is walled in: between a tentacle and an arm, or in the holes of a net.
  - **It is a dry run unless told otherwise** -- `--in-place`, or `--out` to
    look first -- because what it overwrites is tracked art. It repeats itself
    until a pass clears nothing, so what comes out does not depend on how often
    it has been run; a pass drops pixels as it scans, which the pixels it has
    already passed never saw. `D12BallPortraitRecutTests` asserts every tracked
    portrait is already settled, which is the check a new painting fails.
  - **Look at a new portrait on black, not on white.** White is exactly the
    background that hides this. The printed card is white, which is why the
    fault survived the cards being looked at, and the dark matchup image is
    what showed how much of it was still there.
- **`Pen.paste` resizes straight to the supersampled canvas.** The
  supersampling is there because Pillow does not antialias the shapes the cards
  are drawn out of; a photograph put through it would be resampled twice for
  nothing.
- **A team sheet is three across**, not the maneuvers' four: a team is nine
  players, and nine poker cards in a 3x3 come out at about 8 x 11 inches --
  a page. Print it at 100% on A4, or borderless on letter, or the cards come
  off the printer undersized.
- **The species icon answers the role badge across the header band.** The two
  things about a player that are not their name are the job they do and what
  they are, and a card should give up both in one glance -- so the role's
  initials sit in a badge at the left of the band and the species icon at the
  right, with the name and the team stacked between them. The team used to
  have that right-hand spot; stacking it under the name is what paid for the
  icon, and it is also what lets the back say `ORANGE · ADVANCED` on the same
  line. Both the icon and the badge are drawn in `high_contrast_ink`, which is
  the whole reason the art is one flat silhouette -- see "The species icons".

- **The back is the player's gambit**, drawn by
  `render_player_card_back`. Not a shared back like a maneuver's: player cards
  are dealt face up and sit on the field and team boards all game, so there is
  nothing to hide -- the other side of the card is the same player in advanced
  mode.
  - **What makes it the advanced one is the species keyword**, in a pill on
    the right of the ability band's heading row -- literally beside the role
    ability. A species ability is only ever in play in an advanced game (see
    "Species abilities in the bot" in [species-abilities.md](species-abilities.md)), so the keyword is the one thing that has
    to be on this face and cannot be on the other. The pill is *filled* with
    the species' colour rather than the keyword being set in it, for the
    reason the header band is filled: Slime green on a white face cannot be
    read, and a filled pill plus `high_contrast_ink` answers all four species
    at once instead of three of them.
  - **The band starts at a fixed height on this face, where the front's
    floats** (`ADVANCED_BAND_TOP`). The badge rides the band's heading row and
    it has to be in the same place on every card in the set -- a marker a
    coach finds by looking at one spot cannot be a marker that moves with how
    long the player's role ability happens to run (the author, 2026-09-07).
    That gives up the thing the front's design is built on: on the front the
    portrait takes whatever the ability leaves, so a short ability buys a
    bigger picture, and here it cannot, because the picture's bottom edge *is*
    the badge's position. Every back gets the same portrait slot and the same
    band, and a card whose text does not fill the band leaves white under it.
    `test_the_advanced_badge_sits_in_one_place_on_every_card` is the guard,
    and the way it breaks is somebody laying the band out from the bottom edge
    up again, the way the front still does.
  - **The species' short form goes under it where the band has room, and the
    question is asked of the species rather than of the card.** How much of
    the band a card has left depends on how long its *role* ability runs, so
    asked per card the answer differs between a Fire Demon fullback and a Fire
    Demon striker -- and a set where two cards carrying the same species line
    disagree about whether it is on there reads as a misprint, not as a layout
    that scaled. `species_short_fits` walks the species and lets the longest
    role ability decide for all of them. **This is the one place a printed
    card carries an abbreviation**, and it is not the role's --
    `ability_short` in `species.json` exists for exactly "anywhere the
    sentence does not fit".
  - **Nothing can overflow the fixed band, so nothing has to be kept ahead of
    the data.** A species whose short form stops fitting simply stops carrying
    one and the cards go on printing. What has to fit unconditionally is the
    role ability on its own, which is 153 units against 340 -- an import that
    doubled one fails
    `test_a_role_ability_alone_always_fits_the_advanced_band` rather than
    printing off the bottom of a card.
  - **`MIN_BACK_PORTRAIT_HEIGHT` is 360 against the front's 380, and the
    20 units are what buy the fixed band.** The front is the picture face and
    the back is the rules face -- it carries a second ability where the front
    carries one -- so the back's portrait is the thing that pays for a badge
    that does not move, and at 340 the band holds every species' short form
    including Volatile's, which is the longest by half again. Neither floor is
    a number tuned to today's data: they are the line at which a player card
    has stopped being a picture, and lowering one to fit a paragraph is the
    move to resist.
  - **What the back is still waiting on is an advanced *role* ability.** The
    sheet's `Advanced` column is empty for all thirty-six, so the band repeats
    the basic sentence; see "Blocked or deferred" in the rules log. The role
    half of the band is the only thing that changes when it fills.
  - **`duplex_order` reverses every row of the back sheet.** A duplex print
    comes out flipped about the paper's long edge, so the leftmost cell of a
    row on the front is the rightmost on the back. A maneuver deck never
    needed this because all thirteen of its backs are the same picture; every
    one of these is a different player, and a run that lands the wrong back
    behind a front is not one you recover from. `print_sheet` pads a short row
    at its *end*, which is why reversing the row as it stands keeps the
    columns.

## The species cards

`d12ball/species_cards.py` draws the four species abilities -- Volatile
(Fire Demon), Lithium powered (Cyborg), Mind Pull (Telekinetic), Slimey
(Ooze) -- as a **three-card reference set**, poker size, out of the same
`Pen`, palette and `print_sheet` as the maneuver and player cards.

```bash
python3 scripts/import_d12ball_species.py                     # -> d12ball/data/species.json
python3 scripts/render_species_cards.py --out cards/species --sheet
```

- **One card per *pairing*, not per player.** Every player of a species
  carries that species' ability, so a species-vs-species game only needs the
  two abilities in play. `CARD_FACES` is the three ways to split the four
  abilities into two disjoint pairs -- the perfect matchings of K4 -- so the
  three double-sided cards carry all six pairings, **each face exactly one**
  (`test_every_pairing_appears_on_exactly_one_face`). Lay the card whose face
  matches the two teams between the coaches; its back holds the other two,
  which is harmless. A mixed colour team fields all four species, so that
  coach gets the whole set.
- **Two abilities to a face, stacked**, each in a fixed-height panel: a
  header band in the species' own colour (the paired colour team's hex, via
  `TEAM_COLORS[SPECIES_TEAM[...]]`, so a card and the board agree), the
  species icon at the head of the band, the name in the display face, and the
  full sentence at the largest size that fits the panel (`_fitted_body`).
  Slime green takes `high_contrast_ink`'s black like everywhere else, icon
  included. The edge is `INK`, not a species colour -- a card carries two.
  The icon is the same silhouette the player cards and the board carry, which
  is the point of it being here: a coach matches this panel to the cards in
  front of them without reading either.
- **The full sentence only, not `ability_short` as well.** A card on a table
  is the whole of what its coach has, and the short form sitting under it in
  the same panel is the same words a size smaller (the author, and the same
  call `player_cards.py` makes). `ability_short` stays in `species.json` for
  wherever the sentence will not fit -- a Discord caption, a later `/ref`.
- **Nothing is written in the module.** `scripts/import_d12ball_species.py`
  regenerates `d12ball/data/species.json` whole from the sheet's
  `spec_abilities` tab (columns `Spec`, `Name`, `Ability`, `Abbreviated`),
  the species counterpart of `import_d12ball_players.py` and following the
  same rules -- revisions are made upstream in the sheet, and the
  formula-guard backtick is stripped on the way in. A revision reaches the
  cards by re-importing and re-running the render.
- **`spec_abilities` is not `basic_abilities`.** `basic_abilities`
  (`gid=1822486506`) is the six *role* abilities the player import reads;
  `spec_abilities` (`gid=123199571`) is these four. The `player cards` tab
  also has a `SpecAbility` column naming each player's species ability, which
  nothing imports -- the species is enough to look it up.
- **The cards are print-only; the abilities themselves are the engine's** --
  see [species-abilities.md](species-abilities.md). This module still only draws the
  three reference cards, and `species.json` still only feeds them; what the
  bot plays is read through `RulesEngine`, which cannot import a Pillow
  module and so does not import this one.
  `SPECIES_ORDER` and `load_species_abilities` moved to
  `d12ball/components.py` for that reason and are re-exported here, the
  arrangement `cogs/d12ball_helpers.py` has with `d12ball/formatting.py`.

## The role cards

`d12ball/role_cards.py` draws the six basic role abilities -- Fullback,
Defender, Midfielder, Playmaker, Winger, Striker -- as a **one-card
reference set**, poker size, out of the same `Pen`, palette and
`print_sheet` as the maneuver, player and species cards.

```bash
python3 scripts/render_role_cards.py --out cards/roles --sheet
```

- **One card, not three -- because there is no pairing to solve.** The
  species set exists because a species-vs-species game only ever needs
  two of the four abilities in play, so three double-sided cards cover
  every pairing and a coach lays the one that matches the two teams. A
  role has no such split: both coaches field all six roles every game,
  so every role's ability is live at once regardless of who is playing
  whom.
- **Both faces carry all six**, not three apiece. A card that split the
  six roles across its two faces would still make a coach flip it to
  find half of them, which is exactly the thing "no pairing to solve"
  is supposed to buy back. `render_role_card_set` renders the face once
  and hands the same image back as both `"front"` and `"back"` -- there
  is nothing a second, different face could add, so it is not drawn.
- **Two columns of three, not six strips.** Six abilities laid out as
  six full-width strips would run off a poker card; splitting every row
  in two is what fits all six on one face without shrinking the set.
  `GRID_ROLES` is `PlayerRole`'s own order (offense 1 through 6) read
  row-major into the grid -- Fullback/Defender, Midfielder/Playmaker,
  Winger/Striker -- rather than a seating chart invented for the card.
- **The badge is the bot's own role emoji, not a redrawn circle.**
  `d12ball/images/emoji/role_<role>.png` -- the plain, team-less badge
  `scripts/render_role_emoji.py` draws and the bot uploads under
  `ROLE_EMOJI_NAMES` -- is read straight off disk and pasted, so the
  two letters on the card are the same art as the two letters beside a
  name in Discord, not a second drawing of them. This is the first
  thing in the bot to actually open that file: everywhere else it is
  written to be uploaded by hand and never read back (see
  `scripts/render_role_emoji.py`'s own docstring and "The brackets have
  an emoji form" in docs/design/naming-and-wording.md). A missing file
  draws nothing, the same swallowed-`OSError` contract every other
  bundled image in this package follows -- `role_cards.py` does not
  need `d12ball/render.py`'s `ROLE_INITIALS` at all, and does not
  import it.
- **The badge nearly fills its own row.** `BADGE_SIZE` is a fraction of
  `NAME_ROW_HEIGHT` rather than a size picked to leave room beside it
  for something else -- the badge is already the picture a coach reads
  this role off in Discord, so a print reference gets more out of
  making it as large as the row will take than out of shrinking it to
  match a smaller badge drawn elsewhere on the card.
- **The name is the largest thing `fitted_bold_font` will fit the row
  at, not a fixed size.** With the badge taking the row's height, the
  name gets whatever width is left of it and is sized to that --
  "FULLBACK" prints larger than "MIDFIELDER" because it is shorter, the
  same search `player_cards.fitted_name` runs for a player's name.
- **The two skills stack under the name, right-anchored, instead of
  sitting beside it.** A name sized to fill the row has no width left
  beside it for numbers on the same line, so each skill gets a row of
  its own under the name row. Right-anchored rather than left is what
  keeps six panels' numbers reading as a column when they sit side by
  side, since "OFF 1" and "DEF 6" are not the same width as "OFF 4" and
  "DEF 3". They stay in `CARD_OFFENSE_COLOR` / `CARD_DEFENSE_COLOR` --
  the same two colours `player_cards.draw_stats` and the bot's own card
  draw them in, so a printed 6 and a drawn 6 are the same red.
- **Only the full sentence, never `ability_short`** -- the same call
  the species and player cards make, and for the same reason: a card
  on a table is the whole of what its coach has. `ability_short` on a
  `RoleProfile` stays for a caption, not a print.
- **The sentence is top-aligned under its band, not centred.** Every
  panel is the same fixed height regardless of how long its own
  sentence runs -- centring each one in the room it leaves would start
  six abilities at six different heights, which reads as unaligned
  rather than as a grid. Top-aligned, the six panels' first lines sit
  level with each other whatever their own lengths, the same way the
  six bands above them do.
- **`BODY_MAX_SIZE` is capped high (40) because the room usually is
  too.** Six one-sentence abilities rarely fill even a third of a
  poker card's height between them, so `_fitted_ability`'s search
  almost always lands well below the cap on width alone -- the cap
  exists to let a short sentence in a short row use the room it has
  rather than sit small in it, not to promise every sentence prints at
  40.
- **Nothing here is written in the module.** The ability text and the
  offense/defense numbers come from `players.json`'s `role_profiles`
  through `load_player_catalog`, the same table `/d12ball
  role_abilities` (`cogs/d12ball/slash_commands.py`) already reads --
  so a card cannot claim a stat the bot does not play, and a sheet
  revision reaches it by re-importing and re-running the render script,
  same as every other card in this file.

## The species icons

One silhouette a species -- a flame for the Fire Demons' Volatile, a cell
with a bolt cut out of it for the Cyborgs' Lithium Powered, an inward
tapering spiral for the Telekinetics' Mind Pull, and a wobbling bubbled blob
for the Oozes' Slimey. `scripts/render_species_icons.py` draws them and
`d12ball/images/species/` holds them.

```bash
python3 scripts/render_species_icons.py                    # dry run
python3 scripts/render_species_icons.py --out /tmp --sheet # look first
python3 scripts/render_species_icons.py --in-place
```

- **Two files a species.** `<species>.png` is the ink silhouette every render
  reads; `<species>_color.png` is the same shape painted in that species' own
  colour -- the paired colour team's hex out of `TEAM_COLORS`, so it is the
  colour the board already draws those meeples in and there is still exactly
  one hex per colour in the codebase (see "Team colors" in [teams-and-players.md](teams-and-players.md)).
  - **Nothing in the bot reads the coloured copy, and it is not a second
    source of truth.** It is written from the same shape in the same pass,
    through the same `render.tint_silhouette` the renderer tints with, so the
    two cannot come to disagree by being generated separately. It is there for
    the places a file has to arrive *already* coloured -- a Developer Portal
    emoji upload, a document, a slide -- where the bot's own drawing tints at
    the moment it draws. **Anything drawing an icon in code still asks
    `species_icon`**; reaching for the coloured file instead is how the Oozes'
    icon ends up invisible on the Oozes' own band.
  - **The way the pair comes apart is somebody regenerating the art and
    shipping half of it**, which nothing would otherwise notice --
    `test_the_coloured_copy_cannot_drift_from_the_silhouette` compares the two
    alpha channels, since the alpha *is* the shape.
  - Read the Oozes' coloured one on something dark. Slime green is the one of
    the four that all but disappears on white, which is the fact
    `high_contrast_ink` exists for and the reason a card never uses this file.
    The script's `--sheet` draws on a dark ground for the same reason.
- **They are one flat ink on transparency, not coloured art**, and that is
  what lets one file serve every place an icon appears. A species icon sits
  on three grounds -- a team-coloured header band on a printed player card,
  the same band on a species reference card, and the white face of the card
  the bot draws on the board -- and no single colour reads on all three.
  `render.species_icon` tints a copy at draw time, keeping the alpha and
  replacing the ink, which is only possible because there is one ink to
  replace. **Nothing may paste `load_species_icon`'s answer straight.**
  `tint_silhouette` is the repaint itself, its own function because the icon
  script calls it too -- two implementations of that is how the coloured
  copies on disk come to disagree with what the bot draws.
- **The tint is cached per (species, colour, size)**, because the board draws
  up to a dozen cards a render and each wants the same few pixels. Asking for
  no size gets the icon as drawn, which is what a caller at print resolution
  wants: `cards.Pen.paste` scales onto the supersampled canvas, so handing it
  something already cut down to the card's units throws most of the icon away.
- **The shapes are drawn from cubic segments in the script, not pasted from
  files**, the same call `render_condition_tokens.py` makes: art nobody has to
  own cannot go missing, and a silhouette regenerates at whatever canvas the
  next use wants. Every measurement is a fraction of the canvas, so changing
  `CANVAS` moves nothing.
- **They are drawn to survive 18px**, which is roughly where the bot's own
  card shows one. That is what settled two of the four. Slimey went through
  four drafts -- a ledge with drips, a ball with a highlight, a splat, and the
  blob that won: the ledge is top-heavy where every other icon in the set is
  centred, the highlight reads as an eye by 26px and turns the icon into a
  creature, and the splat reads as a star. The Ooze's blob and the Fire
  Demon's flame are the pair most at risk of reading alike, which is why the
  flame carries a second tongue and a real valley rather than being a tapered
  teardrop.
- **A missing icon is silent**, like every other bundled image: the loader
  swallows the `OSError` so a render can go on, and what a coach sees is a
  card with nothing beside the role initials. `D12BallFontTests`'
  `test_bundled_art_is_named_exactly_as_the_code_asks_for_it` covers these
  along with the condition tokens, comparing against the directory's own
  listing rather than asking `Path.exists` -- see "A bundled file's name is
  case-sensitive on one developer's machine and not on the other's".
- **They are not Discord emoji.** The four `team_*.png` in
  `d12ball/images/emoji/` are uploaded through the Developer Portal and are a
  second copy of the team colours (see "Team colors" in [teams-and-players.md](teams-and-players.md)); these are card art,
  read off disk at render time, and nothing has to be uploaded for a change
  here to take. `d12ball/images/species/` is its own directory for that
  reason.
- **`scripts/render_species_icons.py` is a dry run unless told otherwise**,
  because what `--in-place` overwrites is tracked art -- the same reason
  `render_condition_tokens.py` and `recut_player_portraits.py` are.

## The print-and-play kit

`scripts/generate_print_and_play_kit.py` is the one command for
everything above plus the boards -- every maneuver, player and species
card, and the field, jumbotron and team boards, into a folder (or a zip)
meant to leave the repo for a meetup, a playtest table or a con booth.

```bash
python3 scripts/generate_print_and_play_kit.py
python3 scripts/generate_print_and_play_kit.py --bleed --pdf --zip
```

- **It draws nothing itself.** It runs `render_maneuver_cards.py`,
  `render_player_cards.py`, `render_species_cards.py` and
  `render_boards.py` in turn -- the same four scripts a developer
  already reaches for one at a time -- and is only their sum into one
  folder. So a rules change, an import or an art fix reaches the kit
  exactly the way it reaches each script on its own, by re-running it;
  there is nothing in the kit script itself for a future rule to drift
  out of step with, because it has no rule of its own to hold.
- **It also writes a README and a copy of the living rules**, so the
  kit is self-contained for somebody who has left the repo behind --
  what's in the box, what paper each component wants, and what a table
  still has to bring that nothing here prints (a d12 a side, meeples,
  exhaustion tokens), read off "The ball, the dice, and the tokens" in
  the living rules rather than kept as a second list here that could
  drift from it.
- **`print-and-play/` is generated output and is gitignored**, like
  `cards/` and `print/` -- run the script again rather than trusting an
  old copy after the rules move.

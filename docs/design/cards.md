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
python3 scripts/render_maneuver_cards.py --sheet  # print/maneuver-cards/print-sheet.png
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
    maneuver and the solo standard game against Dinky -- half a cycle, and the one
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
  effect text is small print at that size, which is what the full-image link on
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
  `load_maneuver_catalog` and `cards.matchup_rank_groups`. So a card cannot claim a rule the bot does not play, and
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
    actual wrapped lines at the row's own name size (26 since 2026-09-28,
    when the author read the printed faces as too small; it was 22) and `render_maneuver_card` sizes the row to that, pinned to the
    card's foot. The room the measurement frees goes to the effect band
    above it.
- **No role abilities on the face** (the author, 2026-09-28). There was an
  "ABILITIES IN PLAY" band along the foot: the roles whose sentence named the
  maneuver, matched on whole words, plus a hand-kept `EXTRA_ROLES` (the
  Striker on High Pass), `EXTRA_NOTES` (the ball speed modifier on Steal and
  Intercept, the Fullback on Clear and Setup Pass, the Playmaker on both
  dribbles) and, on every gambit, a `CARDS` line saying its effect follows the
  cards. It went whole, and its code with it. The role reference card and the
  player cards carry the role abilities; the strip diagram still draws a
  role's variant as a dashed arc; what a gambit does on the cards is now the
  two boxes below. **What the face no longer says anywhere is the ball speed
  modifier a Steal or an Intercept adds to its skill test** (Law 6.4, 19.9.3)
  -- no role owns it, so no reference card carries it either.
- **A gambit's effect is three boxes: SUCCESSFUL GAMBIT, FAILED GAMBIT, TIE**
  (the author, 2026-09-28). The sheet carries one sentence per gambit with
  "If defeated" in the middle of it, which asked a coach to find the turn in
  the sentence before knowing which half applied. `gambit_effect_parts` cuts
  it there: the first box, outlined in the card's colour, is what the gambit
  does when it succeeds; the second, on grey, is what its side pays when it
  fails. The third says what a tie on the cards resolves as -- "Resolves as
  Dribble Advance:" and that basic card's own effect, whole, looked up by
  `catalog.counterpart`. Law 19.4 is when each applies: won on the cards,
  lost on the cards, tied. `gambit_effect_boxes` is the list.
  - **Both halves are the sheet's own words.** Only the lead-in "If
    defeated," goes, since the heading says it, and the next letter is
    capitalised. Cutting here rather than adding two columns to
    `maneuvers.json` because the import rewrites that file whole from the
    sheet; if the sheet grows the two columns, read them instead.
  - **A gambit whose sentence loses the clause is drawn without a failure
    box and logged, not raised.** The bot draws every hand at startup, and a
    reworded sheet must not stop it starting.
  - **All three boxes share one searched size**, so none reads as the more
    important, and the boxes sit close together, since the room between them
    is room the text does not get.
  - **A gambit has no time pill; the tie box took its place** (the author).
    A gambit's clock is the same as its basic card's, and the basic card,
    which is always in the same deck, still carries it.
- **The rank is Roboto Slab Bold, like everything else on the card**
  (`cards.rank_font`). Roboto Slab's O is the width of its 0, so "O1" can
  read as "01", and on 2026-09-28 Montserrat ExtraBold was tried for the
  rank alone -- its O a full circle beside a narrow oval zero, picked from
  nine faces compared side by side. The author read it as the wrong font
  beside the slab and put the rank back the same day. The O-and-zero
  question is still open; a different face was not the answer.
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
    to the next caption on its row (21 at most), and ability variants get a
    second row.
  - **The panel is as tall as its own diagram, from 230 up**
    (`strip_panel_height`). It was a fixed 288 for every card, which left
    most of them a band of empty panel and still let Double Team's third
    caption row run out underneath. The height is found off the same
    `strip_geometry` that draws it, the way the matchup row is measured, and
    what it frees goes to the effect text. The diagram is centred in any room
    left over and is never pushed up into the legend.
  - **An arc's reserve above the strip is half its `arc_rise`.** `arc_rise`
    is the quadratic Bezier's control point, and the curve only climbs half
    way to it; reserving the whole rise was most of the empty panel.
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
  edge. **`FACE_COLOR` is still cream**, for the hand image alone, and is
  deliberately not the cards'. The printed boards, the rulebooks and their
  figures used to share it and went white on 2026-09-27: they are `PAPER`,
  with `PAPER_PANEL` and `PAPER_EDGE`, beside it in `cards.py`; see
  printed-boards.md.
- **The rounded outline is the cut line.** With the face and the sheet both
  white there is nothing else to say where a card ends, which is why the
  corner radius is drawn rather than implied and why `FRAME` is small enough
  that the outline is the card's own edge.
- **The back is keyed by tier -- `render_maneuver_card_back(catalog, bleed,
  tier=...)`.** `MANEUVER_TIER_GAMBIT` (the default) is one back for all
  twelve: a coach holding both sets must not show which side
  of the ball -- or which tier -- they are reading, and the offense there
  holds six. `MANEUVER_TIER_BASIC` draws six nodes with one name apiece
  instead: a standard-mode coach's hand is never anything but the three basic
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
    bottom node, which still sits on this same vertical line. **They are set
    at 24** (the author, 2026-09-28: 19 was too small), paid for by moving
    the cycle up 28 and the title up with it.
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
  - **The two margins are different numbers because only one of them is
    under pressure.** Four poker cards across is 10in of card before any
    gutter at all, and a letter page turned landscape has about 10.5in of
    printable width -- so every horizontal pixel comes off what a home
    printer can fit, and at the old shared 24 the sheet was 10.64in and lost
    its outside columns at 100%. The cut is lined up on the card's own
    rounded outline rather than on the space around it, so the gutter can go
    narrow without costing anything. Height is under no such pressure: a
    thirteen-card sheet is 14.6in whatever the gutter, and is tiled or
    printed a page at a time either way. Nothing about the image says how
    wide it is meant to be, so check the arithmetic -- width over 300dpi,
    against 10.5in -- after changing either margin.
- **The header carries no tier label** (the author, 2026-09-28). Its corner
  printed "die 1-2" while the cards and the selection die had to coexist, then
  "BASIC MANEUVER", then the card's own tier on both sets. It went from both:
  a gambit's subtitle says "ADVANCED ..." and its colour is its
  own, so the label was the third saying of it, and a basic card is the one
  with no subtitle. The title is centred on the card in the room the label
  left. The face is still what tells the two sets apart -- the back cannot,
  and must not.
- **A gambit's header also says, in words, which basic maneuver it is
  the advanced version of** (the author, 2026-09-20) -- a line under
  the title reading "ADVANCED PRESSURE". It read "ADVANCED VERSION OF
  PRESSURE", the living rules' gambit table's phrase, until the author cut
  it to the two words on 2026-09-28. The matchup band already carried
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
- **The effect text's size is searched, not set.** The effects run from
  Deflect's twenty words to Double Team's seventy against a band that is
  whatever the strip and the matchups leave behind. A fixed size
  fitted the short cards and ran Double Team's paragraph straight over three
  bands at once, silently, because nothing measured what it had been given.
  The search runs from 36 down to 20 (`EFFECT_MAX_SIZE`, `EFFECT_MIN_SIZE`;
  29 and 17 until the author read the printed faces as too small on
  2026-09-28): a basic card sets at 36, a gambit's three boxes at 23 to 32.
  The header band went from 152 to 136 for the same room.
- The cards are generated output, written under `print/` and gitignored
  ("Where printed output goes", below).

## The player cards

`d12ball/player_cards.py` draws the roster as cards -- one a player, poker
size at 300dpi, the same as a maneuver's and out of the same `Pen`, palette
and `print_sheet`. The player, species and role cards are drawn for print and
carry no tests -- nothing printed does (the author, 2026-09-23) -- so a change
to one is checked by rendering the cards and looking. The bot posts the same
images; see "The cards on Discord" below.

```bash
python3 scripts/render_player_cards.py --sheet  # into print/player-cards/
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
- **The stats panel is one row, and it does not name the role** (the author,
  2026-09-27). `OFFENSE 2 | 5 DEFENSE`: each number centred in its half at 70,
  its label on the outside of it at 19 (the author, 2026-09-27), in a panel
  88 units tall where it was 132 with a `ROLE`
  column between the two. The role is already said twice -- in words under
  the name, and in the badge beside the role ability -- so the column was
  the third saying of it, and the height it held went to the portrait and
  the ability text. Both faces draw the panel, so the back's portrait slot grew by the
  same amount; its band did not move (`ADVANCED_BAND_TOP`).
- **The line under the name is the role, set at 26** (the author,
  2026-09-27): `DEFENDER`, and on the back `DEFENDER · ADVANCED`. It was the
  team at 16, but the team is already the band's colour, the card's edge and
  the corner emoji. It is fitted to the name's room with 26 as the ceiling,
  because `MIDFIELDER · ADVANCED` does not fit at 26 and a line that ran
  under the emoji would read as a mistake.
- **The front's ability band is two rows, each behind a badge, with no
  heading** (the author, 2026-09-27): the role's emoji beside the role's
  sentence, and the species' icon beside the species ability's *name*. The
  badges are the labels -- which sentence is the role's and which ability is
  the species' is read off the two pictures in front of them -- so
  the `ABILITY` heading went, and the text went from 30 to 36. The role
  badge is the bot's own emoji in the card's team colour
  (`role_defender_purple.png`), a species team using its colour team's file
  as it uses its hex; the species badge is the icon in `high_contrast_ink`
  on a rounded square of the species' colour, the size and shape of the role
  badge, because Slime green on a white face cannot be read. Only the species
  ability's name is on the front: its rules are on the species reference
  cards, and the front is the picture face. The badge is level with the
  sentence's first line, so a three-line ability hangs off it. The longest
  role ability still leaves the portrait about 480 units, well over
  `MIN_PORTRAIT_HEIGHT`.
- **What the print adds is the ability, and it is the full sentence.** The
  bot has the roster and the rules commands a click away; a card on a table is
  the whole of what its coach has, so the sentence goes under the portrait.
  Never `ability_short` -- see "Every ability is imported twice".
- **The ability is measured before anything is drawn, and the portrait takes
  what is left.** Its length is the one thing on the card the layout does not
  choose, so the header and stats are pinned to the top, the ability band to
  the bottom, and the picture gets the middle. That is silent when it goes
  wrong -- a longer ability squeezes the portrait rather than overflowing --
  which is why the slot has a floor, and why a render that merely completes
  proves nothing.
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
- **The ball in a portrait is a d12, with real numbers on it** (the author,
  2026-09-27). Eighteen of the paintings showed a round ball and Kindlefinger's
  die carried glyphs; the game is played with a d12. The balls were replaced by
  the box art's own die (`box_art.d12_art`'s solid) wearing each painted
  ball's surface, so an ooze die keeps its veins and a telekinetic one its
  dimples. Every face turned to the viewer carries a number drawn in its own
  plane, and the numbering is a real d12's: opposite faces sum to 13, so no
  visible pair does, and 6 and 9 carry a dot. What stood in front of a ball
  -- a hand, a toe, flames -- was put back over the die from the painting.
  Kindlefinger kept its painted die and had its glyphs painted out and
  numbered. **Synapse came later** (2026-09-27): its first d12 draft was not
  taken, and its ball became a die in a second pass -- the same solid seen
  corner-on, wearing its ball's bronze panels and teal lens, numbered in
  teal-tinted numerals, with the kick's spark put back in front of it, and
  turned so one of its flat sides lies flush against the end of the arm that
  touched the ball. Putting any of
  these back to its painting is
  [docs/portrait-d12-revert.md](../portrait-d12-revert.md), portrait by
  portrait.
  - **A light grey on a die is tinted, never left colourless.** A silver
    highlight or a pale numeral is exactly what the recut takes for studio
    background, so the replaced pixels near each die carry a few units of the
    team's colour and stay under the level the cut feathers at -- the check in
    `D12BallPortraitRecutTests` is what caught them.
- **`Pen.paste` resizes straight to the supersampled canvas.** The
  supersampling is there because Pillow does not antialias the shapes the cards
  are drawn out of; a photograph put through it would be resampled twice for
  nothing.
- **A team sheet is three across**, not the maneuvers' four: a team is nine
  players, and nine poker cards in a 3x3 come out at about 8 x 11 inches --
  a page. Print it at 100% on A4, or borderless on letter, or the cards come
  off the printer undersized.
- **The header is the name, the role under it, and the team's emoji in the
  right-hand corner** (the author, 2026-09-27). It used to carry the role's
  initials in a badge on the left and the species icon on the right; both
  moved down to the ability band, where each sits beside the ability it
  grants, and the header says the role once in full. The corner is the
  team's own emoji as the bot uploads it (`images/emoji/team_<team>.png`):
  on the band of the same colour its ring disappears and what reads is a
  white disc with the team's letter. A species team's emoji is its icon in
  that disc rather than a letter, because that is the emoji the bot shows
  for it. The left corner stays empty and the name's room stays symmetric,
  so the name is centred on the card.
  The name and the role are set in `high_contrast_ink` -- black on Slime
  green, white on every other band (the author, 2026-09-27) -- because
  white on Slime could not be read. The corner emoji follows: on a band
  whose ink is black, `corner_mark` redraws the emoji's letter black inside
  its white disc, from the file's blue channel (Slime green's is 0 and
  white's 255, so the antialiasing comes through exactly). The file itself,
  and the emoji the bot uploads, are unchanged. A printed set is the four colour teams'
  cards; a species team's card is one the bot posts, and there the species
  icon in the corner is the right mark (the author, 2026-09-27).

- **The back is the player's gambit**, drawn by
  `render_player_card_back`. Not a shared back like a maneuver's: player cards
  are dealt face up and sit on the field and team boards all game, so there is
  nothing to hide -- the other side of the card is the same player in advanced
  mode.
  - **What makes it the advanced one is what advanced mode plays for this
    player** (the author, 2026-09-25): their advanced skills in the stats row
    (`advanced_card_skills` -- Hellguard prints 0/8), and **their personal
    ability instead of the role's** in the band where they have one
    (`advanced_card_ability`). The replacement is the card's, not the game's:
    in play a player keeps their role ability too, and its sentence is on the
    front. A player whose sheet sentence only names a higher skill prints that
    sentence ("High defensive skill.") as the sheet words it, and a player
    with no personal ability prints the role's sentence on both faces.
    `CardSkills` rather than a `RoleProfile` carries the numbers, because an
    advanced score is not held to 1-6.
  - **It is laid out exactly as the front** (the author, 2026-09-27): the
    same header, stats panel and ability band, the role badge in front of
    the personal ability and the species badge and ability name under it.
    `draw_face` draws both faces; they differ only in the subtitle, the
    skills and the sentence they are handed. The role badge stays in front
    of a personal ability because the ability belongs to a player of that
    role, and the badge is what marks the row as the player's own rather
    than the species'.
  - **This replaced a fixed band with the species keyword in a pill, and the
    species' short form under the ability where it fitted.** The band was
    fixed (`ADVANCED_BAND_TOP`, 2026-09-07) so the pill on its heading row
    sat in the same place on every back; a band laid out from the bottom
    edge up gets that for free now that the species is the band's *last*
    row, so the fixed band, `species_short_fits` and the separate back floor
    all went. The back no longer carries the species' short form, as the
    front never did: the species' rules are on the species reference cards.
  - **A long sentence is set smaller rather than squeezing the portrait
    past its floor.** At 36 a five-line personal ability (Scorchit's,
    Glompex's, Zenith's, Quantor's) would leave the portrait 260-315 units
    against `MIN_PORTRAIT_HEIGHT`'s 380, so `ability_band` comes down a
    point at a time until the portrait keeps its floor, stopping at
    `ABILITY_MIN_SIZE` (24): those four print at 28-33 and every other
    card, front and back, at 36. A card whose sentence is smaller than its
    neighbours' was judged better than a card that has stopped being a
    picture. An import that lengthens a personal ability past what 24 fits
    would push the portrait under the floor, so look at the backs after one.
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
python3 scripts/render_species_cards.py --sheet  # into print/species-cards/
```

- **One card per *pairing*, not per player.** Every player of a species
  carries that species' ability, so a species-vs-species game only needs the
  two abilities in play. `CARD_FACES` is the three ways to split the four
  abilities into two disjoint pairs -- the perfect matchings of K4 -- so the
  three double-sided cards carry all six pairings, **each face exactly one**.
  Lay the card whose face
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
- **The cards draw the text; the abilities themselves are the engine's** --
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
python3 scripts/render_role_cards.py --sheet  # into print/role-cards/
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
- **The name is `fitted_bold_font`'s size for Fullback, used as a
  ceiling on every panel rather than each panel's own largest fit.**
  Left to fit its own row alone, "WINGER" or "STRIKER" would print
  larger than "FULLBACK" simply for being shorter -- six names at six
  different sizes because the words happen to differ in length reads as
  noise, not as a grid. `render_role_card` fits Fullback's name once,
  against the same row width every panel's name row has, and hands that
  size to `_draw_panel` as `name_max_size`; a longer name
  ("MIDFIELDER", "PLAYMAKER") still shrinks to fit under it, since the
  ceiling only ever holds a shorter name back, never stretches a longer
  one past what its own width allows.
- **Offense and defense sit side by side on one row under the name,
  right-anchored as a pair, instead of stacked one above the other.** A
  name sized to fill the row has no width left beside it for numbers on
  the same line, but a one-digit number doesn't need a row of its own
  either -- stacking each under its own label was room the ability text
  below could use instead. The pair is
  right-anchored as a block (`"OFF 1  DEF 6"`, not each number anchored
  on its own) so six panels' pairs still read as a column when they sit
  side by side, since "OFF 1  DEF 6" is not the same width as "OFF 4
  DEF 3". They stay in `CARD_OFFENSE_COLOR` / `CARD_DEFENSE_COLOR` --
  the same two colours `player_cards.draw_stats` and the bot's own card
  draw them in, so a printed 6 and a drawn 6 are the same red. The stat
  row's own left edge, otherwise blank once the numbers moved out to
  make room below, prints `"basic skill values:"` in the same face and
  size as OFF/DEF but plain and in ink -- so the row reads as a single
  labelled line rather than a heading with unexplained numbers under
  it. `STAT_ROW_GAP` between the name row and this one is 2, not the
  6 an earlier pass left it at, once splitting the two stats into
  their own stacked rows stopped needing the extra room.
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
- **The ability text is Defender's own fitted size, used as a ceiling
  the same way the name is.** A short sentence in a short row (Striker
  gets a two-line one; Fullback's is three short words a line) would
  otherwise fit larger than a longer one purely because it has less
  text to wrap, and six sentences at six sizes for that reason reads
  the same as six names would. `render_role_card` runs `_fitted_ability`
  once for Defender's own sentence, against the same panel geometry
  every role's body has, and passes that size down as `body_max_size`;
  `BODY_MAX_SIZE` (56) is not that ceiling but the search bound used to
  find it -- generous enough that Defender's own fit is discovered
  unclipped rather than flattened against an arbitrary cap every short
  sentence would otherwise hit as well, which would leave nothing for
  the ceiling to actually hold back.
- **The title is the card's heading, not a caption.** "ROLE ABILITIES"
  was a small muted line (17px, `MUTED`) sitting above the grid like a
  label; the author asked for it larger, clearer and bold (2026-09-26),
  so it is 40px bold in `INK`, in a `HEADER_HEIGHT` of 76 rather than
  44. The taller header moves the whole grid down 32px, and
  `BOTTOM_PAD` under the grid shrinks from 40 to 20 to give most of
  that back: the rows lose only four pixels, which leaves Defender's
  fitted ceiling -- and so every panel's ability text -- at the size it
  was before. A heading that grew by shrinking the rules under it
  would have traded the thing the card is for.
- **Nothing here is written in the module.** The ability text and the
  offense/defense numbers come from `players.json`'s `role_profiles`
  through `load_player_catalog` -- so a card cannot claim a stat the
  bot does not play, and a sheet revision reaches it by re-importing
  and re-running the render script, same as every other card in this
  file.

## The cards on Discord

Three commands post the printed cards themselves, not a Discord layout of
them, because a coach playing by Discord and a coach at the table should be
reading the same card:

- **`/d12ball role_abilities_reference`** posts the role card
  (`render_role_reference`, the printed face in the dark palette -- see
  below), one image with the full-image link, the way
  `maneuver_reference` posts the hexagon. It replaced `/d12ball
  role_abilities`, a text list of the same six sentences (the author,
  2026-09-26).
- **`/d12ball species_abilities_reference`** posts the two faces of the
  set's first card, which between them carry all four abilities once each,
  **side by side on one image** (`render_species_reference`, in the dark
  palette), with the
  full-image link. The set is three cards only so that every species pairing
  is one face on a table; a channel has no table, so the other two cards
  would only repeat the text. It was two attachments at first, and Discord
  cropped the pair to two tiles that cut off each card's text (the author,
  2026-09-26); one image is shown whole. Posted whatever the game's mode,
  like the role card: it is a reference to the rules, not a statement about
  this game. **Which two faces is `species_cards.REFERENCE_FACES`**, beside
  `CARD_FACES`: it was chosen in the cog until the web page needed the same
  two (step 11 of [../web-app-next.md](../web-app-next.md)), and "a screen
  has no table" is as true of a page as of a channel, so it is not
  Discord's to decide. The page shows the two faces as two images
  ([web-app.md](web-app.md), "The rules and the player aids"), since it
  has no attachment tiles to crop them.
- **`/d12ball team_reference`** posts the asking coach's team (both with
  `all_teams`), one message a team, nine cards inside Discord's ten
  attachments a message. **Which face is the game's mode**:
  `render_player_card_back`, the advanced face, where
  `RulesEngine.personal_abilities_apply` says the game plays the personal
  abilities and advanced skills, and the front everywhere else. The cards are
  in catalog order rather than the roster's by-place order, so a card is in
  the same place every time it is asked for.

All three render in a worker thread per request (`card_png` in
`cogs/d12ball/presentation.py`, which encodes the PNG in the same thread)
rather than at startup the way the maneuver images are: they are asked for
rarely, a card is about a tenth of a second, and the maneuver images are
prerendered because they go out every maneuver. `team_reference` sends
separate attachments rather than one composite: nine cards on one image
would be too small to read inline, and Discord opens any one attachment
full-size. The two species faces are few enough to read side by side, and
two attachments were cropped, so they are one image.

**The two reference cards are posted dark** (asked for on 2026-09-26).
A white card is the brightest thing in a dark channel by a long way, and
the reason the printed cards are white -- a full page of ink per sheet --
does not apply to a screen, the same split `box_art.py` makes between the
page cover and the night one. The layout is the printed card's, drawn in
another `ReferencePalette` (`cards.py`): `PRINT_REFERENCE` is what the
print scripts use and is byte-identical to the card before the palette
existed, and `DARK_REFERENCE` is what the two commands post.

- **The face is `#111820`**, the ground every image the bot draws in a
  game sits on, so the reference reads as the bot's own and not as a
  scan of a printed card.
- **The skills change colour, not only the ink.** The print pair
  (`CARD_OFFENSE_COLOR` / `CARD_DEFENSE_COLOR`) is chosen for white paper;
  the green all but disappears on the dark face. The dark palette uses
  the maneuver reference image's red and green, which the bot already
  draws on that ground -- still red for offense, green for defense.
- **The species bands keep their team colours.** They are fills with
  `high_contrast_ink` on them, so they read on either face unchanged.
- **The corners are cut out** (`screen_cutout`): transparent outside the
  rounded outline, and the gap between the two species faces is
  transparent too. On paper the corners are trimmed off; on a screen a
  dark card would otherwise sit in a square of its own face, visible
  against whatever colour the Discord client is drawn in.
- The team cards are not posted dark: `team_reference` posts the player
  cards as printed; this change leaves them alone.

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
everything above plus the boards -- the maneuver, player and species
card sheets, and the field, jumbotron and team boards, into a folder (or a zip)
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
- **It also writes a README and both rulebooks as PDFs**
  (`build_rulebooks.py` into `rulebooks/`: the Charter and the Learn to
  Play, the author, 2026-09-27 -- it used to copy `living-rules.md`, which
  a table does not read), so the kit is self-contained for somebody who
  has left the repo behind -- what's in the box, what paper each
  component wants, and what a table still has to bring that nothing here
  prints (a d12 a side, meeples).
- **It is the print version of the game, as print sheets only** (the
  author, 2026-09-27): each card set is its sheet -- two for a team,
  its cards' standard sides and their advanced sides in duplex order,
  so each printed card is standard on one face and advanced on the
  other -- and never a PNG per card, and the player cards are all four
  colour teams'. The printed game has no species-team cards; a colour
  team's card carries its species on its advanced side. The kit's
  README says so in those words.
- **The reference cards share one sheet, and the tokens have their own**
  (the author, 2026-09-27). `render_reference_cards.py` lays the three
  species cards and the role card out together, each front beside its
  back for cutting and gluing -- eight faces, two full rows, so nothing
  is padded. `render_token_sheet.py` is the condition tokens as a front sheet and a
  back sheet printed duplex ([printed-tokens.md](printed-tokens.md), "Paper tokens"). So the
  kit prints everything a table needs but the meeples and the dice. The three card scripts take
  `--sheets-only` for this, and the kit passes it and a `--team` per
  colour team. A developer checking one card still runs the script on
  its own and gets every card. The kit came to 128 MB before this and
  35 MB after, which d12ball.com carries in three zips
  ([landing-pages.md](landing-pages.md), "The downloads").
- **`print/print-and-play/` is generated output and is gitignored**, like
  everything under `print/` -- run the script again rather than trusting
  an old copy after the rules move.

## Where printed output goes

**Everything printed is written under one folder, `print/`, gitignored**,
one subfolder per script, named as the kit names its own folders:

| Folder | Written by |
| --- | --- |
| `print/maneuver-cards/` | `render_maneuver_cards.py` |
| `print/player-cards/` | `render_player_cards.py` |
| `print/species-cards/` | `render_species_cards.py` |
| `print/role-cards/` | `render_role_cards.py` |
| `print/reference-cards/` | `render_reference_cards.py` |
| `print/tokens/` | `render_token_sheet.py` (paper) |
| `print/tokens-3d/` | `render_token_models.py` (3MF and STL) |
| `print/boards/` | `render_boards.py` |
| `print/rulebooks/` | `build_rulebooks.py` |
| `print/box/` | `render_box_art.py` |
| `print/print-and-play/` | `generate_print_and_play_kit.py` (and its `.zip` beside it) |

Each is only the script's default `--out`; the kit passes its own. They
were `cards/`, `print/`, `box/` and `print-and-play/` at the root, and
the 3D tokens had no default at all, until the author asked for one place
(2026-09-27). The old names stay in `.gitignore` so a checkout that still
has them does not see them as untracked; delete them by hand.

`board.png` at the root is not print output: it is `render_sample.py`'s
look at a live board, and stays where it is.

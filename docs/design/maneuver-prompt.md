# The maneuver prompt, and the distance prompts under the field

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## The maneuver prompt

Both sides pick their maneuver off **one public message carrying both rows of
buttons**, and the click is answered ephemerally.
`ManeuverActionPromptView` is the whole of it.

It used to be two steps: a public prompt with a single "Choose Your Maneuver"
button that opened an ephemeral menu of the clicking coach's own cards. That
extra click existed because **an ephemeral message must answer that coach's own
interaction**, and only one of the two coaches is ever holding a live one when a
maneuver begins -- whoever picked Maneuver, or whoever picked the challenger.
The other had nothing for the bot to reply to.

**The cards were never the secret.** The twelve of them and the defeat cycle are
public information either coach may ask for at any time --
`/d12ball maneuver_reference` posts the hexagon to the whole channel. What has
to stay hidden is the **pick**, and that is hidden by the reply being ephemeral
rather than by the menu being private: Discord tells nobody else who pressed
what, and the prompt is never edited to say (see `close_maneuver_prompt`). So a
coach reading this message cannot tell whether the other side has clicked. The
extra click bought a round trip and nothing else.

- **`RulesEngine.maneuver_pick_sides` is the only answer to whose buttons get
  built**, and it is every side of this maneuver a *person* still picks for.
  Two things take a side off it, and both are settled before the prompt exists:
  an unchallenged maneuver has no defense to pick for, and **Dinky's pick is
  written into the match before the prompt is built** -- so a solo game's
  prompt is one hand and one row. It is read off persisted state alone, which
  is what lets a restart rebuild the identical view.
  - **It answers the mention line as well as the buttons.**
    `begin_maneuver_action_selection` builds `waiting_on` out of the same list:
    a coach named above the prompt and given no row to press would stall a game
    and nothing would catch it.
- **A side that has already picked keeps its buttons.** The message is
  deliberately never edited -- that is [the tightest rate-limit bucket in the
  game](rate-limits.md#discords-rate-limits) -- so the buttons a restored view dispatches have
  to match the buttons sitting on the message. Taking a picked side's row away
  would leave those clicks answered by nothing. `pick` refuses the second click
  instead.
  - **Not greying them either**, for the same reason and one more: an edit that
    disabled a row would tell the other coach that side had answered. The "X
    has picked their maneuver" message says that already, deliberately and in
    its own message.
- **Authorization is checked before "already picked".** The other coach's row
  is sitting on the same message, so answering a click on it with "that side has
  already chosen" would say whether they had.
- **Each side gets its own rows and its own colour** -- offense red, defense
  green, the cards' and the reference hexagon's own two colours, so a coach
  finds their row without reading the labels. `even_button_rows` splits a hand
  into as few rows as Discord allows and then evenly across them: a hand of
  six chunked at the five-per-row limit would read five and one. A contested
  prompt with both coaches holding their gambits is exactly five rows -- two a
  side plus the reference -- which is Discord's ceiling and worth knowing
  before adding a seventh card. Since 2026-09-20 the two hands can differ
  (`RulesEngine.maneuver_tiers` takes a side), so a prompt is anywhere from
  three rows to that ceiling.
  - **The wording above the prompt names the colour by looking it up**, in
    `MANEUVER_ROW_COLOURS`, rather than by knowing which side a lone row
    belongs to. A one-row prompt is the *defense's* whenever Dinky has the
    ball, and `maneuver_prompt_wording` said "the red row" either way -- which
    sent a solo coach on defense looking for buttons that were not theirs. One
    table for the two names, so the sentence cannot come to disagree with the
    `danger`/`success` styles the buttons are built with.
- **The restart story got simpler, not more complicated.** The prompt is on a
  real message recorded in `turn_message_id`, so `on_ready` re-attaches it
  through `pending_turn_view` like any other view. The message-agnostic
  `add_view` registration the ephemeral menu needed (`restore_maneuver_menus`)
  is gone; [the shootout's two menus](shootout.md#the-extreme-shootout) still need it and
  still have it.
- **The uploads halve.** One public hand image and one public field strip,
  against a hand and a field to each of two coaches. See
  [The maneuver cards](cards.md#the-maneuver-cards).

## Choosing a distance, and the field under it

**Six prompts ask a version of one question** -- how far does the ball or its
handler go, and who ends up with it -- and all of them are posted over
[the field strip](board-image.md#working-on-the-board-image).
`D12Ball.send_field_prompt` is the funnel for five of them: the Low Pass and
Skilled Pass destination (`LowPassChoiceView`), the High Pass and Setup Pass
distance, and both dribbles' run. The sixth is the run back, which asks the
same question either side of a turnover and carries the same picture through
`send_run_back_prompt` -- see
[Turnovers](possession-and-turnovers.md#turnovers-steals-and-new-plays).

- **They are one helper because they are one question.** Every one is answered
  by reading where everybody is standing relative to the ball, and by the time
  a maneuver has resolved the persistent board has scrolled away up the channel
  -- the same reasoning as the strip under the maneuver cards. They were five
  copies of the same four lines, two of them already carrying the strip and
  three carrying nothing at all.
- **The strip, and deliberately not the coaching image's half-field.** These
  questions are about the *position*, and a position is both sides: a long pass
  is contested where it lands, a dribble can run into somebody, and a set-up's
  shot is priced by who is standing in front of the goal. The coaching image
  shows one side's row with the ball left off, which is right for arranging
  your own team with play stopped and wrong for reading a live position --
  see [The Coaching Choice](coaching-choice.md#the-coaching-choice). `render_field_image` is a
  **crop of the match image's own board**, so what a coach reads here cannot
  differ from the board both of them are already looking at.
  - This was got backwards once: the first build of these prompts used
    `render_coaching_image` and gave `render_coaching_image` a `show_ball` to
    make it fit, which also took the strip *off* the High Pass and Setup Pass
    prompts that already had it. The half-field is the Coaching Choice's and
    nothing else's; `coaching_file` says so.
- **One attachment, on the prompt rather than beside it.** Discord lays two
  images on one message out side by side and halves both, which is why the
  strip under the maneuver *cards* is a message of its own and these are not.
  Riding on the prompt is what lets the click that answers take the picture
  away with `attachments=[]`: it shows the position the effect was chosen
  against, and that position has just moved. The Low Pass's receiver pick is
  the one step that *keeps* it -- the ball has not moved between the two
  questions -- and so has to rebuild the full-image link onto the new view by
  hand, the way `RunBackPlayerChoiceView` does.
- **Every one carries a full-image link**, for the reason the strip under the
  cards does: it is the whole width of the board in a strip a fifth as tall,
  which is the smallest thing the bot sends inline.
- **Both sends are the webhook route** -- the `followup.send` and the edit that
  cuts the link -- so neither competes with the board for the channel's
  five-in-five edit bucket. The clicks that answer are
  `interaction.response.edit_message`, the interaction-callback route, which is
  free of it too. See "Discord's rate limits" in [rate-limits.md](rate-limits.md).
- **A restart re-posts these prompts without the picture.**
  `resume_pending_prompt` posts `pending_turn_view`'s view on a bare message,
  the same as every other image a resume loses.
- **`tests/test_d12ball_field_prompts.py` guards the funnel**, which is the
  thing that can quietly come apart: a resolver that goes back to building its
  own `followup.send` still works, and still drops the field out from under its
  own question.

# Loose balls, and where the ball comes to rest

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Loose balls and the board

A loose ball is announced **with the board under it and the space named**, and
those two are one decision: the ball is lying somewhere nothing else in the
channel has named, and the question that immediately follows -- who to send
after it -- is a question about how far away everybody is. Who a coach may
send is [Sending a player](sending-a-player.md#sending-a-player), the same pool a challenge and a
pickup use.

- **`begin_loose_ball` posts through `announce_board_update`**, which is why
  that helper is no longer only for manual corrections. The snapshot is drawn
  once and the persistent message is brought in line from the same bytes, so it
  costs the render everything else costs; the callers that used to refresh
  immediately before it (the receiverless Low Pass) no longer do, or the same
  board would be written twice. See "Discord's rate limits" in [rate-limits.md](rate-limits.md).
- **A High Pass is not a loose ball, here as everywhere else.** It borrows the
  same contest, but the ball is on a receiver both coaches watched catch it, so
  that branch sends its headline plainly and pays no upload. `is_high_pass` is
  the test, the same one `contest_noun` reads.
- **The pick prompt names the space as well**, because it outlives the message
  that announced it: `/d12ball resume` puts that prompt back up on its own, and
  a restart re-arms it wherever it has scrolled to.
- **The headline is read off the position, not off what made the ball
  loose.** `build_loose_ball_headline` words an empty space and an occupied one
  differently, because they are different questions to the two coaches, and
  since 2026-08-18 both are loose. A caller passing its own `headline=` is
  saying the wording would be a lie, which is the High Pass's case and nobody
  else's.
- `ball_location_line` and `ball_space_label` in `cogs/d12ball_helpers.py` are
  the wording, over `space_label`. The line spells the zone out beside the code
  because "M2" alone means nothing to anyone not already looking at the board.

## Where the ball comes to rest

**What is standing on the space the ball lands on decides how it is won, and
only an empty space is a *loose ball*** -- the author, 2026-08-26. See "Where
the ball comes to rest" in the living rules. Three positions:

| On the landing space | What happens |
| --- | --- |
| Nobody | **Loose.** Each side may send a player after it, or send nobody. |
| One side only | **Theirs**, uncontested. No roll, and the other side is never offered a send. |
| Both sides | A **contest** between the players already there. Nobody else may be sent. |

That corrects the 2026-08-18 ruling, which made *loose* a fact about the ball
("nobody is in possession") rather than about the space, and so let a side walk
somebody in against a space the other side already held. Half of it was already
built: `restrict_to_occupants` landed on 2026-08-24 as Deflect/Clear's own
narrowing and **is** the rule above -- what was wrong is that it was a flag, so
the two paths that did not pass it kept the old behaviour.

- **The rule is unconditional and the flag is gone.** `D12Ball.begin_loose_ball`
  reads both sides' `loose_ball_occupants` and, when exactly one is empty, calls
  `match.decline_loose_ball` on it *before* `auto_resolve_loose_ball_picks`
  runs -- so that side is never put on the clock, `LooseBallChoiceView` is never
  built for them, and the occupying side resolves through the existing "sole
  occupant auto-contests, several -- coach picks" / "one side only, takes
  without a test" machinery with nobody left to contest against. Don't
  reintroduce a parameter for this: a call site that could opt out is exactly
  how the two wrong paths survived 2026-08-24.
- **A High Pass is the one exemption, and `is_high_pass` is already its flag.**
  The ball is high in the air, which gives players time to run at it, so a
  landing space holding only one side may still be contested by the other. That
  is a property of the pass and not of the space, which is why it rides on the
  same flag that carries the ball speed modifier rather than getting one of its
  own. Read **symmetrically** -- the author states it as the defense running at
  the passer's own teammates, and the justification is about the ball, so the
  mirror case is contestable too.
- **Each side's contestant is whoever of theirs is standing on the ball, and
  otherwise a player they may send.** `MatchState.loose_ball_occupants` is the
  first half and `MatchState.contest_candidates` the second;
  `RulesEngine.loose_ball_candidates` is `occupants or candidates` -- one of two
  pools and never a mixture, exactly the shape `challenge_candidates` has, and
  for the same reason. The second half is now only ever reached on an empty
  space or a High Pass.
- **The word is a rule, not decoration.** `contest_noun` answers three ways --
  "high pass", "loose ball", "ball" -- and `build_loose_ball_headline` the same
  three. The message the author caught called every arrival a loose ball *and*
  offered a send the occupancy rule had already taken away; both halves were
  wrong, and only in the case a coach was most likely to meet. "ball" rather
  than "contest" is what the sentences around it need: a coach "contests the
  ball", never "contests the contest". See
  [What a message says](naming-and-wording.md#what-a-message-says) for the wording rules the same
  correction produced.
  - **Every message on the path asks for it, the result and the resume
    included.** `settle_loose_ball_winner` announced "wins the loose ball!"
    whatever had happened, so the sentence a coach read *after* watching two
    players roll for a space they were both standing on denied what they had
    just seen; `pending_turn_view`'s two loose-ball prompts said it too, in
    front of a coach about to act on the position. The noun is read with the
    rest of the position, before the fields the result clears.
- **`pending_loose_ball_on_empty_space` is persisted, and cannot be derived.**
  By the time a roll or a result is worded the contestants have been walked onto
  the space, so the position that decides the word is gone --
  `MatchState.begin_loose_ball` reads it at the one moment it exists. Same
  reason `pending_loose_ball_is_high_pass` is stored. A game saved before the
  field defaults to True, which is what every arrival was called before this.
- **The machinery keeps its `loose_ball_*` names.** Three positions share one
  flow, and renaming it would rename a persisted field and every custom_id
  already sitting in a channel. What a coach reads is what the correction was
  about.
- **A side with somebody on the ball may not withhold them**
  (`may_decline_loose_ball`), the same reading `may_decline_challenge` makes:
  declining is a refusal to pay a walk-in's exhaustion and they have no
  walk-in to pay for. `LooseBallChoiceView` does not build the Send nobody
  button rather than disabling it, and `decline` re-checks for a stale click.
  **That is also what keeps out of bounds an empty space's outcome alone.**
- **Skipping the prompt is a count, not a flag**, exactly as with the
  challenge. `auto_resolve_loose_ball_picks` puts up a **lone** player on the
  ball unasked -- there is nothing to ask -- and leaves two to the coach
  (2026-08-18, the same call as the maneuver challenge's).
  `build_loose_ball_prompt` words that case differently, because the question
  is which of them rather than whether to send anybody.
- **The passer is struck out of the offense's pool in a High Pass contest**,
  in `loose_ball_occupants` and nowhere else, so the pool, the decline and the
  auto-pick cannot disagree about who is standing there. It can only bite on a
  pass clamped to 0 spaces, which never reaches a contest -- stated anyway, for
  the reason `high_pass_receiver_candidates` states it.
- **A Deflect calls `begin_loose_ball` directly** rather than going
  through `finish_maneuver_resolution`. It knocks the ball out of possession
  whoever is standing there, so `check_for_loose_ball`'s question -- does the
  possessing team have somebody on the ball -- has an answer that does not
  matter. It also stops refreshing the board first, since `begin_loose_ball`
  posts one.
  - **Since rank D1 of the model/Discord split it reaches it as a
    follow-on.** `deflection_step` in `d12ball/flow/effects.py` is both
    cards, and it ends by naming `FollowOnStep.BEGIN_LOOSE_BALL` rather than
    by awaiting anything -- see
    [model-discord-split.md](model-discord-split.md). Two things about the
    paragraph above changed shape and neither changed behaviour: the
    `distance_moved` of 1 arrives as a keyword, because
    `dispatch_step_result` passes a follow-on's arguments by name; and "stops
    refreshing the board first" is now a rule rather than an absent call. The
    step reports `board_changed=True` honestly -- the ball moved -- and
    `FOLLOW_ONS_THAT_DRAW_THE_BOARD` is what keeps the cog from writing a
    board this function is about to write itself. Keyed to the step, so the
    seven callers still to be lifted inherit it; see "Discord's rate limits"
    in [rate-limits.md](rate-limits.md).
  - **Setup Pass's cost rides inside the deflection**, so it is in that set
    too. `offer_setup_pass_push_back` asks the coach who beat the pass how
    much further back the ball goes, and all three of its branches end here
    anyway -- so the board arrives with the loose ball, once, on the far side
    of the answer.
- **`check_for_loose_ball` has one detour now, not two.** Its guard still
  earns its keep: the maneuvers that leave the ball with a named player are not
  loose, and that is what it asks. What changed on 2026-08-26 is what happens
  *after* the detour -- a ball landing where only the defense stands is theirs,
  where between 2026-08-18 and then the offense could walk somebody in.

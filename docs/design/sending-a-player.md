# Sending a player, and the maneuver nobody challenges

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Sending a player

Three rules ask a coach to send somebody to the ball's space, and since
2026-08-16 they ask it the same way: **the nearest player either side of the
space, from any zone**. `MatchState.contest_candidates` is the whole of it --
see "Sending a player" in the living rules -- and the three are the maneuver
challenge (`eligible_challengers`), the loose ball (`loose_ball_candidates`),
and the pickup after an out-of-bounds ball, a time out, a missed shot or an
avoided own goal (`begin_ball_recovery` in
[`d12ball/flow/turnovers.py`](../../d12ball/flow/turnovers.py),
`recover_out_of_bounds_ball`). It was
four until 2026-08-18: the long High Pass contest **is** the loose ball now
rather than borrowing it -- see
[Loose balls and the board](loose-balls.md#loose-balls-and-the-board).

- **Distance is the measure, and it always was -- the zone was a second gate
  on top of it.** Every one of these charges a token a space, so a defender
  two spaces away was being refused a challenge a defender four spaces away in
  the same zone was offered. Zone now decides where a player *lives* -- the
  arrangement, the run back, `position_meeple` -- and nothing about what they
  may be sent to do. `fielded_players_in_zone` is gone; don't bring it back.
- **Two candidates, and a tie is every player tied.** Two players the same
  distance off on the same side differ only in who they are, which is the
  coach's call, so the function returns them all rather than picking. It
  iterates `field_players` rather than the board or a set, because the buttons
  a coach is offered have to come back in the same order twice.
- **Anyone already on the space is a candidate at distance 0**, and is never
  actually sent: `automatic_challengers` filters them out of the pool (and
  would have nothing to filter otherwise), the High Pass contest forces them,
  and `eligible_ball_handlers` catches them before a pickup is asked for at
  all.
- **A challenge narrows to them, and this is the one place the wider pool is
  not the offer.** `MatchState.challenge_candidates` is
  `automatic_challengers() or eligible_challengers()`: a defender standing on
  the ball challenges, so **nobody may be walked in past them** (the author,
  2026-08-17). It is what the view builds from, what `choose_challenger`
  validates against and what `DinkyAI` picks out of (`SendOptions.player_ids`
  on the prompt, since step 7 of docs/architecture-migration.md), so the three
  cannot disagree about who is on offer. The other three rules keep the whole pool --
  a contest and a pickup have somebody on the space or they have nothing to
  ask.
- **Two branches are now guards rather than states.** An empty candidate list
  means a side with no meeples on the board, which `validate()` rejects -- so
  "nobody in the zone to challenge" and "neither side has anyone to send" are
  unreachable from a game that loads, and an unchallenged maneuver and an
  out-of-bounds ball are reached by declining and by nothing else. The
  branches stay: without them the flow builds a prompt with no buttons on it.
- **The walk-in is no longer bounded by geometry** -- up to eight spaces on
  board 9, which is past every player's defensive skill. That is the point of
  the decline, and it is why `DinkyAI` sends the *nearest* candidate in all
  four rather than the best. The loose-ball pick took the higher skill until
  this landed and takes distance first since (`DinkyAI._loose_ball`, answering
  the `LOOSE_BALL_PICK` prompt).
- **A missed shot and an avoided own goal joined the pickup on 2026-08-24.**
  Both restart the ball on a space with no coverage guarantee -- unlike a
  goal, whose kickoff space every arrangement is required to cover -- so
  before this they fell through to `finish_maneuver_resolution`'s generic
  loose-ball check at the tail of the reset, which would have let the *other*
  side contest a position they never earned. `ScoreAttemptView.roll`'s missed
  branch and `run_own_goal_roll`'s avoided branch now both set
  `pending_ball_recovery = True` the moment the restart is decided -- the
  same pattern `apply_setup_pass_out` already used for an out-of-bounds
  Setup Pass -- so `begin_ball_recovery` asks the restarting side once the
  reset has settled, and asks nobody at all when the reset already covers the
  space, which the standard deal and every formation usually do.

## The maneuver with nobody to challenge it

A maneuver normally needs two players. When the defense has no challenger the
maneuver the offense picks succeeds outright -- see "Maneuvers" in the living
rules. `MatchState`'s `maneuver_uncontested` is the whole of it.

**Sending nobody is the way in, and since 2026-08-16 it is the only one.**
Walking in costs 1 token per space, and since 2026-08-12 paying it is a
choice. There used to be a second way -- the defense with nobody in the
ball's zone -- and the two were deliberately one state; the zone is no longer
the measure (see [Sending a player](#sending-a-player)), so a side with a
meeple anywhere on the board has somebody to send, and a side with none is a
match `validate()` refuses. The no-candidate branches are still there as
guards. `begin_uncontested_maneuver` is the only way in either way, so
nothing downstream has to know which happened.

- **Exhaustion is where the line is drawn**, which is why the choice is not
  offered to everybody. A defender already standing on the ball pays nothing
  to challenge, so there is nothing to weigh and nothing to refuse: they
  challenge, as they always did. `automatic_challengers` is that reading -- it
  is what `begin_uncontested_maneuver` refuses on -- and `may_decline_challenge`
  is the same fact from the defense's end, asked by the prompt before it words
  one and, since step 6 of docs/architecture-migration.md, by
  `driver._answer_maneuver_challenge` before it declines: the Send nobody
  button is built from the prompt's `SendOptions.may_decline`, and a
  decline the position does not offer is refused by the adapter rather
  than only by the button not being there.
  - **Skipping the prompt is a count, not a flag.** `choose_action` applies the
    challenge unasked only when there is exactly **one** of them. Two is the
    defending coach's pick (the author, 2026-08-17), because a challenge is
    settled on defensive skill and the two differ only in who they are -- so
    the view is now built in a state where declining is refused, which used to
    happen only after a restart re-attached it to a stale prompt. That check
    still earns its keep for the same reason it did before.
    - **There is one route into a challenge since step 7**, `begin_maneuver_step`,
      whichever side is maneuvering: the AI's turn action is the same
      `PLAYER_ACTION` answer a coach's is. Before that the AI's own turn step
      read the count too, and had once read it as a flag -- took
      `on_ball_space[0]` and sent it, picking for the human defense off
      placement order. A rule about how many candidates there are has to be
      asked wherever candidates are counted, not only where it was written
      down first.
    - **The two prompts word themselves out of `challenger_prompt_ask`**, in
      `d12ball/formatting.py`: two defenders on the ball cannot be held back,
      so a prompt offering "or send nobody" offers what
      `ManeuverChallengeView` does not build. The AI's route said it
      regardless, which is what having the sentence twice buys you.
- **Which way it happened is read off the candidates, never stored.** Anybody
  still eligible to challenge means the defense was offered the challenge and
  passed, since a defense with nobody to send is never asked.
  `announce_uncontested_maneuver` (a flow step in
  [`d12ball/flow/turn.py`](../../d12ball/flow/turn.py) since Phase 4, with
  `auto_resolve_challenger` beside it) and the "no defensive maneuver to
  pick" reply
  both word themselves from that, so nothing has to be persisted to word a
  message after a restart. Both branches survive the 2026-08-16 change even
  though one of them is now practically unreachable -- the wording asks the
  state rather than knowing the answer.
- **Dinky never declines.** Its answer to `MANEUVER_CHALLENGE` is always
  `send`, so in a solo game keeping somebody back is the human's option alone
  -- the same call as never slipping in and never leaving a loose ball
  uncontested.
- **It stands in for `challenger_id` everywhere that flag means "a maneuver is
  under way".** `challenger_id` is what tells `validate()` that the handler is
  allowed to be off the ball mid-effect, and what tells `on_ready` which
  prompt to restore. An uncontested maneuver has no challenger and never will
  have a `defense_maneuver`, so both of those checks read
  `maneuver_uncontested` as well.
- **It is persisted, unlike `new_play`.** Nothing else in a saved state can
  tell "the defense has not picked yet" from "the defense is never going to
  pick", and a restart between the offense's pick and its effect has to know
  which. `reset_maneuver` clears it, along with everything else the turn set.
- **`maneuver_selections_complete` is the only "are we ready to resolve"
  test.** Two call sites used to check `offense_maneuver and defense_maneuver`
  directly and would have hung the turn; anything new should ask the property.
- **Two entry points go through the same branch** --
  `PlayerActionView.choose_action` for the offense (the AI's Maneuver is the
  same answer, through the service), and `ManeuverChallengeView.decline` for
  a defense that sends nobody --
  and all of them then use the ordinary maneuver prompt, so a coach reads the
  menu they always read. What is skipped is the challenger pick, the matchup
  image (it draws two players against each other), the reveal, and the skill
  test. A decline moves nobody and charges nobody, so it is also the one of
  the three that asks for no board refresh.

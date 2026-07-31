# D12 Ball -- rules questions and code/rules divergences

**As of:** 2026-07-31, against `main` at `8fad2b3` plus the unmerged
`claude/import-maneuvers-script` branch.
**Companion to:** [d12ball-rules.md](d12ball-rules.md), the vendored copy of upstream.

This file is for things that **cannot be answered from either upstream source** and should
go to the author rather than be guessed at. It is expected to shrink as answers land.

The headline: the code has outrun the written rules. Several mechanics the bot already
implements appear in neither the Notion page nor the spreadsheet, so for those the code is
currently the only specification -- which means a bug and a design decision look identical
from the outside.

---

## A. Rules the code implements that are written down nowhere

Highest priority. Each of these is a real behaviour with no upstream text to check it
against.

### A1. Board sizes 6, 7 and 9

`VALID_BOARD_SIZES = {6, 7, 9}` with layouts 2-2-2, 2-3-2, 3-3-3, defaulting to **7**.

Both upstream sources describe a **6-space** field only: Notion says "12 cards", "6 field
cards" each, "3 zones, each comprised of two pairs opposing spaces", and the spreadsheet's
`older Field` tab lists exactly six named spaces per team. The 7 and 9 layouts came in via
commit `5b0508c`.

- Is 7 the intended default, and 6 now a variant?
- With a 3-space zone the standard 2-2-2 setup only ever fills two of the three spaces --
  the third stays empty. Intended?
- Do any zone-relative rules change? "Back"/"front" is unambiguous for two spaces and not
  for three.

### A2. The coin toss, and the winner's home/visiting choice

The code flips a coin with **fortune** and **doom** faces; fortune wins the flipper the
toss, doom hands it to the opponent. The winner then chooses home or visiting
(`choose_home_or_visiting`).

Notion says only: "One player is randomly assigned to be home team player." No coin, no
faces, no choice. The `Coins` tab defines coins as currency ("Worth in Dinkys") and says
nothing about fortune or doom.

- Is "winner of the toss picks a side" the real rule, or a bot convenience?
- Does the choice matter beyond first possession? Home kicks off; visitors get possession
  after halftime -- so choosing to be the visitor trades the opening for the second-half
  restart. Deliberate?

### A3. What are coins and Dinkys for?

The `Coins` tab is a full currency table with an exchange matrix, and it is unreferenced by
any rule. Is it a D12 Ball mechanic that is not written up yet, a component shared with
another Prophetic Fools game, or dead data?

Also: the AI opponent is named "Dinky AI" and Dinky is the currency unit. Coincidence?

### A4. Role abilities

All six are in the spreadsheet and none are implemented:

| Role | Ability | Needs to be pinned down |
|---|---|---|
| Fullback | No disadvantage on own goal rolls | requires "disadvantage" to be defined -- see B4 |
| Defender | Can manipulate the ball when stealing | Steal Intercept already lets anyone manipulate speed. Does this mean the defender is the **only** role that can, or that they manipulate on some other trigger? |
| Midfielder | +3 for dribble/advance | added to a clash roll when their action is Dribble Advance? |
| Playmaker | +3 for all passes | both Low and High Pass, on the clash roll? |
| Winger | Can set up a scoring opportunity with a low pass | High Pass says "if ball reaches goal, set up a scoring opportunity" -- so what is a scoring opportunity, mechanically? |
| Striker | +3 for scoring off a high pass | applies to the score-attempt roll after a High Pass set-up? |

"Set up a scoring opportunity" is used by both High Pass and the winger's ability and is
never defined. That is the single biggest gap in the maneuver rules.

---

## B. Ambiguities in the Notion text, still unresolved

Carried forward from the 2026-07-25 read; all still present upstream.

### B1. "The attacker chooses an offensive action while the defender chooses an offensive action."

The second "offensive" should be "defensive". Effectively settled by the spreadsheet, which
types each maneuver Offense or Defense, and by the two separate coloured dice -- but the
sentence is still wrong upstream and worth fixing at source.

### B2. "zone" vs "space" -- and this one is now load-bearing

Notion uses both interchangeably ("scoring from zone 4", where spaces are numbered and
zones are not; "conceding team starts from zone 1 (back of their Goal zone)").

The maneuver rule reads: pick a challenger "in the same **space**"; "in the case where
there are no players in the **zone**", pick any other player and move them in.

`MatchState.eligible_challengers()` returns every defender in the ball's **zone**. That is a
choice, and it has two consequences worth confirming:

- If a defender is standing on the ball's exact space, must they be the challenger, or may
  the defence pick a different one from elsewhere in the zone and walk them over?
- **This is a live dead end:** when no defender is in the ball's zone at all,
  `eligible_challengers()` returns empty and the bot replies "The defending team has no
  player in the ball's zone to challenge", so the turn cannot proceed. The rules say the
  defender must instead choose one of their *other* players, move that token to the ball
  and take one exhaustion token per space travelled. The fallback is written but not
  implemented.

### B3. Who rolls in a score attempt?

"each player rolls a d12 ... while all defending players add their defensive skill (5+2+6 in
this case)". The worked example sums three defenders into one total, implying one defending
roll plus summed skills rather than one roll each. Not stated. Score attempts are the next
thing to build ("Shoot to score" currently answers "not implemented yet"), so this needs an
answer before that work starts.

### B4. The score threshold, and what "disadvantage" means

"If the attacker rolls a higher number that is equal or higher than the defense" is
self-contradictory. Presumably attacker total >= defender total, but ties decide goals so
it matters.

Separately, "disadvantage" appears in the own-goal rule ("Roll with offense skill,
disadvantage. Need 7+ to avoid") and in the injured-player rule, and is never defined. Roll
two d12 and take the lower? And does the offense skill add to or subtract from that roll --
a fullback is 1/6, so "roll with offense skill" makes the best defender the *worst* at
avoiding an own goal, which reads odd next to their ability being "no disadvantage on own
goal rolls".

### B5. "Conceding team" in the Score/Miss table

Appears to mean "the team defending that attempt" in both rows -- on a Score they restart at
their space 3, on a Miss they take the ball at their space 1 -- but on a miss nobody
concedes anything.

### B6. Halftime exhaustion recovery

Upstream still says "1 (or 2, TBD)".

### B7. Ball speed modifier scope

Stated as affecting "scoring and stealing attempts". Does it apply only to a Steal Intercept
clash, or to any clash where possession is contested? The unmerged maneuver code applies it
to Steal Intercept only.

### B8. Low Pass can now go backward

The new wording is "Ball moves 1-2 spaces **forward or backward**". A backward low pass
toward your own goal raises questions the text does not cover: can it reach your own goal,
and if so does the own-goal rule fire? Does it still increase ball speed by 1 when moving
backward?

---

## C. Divergences and gaps between code and the written rules

Not questions for the author so much as work items -- but each should be confirmed as "not
built yet" rather than "built wrong".

### C1. Kickoff space looks off by one

`MatchState.standard` places the ball at `Zone.MIDFIELD, space_index=min(1, len-1)`.

Home attacks left-to-right and low indices are home's end (the same convention the meeple
placement uses -- fullback at index 0). So the **back of the midfield for home is midfield
index 0**, and the code uses index 1.

On a 6-board that is the *front* of the midfield -- one space too far forward. On 7 and 9
(three midfield spaces) index 1 is the exact centre of the board, which is a defensible
"kickoff from the centre" reading.

Both upstream sources say back of the midfield: Notion ("space 3 of the home team", "home
team starts with the possession at the back of the midfield") and the `older Field` tab
("Back of the Midfield -- Kickoff from here at the start of the game"). So either the rule
changed for variable boards, or this is a bug. **Ask before changing it** -- the same
position is reused after a goal.

### C2. Ball speed modifier lives in the cog, untested

`main` has no speed modifier at all. The unmerged maneuver branch computes
`modifier = match.ball.speed // 2` inline in `cogs/d12ball.py`.

That formula is **correct** -- it reproduces all twelve rows of the rules table exactly. But
it is an undocumented magic expression in the Discord layer rather than a table in
`d12ball/`, and nothing tests it. If the table ever stops being integer division, this
silently diverges.

### C3. Exhaustion accumulates but does nothing

`add_exhaustion` sums tokens. There is no "exhausted" threshold (tokens > defensive skill),
no exhaustion check roll, no injured state, and nothing ever puts a player on the
`back_bench` even though the spreadsheet defines it as where injured players go.

### C4. Substitution has no policy

`MatchState.substitute` performs the swap but enforces none of the rules around it: once per
half, up to 2 out, opponent may then respond with 1, no re-entry except for injuries, half
the exhaustion tokens returned on re-entry.

### C5. Not built yet

Score attempts, clock advance, turnover, players-run-back, halftime, the last-possession
rule, and the extreme shootout. Maneuver *effects* are not mechanized either -- the bot
reveals the winner and asks them to apply the effect by hand.

---

## D. Project questions

- The **AI opponent** ("Dinky AI") now picks maneuvers by rolling a d6 and picks the closest
  challenger with defensive skill as tie-break. Is it meant to stay a dice-roller, or become
  a real opponent?
- `foolbot.py` still carries the original generic `/newdeck`, `/draw`, `/roll`, `/place`,
  `/move`, `/board` commands over a single global `game_state.json`, untouched by all of
  this. `/place` and `/move` take unbounded `(x, y)`, which is not the board's coordinate
  system. Keep as generic playtest helpers, or retire them?
- The 72-card "Foolish" deck (`SUITS`/`RANKS`, ranks `L` and `R`, a joker-glyph suit) in
  `foolbot.py` still belongs to no D12 Ball rule. Is it for another game in the setting?

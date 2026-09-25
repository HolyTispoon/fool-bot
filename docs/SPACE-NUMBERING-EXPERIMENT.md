# Experiment: flat left-to-right space numbering

**Status:** temporary experiment, on. Started 2026-09-23 on the branch
`space-numbering-experiment`.

**Nothing in this is a rule.** No rule was changed, no rulebook was
changed, and no saved game changed shape. The only thing that changed
is what the bot *calls* a space.

## What it does

The board's spaces were named by zone letter and position within the
zone. They are now numbered as one run from the home end:

| Board | Was | Now |
| --- | --- | --- |
| 7-space | `H1 H2 ǀ M1 M2 M3 ǀ V1 V2` | `1 2 ǀ 3 4 5 ǀ 6 7` |
| 9-space | `H1 H2 H3 ǀ M1 M2 M3 ǀ V1 V2 V3` | `1 2 3 ǀ 4 5 6 ǀ 7 8 9` |

It is the same ordering `BoardState.flat_index` already measures
distance along, one-based. Everything a coach reads follows it: the
board image, the coaching half-field image, every button and every
sentence, the tutorial's lessons, the web app, and the print-and-play
field strip. The zone *names* are untouched -- a space is still in
the Home Zone, midfield or the Visitors Zone, and the zone is still
spelled out beside the number wherever it was before ("**space 4**
(Midfield)").

## The switch

`FLAT_SPACE_NUMBERING` in
[d12ball/space_numbering.py](../d12ball/space_numbering.py). Set it to
`False` and restart the bot, and every space code goes back to the
letter form. Nothing else has to change for the bot to run.

Two readers ask it: `d12ball.formatting.space_label` (sentences and
buttons) and `d12ball.render.space_code` (the code drawn in a space's
corner). Both take the board, because a flat number has to count the
spaces in the zones to its left and the two board sizes differ there.

## Reverting

### The clean revert

Don't merge the branch, or `git revert` the commit
*"Number the board's spaces left to right, behind one switch"*. That
puts everything back, the goldens included.

### Flipping the switch in place

Set `FLAT_SPACE_NUMBERING = False` and restart. The bot is then
exactly as it was; the only loose end is that the four golden
transcripts were regenerated with the flat numbers in them, so
`tests/golden/` has to come back too:

```bash
git checkout main -- tests/golden
```

...or regenerate them:

```bash
FOOLBOT_UPDATE_GOLDEN=1 python3 -m unittest discover -s tests -p "test_golden_*.py"
```

With the switch off and the goldens restored, the suite passes exactly
as it does on `main` (the eight `test_d12ball_box_art` errors predate
this work and are unrelated).

### Taking the code out entirely

Everything below is the whole of the change, in the order it is
easiest to undo.

1. **Delete [d12ball/space_numbering.py](../d12ball/space_numbering.py)
   and [tests/space_codes.py](../tests/space_codes.py).**
2. **`d12ball/tutorial.py`** -- delete the block marked
   `TEMPORARY EXPERIMENT: flat space numbering` (it sits just after
   `SKIPPED`), and the imports it added: `re`, `Zone`,
   `space_label`, `FLAT_SPACE_NUMBERING`, `replace`. The lessons
   themselves were never edited -- they still say `M2`, and the block
   rewrites them as the module loads.
3. **`d12ball/formatting.py`** -- `space_label` goes back to its
   one-line body, and the `board` parameter comes off it,
   `travel_space_label` and `travel_space_phrase`, whose
   `FLAT_SPACE_NUMBERING` branches go. `ball_space_label` stops
   passing `match.board`. `capitalized` can stay (harmless on the
   letter form) or go with its five callers: `coaching.py`'s space
   button, `presentation.py`'s two image captions,
   `d12ball_helpers.space_choices` and the tutorial block. The High
   Pass note's comma (`high_pass_destination_note`) reads as well
   with a letter code and can stay.
4. **`d12ball/render.py`** -- the same for `space_code`; drop the
   `board` parameter `draw_coaching_space` gained and the
   `board=match.board` its caller passes; drop the `BoardState`
   import.
5. **`d12ball/boards.py`** -- the printed field strip stops passing
   `layout` to `space_code`.
6. **The call sites** -- 37 of them pass the board now, as a trailing
   `match.board` (or `asked.match.board` in `webapp/present.py`).
   They are in `d12ball/prompts.py`, `d12ball/engine.py`,
   `d12ball/flow/{arrivals,turnovers,windows}.py`,
   `cogs/d12ball_helpers.py`, `cogs/d12ball/{presentation,slash_commands}.py`,
   `cogs/d12ball_views/{effects,loose_ball,runback,coaching}.py` and
   `webapp/present.py`. `git diff main` finds every one.
7. **`cogs/d12ball/slash_commands.py`** -- the two `/d12ball debug`
   option descriptions say `e.g. 1` and said `e.g. H1`.
8. **The tests** -- four files name spaces through
   `tests/space_codes.py`'s `code`/`codes` instead of writing `"M2"`:
   `test_d12ball_formations.py`, `test_d12ball_high_pass.py`,
   `test_d12ball_dribble_advance.py`, `test_d12ball_team_roster.py`.
   They pass either way, so they can be left alone.
9. **`tests/golden/`** -- four transcripts, as above.

## What was deliberately left alone

- **The rules.** [docs/living-rules.md](living-rules.md),
  [docs/learn-to-play.md](learn-to-play.md) and
  [docs/rules-log.md](rules-log.md) are untouched, and so is every
  design note. They still name spaces `H1`/`M2`/`V1`. **If the
  experiment is kept, that is the work that follows it**, and it is a
  rules change with a dated rules-log entry, not this.
- **The rulebook figures.** `d12ball/rulebook_figures.py` positions
  its markers by parsing `"M2"`, which still works -- but the boards
  it crops are `render.py`'s, so a rulebook built while the
  experiment is on has flat numbers in its pictures and letter codes
  in its prose. Don't build a rulebook for distribution from this
  branch.
- **The save format.** Nothing persisted changed. A game saved with
  the experiment on loads with it off and the other way round; the
  model has always held positions as `(zone, space_index)` and the
  code was never anything but a label. The goldens' `*_final_match.json`
  files not moving when the transcripts did is the evidence.
- **The model's own vocabulary.** Docstrings, comments and variable
  names still talk about zones and space indices, because that is
  what the model still measures in.

## Things to look at while it is on

- **In text, a space is "space 4", never a bare "4"** (the author,
  2026-09-25). The images keep the bare number in each space's
  corner, where nothing else is a number; everywhere a space is
  *written* -- sentences, buttons, selects, image captions, the web
  app -- `space_label` returns "space 4". A bare number sat beside
  counts, distances, minutes and scores and could be read as any of
  them: "Ball is now 3, ... Time has advanced 1, now at 37",
  "2 spaces (4-Sizzifizik [PM])", "Advance 2 spaces (6)", "runs back
  to 3." (which read as a distance, on a move charged by the space).
  It is lowercase because it is mostly named mid-sentence;
  `formatting.capitalized` raises it where it opens a label or a
  caption, and the tutorial's `renumber_spaces` where it opens a
  sentence. The pieces that compose it with something else changed
  with it: a run back reads "Space 4 (2 away)" on the button and
  "space 4 (2 away)" in the sentence (`travel_space_label` /
  `travel_space_phrase`), a High Pass "2 spaces (space 4,
  Sizzifizik [PM])" (a comma where the hyphen was), and the
  tutorial's ranges "spaces 1-2" rather than "space 1-space 2".
- **Shooting range** is described as "space 5 and beyond" on the
  7-space board, which it reads better as than "M3 and beyond" did.

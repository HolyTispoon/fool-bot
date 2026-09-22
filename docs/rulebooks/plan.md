# The two rulebooks: a plan

D12 Ball's rules are going to be published as two books, on the model
Leder Games uses for Root: a **Learn to Play** that gets a table
playing in one sitting, and a **Law of the Game** that settles every
question the table can ask. This file is the plan for both. The two
outlines beside it -- [charter-outline.md](charter-outline.md) and
[learn-to-play-outline.md](learn-to-play-outline.md) -- are what the
books will contain, section by section, with the illustrations sketched
in [figures/](figures/). `scripts/build_rulebooks.py` turns the books
into PDFs for print.

**Nothing in this folder is a rule.** The rules are in
[docs/living-rules.md](../living-rules.md) until the Charter replaces
it, and then they are in the Charter. This plan is the worksheet the
books are built from, and it goes when they have shipped.

## The two books

| | The D12Ball Charter: Laws of the Game | Learn to Play |
| --- | --- | --- |
| Job | The ultimate source of truth. Every rule, once, settled. | Get a new table playing within fifteen minutes of opening the box. |
| Voice | Precise, exhaustive, impersonal. States what is true. | Warm, second person, one idea at a time. Teaches by playing. |
| Structure | Hierarchical. Numbered Laws, sections and paragraphs (`6.4.2`). Every cross-reference is a number. | Linear. A spread per idea, in the order a first game meets them. |
| Scope | Basic mode and advanced mode, both in full. | Basic mode only, with a two-page appendix that says what advanced mode adds and sends the reader to the Charter for it. |
| Pictures | Diagrams only where a table cannot say it: the field, the cycle, the shooting-range bands. | On every spread. Every rule in it is shown on a board before it is stated. |
| Length | Whatever the rules take. Today's living rules are about 30 letter pages set as prose. | Sixteen pages, hard limit. Root's is sixteen. |
| Precedence | The Charter wins over the Learn to Play, over the card text, over the printed boards, and over the bot. A bot that disagrees with the Charter has a bug. | Where it simplifies, it says so and names the Law. It never contradicts the Charter; it leaves things out. |

The one sentence that makes the pair work, and that both books carry
on their first page: **if the two books disagree, the Charter is
right, and the Learn to Play has left something out on purpose.**

## The Charter is the living rules, renumbered -- not a copy of them

`docs/living-rules.md` already is the Charter's first draft. It states
each rule once, settled, with history and open questions kept out in
the rules log, and it is organised under the headings the Charter's
Laws will carry. What it lacks is the numbering, a preface, a glossary
and a precedence rule.

So **the Charter replaces the living rules rather than sitting beside
them.** CLAUDE.md holds a hard rule that there is one copy of the rules
text anywhere in the bot: the two rules commands read
`docs/living-rules.md` itself. A second file that says the same thing
in numbered paragraphs is exactly the second copy that rule exists to
prevent, and the two would drift within a week. The proposal:

1. The Charter is written **in place**, as the next revision of the
   living rules file. It is renamed to `docs/charter.md` in the same
   commit, and `d12ball/rules_doc.py`, CLAUDE.md and every design doc
   that links `living-rules.md` are repointed. `/d12ball rules` and
   `/d12ball rules_lookup` then serve the Charter, numbers included.
2. `docs/rules-log.md` stays exactly what it is: every change, dated
   and sourced, plus what is still open. A rules change is still the
   Charter plus a dated log entry, as its own commit.
3. The Learn to Play is a **new** file, `docs/learn-to-play.md`. It is
   not a copy of the rules -- it is a lesson that cites them -- so the
   one-copy rule is not touched.

Both are markdown, because the bot reads one of them and GitHub renders
both, and the PDF is built *from* the markdown rather than being a
third place the words live.

## Numbering

The Charter's paragraphs are numbered the way the Law of Root's are:
**Law . section . paragraph**, with sub-paragraphs lettered where a
paragraph lists cases.

```
6       Maneuvers
6.4     The skill test
6.4.1   Both participants gain 1 exhaustion token, and then each rolls a d12.
6.4.2   The offense adds the handler's offensive skill and the defense adds ...
        a. A Midfielder adds 3 more when the maneuver being tested is ...
        b. A defense contesting with Steal or Intercept adds the ball speed modifier.
```

A cross-reference is a number in parentheses: *"... exactly as after an
out-of-bounds ball (10.5.2)."*

**How the numbers get onto the page is the decision to make.** The
builder does the first today; the second is the next thing it grows:

| | Numbered at build time (default today) | Numbers written into the source |
| --- | --- | --- |
| How | The builder numbers Laws from the H2 headings in order, sections from the H3s, and paragraphs from the blocks under them; a list under a numbered paragraph is lettered. Every `[text](#anchor)` link the living rules already carry becomes *text (6.4)* in the PDF. **Built.** | A `--renumber` mode rewrites the markdown itself: each paragraph starts with its bold number, and each link becomes a number. Anchors stay in the source as the stable identity a reference is resolved through, so inserting a paragraph is one edit and one `--renumber`. **Not built yet**; sized once the Charter's text has settled. |
| Where the numbers show | The PDF only. GitHub and Discord show the headings and the links, as now. | Everywhere, including `/d12ball rules_lookup`. |
| Cost | None. The file the bot reads does not change. | A one-time reformat of the whole file, and a `--renumber` after every insertion (the test suite can check it has been run). |

**Recommendation: build-time numbering for the first printing, and the
source numbering once the Charter's text has settled.** The first pass
through the Charter will move paragraphs around, and numbers in the
source would be renumbered on every commit while it does. When the
paragraphs stop moving, write the numbers in and they become part of
the text the author edits and the bot serves. This is the one decision
in this plan that changes the source file, so it is called out.

## Writing the Charter

The pass from the living rules to the Charter is an edit, not a rewrite.
The conventions:

- **One rule per paragraph.** A paragraph that says two things is two
  paragraphs, because a reference has to be able to point at either.
  The living rules' long paragraphs on the High Pass overshoot and on
  Mind Pull are the ones that split most.
- **The paragraph states the rule; the reason goes.** Several living-rules
  paragraphs end with why (*"-- a ball that came in too fast to
  settle"*). In the Charter the reason is either cut or kept as a
  one-line *Note* under the paragraph, set apart and never numbered, so
  a note can never be cited as a rule.
- **Defined terms are bold at their definition and nowhere else**, and
  every one is in the glossary with its paragraph number. Law 2
  gathers the definitions the living rules keep under "Words these
  rules use", and adds the ones defined in passing today: *challenger*,
  *interceptor*, *carrier*, *loose*, *behind*.
- **Every cross-reference is a link in the source**, as now, so it
  resolves to a number. A rule that cites another by name and not by
  link is a rule the builder cannot number.
- **Tables stay tables.** The cycle, the boards, the roles, the
  formations, the set-ups, the tokens and the clock costs are all better
  as tables and are already tables.
- **Advanced mode is Part II.** Laws 1-17 are the whole of basic mode
  and never mention a gambit or a species. Part II opens with the one
  Law that says what advanced mode switches on, then the gambits, then
  the species. Everywhere basic mode has an exception in advanced
  mode (the Cyborg's threshold, the Dribble Burst's speed), the basic
  Law states the basic rule and Part II states the exception -- not the
  other way round, which is how the living rules read today in three
  places.
- **What is still open stays out**, in the rules log. The three
  role-ability contradictions on the gambit cards and the injury
  substitution question are the rules log's, not the Charter's. The
  Charter states what is played.

The full section map, with the living-rules heading each Law comes from,
is in [charter-outline.md](charter-outline.md).

## Writing the Learn to Play

Root's Learn to Play works because it refuses to be complete. The
principles this one is written to:

- **Basic mode, and nothing else.** No gambit, no species, no "in
  advanced mode ...". The appendix is two pages and is the only place
  the words appear.
- **Teach by playing.** The middle of the book is *your first five
  turns*: the same five-turn opening the bot's tutorial plays, from the
  standard deal, with the board shown after every turn. The reader sets
  the board up from Figure 1 and plays along. Both teaching tools then
  teach the same game in the same order -- and where the bot's script
  changes, the book changes with it. (The bot's tutorial text in
  `d12ball/tutorial.py` is the first draft of that chapter's prose.)
- **A picture before every rule.** Nothing is stated that the reader
  has not just seen on a board. The figures are built off the bot's
  own renderer for that reason: a picture that shows a position the
  game cannot reach is worse than no picture.
- **Every rule cites its Law**, in the margin: *Law 6.4*. The citation
  is how the reader finds out there is more, and how the two books stay
  honest with each other. A Learn to Play sentence that cannot be
  matched to a Charter paragraph is either a mistake or a Charter gap,
  and the citation pass will find both.
- **Say what the position is.** CLAUDE.md's wording rules for every
  message the bot posts hold for the book too: what a position is,
  never what it is not; a move that costs nothing says nothing. The
  only exception is the one exception Root also makes -- *"You cannot
  shoot from here"* is worth saying once, on the page that introduces
  shooting range.
- **Sixteen pages, letter, saddle-stitched.** Eight spreads. A spread
  is one idea and one or two figures. If it does not fit, it is cut,
  not shrunk.

The page-by-page outline is in
[learn-to-play-outline.md](learn-to-play-outline.md).

## The illustrations

Fifteen figures are sketched in [figures/](figures/) and shown in place
in the Learn to Play outline. They are for approving *what each picture
shows*: the position, the arrows, the notes. They are not the final
art.

**How they were made.** Every board in a figure is a real `MatchState`
rendered by `render.render_field_image` -- the same function that draws
the field in Discord -- with arrows and numbered markers added above it
and the numbered notes below (`d12ball/rulebook_figures.py`). The cycle,
the cards and the coaching image are the bot's own images unchanged.
Nothing in the figures draws a space or a meeple itself.

**The five walkthrough boards are set by hand from the tutorial's
script**, moving each meeple to where the lesson text says it ends up.
That is accurate enough to approve the pictures on and not enough to
print: the final figures should be **captured from the golden
playthrough** (`tests/test_golden_transcript.py` already plays the
whole opening through the real cog with pinned dice), snapshotting the
match after each beat. Then a picture in the book cannot disagree with
the game, and a change to the script regenerates the chapter's figures.
That is a small addition to the script, sized once the sketches are
approved.

**What still needs an artist**, because the renderer has no picture of
it: the cover; the components spread (the printed boards, the cards,
the tokens and the d12 as objects on a table); the six role cards shown
as a fan; two coaches revealing cards at once; the own-goal moment; the
halftime and shootout page. Each is listed in the Learn to Play outline
with what it must show. The figures that come off the renderer can stay
renderer output in the final book if the author wants the book to look
like the bot, or be redrawn by the artist over the same positions.

**The Charter's own figures** are three: the field with its zones,
shooting ranges and kickoff spaces for both boards; the cycle; and
the standard deal on board 9, which is the only board where the deal is
not obvious. All three come off the renderer today.

## Production

`scripts/build_rulebooks.py` builds both books:

```bash
python3 scripts/build_rulebooks.py                 # both books -> print/
python3 scripts/build_rulebooks.py charter --paper a4
python3 scripts/build_rulebooks.py --figures       # regenerate docs/rulebooks/figures/
python3 scripts/build_rulebooks.py --outlines      # the two outlines as PDFs, for review
```

- **Markdown in, PDF out.** The layout lives in `d12ball/rulebooks.py`
  and the script is the CLI, the same split `boards.py` and
  `render_boards.py` make. It reads the subset of markdown the two
  books use -- headings, paragraphs, bold and italic, bullet and
  numbered lists, tables, images with captions, and an explicit page
  break -- and refuses anything else loudly rather than dropping it.
- **reportlab** does the typesetting; it is the one new dependency
  (`requirements.txt`). A rulebook is thirty pages of running text with
  tables, page numbers and a contents page, and Pillow -- which draws
  every board and card -- has no notion of a paragraph. Every other
  route (HTML through a browser, LibreOffice) needs a program the two
  bot hosts do not have.
- **The bundled fonts, by absolute path**, as everywhere else: DejaVu
  for the text and Racing Sans One for the titles, so the books, the
  boards and the cards are one family.
- **The cards' palette.** Ink on cream, the cards' `INK` and
  `FACE_COLOR`, with the cards' offense red and defense green for the
  two sides wherever the books colour a maneuver.
- **Letter by default, A4 by flag.** Both books are one paper size; the
  Learn to Play is imposed as a saddle-stitched booklet at the print
  shop rather than by the script. No bleed: nothing in either book
  reaches the edge.
- **`print/` is the output folder**, gitignored, as it is for the boards.
  The figures are the exception: `docs/rulebooks/figures/` is committed,
  regenerated whole by `--figures` and never edited by hand, so the
  outlines and later the books show them on GitHub.

## Order of work

| Milestone | What lands | Reviewed by |
| --- | --- | --- |
| **1. Landed** | The plan, both outlines, fifteen figure sketches, the build script proven on the outlines. | Reading the outlines; approving or redlining each figure. |
| **2. Landed** | The living rules restructured into the Charter **in place** -- the file keeps its name, `docs/living-rules.md`, so nothing that reads it moved (see below) -- with the preface, Law 2's definitions, the Part II exceptions table and the four appendices; the builder producing the Charter PDF with build-time numbers, 40 letter pages. | Inline comments on the PR, paragraph by paragraph -- the way rules questions have been settled so far. |
| **3. Landed, one step open** | `docs/learn-to-play.md`, 18 letter pages today against the sixteen the book is cut to, every rule with its Law citation. **Still open:** the walkthrough figures captured from the golden playthrough rather than set by hand. | A read-through, then two people who have never played playing from it. |
| 4. Art | The artist's pieces from the list in the outline; the renderer figures redrawn or kept. | Proofs. |
| 5. Print proof | Both PDFs at the print shop; the numbers written into the Charter's source once the text has stopped moving. | Holding the books. |

Milestones 2 and 3 can run in parallel once the outlines are approved;
3 needs 2's numbers for its citations before it ships, not before it
starts.

## Decisions to approve

1. **The Charter replaces `living-rules.md`** rather than being a second
   file. *Done in place:* the Charter is `docs/living-rules.md` under its
   old name, because a rename would have touched `rules_doc.py`, CLAUDE.md
   and every design doc that links the file for no gain a reader can see.
   The rename to `docs/charter.md` is one `git mv` and a link sweep, for
   whenever the author wants the filename to match the title.
2. **Numbering: build-time now, written into the source once the text
   settles.** Or written in from the start.
3. **The Charter's section map** in [charter-outline.md](charter-outline.md)
   -- in particular Part II holding every advanced-mode exception, and
   Law 2 gathering every definition.
4. **The Learn to Play's sixteen pages** in
   [learn-to-play-outline.md](learn-to-play-outline.md), and that its
   walkthrough is the bot's tutorial opening.
5. **Each of the fifteen sketches**: what it shows, or what it should
   show instead.
6. **The artist list** -- which figures are drawn by hand and which
   stay renderer output.
7. **Letter paper, reportlab as the one new dependency.**

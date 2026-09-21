# The two rulebooks

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## The two rulebooks

D12 Ball's rules are being published as two books on the Root model: a
short, illustrated **Learn to Play** and **The D12Ball Charter: Laws of
the Game**, the numbered, exhaustive source of truth. The plan, the two
outlines and the illustration sketches are in
[docs/rulebooks/](../rulebooks/) -- **nothing in that folder is a
rule**, and it goes when the books have shipped. This file is about the
code that builds them.

- **The Charter is the living rules, restructured in place -- not a
  second file.** CLAUDE.md's hard rule that there is one copy of the
  rules text stands: `docs/living-rules.md` *is* the Charter, under its
  old filename, so the bot's rules commands and the printed book read one
  file and nothing that linked it moved. `BOOKS["charter"]` prefers
  `docs/charter.md` if it ever exists and falls back to the living rules,
  so the rename is one `git mv` whenever the author wants it. `BOOKS`
  names every source a book may have, first one found wins.
- **The Charter's structure is load-bearing for the numbers.** Every
  level-2 heading that is not front matter, a Part or an Appendix is a
  Law, in file order; every level-3 heading under it a section. The
  Learn to Play cites those numbers and `test_rulebooks.py` pins the ones
  it cites, so inserting a Law or a section fails the suite until the
  citations are looked at. Two headings with one slug fail
  `test_d12ball_rules_lookup.py` (the anchor test), which is why the
  sections are named `The own-goal roll` and `What a send costs` rather
  than `The roll` twice.
- **A level-2 heading is unnumbered when it is front matter
  (`FRONT_MATTER_SECTIONS`), or begins `Part ` or `Appendix `**
  (`UNNUMBERED_PREFIXES`); its blocks carry no numbers either, and an
  Appendix resolves in a cross-reference as `(Appendix A)`. A paragraph
  opening `*Note` is never numbered and is set small and indented: the
  Charter's preface says a note is never a rule, and the layout is what
  makes that visible.
- **Numbering is done at build time and the source is not touched.**
  `number_blocks` gives every level-2 heading a Law number, every
  level-3 heading a section number, and every paragraph, list, table or
  quote under one its own number; a paragraph straight under a Law
  shares the second position with the sections (`1.3`, then `2.1 The
  field`), as the Law of Root does. A `[text](#slug)` link to a heading
  becomes `text (6.4)`; a list under a numbered paragraph is lettered so
  a case can be cited. A source section whose slug is in
  `UNNUMBERED_SECTIONS` (the living rules' own "Contents") is dropped,
  because the builder generates the contents page. Writing the numbers
  into the markdown (`--renumber`) is the plan's second step and is not
  built.
- **The Learn to Play is `docs/learn-to-play.md`**, unnumbered, one
  page break (before the appendix) and figures at the text width. It
  cites the Charter inline as *(Law 6.4)*; it is not a copy of any rule.
  It builds to 18 letter pages against the sixteen the plan cuts it to;
  the cover and the artist's pieces are what the last two pages are
  waiting on.
- **`d12ball/rulebooks.py` holds the layout and `scripts/build_rulebooks.py`
  is the CLI**, the split `boards.py` / `render_boards.py` makes. It is
  under `d12ball/` and so under the purity ratchet: no discord, no
  async. It reads a fixed markdown subset -- headings, paragraphs, bold,
  italic, inline code, links, nested bullet and numbered lists, tables
  with alignment, images with a caption, `>` quotes, fenced code, and
  `---` alone on a line as a page break -- and raises `MarkdownError`
  on anything else rather than dropping it. HTML is refused outright.
  `test_rulebooks.py` parses the living rules and every file in
  `docs/rulebooks/` so a line outside the subset fails the suite, not
  the print run.
- **reportlab is the one new dependency**, pinned in `requirements.txt`.
  A rulebook is running text with tables, a contents page and page
  numbers; Pillow has no paragraph, and every other route needs a
  program neither bot host has. It is used only here.
- **The bundled fonts, by absolute path**: DejaVu for text, Racing Sans
  One (`Display`) for the title and the Law headings -- the boards' and
  cards' family. No oblique face is bundled, so `<i>` falls back to the
  regular face; adding `DejaVuSans-Oblique.ttf` under the licence already
  in `d12ball/fonts/` is the fix. The palette is the cards' (`INK`,
  `FACE_COLOR`, `PANEL_COLOR`).
- **Letter by default, A4 by `--paper`; no bleed.** Nothing in either
  book reaches the edge, and the Learn to Play is imposed as a booklet
  by the print shop, not the script. Output goes to `print/`, which is
  gitignored like the boards'.
- **The figures are the bot's own renderer, annotated.**
  `d12ball/rulebook_figures.py` builds a real `MatchState` for every
  board in a figure and renders it with `render.render_field_image`;
  arrows and numbered markers go in a band above the field and the
  numbered notes below (`Sketch`). The cycle, the cards and the coaching
  image are the bot's images unchanged. Nothing there draws a space or
  a meeple, so a figure cannot show a position the game cannot reach
  and cannot drift from the board a coach sees. `space_centre_x` reads
  `render.zone_bounds` rather than guessing the geometry.
- **The walkthrough positions are set by hand from the tutorial's
  script** (`walkthrough_positions`), which is a sketch's accuracy. The
  plan's next step captures them from the golden playthrough instead,
  so a change to `d12ball/tutorial.py` regenerates the chapter.
- **`docs/rulebooks/figures/` is committed and regenerated whole** by
  `--figures`, never edited by hand -- like `d12ball/data/`. `FIGURES` is
  the registry of stems, and the suite holds the folder's listing to it
  and every image an outline references to a file, so a renamed figure
  or a stale file fails a test rather than printing a broken page.

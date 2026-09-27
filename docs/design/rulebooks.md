# The two rulebooks

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## The two rulebooks

D12 Ball's rules are being published as two books on the Root model: a
short, illustrated **Learn to Play** and **The D12Ball Charter: Laws of
the Game**, the numbered, exhaustive source of truth. The plan, the two
outlines and the illustration sketches are in
[docs/rulebooks/](../rulebooks/) -- **nothing in that folder is a
rule**, and it goes when the books have shipped. This file is about the
code that builds them. The books and their figures carry no tests -- the
print materials have none (the author, 2026-09-23) -- so a build is
checked by reading the PDF.

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
  Learn to Play cites those numbers, so inserting a Law or a section means
  looking at every citation after it. Two headings with one slug fail
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
- **The builder numbers; the source carries what it numbered.**
  `number_blocks` gives every level-2 heading a Law number, every
  level-3 heading a section number, and every paragraph, list, table or
  quote under one its own number; a paragraph straight under a Law
  shares the second position with the sections (`1.3`, then `2.1 The
  field`), as the Law of Root does. A `[text](#slug)` link to a heading
  becomes `text (6.4)` -- unless its words already are the number
  (`[Law 18]`, `[Appendix B]`), which `cites_itself` leaves alone
  rather than printing `Law 18 (18)`. **A list or table straight after
  a numbered paragraph is that paragraph's** (the author, 2026-09-26)
  and takes no number of its own (`Numbering.cases`): a list's items
  are the paragraph's cases, lettered, so 6.4.2 "On top of that:" is
  followed by 6.4.2a and 6.4.2b, as the Charter's preface says and the
  Law of Root does. One straight after a heading has no paragraph to
  belong to and is numbered, on a line of its own; a list there is
  lettered under its own number. A source section whose slug is in
  `DROPPED_SECTIONS` (the living rules' own "Contents") is dropped,
  because the builder generates the contents page.
- **`--renumber` writes those numbers into the source** (the author,
  2026-09-26: the file carries the printed edition's numbers), so
  GitHub, `/d12ball rules_search` and the web page read the numbers
  the book prints. `renumber` writes `## 6. Maneuvers`, `### 6.4 The
  skill test`, a paragraph opening `**6.4.2**`, a paragraph's cases
  straight under it as `- **a.**`, a list or table under a heading
  under its own number on a line of its own, and a cross-reference as
  the link followed by its number, `[the skill
  test](#64-the-skill-test) (6.4)`. `unnumber` takes all of it out
  again, and **the book is built from `unnumber`'s text**, so the
  numbering logic stays in one place and a stale number in the file
  never reaches a page; the two are inverses on a renumbered file,
  which `tests/test_charter_numbers.py` checks -- the suite fails until
  `--renumber` has been run after an edit that moves a number. That
  test is not a print test: it guards the file the bot serves.
- **A numbered heading's GitHub anchor moves with its number**
  (`#64-the-skill-test`), because GitHub slugs the heading as written
  and markdown has no fixed anchor without HTML, which the subset
  refuses. So the links carry the anchor as written and `renumber`
  rewrites them; `--renumber` also moves every `living-rules.md#...`
  link in `docs/` and CLAUDE.md through `anchor_moves`. The stable name
  a section is known by inside the bot is the slug of its title without
  the number: `rules_doc` splits the number off (`split_heading_number`)
  into `RulesSection.number`, keeps `slug` numberless and puts GitHub's
  anchor on `anchor`, so an autocomplete value, a page's `#the-skill-test`
  and every test that names a section survive a renumbering. `find`
  also takes a number, so `/d12ball rules_search 6.4` answers.
- **The Learn to Play is `docs/learn-to-play.md`**, unnumbered, one
  page break (before the appendix) and figures at the text width. It
  cites the Charter inline as *(Law 6.4)*; it is not a copy of any rule.
  It builds to 19 letter pages with its cover against the sixteen the
  plan cuts it to; the artist's pieces are what the rest are waiting on.
- **Both books open on a cover** (the author, on the landing pages'
  canvas, 2026-09-27): cream paper, a gold band at the head, the title
  in Racing Sans One broken where the author broke it, a gold rule, the
  lines under it, the box's d12 low right, the publisher at the foot.
  The words are the book's `Cover` in `BOOKS`, and the layout is
  `cover_layout`, in shares of the page, so the PDF's first page
  (`draw_cover`, its own page template with no footer) and the picture
  of it on the d12ball landing page (`landing/covers.py`, in Pillow)
  are the same cover at any size. A book with a cover drops its title
  line from the page after it, which opens on the edition line; the
  outlines have no cover and keep theirs. The gold is the jumbotron's,
  used only as a band and a rule -- `box_art` says why it is never text
  on paper.
- **`d12ball/rulebooks.py` holds the layout and `scripts/build_rulebooks.py`
  is the CLI**, the split `boards.py` / `render_boards.py` makes. It is
  under `d12ball/` and so under the purity ratchet: no discord, no
  async. It reads a fixed markdown subset -- headings, paragraphs, bold,
  italic, inline code, links, nested bullet and numbered lists, tables
  with alignment, images with a caption, `>` quotes, fenced code, and
  `---` alone on a line as a page break -- and raises `MarkdownError`
  on anything else rather than dropping it, so a line outside the subset
  fails the build loudly rather than printing wrong. HTML is refused
  outright.
- **reportlab is the one new dependency**, pinned in `requirements.txt`.
  A rulebook is running text with tables, a contents page and page
  numbers; Pillow has no paragraph, and every other route needs a
  program neither bot host has. It is used only here.
- **The bundled fonts, by absolute path**: Roboto Slab for text (DejaVu
  until 2026-09-27; see "Fonts" in board-image.md), Racing Sans One
  (`Display`) for the title and the Law headings -- the boards' and cards'
  family. No italic face is bundled and Roboto Slab has none, so `<i>`
  falls back to the regular face; emphasis would need a second family. The palette is the cards' (`INK`,
  `FACE_COLOR`, `PANEL_COLOR`).
- **A book is bytes first.** `book_bytes` sets a book into memory and
  `build_book` writes those bytes. The web app served that PDF until
  step 10 of [../web-app-redesign.md](../web-app-redesign.md), when the
  author's "no PDF anywhere" put both books in the page instead
  ([web-app.md](web-app.md), "The rules and the player aids"): the
  Learn to Play read by `parse_markdown`, the books' own subset, with
  its figures, and the Charter's numbers read from the file, where
  `renumber` wrote them, rather than numbered by the page.
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
  the registry of stems; the folder's listing should match it and every
  image an outline references should be a file in it, or a renamed figure
  or a stale file prints a broken page.

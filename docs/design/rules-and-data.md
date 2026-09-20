# The rules, and the data they come from

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## The rules

**Read [docs/living-rules.md](../living-rules.md) before changing anything that models the
game.** It is the whole ruleset as it currently stands and the single thing to check a
mechanic against: it states each rule once, settled, with no history and no upstream
wording to reconcile.

The rules themselves live in two upstream places, neither complete on its own, plus a third
body that has only ever existed in the author's head:

- a [Notion page](https://propheticfools.notion.site/D12-Ball-6c9e1ea7ca61825391e881ec5fbfdca5)
  for the narrative rules. It is a JS app, so a plain fetch returns an empty shell -- render
  it in a browser to read it.
- a [Google Sheet](https://docs.google.com/spreadsheets/d/1PKPpTseisPmM-tH6PMLbtsrYsZ_zG8smluP5VmHKcMw)
  for component data. The share URL is not fetchable but `export?format=csv&gid=<gid>` is,
  which is how `scripts/import_d12ball_players.py` works.
  **Don't guess a gid -- run the import script, or read its `DEFAULT_SOURCE`.** The workbook
  keeps its old tabs: `gid=0` is the pre-reshuffle player table, still there and still
  answering, with nine-of-one-species rosters and the retired `{colour}_{name}` ids. Fetching
  it by hand and reading it as current is a mistake that has been made; the live tab is
  "Player Cards" (`gid=6660238`), and the scripts already point at the right ones.

**Every ability is imported twice**, in full and abbreviated -- `ability` and `ability_short` on
each role profile in `players.json`, from the `basic_abilities` sheet's own two columns. Text
that shows an ability on its own (the roster, the rules listing) uses the sentence;
anything captioning a portrait with it uses `RoleProfile.short_ability`, which falls back to
the sentence when there is no short form. **Don't shorten an ability in code.** Which half of a
two-part ability survives is a rules judgement, so the author makes it upstream and the import
carries it. Two quirks of that sheet are handled in the script and covered by
`tests/test_d12ball_player_import.py`: the column is spelled `Abbreivated` and stored with a
trailing space, and a cell beginning `+3` may be typed with a leading backtick so the
spreadsheet doesn't read it as a formula.

**The escape is on sentences as well as abbreviations, and not predictably.** It was stripped
from the abbreviated column alone -- which is where the `+3`s were first noticed -- and the
Striker's *sentence* starts `+3` too, so it shipped in `players.json` as
`` "`+3 for scoring off a set up." `` and printed with the backtick on the maneuver card, the
roster and the rules listing. Whether a given cell carries the guard is the spreadsheet's
business: the Midfielder's sentence also starts `+3` and is stored without one. So
`strip_formula_escape` is applied to **every** ability column, and
`test_no_shipped_ability_carries_a_formula_escape` asks the shipped catalog rather than the
importer -- the importer was only half wrong, so every test about it passed.

[docs/rules-log.md](../rules-log.md) is the other half: every rules change with its date and
where it came from, what is still unanswered, and what the answers unblock. Two parts of it
earn their keep when upstream moves:

- **Where upstream is behind** lists every point at which the living rules already differ from
  Notion or the sheet, so a fresh pull can tell old news from a real change.
- The **change log** is the running record. The rules are a live prototype and move: when they
  do, update the living rules and add a dated entry as its own commit, so each rules change
  stays a reviewable diff.

[docs/gambit-matrix.md](../gambit-matrix.md) is a third document and a
different kind of thing: the **worksheet advanced mode was built from**, cut back to what is
still open. It was a table of every gambit against every maneuver it could meet,
with each assumption named and each undecided cell marked; the author answered, the six cards
went into the living rules on 2026-08-19, and **the answered parts were deleted rather than
kept in parallel** -- which is what happens to a worksheet, and the reason a settled rule has
exactly one home. **Nothing left in it is a rule.** What it still holds is the player
abilities that have no data yet, one cell that may be inert, two judgement calls the build
made, and the map of where advanced mode touches the code. Don't read it as a specification,
and don't implement from it.

**Take rules questions to the author rather than inferring them from the code** -- several
mechanics exist only in the code, so there a bug and a deliberate decision look identical.
Asking as inline comments on a docs PR has worked far better than asking in chat, and it
leaves the answers versioned.

### Serving the rules in Discord

`/d12ball rules_full` posts the living rules in a thread and `/d12ball rules_search`
posts one section of them. Both read `docs/living-rules.md` itself, through
`d12ball/rules_doc.py` -- **there is no second copy of the rules text in the bot**, so a
rules change reaches the commands in the commit that makes it, and cannot be half-applied.

- **The parse is cached against the file's timestamp**, so an edited ruleset is served
  without restarting the bot -- the opposite of the fonts, which are resolved at import
  (see "Fonts" in [board-image.md](board-image.md)). It is re-read on every autocomplete keystroke otherwise.
- **A section carries its subsections.** Asking about "Maneuver" means the four steps as
  well, so `RulesSection.text` is the whole subtree; `label` is the heading path
  (`Maneuver › 3. Who wins`) and `slug` is GitHub's own anchor, which is what the
  document's internal links already use.
- **The autocomplete searches the body as well as the headings**, because a coach knows
  the rule and not what it is filed under -- "scissors" has to find "3. Who wins". Headings
  match first, then bodies, deepest first, since the subsection is the more specific answer
  to the same question.
- **A coach can submit text that was never offered**, so `best_match` is what the command
  asks rather than `find`. It answers when the words can only mean one thing: they name a
  heading, or every section mentioning them is on one branch -- a subsection and the parents
  carrying its text, which are the same rule read at different depths. Anything wider comes
  back as a list of headings, because it is a choice and not an answer.
- **Discord renders neither anchors nor tables.** `[text](#anchor)` shows as its raw
  brackets, so `for_discord` drops the syntax and keeps the words; tables are left alone,
  because the alternative is restating the rules in a second form and that is exactly what
  this avoids.
- **`chunk_for_discord` breaks at blank lines and starts a message at every `##`.** A chunk
  boundary is a visible seam in the channel, and a heading is where a seam belongs; a table
  split down the middle renders as neither a table nor prose.
- **The full rules are around forty messages, which is why they go in a thread.** A thread
  has its own channel id, so those sends are a rate-limit bucket of their own rather than
  the game channel's -- see "Discord's rate limits" in [rate-limits.md](rate-limits.md). Run inside a thread already, the
  command posts there instead, since threads do not nest.

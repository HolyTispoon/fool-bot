# The two landing pages: `d12ball.com` and `propheticfoolsgames.com`

**This is a worksheet, not a specification.** It was written on
2026-09-26 from the author's ask -- a landing page for D12 Ball on
`d12ball.com`, and one for the studio on `propheticfoolsgames.com`,
which for now has two games: D12 Ball and the Prophetic Folly RPG
system, which lives on the studio's Notion site -- against what the
repository already has (the box art, the sale sheet, the rulebooks,
the web app's tunnel plan) and what the Notion site already says.
Each step below has a prompt a Claude Code session is started with.
Strike a step when it lands and move what it settled into
`docs/design/landing-pages.md`, the design note the first step
creates. **Nothing in it is a rule.**

The sketch the author reviewed is the canvas at
<https://claude.ai/artifact/FRg1ACEjVcHj6k6mRkTQsh>: both pages at
desktop and phone width, every picture on them the repository's own
render, the open questions marked in brackets.

Both domains are on Cloudflare, bought the same way (the author,
2026-09-26). The web app's tunnel plan in
[collaboration.md](design/collaboration.md), "Exposing the port",
has not yet been run on the `K:\` host; nothing here waits on it.

## What was found, and what it settles

**Where the game's public face was going to go.** `play.d12ball.com`
is the web app's hostname, and the bare `d12ball.com` was left free
on purpose "for whatever the game's public face turns out to be"
(collaboration.md, 2026-09-26). This is that. The app keeps `play.`;
the landing page takes the bare domain and `www.` redirects to it.

**What the sale sheet already sends people to.** `d12ball/box_art.py`
holds two addresses: `PAGE_URL`, the D12 Ball page on
`propheticfools.notion.site`, which the sale sheet's QR points at, and
`SURVEY_URL`, the Notion survey the playtest card's QR points at. Both
are addresses the author does not control the shape of, printed on
card. The landing page is where `PAGE_URL` should point once it is
up, and `d12ball.com/survey` -- a redirect the site owns -- is what
the playtest card should carry, so the survey can move without
reprinting a card. That change to `box_art.py` is its own commit,
because it changes what gets printed (step 5).

**What the box already knows, the page reuses.** The box art's
principle is that every claim on it is read from the game and every
quoted rule is the books' own, word for word
([box-and-sale-sheet.md](design/box-and-sale-sheet.md)). The landing
page inherits both. Its numbers -- two coaches, `DEFAULT_CLAIMS`'s
30-45 minutes and ages 10+ (the author's, 2026-09-23), the count of
teams, species and maneuvers -- come from the same functions the
sale sheet reads. Its one line of voice is `STRAPLINE`. Its pictures
are `render_box_art.py`'s: the night banner (3000 x 1200, "for a
Notion page" today; for this page tomorrow), the night cover, and
the board, cards and species icons the bot itself draws. **The page
never words a rule for itself**; where it shows how a turn goes it
quotes the Charter and cites the Law, as the sale sheet does.

**The night palette, because a page is a screen.** Everything printed
is white (a press run nobody wants to pay for); the night cover and
the banners exist because "a banner is read on a screen". The two
sites are dark, in the banner's palette, and the team colours come
from `TEAM_COLORS` and nowhere else.

**What the studio's Notion site already says.** The studio page's
paragraph -- "Prophetic Fools is a tabletop gaming studio creating
meaningful and engaging play experiences..." -- is the studio's own
voice and goes on `propheticfoolsgames.com` as written, not reworded.
Its Games database lists two: D12 Ball (stage: Early development;
its Notion page's overview line is "a fast playing fantasy sports
game with tense last-ditch efforts and dramatic comebacks...") and
Prophetic Folly (stage: Playtesting; its callout: "A streamlined
tabletop roleplaying system, providing a robust mechanics for action
resolution with lots of flexibility for narrative driven
interactions"; its subpages: Resolution Roll Sheet, Fool's guide,
Epic fantasy World; the mechanic: 2d12, Fortune and Doom). The
studio page's game cards carry those sentences, the author's, and
link out: D12 Ball to `d12ball.com`, Prophetic Folly to its Notion
page. **The Folly page is headed "DRAFT - DO NOT CIRCULATE OR CITE
WITHOUT PERMISSION."** Linking a public site to it is circulating
it. The card is built either way; whether it links, or says "in
closed playtesting" and offers a contact, is a question for the
author (below) and the prompt for step 4 builds the gated version
until answered.

## What the canvas review changed (2026-09-27)

The author reviewed the sketch on the canvas over the evening of
2026-09-26 and the morning after, in comment threads answered as they
came; each is resolved on the canvas with what was done. What they
settled, so the steps below build it rather than the first draft:

- **The copy is the author's.** The three beats of "How a turn goes",
  the four species lines, the section headings, the playtest panel and
  the card texts were written on the canvas in the author's voice and
  are reproduced in step 2 word for word. The first draft quoted the
  Charter; the page now quotes nothing, and the verbatim test guards
  only a `<blockquote data-law>` a later edit might add.
- **The board is the web app's.** Not the sale sheet's printed board
  and not the bot's PNG: a headless-Chrome capture of a room page's
  board panel, the way play.d12ball.com draws it. Taking it turned up
  a web app bug -- a space clipped the badges of a piece at its edge --
  fixed in PR #358 and re-captured.
- **Ways to play is three cards**: the browser, the print-and-play kit,
  and the rulebooks as two cover images with only their titles.
  Screentop is off the page; Discord is not a way to play but an icon,
  in the footer and beside the playtest panel's contact line, carrying
  the invite https://discord.gg/MpgGm8FvKB.
- **The rulebooks get covers.** The built PDFs open on their first text
  page, which does not read as a book at thumbnail size; the author
  gave each cover its line (step 3).
- **The contact is politicsgames@gmail.com**, on both sites.
- **Prophetic Folly is "In development"** with playtest access on
  request at the studio address, and -- the author's second thought,
  on this PR -- a link to its Notion page after all. Its
  picture is one composed still: two d12s rendered as solids, bone
  Fortune showing 12 and obsidian Doom showing 1, with the bot's six
  coins gathered round them, fortune faces on Fortune's side and doom
  faces on Doom's. The renderer written for it is
  `scripts/render_landing_dice.py`, which step 4 moves under
  `landing/`.
- **The player cards follow `player_cards.py`**: PR #356 changed the
  face while the sketch was open and the sketch was re-rendered from
  main; the build renders them, so the page follows every merge.
- **Typos fixed in the author's copy on the canvas, nothing reworded**:
  "DIdn't", "secrets picks", "The maneuvers related", "around each",
  "for most of the games".

## The decisions

These are the ones the plan is built on. Each is the recommendation
and its reason; the author overrules any of them by saying so on the
PR, and the step's prompt is rewritten rather than argued with.

1. **Static pages on Cloudflare Pages, not through the tunnel.** The
   author's instinct was the tunnel, since the domain was bought the
   same way. The domain part is indeed the same -- the site has to be
   Active on Cloudflare, and that is all the tunnel setup shares with
   this. But the tunnel exists to reach a process that has to run on
   the PC (the game lives in it); a landing page is files, and a
   page that goes dark when the PC sleeps, the `K:\` drive is not
   mounted, or `cloudflared` is being reinstalled is a poor public
   face. Cloudflare Pages is on the same account and the same
   dashboard, free at this size, serves from the edge with HTTPS
   already terminated, attaches a custom domain in one screen, and
   needs no service on any machine. (Cloudflare has been steering
   new projects toward "Workers with static assets"; either works
   and the step checks which the dashboard offers.) **The fallback,
   if the author wants one process to own everything**: a second
   Public Hostname on the same tunnel, `d12ball.com` to
   `http://127.0.0.1:8080`, and the aiohttp app serving the built
   landing page when the `Host` is the bare domain. It is written
   down here so it is not rediscovered; it is not the plan.

2. **Both sites live in this repository, under `landing/`, built by
   one script.** The D12 Ball page has to be built here: its numbers,
   pictures and quoted rules come from the game's own code. The
   studio page is one HTML file today and a repository of its own for
   one file is overhead. `landing/build.py` builds both into
   `landing/dist/<site>/`, gitignored like `box/` and `print/`. Not
   named `site/`: that is a stdlib module. **The exit**: when the
   studio site has pages that are not about a game in this
   repository (a blog, a second game with its own code), it moves to
   its own repository and takes `landing/studio/` with it; the D12
   Ball page stays.

3. **Hand-written HTML and one stylesheet per site, no framework, no
   build tooling beyond Python.** Two pages. The repository already
   has a Python build for every other artefact and a developer who
   reads Python; a `node_modules` for two pages is a second toolchain
   for no gain. The template is `string.Template` or plain
   `str.format` over an HTML file; if a third page wants loops, the
   step reaches for Jinja2, which `requirements.txt` gains then and
   not before.

4. **Deploy is Cloudflare Pages' Git integration on
   `HolyTispoon/fool-bot`, production branch `main`, build command
   the repository's own script.** Every merge to `main` rebuilds and
   publishes both sites, the way a rules change reaches the printed
   kit by re-running it: nothing to drift. Two Pages projects, one
   per domain, same repository, different output directories
   (`landing/dist/d12ball`, `landing/dist/studio`). The Pages build
   image has Python and `pip`; Pillow's wheel installs. **If the
   build image turns out not to run the renders** (a font, a missing
   system library), the fallback is `wrangler pages deploy` from a
   GitHub Action on push to `main`, with the API token as a
   repository secret; the step records which one it took and why.

5. **The site owns every address that gets printed.** `d12ball.com`
   for the game, `d12ball.com/survey` for the survey,
   `d12ball.com/rules` and `d12ball.com/learn` for the two books,
   `d12ball.com/play` for the app. Redirects are a `_redirects` file
   in the built site, so a survey that moves to a new form is a
   one-line change and no card is reprinted.

6. **The rulebooks and the print-and-play kit are downloads on the
   page, built by the same build.** `build_rulebooks.py` makes the
   two PDFs, `generate_print_and_play_kit.py --zip` the kit; the
   landing build runs both into `dist/d12ball/downloads/`. The
   Charter and Learn to Play are the books the box quotes; a
   download link is how a table gets them without the app. On the
   page they are two cover images under "Ways to play", so each book
   gains a cover page (step 3) and the page shows that page.

7. **Nothing on the pages is tested for how it looks; one test checks
   the build stands up.** The author's rule for everything printed
   holds here: check it by rendering and looking. What a test *can*
   catch cheaply is a build that fails or a link into the site that
   points at nothing, so `tests/test_landing_build.py` builds both
   sites into a temp dir, asserts every local `href`/`src` resolves
   to a file in the output, and asserts every `<blockquote data-law>`
   on the D12 Ball page appears verbatim in `docs/living-rules.md` --
   the same test the box art has. The page as reviewed carries no
   such quote (its copy is the author's); the check is there for the
   day one is added.

8. **Cloudflare Web Analytics, on, cookieless.** One `<script>` from
   the dashboard, no consent banner needed, tells the author whether
   anybody arrives from the QR. Off if the author says so.

9. **Play links go to `play.d12ball.com`; the app links back.** The
   app's front door (`webapp/static/index.html`) gains one line
   pointing at `d12ball.com` for "what is this", and stops being the
   only page a stranger can land on. The bot's channel welcome text
   (`cogs/d12ball_helpers.py`, "Prophetic Fools Games") names the
   two sites. Neither is content the sites depend on; both are in
   step 6 so they are not forgotten.

## Questions for the author

Each step's PR carries a `## Questions for the author` section; these
are the ones known before any step starts. A step whose prompt needs
the answer says what it builds until it has one. Struck ones were
answered on the canvas on 2026-09-27.

Nothing is open as of the author's review of this PR (2026-09-27).

- ~~The Discord invite.~~ https://discord.gg/MpgGm8FvKB (the author,
  on this PR). The page carries it as an icon, in the footer and
  beside the playtest panel's contact line.
- ~~`www.d12ball.com` to `d12ball.com`, or the other way?~~ Bare.
- ~~Does the studio site want a mailing list?~~ Not for now.
- ~~Does the Prophetic Folly card link to the Notion page?~~ Yes,
  after all (the author, on this PR): the chip stays "In
  development" and the card links to
  https://propheticfools.notion.site/ under its contact line.
- ~~What contact goes on both sites?~~ politicsgames@gmail.com.
- ~~Is the Screentop table public?~~ Public, and off the page anyway.
- ~~The stage words.~~ D12 Ball "in playtesting"; Prophetic Folly "In
  development".

## The steps

Every step is one branch off an up-to-date `main`, one PR, the suite
green, and a `## Questions for the author` section on the PR even
when it is empty. A step lands by striking its row below, as the
other worksheets do (`| ~~n~~ | ~~title~~ -- landed; ... |`).

| # | Step | Size |
| --- | --- | --- |
| ~~1~~ | ~~The build: `landing/`, the two skeletons, the shared look, the test, the design note~~ -- landed; see [landing-pages.md](design/landing-pages.md) | ~~medium~~ |
| ~~2~~ | ~~`d12ball.com`: the page itself~~ -- landed; see [landing-pages.md](design/landing-pages.md) | ~~medium~~ |
| ~~3~~ | ~~`d12ball.com`: the downloads and the redirects~~ -- landed; the kit is the colour teams' print sheets, in three zips -- the components, and the player cards in two -- to fit Pages' 25 MB; see [landing-pages.md](design/landing-pages.md) | ~~small~~ |
| ~~4~~ | ~~`propheticfoolsgames.com`: the page itself~~ -- landed; the dice renderer is `landing/dice.py` and `requirements.txt` carries numpy for it; see [landing-pages.md](design/landing-pages.md) | ~~small~~ |
| ~~5~~ | ~~Deploy: the two Pages projects, the domains, the printed addresses~~ -- landed on the repository side: the box prints `d12ball.com` and `d12ball.com/survey`, and the build refuses a printed address the site does not serve; **the dashboard half is the author's to run**, the checklist in [landing-pages.md](design/landing-pages.md), "Deploying" -- Web Analytics is Pages' one-click setting rather than a snippet in the template | ~~medium, half of it in dashboards~~ |
| 6 | Cross-links: the app, the bot, the Notion pages | small |

Steps 1 to 4 can be looked at locally (`python3 -m http.server` in
`landing/dist/<site>`), and nothing goes public until step 5.

### Claiming a step

`scripts/claim_web_step.py --series landing <n>` claims step `n`: it
pushes an empty commit to `landing-step-<n>` and refuses if the
branch, an open PR titled `Landing step <n>:`, or a struck row
already exists. The series does not exist yet: **step 1's prompt
adds it** -- one entry in `SERIES`
(`"landing": ("docs/landing-pages.md", "landing-step", "Landing step")`),
plus the `--series` help string and the module docstring, which both
list the series by hand. No cloud routine is set up for this series
unless the author asks; six steps is a week of sessions, not a
pipeline.

## Preamble

Every step's prompt starts with this block.

```text
You are working in the fool-bot repository on the two landing pages
planned in docs/landing-pages.md. Read that worksheet first, then the
design note docs/design/landing-pages.md if it exists, then
docs/design/box-and-sale-sheet.md (the principles the pages inherit:
every claim read from the game, every quoted rule the books' own,
word for word, the night palette for screens). Do not read the rest
of docs/design/ unless a step names a file.

Start on a fresh branch off an up-to-date main (the claim script has
made it: git fetch && git checkout landing-step-<n>). Never work on
main.

The pages are marketing, not the game: nothing under landing/ decides
a rule, words a rule, imports discord, or touches webapp/ except
where a step says. A number on a page is read from the game's code
(box_art.py's facts and DEFAULT_CLAIMS, the catalogs, TEAM_COLORS),
never typed. A rule on a page is quoted from docs/living-rules.md
verbatim with its Law cited. The one line in the box's own voice is
box_art.STRAPLINE; do not write a second.

Nothing printed or rendered is tested for how it looks: build it and
look at it in a browser, at desktop and phone widths. What is tested
is that the build stands up and every local link resolves
(tests/test_landing_build.py).

Run python3 -m unittest discover -s tests before the PR. The PR
carries a ## Questions for the author section, even if empty, and
strikes this step's row in docs/landing-pages.md. When the step
settles something the worksheet only proposed, write it into
docs/design/landing-pages.md with the reasoning, and add a row to
CLAUDE.md's tables only for a new module or a new hard rule.
```

### 1. The build: `landing/`, the two skeletons, the shared look, the test, the design note

Sets up everything the other steps fill in, and proves the build
runs on a clean checkout.

```text
Step 1 of docs/landing-pages.md.

Create landing/ as a package:
- landing/build.py: build(site, out_dir) for site in {"d12ball",
  "studio"}, and a main() that builds both into landing/dist/<site>/
  (add landing/dist/ to .gitignore beside box/ and print/). It fills
  landing/<site>/index.html, a plain HTML template, with values it
  reads from the game -- for d12ball: box_art.TITLE, PUBLISHER,
  STRAPLINE, the coach count and DEFAULT_CLAIMS' minutes and age the
  way the sale sheet's chips read them, the team and species counts
  from game.Team / TEAM_PAIRS, the maneuver count from the catalog --
  and copies landing/<site>/site.css and landing/shared/*.css
  alongside. Every value is looked up through the same functions
  box_art.py uses; do not duplicate a lookup.
- landing/build.py also renders the pictures the pages need, through
  the existing renderers and in a thread-free plain call: the night
  banner and night cover via render_box_art's functions (call
  box_art directly, not the script), the four species icons via
  render.species_icon, and TEAM_COLORS written into a generated
  colours.css so the page's team swatches are the renderer's hex.
  Nothing is drawn in landing/ itself.
- scripts/build_landing.py: the CLI (--out, --only d12ball|studio),
  in the shape of scripts/render_box_art.py.
- landing/shared/base.css: the dark palette of the night banner
  (write the hex values of box_art.NIGHT_COVER -- ground, ink, muted,
  accent, edge -- into the generated colours.css rather than retyping
  them), one typeface stack that falls back to system fonts
  (the bundled Racing Sans One for display, served from the site as a
  woff2 if the licence allows; check d12ball/fonts/ for the licence
  file and say on the PR if it does not), a 16px gutter, no
  horizontal scroll at 375px wide.
- The two skeletons: d12ball/index.html has the hero (banner, title,
  strapline, the chips, two buttons "Play in your browser" ->
  https://play.d12ball.com and "Learn to play" -> /learn, a redirect
  step 3 fills), and empty sections with the headings step 2 fills.
  studio/index.html has the studio paragraph (quoted from the
  worksheet, the author's words), a Games section with two empty
  cards, a footer. Both have a <title>, a meta description, an
  Open Graph image (the banner), and a favicon: the d12 drawn by
  box_art.d12_art at 64px (there is no d12 PNG in d12ball/images/;
  the bot's d12 emoji is an application emoji fetched at runtime).
- tests/test_landing_build.py: builds both sites into a temp dir;
  asserts index.html exists for each; parses every href and src that
  is not http(s):, mailto: or #, and asserts it resolves to a file
  in that site's output (a redirect listed in _redirects counts as
  resolving); asserts every <blockquote data-law> on the d12ball page
  appears verbatim in docs/living-rules.md (there are none yet -- the
  test is here so step 2 cannot forget it). Suppress nothing: the
  build touches no game save.
- scripts/claim_web_step.py: add the "landing" series as the
  worksheet's "Claiming a step" says.
- docs/design/landing-pages.md: the design note. Record the
  decisions from the worksheet that this step made real (where the
  pages live and why not their own repo, why Python and no
  framework, why the night palette, why the numbers are read and not
  typed, what the test does and does not check), and a "Building and
  looking" section: the CLI, the http.server line, the widths to
  check.
- CLAUDE.md: one row for landing/ in "Where things live", one row in
  "Read this before touching", pointing at the design note.

Build both, open each in a browser at desktop and 375px, and attach a
screenshot of each to the PR.
```

### 2. `d12ball.com`: the page itself

The sections, top to bottom, as the author left them on the canvas.
Where the words below are in quotation marks they are the author's
and go on the page unchanged.

```text
Step 2 of docs/landing-pages.md. Step 1 has landed. The copy below
was written by the author on the canvas on 2026-09-27; reproduce it
exactly, and do not reword what is quoted.

Fill the d12ball page's sections, in this order below the hero. The
nav is How it plays, The teams, Ways to play, Playtest, and the gold
Play now; there is no Books entry.

1. "What it is": the overview paragraph from the game's Notion page
   ("D12 Ball is a fast playing fantasy sports game with tense
   last-ditch efforts and dramatic comebacks, where two teams of
   fantasy creatures compete by maneuvering around the field,
   manipulating the ball and outwitting the other team on their way
   to score epic goals."), on its own -- no Charter quote beside it.
   Under it, full width, the board as the web app draws it: a 2x
   headless-Chrome capture of a room page's board panel (the field,
   the goals, both benches) with the caption "The board as the web
   app draws it at play.d12ball.com." The build takes it itself:
   it starts a web app on a spare port over a games file it writes
   from a fixture in landing/fixtures/ (one saved web game at
   kickoff, Purple at home against the Cyborgs), captures the room
   with `chrome --headless=new --screenshot --force-device-scale-
   factor=2`, crops the `.board-panel` rectangle it reads from the
   page, and stops the app. Where no Chrome is on the machine (the
   Pages build image), it uses the committed capture in
   landing/d12ball/board.png and says so; the design note records
   that the committed capture is refreshed by hand after a redesign
   step lands. Not the sale sheet's printed board, and not the bot's
   PNG: the author asked for the web app's picture.

2. "How a turn goes": heading "Maneuver around each other in a spicy
   Rock, Paper, Scissors game". Three cards, each a maneuver card face
   from cards.py over one of the author's paragraphs:
   1. "The offense chooses its action", over the Low Pass card: "When
      you're close enough to the opponent's goal you can try to score,
      but for most of the game players maneuver: choosing one of three
      possible actions to handle the ball."
   2. "The defense challenges", over the Intercept card: "The
      defending coach secretly picks a maneuver of their own. Both
      sides reveal their choice simultaneously."
   3. "Resolution", over the High Pass card: "The maneuvers relate to
      each other in a rock-paper-scissors cycle of priority: a low
      pass beats pressure, which beats dribble advance, and so forth.
      In case of a tie in rank, players engage in an exhausting skill
      test, rolling d12s until one side gains the upper hand, or
      tentacle!"
   No Charter quotes and no Law citations: the beats are the author's
   voice. The <blockquote data-law> test stays for any quote a later
   edit adds.

3. "The teams": heading "Four species, eight teams"; intro "Four
   colour teams, and the four species that wear their colours. Nine
   players a team, six on the field and three on the bench." Four
   cards, one per species: a player card from player_cards.py in the
   basic face (the Fire Demons' fullback, the other three's
   goalkeeper -- named by role, never by id), a row of the species'
   coloured icon, the species name and the colour team's swatch from
   colours.css, and one line of the author's under the row:
   - Fire Demons: "Can ignite the ball for explosive successes as well
     as catastrophic burns."
   - Cyborgs: "Can overcharge for a significant boost, but only if
     they get charged up enough to keep up with the energy cost."
   - Telekinetics: "Be careful when you go by them, because they may
     just pull the ball away from you."
   - Oozes: "Most players get assigned to just one space, but these
     oozes tend to spread around on as many as they want."
   The cards are rendered by the build, so a change to
   player_cards.py reaches the page on the next merge.

4. "Ways to play": heading "Try it today!". Three cards:
   - "In your browser": "Try the game online by playing in your
     browser. Play against friends or an AI opponent. There's even a
     tutorial!" -> https://play.d12ball.com
   - "At the table": "Get the print-and-play kit. Meeples and d12s
     not included. 3D files for printing tokens are available on
     request." -> /kit (step 3)
   - "The rulebooks": no description. Two cover images side by side,
     each a link, only the titles under them: "Learn to Play (PDF)"
     -> /learn and "The Charter: Laws of the Game (PDF)" -> /rules.
     The covers are the books' own cover pages rendered by step 3's
     cover function; until step 3 lands the card links with the
     titles alone.
   Not Screentop and not Discord: the author took both off this list.

5. "Playtesting": heading "You liked it? Great! Didn't like it? Tell
   us why!"; line "D12 Ball is in playtesting and we'd love your
   feedback."; the survey button -> /survey (step 3); the contact
   line "For more information: politicsgames@gmail.com or join our
   Discord!" with the address a mailto link and the Discord mark
   beside the line as the invite link -- a 32px blurple square with
   the white mark, an aria-label, the permanent invite once the
   author gave on the worksheet's PR: https://discord.gg/MpgGm8FvKB.
   On the
   desktop the night cover sits beside the text.

6. Footer: PUBLISHER linking https://propheticfoolsgames.com, the
   stage word, the year, and the Discord mark again as an icon-only
   link at the right.

Where the author has not written the words, keep the copy rules: a
number is the game's; no second strapline. Build, look at desktop
and phone, screenshots on the PR, and list under Questions for the
author every place the page is thinner than it should be because an
answer is missing.
```

### 3. `d12ball.com`: the downloads and the redirects

```text
Step 3 of docs/landing-pages.md. Step 1 has landed; step 2 may or may
not have.

- landing/build.py gains, for the d12ball site, a downloads step:
  build_rulebooks' charter and learn-to-play PDFs (call
  d12ball.rulebooks' functions directly, letter paper) into
  dist/d12ball/downloads/, and the print-and-play kit as one zip by
  running scripts/generate_print_and_play_kit.py --zip with its
  output pointed inside dist/d12ball/downloads/. Report the sizes on
  the PR; if the kit zip is over 25 MB, the Pages file limit, say so
  and stop -- the author decides whether the kit is split or hosted
  elsewhere, and the page's kit card links wherever that lands.
- A _redirects file in the built d12ball site, Cloudflare Pages'
  format, one line each:
    /play    https://play.d12ball.com  302
    /rules   /downloads/<charter pdf>   302
    /learn   /downloads/<learn pdf>     302
    /kit     /downloads/<kit zip>       302
    /survey  <box_art.SURVEY_URL>       302
  The survey line reads SURVEY_URL from box_art.py so there is one
  copy of it. Make the test count a redirect source as a resolving
  link and check each redirect target that is local resolves too.
- The books gain a cover page. The built PDFs open on their first
  text page, which does not read as a book at thumbnail size (the
  author, on the canvas, 2026-09-27). Each entry in rulebooks.py's
  book table gains its cover's words -- Learn to Play: "Learn the
  fundamentals quickly with a beautifully illustrated guide for the
  training mode."; the Charter: "Laws of the Game." and under it
  "Comprehensive rules reference for the game." -- and the same
  layout is drawn twice from those fields: by reportlab as page 1
  of the PDF, and by Pillow (a function in landing/, cream paper,
  a gold band at the head, the title in Racing Sans One, the
  subtitle, box_art.d12_art low right, the publisher line at the
  foot) as the cover image the rulebooks card shows. One source for
  the words; two drawings of them, checked by looking. The PDF
  change is reviewed against docs/design/rulebooks.md.
- The books are the ones the box quotes; if build_rulebooks fails on
  the markdown subset, that is a rulebook bug to fix in
  d12ball/rulebooks.py, not to work around here.
- Write the download-and-redirect design into the design note: why
  the site owns the printed addresses, why the survey is a redirect,
  the size limits.
```

### 4. `propheticfoolsgames.com`: the page itself

```text
Step 4 of docs/landing-pages.md. Step 1 has landed.

Fill the studio page:

1. Hero: the studio's name, and the studio paragraph already in the
   skeleton, unchanged, set as the headline in the serif. No
   strapline: the studio has not written one, and the page does not
   write one for it. Beside it, the night box cover with two of the
   bot's coins at its foot.

2. "Games", heading "Two at the table": two cards.
   - D12 Ball: the night banner (built by the same build; copy it
     from the d12ball build or render it again, once), the overview
     line from the game's Notion page, the chips (coaches, minutes,
     age, read the same way as the d12ball page), the chip
     "IN PLAYTESTING", and a link to https://d12ball.com.
   - Prophetic Folly, gated (the author, 2026-09-27): the callout
     sentence from its Notion page ("A streamlined tabletop
     roleplaying system, providing a robust mechanics for action
     resolution with lots of flexibility for narrative driven
     interactions."), the author's paragraph on the mechanic ("A novel action
     resolution based on two twelve-sided dice: a Fortune die and a
     Doom die. Rolling with Hope makes it possible to beat challenges
     you wouldn't otherwise be able to face but is overall less
     successful. Rolling with Fear makes spectacular successes less
     likely but also avoids catastrophic failures."), the
     chip "IN DEVELOPMENT", and the gold link "Read more about the
     system" -> https://propheticfools.notion.site/ at the card's
     foot; the title "Prophetic Folly" links there too. No contact
     line on the card: the footer's address is the studio's (the
     author, on the worksheet's PR and the canvas, 2026-09-27,
     reversing the earlier "keep it gated": the stage word stays,
     the link goes public). Its picture is one composed still, centred in the
     card's picture panel: the two d12s rendered as solids -- bone
     Fortune showing 12 with engraved umber numerals, obsidian Doom
     showing 1 with painted bone numerals, each resting on a face
     with a contact shadow -- and the six coins from
     d12ball/images/emoji gathered tight round their feet, turned a
     little, fortune faces (gold 3, silver 1, bronze 3) at Fortune's
     side and doom faces (gold 1, silver 3, bronze 1) at Doom's.
     scripts/render_landing_dice.py is the renderer written for the
     sketch; move it to landing/dice.py, keep its output identical,
     and compose the still in landing/build.py with Pillow.
     The renderer shades per pixel with numpy, which requirements.txt
     does not list: add it in this step (the Pages build image
     installs its wheel), or rewrite the shading in plain Pillow if
     the author would rather not add a dependency for one picture.

3. Footer: the studio's name, politicsgames@gmail.com as a mailto
   link, the year.

The studio page shares landing/shared/base.css with the d12ball page
and has its own site.css for the card grid. It has no downloads and
no redirects except www (step 5). Build, look, screenshots on the PR.
```

### 5. Deploy: the two Pages projects, the domains, the printed addresses

Half of this is the author in the Cloudflare dashboard; the prompt
writes the checklist into the design note and does the repository
side. Nothing before this step is public.

```text
Step 5 of docs/landing-pages.md. Steps 1 to 4 have landed.

Repository side:
- landing/build.py's main() builds both sites with no arguments and
  exits non-zero on any failure, so a Pages build fails loudly.
- Confirm requirements.txt installs on a clean Linux Python (a
  Pages build image is Linux; Pillow, reportlab and the rest have
  wheels) and that the renders find the bundled fonts by absolute
  path from any working directory. Run the build from a different
  cwd to prove it.
- d12ball/box_art.py: change PAGE_URL to https://d12ball.com and
  SURVEY_URL's use on the playtest card to https://d12ball.com/survey
  (keep the Notion survey address as the redirect's target in
  _redirects, which step 3 reads from a constant -- rename that
  constant so the card's address and the redirect's target are
  clearly two things). This is its own commit with its own message,
  because it changes what is printed; render the sale sheet and the
  playtest card and attach both to the PR. Fix the stale sentence in
  box_art.py's module docstring that says playing time and age are
  left off the box while you are there; DEFAULT_CLAIMS has printed
  them since 2026-09-23.

Design note side, a "Deploying" section written as a checklist the
author runs in the dashboard, in the shape of collaboration.md's
tunnel section (names are the shape, not a promise):
1. Both domains listed as Active on Cloudflare.
2. Workers & Pages -> Create -> Pages -> Connect to Git ->
   HolyTispoon/fool-bot. Project d12ball: production branch main,
   build command `pip install -r requirements.txt && python3
   scripts/build_landing.py --only d12ball`, build output
   landing/dist/d12ball. Project propheticfoolsgames: the same with
   studio. If the dashboard only offers "Workers with static
   assets", use that with the same command and a wrangler.toml
   naming the assets directory; record which it was.
3. Custom domains: d12ball.com on the first project,
   propheticfoolsgames.com on the second; then www.<domain> on each,
   with a Bulk Redirect (or a _redirects line) sending www to bare.
   Cloudflare creates the DNS records; play.d12ball.com's record is
   the tunnel's and is not touched.
4. "Always Use HTTPS" on both domains.
5. Web Analytics: enable for each site, paste the snippet into the
   template's <head> (a build-time value, blank when unset, so the
   test build carries no beacon).
6. From a phone off the home Wi-Fi: both bare domains load, www
   redirects, /play reaches the app, /survey reaches the form,
   /rules and /learn download, the Open Graph card previews in a
   Discord message.
7. If the Pages build fails on the renders, fall back to a GitHub
   Action on push to main running the build and `wrangler pages
   deploy`, with CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID as
   repository secrets; write down which path was taken and why.
Also record in the design note what is per checkout and what is
per account here (nothing is per checkout: the sites are built from
main, not from a machine).
```

### 6. Cross-links: the app, the bot, the Notion pages

```text
Step 6 of docs/landing-pages.md. Step 5 has landed and both sites are
live.

- webapp/static/index.html: one line under the "D12 Ball" panel
  linking https://d12ball.com ("What is D12 Ball?"), styled like the
  existing "Rules & aids" link. Nothing else in webapp/ changes; the
  app does not depend on the site.
- cogs/d12ball_helpers.py: the "## Prophetic Fools Games" welcome
  text names the two sites, one line each. This is a cog string, not
  the model's; no token, no rule. Check the goldens still pass (they
  record what the bot sends; if this text is in one, re-record it and
  say so on the PR).
- docs/rules-log.md and docs/design/rules-and-data.md point at the
  Notion D12 Ball page as where the rules live upstream; add
  d12ball.com beside it where it names the public page, and leave
  the upstream pointer alone -- the Notion page is still where the
  author writes.
- Under Questions for the author: the Notion pages themselves should
  now point at the domains (the studio page's D12 Ball entry at
  d12ball.com; the D12 Ball page's overview at the site); that is a
  Notion edit, not a repository change, so it is asked, not done.
```

## What is not in these prompts, on purpose

- **A blog, news, a mailing list, a shop.** Not until the author asks
  for one; each needs a provider or a second toolchain.
- **Screentop, and Discord as a way to play.** Both were on the first
  draft; the author took them off. The Discord invite lives on as an
  icon.
- **A landing page for Prophetic Folly of its own.** It has a Notion
  site and is in closed playtesting. When it has a domain, this
  worksheet's shape is what to copy.
- **Serving the pages from the aiohttp app.** Decision 1 says why;
  the fallback is written down there and nowhere else.
- **A second wording of any rule.** The page quotes the Charter or
  says nothing about the rule.
- **A cloud routine for the series.** Six steps; claim by hand.
- **A test of how a page looks.** The author's rule for everything
  printed: build it and look.

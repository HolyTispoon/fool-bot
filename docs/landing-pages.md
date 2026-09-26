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
   download link is how a table gets them without the app.

7. **Nothing on the pages is tested for how it looks; one test checks
   the build stands up.** The author's rule for everything printed
   holds here: check it by rendering and looking. What a test *can*
   catch cheaply is a build that fails or a link into the site that
   points at nothing, so `tests/test_landing_build.py` builds both
   sites into a temp dir, asserts every local `href`/`src` resolves
   to a file in the output, and asserts every quoted rule on the D12
   Ball page appears verbatim in `docs/living-rules.md` -- the same
   test the box art has.

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
the answer says what it builds until it has one.

- **Does the Prophetic Folly card link to the Notion page?** The page
  is marked draft, do not circulate. Until answered the card says
  "in closed playtesting" and offers the contact address.
- **What contact goes on both sites?** An email, a Discord invite, a
  form. The sale sheet's `--contact` flag has the same hole. Until
  answered, no contact is shown and the footer names the studio
  only.
- **Is the Discord server public?** If a stranger may join and play
  the bot, "Play on Discord" is a way to play and needs an invite
  link that does not expire. Until answered the page lists the
  browser, the table and the print-and-play kit.
- **Is the Screentop table public, and what is its address?** The
  Screentop banner exists (`screentop-banner-night.png`); whether
  the table is listed is the author's.
- **`www.d12ball.com` to `d12ball.com`, or the other way?** Bare is
  the recommendation; it is what is printed.
- **Does the studio site want a mailing list?** Not built unless
  asked: it needs a provider and a privacy line.
- **The stage words.** Notion says D12 Ball is "Early development"
  and Folly "Playtesting". The pages say what the author wants
  strangers told; the D12 Ball page currently says "in playtesting",
  which is what the playtest card says.

## The steps

Every step is one branch off an up-to-date `main`, one PR, the suite
green, and a `## Questions for the author` section on the PR even
when it is empty. A step lands by striking its row below, as the
other worksheets do (`| ~~n~~ | ~~title~~ -- landed; ... |`).

| # | Step | Size |
| --- | --- | --- |
| 1 | The build: `landing/`, the two skeletons, the shared look, the test, the design note | medium |
| 2 | `d12ball.com`: the page itself | medium |
| 3 | `d12ball.com`: the downloads and the redirects | small |
| 4 | `propheticfoolsgames.com`: the page itself | small |
| 5 | Deploy: the two Pages projects, the domains, the printed addresses | medium, half of it in dashboards |
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

The sections, top to bottom. Every sentence that is not the author's
is a caption over something drawn or quoted.

```text
Step 2 of docs/landing-pages.md. Step 1 has landed.

Fill the d12ball page's sections, in this order below the hero:

1. "What it is": the overview paragraph from the game's Notion page,
   quoted in the worksheet ("D12 Ball is a fast playing fantasy
   sports game with tense last-ditch efforts and dramatic
   comebacks..."), the author's words unchanged. Beside it, the
   printed board with meeples on it, rendered the way the sale sheet
   renders its picture of the game (box_art.board_photo and
   draw_meeples_on_board; reuse them, do not redraw).

2. "How a turn goes": three beats, each a <blockquote data-law="N">
   quoting one sentence of docs/living-rules.md verbatim -- the
   maneuver being chosen, the challenge, the roll -- with a
   one-line caption above each that names what the picture shows.
   Pick the sentences the sale sheet already quotes (box_art's quoted
   rules) before reaching for new ones. Under each beat, the picture
   the bot itself posts at that moment: a maneuver card face from
   cards.py, the challenge image from dice_brief's brief through
   render.py, the skill-test dice. Build a real match state to render
   from, the way d12ball/rulebook_figures.py does; do not hand-place
   anything.

3. "The teams": eight team swatches from the generated colours.css,
   grouped by TEAM_PAIRS, each species' coloured icon beside its pair,
   and one player card per species from player_cards.py in the basic
   face. Names through team_display_name, never .value.title().

4. "Ways to play": cards for the browser (play.d12ball.com, one line:
   two coaches, or one against the AI), the table (the
   print-and-play kit, linking to /kit, step 3), and the Screentop
   table if the author has answered with an address; Discord only if
   the author has answered that the server is public. A way the
   author has not confirmed is not on the page.

5. "The books": the Charter and Learn to Play as two download cards
   linking /rules and /learn (step 3), each with its title from
   rulebooks.py's book table and its page count read from the built
   PDF if step 3 has landed, otherwise no count.

6. "Playtesting": one paragraph saying the game is in playtesting
   and inviting a table to play and answer the survey, linking /survey
   (step 3). No contact until the author gives one.

7. Footer: PUBLISHER linking https://propheticfoolsgames.com, the
   stage word, and the year.

Keep the copy rules: say what the game is, never what it is not; a
number is the game's; no second strapline. Extend the test's
blockquote check so it fails on any quote that is not verbatim in
the living rules. Build, look at desktop and phone, screenshots on
the PR, and list under Questions for the author every place the page
is thinner than it should be because an answer is missing.
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
   skeleton, unchanged. No strapline: the studio has not written one,
   and the page does not write one for it. Under Questions for the
   author, ask whether it wants one.

2. "Games": two cards.
   - D12 Ball: the night banner (built by the same build; copy it
     from the d12ball build or render it again, once), the overview
     line from the game's Notion page, the chips (coaches, minutes,
     age, read the same way as the d12ball page), the stage word,
     and a link to https://d12ball.com.
   - Prophetic Folly: the callout sentence from its Notion page
     ("A streamlined tabletop roleplaying system, providing a robust
     mechanics for action resolution with lots of flexibility for
     narrative driven interactions."), one line naming the mechanic
     (two twelve-sided dice, Fortune and Doom -- the page's own
     words, quoted), the stage word "Playtesting", and -- until the
     author answers -- "In closed playtesting" with no link. If the
     author has answered that the link goes public, link
     https://propheticfools.notion.site/ and drop the closed line.
     The card has a picture slot; the Folly page has no art of its
     own, and the bot already draws a Fortune die and a Doom die
     (d12ball/images/emoji/*_fortune.png, *_doom.png -- the same
     names Folly gives its two dice), so the card shows that pair,
     one darker than the other as the page describes them, rather
     than leaving a hole. Ask the author whether the shared names
     are a coincidence or the studio's house dice.

3. Footer: the studio's name, the year, the contact if given.

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

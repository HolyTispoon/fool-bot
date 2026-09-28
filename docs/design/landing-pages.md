# The landing pages

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md). The
worksheet these are built from is [docs/landing-pages.md](../landing-pages.md);
what a step settles moves here as it lands.

Two static sites, built from this repository by one script:

| Site | Served at | What it is |
| --- | --- | --- |
| `landing/d12ball/` | `d12ball.com` | The game's public face. `play.d12ball.com` stays the web app |
| `landing/studio/` | `propheticfoolsgames.com` | The studio: its paragraph, and a card per game |

```bash
python3 scripts/build_landing.py                   # both, into landing/dist/<site>/
python3 scripts/build_landing.py --only d12ball --out /tmp/site
```

`landing/dist/` is generated output and is gitignored, like `print/`.

## Why they live here, and not in a repository of their own

The D12 Ball page has to be built here: its numbers, its pictures and any rule
it quotes come from the game's own code, and a copy of them anywhere else is a
copy that goes stale on the next import. The studio page is one HTML file, and
a repository for one file is overhead. `landing/build.py` builds both.

**The exit** is written down so it is not argued again: when the studio site
has pages that are not about a game in this repository -- a blog, a second
game with its own code -- it moves to its own repository and takes
`landing/studio/` with it. The D12 Ball page stays.

The package is `landing/`, not `site/`: `site` is a stdlib module, and a
package of that name at the repository root would shadow it.

## Python and plain HTML, no framework

Two pages. The repository already builds every other artefact with Python --
the boards, the cards, the box, the rulebooks -- and its developers read
Python; a `node_modules` for two pages is a second toolchain for nothing. So
each page is `landing/<site>/index.html`, a plain `string.Template` whose
`$names` the build fills, and each site has one stylesheet of its own
(`site.css`) over one both share (`landing/shared/base.css`). If a third page
wants loops, the build reaches for Jinja2 then, and `requirements.txt` gains it
then and not before.

A value goes into the page escaped, by the build. A `$` a page needs for itself
is written `$$`.

## Every number is the game's, and every picture the renderer's

The pages inherit the box's principle ([box-and-sale-sheet.md](box-and-sale-sheet.md)):
**a claim on the page is read from the game, and the page never words a rule
for itself.** Concretely, `landing/build.py` reads:

- the title, the publisher and the one line in the box's own voice from
  `box_art.TITLE`, `PUBLISHER` and `STRAPLINE`. There is no second strapline;
- the chips from `box_art.retail_chips(BoxFacts, DEFAULT_CLAIMS)`, the function
  the cover and the sale sheet print theirs with -- so the page says "2
  PLAYERS" because the box does;
- the palette from `box_art.NIGHT_COVER` and every team's hex from
  `render.TEAM_COLORS`, written by the build into a generated `colours.css` as
  custom properties (`--accent`, `--team-oozes`). No hex is typed in a
  stylesheet; the two surfaces a section and a card sit on are `color-mix`es of
  the ground and the edge;
- the pictures from the renderers: the night banner (`render_banner`, in
  1500 and 3000 wide for `srcset`), the night cover (`render_box_cover`), the
  Screentop-sized night banner as the Open Graph image -- 16:9, because a link
  preview crops a 2.5:1 banner to a sliver -- the four species icons through
  `render.species_icon` in their colour team's hex (`species_cards.SPECIES_TEAM`),
  and each site's favicon, one of Prophetic Folly's dice ("The dice as marks").

One picture is drawn under `landing/`, and it is not of the game: the books'
covers (`covers.py`, off `rulebooks.cover_layout`, "The downloads"). Prophetic
Folly's dice are `d12ball/dice.py`'s ("The studio page"), because the books'
PDFs draw one too. Anything that shows D12 Ball is the renderer's.

What the code cannot answer is one constant each in `landing/build.py`, dated
where it is the author's call: the contact address, the Discord invite, the studio's paragraph
(quoted from its Notion page as written), the game's overview line (`OVERVIEW`,
its Notion page's, which both sites carry), Prophetic Folly's words and
address, and each site's origin. The stage word (`STAGE`, "in playtesting",
2026-09-27) and the playtest panel's headline (`PLAYTEST_HEADLINE`) are
`box_art`'s instead, because the playtest card prints them too: one copy,
which the card and the page both read. The panel's line under it and its
"Give us feedback" button are the page's own (the author's rewording,
2026-09-27); the card words its line differently, since it points at a code
the page does not have.

## The night palette, because a page is a screen

Everything printed is white, because a dark press run is the expensive one
([box-and-sale-sheet.md](box-and-sale-sheet.md), "Everything is printed on
white"). The night cover and the banners exist because a banner is read on a
screen; so is a web page, so both sites are dark, in `NIGHT_COVER`, and the gold
is the jumbotron's.

**The display face is the bundled Racing Sans One, served as the TTF it is
bundled as.** The OFL lets it be redistributed unmodified beside its licence
(`fonts/RacingSansOne-OFL.txt` goes out with it); converting it to woff2 would
be a second file to keep in step with the first and a question about whether
a conversion is a Modified Version. It is 146 KB, once, cached.

**The text faces are IBM Plex, bundled, not linked** (the author,
2026-09-27): Plex Sans at 400, 500 and 600 for every page's text, and Plex
Serif at 400, 500 and italic for the studio's voice -- the six weights the
reviewed sketch used. They sit in `landing/shared/fonts/` as IBM ships them
(woff2 from `@ibm/plex-sans` 1.1.0 and `@ibm/plex-serif` 2.0.0, one copy of
their shared OFL beside them), and the build copies them into each site's
`fonts/`. The sketch loaded them from Google Fonts; served from the site
instead, no visitor's browser calls anybody else, and the page does not
depend on another host being up. About 410 KB in all, and a browser fetches
only the weights a page uses. A weight not in the folder is one the pages do
not use yet -- add its file and its `@font-face` together.

The layout holds at 375px with a 16px gutter and no horizontal scroll; the
gutter is 40px from 720px up, and the nav's section links show from 900px.

## What the test checks, and what it does not

**Nothing on the pages is tested for how it looks** -- the rule for everything
printed holds here: build it and look. `tests/test_landing_build.py` builds
both sites into a temporary directory and checks what a look would miss:

- each site has its `index.html`, and no `$name` was left unfilled;
- **every local link resolves**: every `href`, `src` and `srcset` candidate on
  the page, and every `url(...)` in a stylesheet, that is not an outside
  address names a file in that site's build -- or a source in its `_redirects`,
  whose local targets are held to the same;
- **every `<blockquote data-law>` on the D12 Ball page is in
  `docs/living-rules.md` word for word** (both sides with emphasis marks and
  whitespace flattened, `box_art.plain`). The page as reviewed quotes nothing,
  since its copy is the author's; the check is there for the day a quote is
  added, and a second test holds the reader to reading one.

The build touches no game save, so nothing is suppressed.

## The D12 Ball page

Top to bottom, as the author left it on the canvas (2026-09-27): the hero,
"What it is" with the board, "How a turn goes", "The teams", "Ways to play",
"Playtesting", the footer. **The copy is the author's**, written on the canvas
and reproduced word for word -- the section headings, the three beats, the
four species lines, the playtest panel and the card texts -- and the overview
is the game's Notion page's own line. None of it quotes the Charter, so none
of it cites a Law; the `<blockquote data-law>` check stays for the day a
quote is added.

Where the author's sentence carries a number, the build fills the number
in from the game, so the sentence reads as written today and follows the
roster tomorrow: "Four species, eight teams" and "Nine players a team, six on
the field and three on the bench" are `BoxFacts`' species, teams,
`players_per_team` and `fielded` (and the colour teams `COLOR_TEAMS`),
written as words by `number_word`.

**The pictures are rendered by the build**, so a merge that changes a card
changes the page: the three maneuver cards under the beats are
`cards.render_maneuver_card` (`TURN_CARDS`: Low Pass, Pressure, High Pass),
and the four player cards `player_cards.render_player_card` in the basic face.

- **The turn cards are basic cards, and the build refuses one that is not.**
  The beats describe a basic turn, and a gambit is only held by a coach who
  is behind; the sketch's Intercept was not intended (the author,
  2026-09-27). Pressure stands under the defence's beat because it is the
  card the Resolution beat names.
- **Each species' card is the box cover's player of that species**:
  `species_face` takes the one of `box_art.COVER_CAST`'s four on that
  species' team -- Flickerwing, Gearclaw, Dravox and Goopkeeper, a winger, a
  playmaker, a defender and a fullback -- so the page and the box show the
  same four from one list. The page first asked the roster for a role per
  species and took the first player of it (`SPECIES_FACE_ROLE`); that gave
  Synapse for the Cyborgs, and when the author put Gearclaw -- the Cyborgs'
  other playmaker -- on the box and then asked for him on the page too
  (2026-09-27), a role could no longer say who. The cover names its players
  anyway, because it needs a facing ([box-and-sale-sheet.md](box-and-sale-sheet.md),
  "The cover's four"), so the page reads those names rather than keeping a
  second list. The build refuses a cast without exactly one player of each
  species, and a roster revision that renames one of the four needs the
  cast re-picked.

**A link says what it opens.** The two books are "Learn to Play (PDF)" and
"The Charter: Laws of the Game (PDF)" because `/learn` and `/rules` forward
to PDFs; `book_title` reads the target, so a redirect pointed back at a page
drops the "(PDF)" by itself. The print-and-play card stands unlinked until
the site forwards `/kit`; adding that redirect is what links it
(`kit_card_html`).

## The board

The page shows **the board as the web app draws it**, not the printed board
and not the bot's PNG -- the author's call on the canvas. `landing/capture.py`
takes it: it stages a web game through `GameService` in a temporary directory
(two coaches seated, Purple picked by the first and the Cyborgs by the
second, Purple at home whoever wins the coin, the match dealt and begun, so
it is the kickoff), runs `webapp.server.serve` over that directory alone on
a spare local port -- every file the app would keep under `data/` named
there instead -- opens `/room/<id>` in a headless Chrome as an observer (both
seats are held, so the visitor takes neither), waits for the board's SVG, and
captures the `.board-panel` rectangle at twice the density over the
DevTools protocol (aiohttp's websocket client, which the web app already
needs). Chrome's own `--screenshot` flag was tried first and never exited.

**The capture is committed, as `landing/d12ball/board.png`, and the build
copies it; it never starts a browser.** The worksheet had the build take the
picture itself wherever Chrome was installed. That would make the page a
different set of bytes depending on the machine, start a server and a
browser in every test run, and do nothing on Cloudflare's build image, which
has no Chrome. So taking it is its own command,

```bash
python3 scripts/build_landing.py --capture-board
```

run by hand **after a web app change to the board** -- a redesign step, a
fix to how a piece is drawn -- and committed. `LANDING_CHROME` names a
browser when none is found. The root `.gitignore` ignores every `board.png`,
so this one is excepted by path.

## The downloads

**The two rulebooks are built by this build**, into `downloads/` in the
d12ball site: `write_downloads` calls `rulebooks.book_bytes` for each book in
`BOOK_DOWNLOADS`, on letter paper -- the same code `scripts/build_rulebooks.py`
runs, so a merge that changes the Charter changes the download, and there is
no PDF committed anywhere to go stale. Each file is named for what it is
(`d12ball-charter.pdf`, `d12ball-learn-to-play.pdf`), because that is the name
it keeps in somebody's downloads folder. They are about 0.8 MB and 6 MB; the
Learn to Play is its figures.

**Each book has a cover, and the rulebooks card shows it.** The PDFs used to
open on their first text page, which does not read as a book at the size the
card shows it (the author, on the canvas, 2026-09-27). The cover's words are
the book's own, `Cover` in `rulebooks.BOOKS` -- the title broken where the
author broke it, and the lines under it -- and the layout is one function,
`rulebooks.cover_layout`, in shares of the page, which takes the drawing's
own way of measuring a run of text. It is drawn twice: by reportlab as page 1
of the PDF (`draw_cover`), and by Pillow in `landing/covers.py` as the picture
on the card. One source for the words, one for where they go, two drawings,
checked by looking: the picture is the page the download opens on. The die on
each is one committed picture, `rulebooks.cover_die_path`, which both
drawings put down ("The dice as marks").

**The print-and-play kit is three zips: the components, and the player
cards in two.** `write_kit` runs `scripts/generate_print_and_play_kit.py`
into a temporary folder and zips it as `KIT_DOWNLOADS` says:

- `/kit` -- the boards, the maneuver, reference and token sheets, the README
  and both rulebooks as PDFs (about 12 MB);
- `/kit-players-1` and `/kit-players-2` -- the player sheets of two colour
  teams each, Orange and Teal, then Purple and Slime (about 15 MB each).

Every part holds one folder, `d12ball-print-and-play/`, so unzipped together
they are the one kit. The card links each and says what is in it.

Why: a single file on Cloudflare Pages may be 25 MB. The kit was 128 MB
(2026-09-27), because it wrote every card of all eight teams as a PNG of its
own besides the sheets; the author cut it to the print version -- sheets
only, all four colour teams, each card standard on one side and advanced on
the other, and no species-team cards, which the printed game does not have
([cards.md](cards.md), "The print-and-play kit"). That is 35 MB, 28 of it the
eight player sheets, which PNG will not squeeze (re-encoding saved 1%). The
author kept PNG and split the player cards from the boards and the other
components. The player sheets alone are over the limit too, so they are
split again by team pair, each team's standard and advanced sheets in the
same zip because they print duplex together. **The build refuses a zip over
the limit** (`PAGES_FILE_LIMIT`) rather than leaving it to fail the deploy.
The split is fixed rather than worked out from the sizes, because its
addresses are what a page or a card links: if the art grows past the limit,
`KIT_DOWNLOADS` is what changes, by hand.

## Redirects

**The site owns every address that gets printed.** A card, a box or a
rulebook prints `d12ball.com/rules`, never the file or the form behind it, so
that what is behind it can move without anything being reprinted. The
addresses a site forwards are `REDIRECTS` in `landing/build.py`, written into
the build as Cloudflare Pages' `_redirects` file:

- `/play` -- the web app.
- `/learn` and `/rules` -- the two books' PDFs in `downloads/`, built beside
  the page.
- `/kit`, `/kit-players-1` and `/kit-players-2` -- the print-and-play kit's
  three zips, likewise.
- `/feedback` -- `box_art.SURVEY_FORM_URL`, read rather than copied. The
  playtest card prints `box_art.SURVEY_URL`, which is this address, so a
  form that moves is a one-line change here and no printed card is
  reprinted.

Every redirect is a 302, not a 301: a browser caches a 301 for good, and the
point of the address is that its target may change. A local target is held
by the test to name a file in the build, and one ending `.pdf` or `.zip` to
name one.

## The studio page

Top to bottom, as the author left it on the canvas (2026-09-27): the hero, the
games, the footer. It shares `base.css` with the D12 Ball page and has its own
`site.css` for the hero and the card grid; it has no downloads and no
redirects.

**The hero is the studio's paragraph, set as the headline in the serif, and
no strapline**: the studio has not written one, and the page does not write
one for it. The paragraph is `STUDIO_PARAGRAPH`, word for word; the two
phrases the reviewed sketch lit in gold (`STUDIO_EMPHASIS`) are set in `<em>`
by the build, which refuses a phrase the paragraph no longer holds -- a
rewording upstream shows up as a failed build rather than as emphasis on
nothing. Beside it from 900px up, the night box cover with two of the bot's
coins at its foot; on a phone the paragraph stands alone, as the sketch had
it.

**The games are two cards, each with a 5:2 picture across its head**, the
banner's shape, so the two titles line up:

- **D12 Ball**: the night banner, the stage chip, `OVERVIEW` as a sentence of
  its own, the box's chips (`retail_chips`, as on the d12ball page), and a
  link to `d12ball.com` that reads as the address it opens. The d12ball page
  opens "What it is" with the same constant after the title, so the line has
  one copy.
- **Prophetic Folly**: its still, "IN DEVELOPMENT", the callout from its
  Notion page, the author's paragraph on the mechanic, and "Read more about
  the system" to `propheticfools.notion.site`; the title links there too.
  The Notion page is headed "draft, do not circulate"; the author made the
  link public on the worksheet's PR anyway (2026-09-27), keeping the stage
  word. No contact line on the card: the footer's address is the studio's.

**Prophetic Folly's picture is one composed still**: three pairs of
Fortune and Doom dice as solids of resin, close together, orange and purple
behind and teal in front. In each pair, Fortune is a clear die, bright, with
white numerals, and Doom is dark, swirled with a lighter shade, with gold
numerals. All six show a different number (12, 3, 9, 1, 7, 5), so the picture
is not one throw repeated. The bot's six coins lie round them, turned a
little: the fortune faces (gold 3, silver 1, bronze 3) on the Fortune side,
and the doom faces (gold 1, silver 3, bronze 1) on the Doom side.
`d12ball/dice.py` draws a die and holds the three pairs (`ORANGE`, `TEAL`,
`PURPLE`, each built by `resin_pair`); `folly_still` in `landing/build.py`
draws `FOLLY_STILL`'s layers back to front, on a transparent ground the
card's panel shows through. The layout was checked by rendering it and
looking, at the size the card shows it.

**`dice.py` is the renderer written for the sketch, moved, its output
unchanged** (the pixels of both dice hashed before and after the move).
**The dice are resin because the author's own are** (a photo, 2026-09-27).
The sketch had one pair, in bone and obsidian. The author then asked for dice
like the orange pair they play with, then for teal, then for three pairs --
orange, teal and purple -- close together, each showing its own number, with
the bright die clear. Resin is three finishes a `Die` may carry beside the
old ones:

- `glow`, the light coming through, strongest on the faces turned from the
  light and along the silhouette;
- `swirl`, broad streaks of a lighter shade poured into the dark die;
- `clear`, a see-through body. The faces turned away are drawn first, lit
  from inside, their numerals reading backwards through the body; the near
  faces go over them only partly covering, and the table shows a little
  through both. The numerals painted on the near faces stay solid, and the
  shadow on the table is the die's colour, as the light through a clear die
  lands. A die showing its far faces is what reads as clear; a lighter or
  paler body alone reads as frosted. The Fortune dice are `clear=0.45`:
  0.6 was a little too glassy for the author, and below about 0.4 the far
  faces fade to where the die stops reading as clear.

A polished reflection on the bright die was tried and taken out (the author,
2026-09-27). A die with none of the three draws exactly what it drew before,
which was checked by hashing the sketch's two presets again. The swirl is
seeded noise, so the picture is the same on every build. The renderer
shades every pixel of every face with numpy, which is why `requirements.txt`
carries numpy: the one picture that needs it, and the only thing the bot or a
build imports it for (`scripts/render_token_models.py` uses it too, run by
hand with the rest of its own list). The alternative was rewriting the
shading in plain Pillow, which would have been a second renderer to check by
eye against the one the author reviewed; the wheel is on every platform the
bot and the Pages build run on. The six dice are drawn at 400px; a clear die
draws its far faces too, and the six take about twenty seconds of the studio
build, most of what it costs.

### The dice as marks

**Each site's tab icon and each rulebook's cover die is one of these dice**
(the author, 2026-09-27), in place of the box's d12 solid (`box_art.d12_art`)
that both carried before: the d12ball site's is the teal pair's, the studio's
the orange pair's, and the books take the purple pair, one die each -- the
Learn to Play the Fortune, the Charter the Doom. A site's icon is the bright
Fortune die because the dark Doom is lost on a dark tab bar at 16 to 32
pixels. The d12ball page's nav shows its favicon beside the title, so the
nav's die is the teal one too. `dice.die_mark` draws a die cropped to itself
-- a render keeps a margin round the die for the table, which would shrink it
in a tab or in the cover's square -- and caches it, so a build draws each mark
once. The books' die is why the renderer moved from `landing/` to
`d12ball/`: `rulebooks.write_cover_dice` draws it, and nothing under
`d12ball/` imports `landing`. **The books' dice are committed pictures**,
`d12ball/images/cover_dice/`, redrawn by `scripts/build_rulebooks.py
--cover-dice` when the dice change (the author, 2026-09-27): shading one at
the cover's 300 dpi took about four seconds, paid on every book set, every
kit and every landing build, for a picture that never changes between them.
The PDF embeds the file as it is and the page's picture scales it down, so
setting a book needs no numpy and draws no die.

## Building and looking

```bash
python3 scripts/build_landing.py
python3 -m http.server -d landing/dist/d12ball 8000
python3 -m http.server -d landing/dist/studio 8001
```

Look at each at a desktop width (1280) and at 375, the narrowest phone the
page is held to: no horizontal scroll, the chips wrap, the hero's two buttons
stack. `http.server` does not read `_redirects`, so `/learn` is a 404 locally;
that is Cloudflare's to serve.

## Deploying

Both sites are Cloudflare Pages projects built from `main` by Cloudflare,
with Pages' Git integration -- nothing is uploaded from a machine. **Nothing
here is per checkout**: the projects, the domains, the redirects and the
analytics are all the author's Cloudflare account's, and a site is whatever
`main` builds. There is no secret in the repository and none on a host.

### What the repository guarantees the build

- **`python3 scripts/build_landing.py` with no arguments builds both
  sites**, and `--only <site>` one. **Any failure exits non-zero**: a
  refusal (a turn card that is not basic, a download over
  `PAGES_FILE_LIMIT`, a printed address the site does not serve) is a
  `ValueError`, the kit is a subprocess run with `check=True`, and nothing
  is caught -- so a broken build is a failed deploy, and the last good one
  stays up.
- **It runs from any working directory**: every path is resolved from
  `landing/build.py`'s own location, and the fonts by absolute path. Built
  from a scratch directory and from the root on 2026-09-27, the studio
  site's 21 files were byte-identical.
- **It installs on a clean Linux Python.** Every pin in `requirements.txt`
  has a manylinux wheel for 3.11 and 3.13 (checked 2026-09-27), so the
  install compiles nothing. numpy 2.4 needs Python 3.11 or later. From a
  fresh 3.13 virtualenv the install took about 12 seconds, and the build
  of both sites 68 seconds -- 49 MB and 2 MB, 59 files, the largest the
  first players' zip at 15 MB. Pages allows 20 minutes a build, 25 MiB a
  file and 20,000 files a site on the free plan.

### The checklist

Written 2026-09-27, before it has been run. Cloudflare's dashboard moves
its menus around; the names below are the shape, not a promise -- as in
[collaboration.md](collaboration.md), "Exposing the port". Pages is still
offered for a new project from Git, though Cloudflare now points new
projects at Workers with static assets and says Pages' new features stop
there. **Pages it is** (the author, 2026-09-27): for two static sites it is
less to set up -- no Wrangler config in the repository -- and does everything
these need, and moving a site of files and redirects to Workers later is a
config file, not a rewrite.

1. **Both domains are on Cloudflare**: `d12ball.com` and
   `propheticfoolsgames.com` listed as sites, each *Active*.
2. **Create the `d12ball` project**: Workers & Pages -> *Create* -> *Pages*
   -> *Connect to Git* -> `HolyTispoon/fool-bot` (this installs
   Cloudflare's GitHub app on the repository, if it is not already).
   - Production branch: `main`.
   - Framework preset: *None*.
   - Build command:
     `python3 -m pip install -r requirements.txt && python3 scripts/build_landing.py --only d12ball`.
     `python3 -m pip` rather than `pip`, so the install lands in the Python
     that runs the build.
   - Build output directory: `landing/dist/d12ball`. Root directory: blank.
   - Environment variable `PYTHON_VERSION` = `3.13`, the version the build
     was checked on. New projects get build image v3, whose default is
     3.13 already; naming it keeps a future default from changing the
     Python under the build unannounced.
3. **Create the `propheticfoolsgames` project** the same way, with
   `--only studio` and `landing/dist/studio`.
4. **On each project, build only what matters** (Settings -> Build):
   - *Branch control*: automatic production deployments on, **preview
     deployments *None***. Otherwise every pushed branch builds -- and
     this repository pushes a branch per task -- and each gets a public
     `*.pages.dev` address.
   - *Build watch paths*, include: `landing/*`, `d12ball/*`, `docs/*`,
     `scripts/*`, `requirements.txt`. The build reads the model, its
     catalogs and images, the Charter and the Learn to Play, and runs the
     kit's scripts; it never reads `cogs/`, `webapp/`, `gamesaves/`,
     `tests/` or `botlog/`, and a merge that touches only those is a build
     that would change nothing. The free plan is 500 builds a month with
     one at a time, and two projects build on every merge that passes the
     filter. A path left off the list is a site that silently stops
     following the game, so when the build starts reading somewhere new,
     add it here.
5. **Custom domains**: `d12ball.com` on the first project,
   `propheticfoolsgames.com` on the second (Custom domains -> *Set up a
   custom domain*). The zones are on the same account, so Cloudflare adds
   the DNS record itself on confirming; a record made by hand first gets a
   522. `play.d12ball.com`'s record is the tunnel's and is not touched.
6. **`www` to the bare domain**, on both: `_redirects` matches paths only,
   never a host, so this is Cloudflare's, not the site's. `www` needs a
   proxied DNS record for the redirect to answer on (Cloudflare's own
   "Redirecting www to domain apex" for Pages says which); then either the
   zone's Redirect Rule template for www to root, or an account-level Bulk
   Redirect, whichever the dashboard offers. Source `www.<domain>`, target
   `https://<domain>`, 301 (this one is permanent, unlike the site's own
   302s), with the query string preserved, subpath matching and the path
   suffix preserved, so `www.d12ball.com/rules` still lands on the book.
7. **"Always Use HTTPS"** on both zones (SSL/TLS -> Edge Certificates). On
   `d12ball.com` it may already be on from the tunnel.
8. **Web Analytics**, on each project: Metrics -> Web Analytics ->
   *Enable*. Pages adds the beacon itself on the next deployment, so the
   templates carry none; a snippet pasted into the page as well would be
   two beacons on one page, which Cloudflare's analytics does not support.
   The worksheet planned a build-time value for the snippet; the one-click
   setting made it unnecessary.
9. **Check from a phone off the home Wi-Fi**: both bare domains load;
   `www.` redirects to the bare one; `/play` reaches the app (once the
   tunnel is up); `/feedback` reaches the form; `/rules` and `/learn` open
   the books; `/kit`, `/kit-players-1` and `/kit-players-2` download; a
   link to each site pasted in a Discord message previews with the Open
   Graph card. And scan the sale sheet's and the playtest card's codes off
   a fresh print.
10. **Check what a browser is told to keep**:
    `curl -sI https://d12ball.com/site.css` and
    `https://d12ball.com/images/board.png`. The
    assets are unversioned names, so a long `max-age` is how a visitor
    gets a new page over an old stylesheet -- exactly what happened to the
    web app through the tunnel ([collaboration.md](collaboration.md),
    "Cloudflare keeps what the web app does not say about"). If Pages
    answers with one, a `_headers` file written by the build is the fix;
    it is not written until a response says it is needed.
11. **If a Pages build fails on the renders** and cannot be fixed in the
    repository, fall back to a GitHub Action on push to `main` that runs
    the same build and `wrangler pages deploy landing/dist/<site>
    --project-name <project>`, with `CLOUDFLARE_API_TOKEN` and
    `CLOUDFLARE_ACCOUNT_ID` as repository secrets -- the one case in which
    a secret exists, and it lives in GitHub, not in a checkout.

**Which path was taken, and anything the dashboard did differently, is
written here when the checklist has been run.** The `*.pages.dev`
addresses stay reachable after the domains are on; each page's canonical
link names its own domain (`ORIGINS`), so a search engine files the copy
under the right one.

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

`landing/dist/` is generated output and is gitignored, like `box/` and
`print/`.

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
  and the favicon, the box's d12 solid (`box_art.d12_art`) at 64px. There is no
  d12 PNG among `d12ball/images/`; the bot's d12 emoji is an application emoji
  fetched at runtime. Nothing is drawn under `landing/`.

What the code cannot answer is one constant each in `landing/build.py`, dated
where it is the author's call: the stage word (`STAGE`, "in playtesting",
2026-09-27), the contact address, the Discord invite, the studio's paragraph
(quoted from its Notion page as written), and each site's origin.

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
- **Each species' card shows a different role, asked of the roster, never
  named**: `SPECIES_FACE_ROLE` maps each species team to a role -- the Fire
  Demons' winger, the Cyborgs' playmaker, the Telekinetics' defender, the
  Oozes' fullback (Flickerwing, Synapse, Dravox and Goopkeeper as the roster
  stood, the author's four, 2026-09-27) -- and the face is the first player of
  that role in roster order. The worksheet's "goalkeeper" is not a role the
  game has. The roster order is the `player cards` tab's, so a re-sort there
  can change the face, as it changes who starts.

**A link says what it opens.** The two books are "Learn to Play" and "The
Charter: Laws of the Game" while `/learn` and `/rules` open the web app's
Reading Room, and gain "(PDF)" once the redirects point at PDFs (`book_title`
reads the target). The print-and-play card stands unlinked until the site
forwards `/kit`; adding that redirect is what links it (`kit_card_html`).

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

## Redirects

The addresses a site forwards are `REDIRECTS` in `landing/build.py`, written
into the build as Cloudflare Pages' `_redirects` file:

- `/play` -- the web app.
- `/learn` and `/rules` -- the web app's Reading Room, which carries both
  books in the page, until the build makes the PDFs and points them there.
- `/survey` -- `box_art.SURVEY_URL`, read rather than copied. The survey is a
  redirect so a form that moves is a one-line change here and no printed
  card is reprinted.

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

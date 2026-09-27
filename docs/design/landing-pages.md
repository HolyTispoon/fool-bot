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

## Redirects

The addresses a site forwards are `REDIRECTS` in `landing/build.py`, written
into the build as Cloudflare Pages' `_redirects` file. The D12 Ball site has
`/play` (the web app) and `/learn`, which forwards to the web app's Reading
Room -- it carries the Learn to Play in the page -- until the build makes the
PDF. The rest of the printed addresses come with the downloads.

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

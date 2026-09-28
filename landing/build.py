"""
Build the two landing pages into static files.

    python3 scripts/build_landing.py
    python3 scripts/build_landing.py --only d12ball --out /tmp/site

`build(site, out_dir)` fills `landing/<site>/index.html`, a plain
`string.Template`, with values read from the game, copies the
stylesheets and the display face beside it, and renders the pictures
the page shows through the renderers the box and the bot already use.
Nothing of the game is drawn here and nothing is typed that the game
can answer: the title, the publisher, the strapline and the chips are
`box_art`'s, the team colours `render.TEAM_COLORS`', the palette
`box_art.NIGHT_COVER`'s. The one picture composed here is the studio's
Prophetic Folly still, from d12ball/dice.py and the bot's coins. See
docs/design/landing-pages.md.
"""
from __future__ import annotations

import shutil
import subprocess
from contextlib import ExitStack
import sys
import tempfile
import zipfile
from datetime import date
from functools import lru_cache
from html import escape
from pathlib import Path
from string import Template

from PIL import Image, ImageFilter

from d12ball.box_art import (
    COVER_CAST,
    DEFAULT_CLAIMS,
    NIGHT_COVER,
    PAGE_URL,
    PLAYTEST_HEADLINE,
    PUBLISHER,
    SCREENTOP_BANNER_INCHES,
    STAGE,
    STRAPLINE,
    SURVEY_FORM_URL,
    SURVEY_URL,
    TITLE,
    BoxFacts,
    render_banner,
    render_box_cover,
    retail_chips,
)
from d12ball.cards import render_maneuver_card
from d12ball.components import (
    MANEUVER_TIER_BASIC,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.dice import ORANGE, PURPLE, TEAL, Die, die_mark, render_die
from d12ball.game import COLOR_TEAMS, Team, team_display_name
from d12ball.player_cards import render_player_card
from d12ball.render import FONT_DIR, TEAM_COLORS, species_icon
from d12ball.rulebooks import BOOKS, DEFAULT_PAPER, book_bytes
from d12ball.species_cards import SPECIES_TEAM
from landing.capture import BOARD_CAPTURE
from landing.covers import render_cover

LANDING_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = LANDING_DIR.parent
KIT_SCRIPT = PROJECT_ROOT / "scripts" / "generate_print_and_play_kit.py"
COIN_DIR = PROJECT_ROOT / "d12ball" / "images" / "emoji"
DIST_DIR = LANDING_DIR / "dist"
SITES = ("d12ball", "studio")

# Where each site is served. Only what a page has to spell out in full
# reads these -- the Open Graph image, the canonical link -- and every
# link inside a site stays relative, so a local build is browsable.
ORIGINS = {
    "d12ball": "https://d12ball.com",
    "studio": "https://propheticfoolsgames.com",
}
PLAY_URL = "https://play.d12ball.com"
CONTACT = "politicsgames@gmail.com"
DISCORD_INVITE = "https://discord.gg/MpgGm8FvKB"

# The studio's own paragraph, from its Notion page, as written -- the
# author's voice, which the page quotes rather than rewords. The studio
# page sets it as its headline with the two phrases the reviewed sketch
# lit in gold (`STUDIO_EMPHASIS`): the words are the paragraph's, only
# their weight is the page's.
STUDIO_PARAGRAPH = (
    "Prophetic Fools is a tabletop gaming studio creating meaningful and "
    "engaging play experiences. We make games that aim to capture a slice "
    "of the human experience, touching a wide array of topics that are "
    "often unusual, complex, or emotionally loaded. We design mechanics to "
    "match the theme to deliver compelling, immersive, and challenging "
    "interactions that invite repeat play."
)
STUDIO_EMPHASIS = ("capture a slice of the human experience", "mechanics to match the theme")

# D12 Ball's overview, the line from the game's Notion page, as written.
# The d12ball page opens "What it is" with it after the title; the
# studio's card for the game carries it as a sentence of its own.
OVERVIEW = (
    "a fast playing fantasy sports game with tense last-ditch efforts and "
    "dramatic comebacks, where two teams of fantasy creatures compete by "
    "maneuvering around the field, manipulating the ball and outwitting "
    "the other team on their way to score epic goals."
)

# Prophetic Folly, the studio's other game, which lives on the studio's
# Notion site. Its stage word is the author's (2026-09-27); the callout
# is its Notion page's, and the paragraph on the mechanic the author's,
# written on the canvas. The card links out: the author made the Notion
# page public on the worksheet's PR (2026-09-27).
FOLLY_TITLE = "Prophetic Folly"
FOLLY_STAGE = "in development"
FOLLY_URL = "https://propheticfools.notion.site/"
FOLLY_CALLOUT = (
    "A streamlined tabletop roleplaying system, providing a robust "
    "mechanics for action resolution with lots of flexibility for "
    "narrative driven interactions."
)
FOLLY_MECHANIC = (
    "A novel action resolution based on two twelve-sided dice: a Fortune "
    "die and a Doom die. Rolling with Hope makes it possible to beat "
    "challenges you wouldn't otherwise be able to face but is overall less "
    "successful. Rolling with Fear makes spectacular successes less likely "
    "but also avoids catastrophic failures."
)

# The two books the site hands out, built by this build into
# `downloads/`: the address that is printed, the book in
# `rulebooks.BOOKS`, and the file's name, which says what it is once it
# is sitting in somebody's downloads folder. The page's rulebooks card
# shows each book's cover in this order.
BOOK_DOWNLOADS: tuple[tuple[str, str, str], ...] = (
    ("/learn", "learn-to-play", "d12ball-learn-to-play.pdf"),
    ("/rules", "charter", "d12ball-charter.pdf"),
)
DOWNLOADS_DIR = "downloads"

# The print-and-play kit, in parts because the whole is over the 25 MB a
# file on Cloudflare Pages may be. The author's split (2026-09-27): the
# player cards apart from the boards and the other components, the
# sheets kept as PNG. The player sheets alone are over the limit too, so
# they are split again by team, each team's standard and advanced
# sheets together so a team prints duplex from one download. Every part
# unzips into the one folder, `KIT_DIR`, and together they are the kit.
# Each entry is the address, the zip's name, and the colour teams whose
# player sheets it carries; the first, with none, carries everything
# that is not a team's.
KIT_DIR = "d12ball-print-and-play"
KIT_DOWNLOADS: tuple[tuple[str, str, tuple[Team, ...]], ...] = (
    ("/kit", f"{KIT_DIR}.zip", ()),
    *(
        (
            f"/kit-players-{number}",
            f"{KIT_DIR}-players-{'-'.join(team.value for team in teams)}.zip",
            teams,
        )
        for number, teams in enumerate((COLOR_TEAMS[:2], COLOR_TEAMS[2:]), start=1)
    ),
)
# The most a single file on Cloudflare Pages may be. The build refuses a
# download over it, rather than the deploy.
PAGES_FILE_LIMIT = 25 * 1024 * 1024

# The addresses a site owns and forwards, Cloudflare Pages' `_redirects`
# format. `/learn` and `/rules` open the books' PDFs and `/kit` and
# `/kit-players-<n>` the kit's zips, which the build makes. The survey
# is a redirect so the form can move without a card being reprinted:
# the card prints `SURVEY_URL`, and this forwards it to the form.
REDIRECTS: dict[str, tuple[tuple[str, str], ...]] = {
    "d12ball": (
        ("/play", PLAY_URL),
        *((source, f"/{DOWNLOADS_DIR}/{filename}") for source, _, filename in BOOK_DOWNLOADS),
        *((source, f"/{DOWNLOADS_DIR}/{filename}") for source, filename, _ in KIT_DOWNLOADS),
        ("/feedback", SURVEY_FORM_URL),
    ),
    "studio": (),
}

# The addresses the box art prints -- the sale sheet's QR and the
# playtest card's. Each is the d12ball site's own and must be one it
# serves, the page or a redirect; the build refuses one that is not,
# because a printed address that goes nowhere is found by somebody
# holding the card.
PRINTED_ADDRESSES = (PAGE_URL, SURVEY_URL)

# The three beats of "How a turn goes", each over one maneuver's card.
# All three are basic cards -- the beats describe a basic turn, and a
# gambit is held only by a coach who is behind (the author, 2026-09-27);
# the build refuses one that is not. Pressure under the defence's beat
# is the card the Resolution beat names ("a low pass beats pressure").
TURN_CARDS = ("low_pass", "pressure", "high_pass")


# The species in the order the page shows them, with the author's line
# for each; the name and the colour are read from the team.
SPECIES_LINES: tuple[tuple[str, str], ...] = (
    ("fire_demon",
     "Can ignite the ball for explosive successes as well as catastrophic burns."),
    ("cyborg",
     "Can overcharge for a significant boost, but only if they get charged "
     "up enough to keep up with the energy cost."),
    ("telekinetic",
     "Be careful when you go by them, because they may just pull the ball "
     "away from you."),
    ("ooze",
     "Most players get assigned to just one space, but these oozes tend to "
     "spread around on as many as they want."),
)

# Discord's mark, for the two links to the invite. One copy, filled in
# wherever the template asks for it.
DISCORD_MARK = (
    '<svg viewBox="0 0 127.14 96.36" aria-hidden="true" focusable="false">'
    '<path d="M107.7,8.07A105.15,105.15,0,0,0,81.47,0a72.06,72.06,0,0,0-3.36,'
    '6.83A97.68,97.68,0,0,0,49,6.83,72.37,72.37,0,0,0,45.64,0,105.89,105.89,'
    '0,0,0,19.39,8.09C2.79,32.65-1.71,56.6.54,80.21h0A105.73,105.73,0,0,0,'
    '32.71,96.36,77.7,77.7,0,0,0,39.6,85.25a68.42,68.42,0,0,1-10.85-5.18c.91'
    '-.66,1.8-1.34,2.66-2a75.57,75.57,0,0,0,64.32,0c.87.71,1.76,1.39,2.66,2a'
    '68.68,68.68,0,0,1-10.87,5.19,77,77,0,0,0,6.89,11.1A105.25,105.25,0,0,0,'
    '126.6,80.22h0C129.24,52.84,122.09,29.11,107.7,8.07ZM42.45,65.69C36.18,'
    '65.69,31,60,31,53s5-12.74,11.43-12.74S54,46,53.89,53,48.84,65.69,42.45,'
    '65.69Zm42.24,0C78.41,65.69,73.25,60,73.25,53s5-12.74,11.44-12.74S96.23,'
    '46,96.12,53,91.08,65.69,84.69,65.69Z"/></svg>'
)

# Prophetic Folly's picture: three pairs of Fortune and Doom dice
# (d12ball/dice.py) close together -- orange and purple behind, teal in
# front -- with the bot's six coins round them, turned a little, the
# fortune faces on the Fortune side and the doom faces on the Doom
# side. The sketch the author reviewed had one pair; the author asked
# for three, close together (2026-09-27). The layers are drawn back to
# front: a die is its render, the size it is drawn at and its top-left
# corner; a coin its file in d12ball/images/emoji (one of which is
# named with spaces), its centre, its width and how far it is turned.
# Every position is in `FOLLY_STILL_SIZE`.
FOLLY_STILL_SIZE = (1600, 640)
FOLLY_STILL_WIDTH = 1200
FOLLY_DIE_PIXELS = 400
FOLLY_STILL = (
    (ORANGE.fortune, 360, (300, 0)),
    (ORANGE.doom, 360, (500, 20)),
    (PURPLE.fortune, 360, (780, 20)),
    (PURPLE.doom, 360, (980, 0)),
    ("3 bronze fortune.png", (400, 375), 115, 8),
    ("1_gold_doom.png", (1200, 375), 115, -6),
    ("3_gold_fortune.png", (455, 495), 120, -7),
    ("3_silver_doom.png", (1140, 495), 120, 6),
    (TEAL.fortune, 410, (470, 215)),
    (TEAL.doom, 410, (720, 235)),
    ("1_silver_fortune.png", (560, 590), 110, 5),
    ("1_bronze_doom.png", (1045, 590), 110, -5),
)
# The two coins at the foot of the box in the studio's hero.
HERO_COINS = ("1_gold_fortune.png", "1_gold_doom.png")

NUMBER_WORDS = (
    "no", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve",
)

DISPLAY_FONT = "RacingSansOne-Regular.ttf"
DISPLAY_FONT_LICENCE = "RacingSansOne-OFL.txt"

BANNER_WIDTHS = (1500, 3000)
COVER_WIDTH = 1200
SPECIES_ICON_PIXELS = 96
# Cards are shown about 200px wide; twice that keeps them sharp.
CARD_PIXELS = 400
# A book's cover is shown about 130px wide on the rulebooks card.
BOOK_COVER_PIXELS = 320
FAVICON_PIXELS = 64
# Each site's tab icon, which the d12ball page's nav shows beside the
# title too: the bright die of one of Folly's pairs -- teal for the game,
# orange for the studio (the author, 2026-09-27). The dark die of a pair
# is lost on a dark tab bar at this size.
FAVICONS = {"d12ball": TEAL.fortune, "studio": ORANGE.fortune}
COIN_SHADOW_PAD = 30
COIN_SHADOW_DROP = 10
COIN_SHADOW_BLUR = 10
JPEG_QUALITY = 85


# ------------------------------------------------------------ the game

@lru_cache(maxsize=None)
def game() -> tuple:
    """The catalog, the ruleset and `BoxFacts`, read once per build."""
    catalog = load_player_catalog()
    rules = load_basic_ruleset()
    return catalog, rules, BoxFacts.read(catalog=catalog, rules=rules)


@lru_cache(maxsize=None)
def maneuvers():
    return load_maneuver_catalog()


def chips() -> list[str]:
    """The box's own three chips: how many, how long, how old."""
    return retail_chips(game()[2], DEFAULT_CLAIMS)


def number_word(count: int) -> str:
    """A count as the page writes it in a sentence -- "nine players" --
    so the author's sentence can carry the game's number."""
    return NUMBER_WORDS[count] if count < len(NUMBER_WORDS) else str(count)


def species_face(species: str):
    """
    The player whose card stands for `species` under "The teams": the
    one of the box cover's four (`box_art.COVER_CAST`) on that species'
    team, so the page and the box show the same four and cannot drift.
    The build refuses a cast with nobody of the species on it.
    """
    team = SPECIES_TEAM[species]
    cast = {name for name, _ in COVER_CAST.players}
    found = [
        player for player in game()[0].teams[team].players
        if player.name in cast
    ]
    if len(found) != 1:
        raise SystemExit(
            f"the box cover's cast has {len(found)} players on the "
            f"{team.value} roster; the page shows exactly one of each species"
        )
    return found[0]


# --------------------------------------------------------- the pictures

@lru_cache(maxsize=None)
def night_banner() -> Image.Image:
    catalog, rules, facts = game()
    return render_banner(
        facts=facts, catalog=catalog, rules=rules, palette=NIGHT_COVER,
    ).convert("RGB")


@lru_cache(maxsize=None)
def open_graph_banner() -> Image.Image:
    # The 16:9 one a Screentop table asks for: a link preview crops a
    # 2.5:1 banner to a sliver, and this one is the same composition
    # laid out for nearly the shape a preview draws.
    catalog, rules, facts = game()
    return render_banner(
        facts=facts, catalog=catalog, rules=rules, palette=NIGHT_COVER,
        size=SCREENTOP_BANNER_INCHES,
    ).convert("RGB")


@lru_cache(maxsize=None)
def night_cover() -> Image.Image:
    catalog, rules, facts = game()
    return render_box_cover(
        facts=facts, catalog=catalog, rules=rules, claims=DEFAULT_CLAIMS,
        palette=NIGHT_COVER,
    ).convert("RGB")


def write_jpeg(image: Image.Image, path: Path, width: int | None = None) -> None:
    if width is not None and image.width != width:
        height = round(image.height * width / image.width)
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)


def write_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)


def write_shared_pictures(out: Path) -> None:
    """What both sites show: the banner, the night cover and the preview
    card."""
    for width in BANNER_WIDTHS:
        write_jpeg(night_banner(), out / "images" / f"banner-{width}.jpg", width)
    write_jpeg(night_cover(), out / "images" / "cover-night.jpg", COVER_WIDTH)
    write_jpeg(open_graph_banner(), out / "images" / "og.jpg")


def fit_width(image: Image.Image, width: int) -> Image.Image:
    height = round(image.height * width / image.width)
    return image.resize((width, height), Image.Resampling.LANCZOS)


def write_d12ball_pictures(out: Path) -> None:
    """The d12ball page's own pictures: the board the web app draws (the
    committed capture, landing/capture.py), the three maneuver cards
    under "How a turn goes", and a player card per species."""
    shutil.copyfile(BOARD_CAPTURE, out / "images" / "board.png")
    catalog = game()[0]
    for key in TURN_CARDS:
        maneuver = maneuvers().get(key)
        if maneuver.tier != MANEUVER_TIER_BASIC:
            raise ValueError(f"{key} is not a basic card; the turn is a basic one")
        card = render_maneuver_card(
            maneuvers(), catalog, maneuver,
            is_offense=maneuvers().side_of(key) == "offense", bleed=False,
        )
        write_png(fit_width(card, CARD_PIXELS), out / "images" / "cards" / f"{key}.png")
    for species, _ in SPECIES_LINES:
        card = render_player_card(
            catalog, species_face(species), SPECIES_TEAM[species], bleed=False,
        )
        write_png(fit_width(card, CARD_PIXELS), out / "images" / "players" / f"{species}.png")
    write_species_icons(out)
    write_book_covers(out)


def write_book_covers(out: Path) -> None:
    """Each book's cover, as its PDF's first page draws it
    (landing/covers.py)."""
    for _, name, _ in BOOK_DOWNLOADS:
        cover = render_cover(BOOKS[name].cover, BOOK_COVER_PIXELS, DEFAULT_PAPER)
        write_png(cover, out / "images" / "books" / f"{name}.png")


def write_downloads(out: Path) -> None:
    """The two books as PDFs, on letter paper, set by the same code
    `scripts/build_rulebooks.py` runs, and the print-and-play kit."""
    for _, name, filename in BOOK_DOWNLOADS:
        path = out / DOWNLOADS_DIR / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(book_bytes(BOOKS[name], DEFAULT_PAPER))
    write_kit(out / DOWNLOADS_DIR)


def kit_part(relative: Path) -> int:
    """Which of `KIT_DOWNLOADS` a file of the kit goes in: a team's
    player sheet goes with its team, and everything else in the first."""
    if relative.parts[0] == "player-cards":
        for index, (_, _, teams) in enumerate(KIT_DOWNLOADS):
            if any(relative.name.startswith(f"{team.value}-") for team in teams):
                return index
        raise ValueError(f"{relative} is no colour team's sheet")
    return 0


def write_kit(downloads: Path) -> None:
    """The kit as `scripts/generate_print_and_play_kit.py` builds it,
    zipped in the parts `KIT_DOWNLOADS` names."""
    with tempfile.TemporaryDirectory() as scratch:
        kit = Path(scratch) / KIT_DIR
        subprocess.run(
            [sys.executable, str(KIT_SCRIPT), "--out", str(kit)],
            check=True, cwd=PROJECT_ROOT, stdout=subprocess.DEVNULL,
        )
        downloads.mkdir(parents=True, exist_ok=True)
        with ExitStack() as stack:
            archives = [
                stack.enter_context(
                    zipfile.ZipFile(downloads / filename, "w", zipfile.ZIP_DEFLATED)
                )
                for _, filename, _ in KIT_DOWNLOADS
            ]
            for path in sorted(kit.rglob("*")):
                if path.is_file():
                    relative = path.relative_to(kit)
                    archives[kit_part(relative)].write(path, Path(KIT_DIR) / relative)
    for _, filename, _ in KIT_DOWNLOADS:
        size = (downloads / filename).stat().st_size
        if size > PAGES_FILE_LIMIT:
            raise ValueError(
                f"{filename} is {size / 2**20:.1f} MB, over the "
                f"{PAGES_FILE_LIMIT / 2**20:.0f} MB a Pages file may be"
            )


def coin(filename: str, width: int, angle: float) -> Image.Image:
    """One of the bot's coins at `width`, turned `angle` degrees, with a
    soft shadow under it so it lies on the table with the dice."""
    face = Image.open(COIN_DIR / filename).convert("RGBA")
    face = fit_width(face, width).rotate(
        angle, resample=Image.Resampling.BICUBIC, expand=True,
    )
    pad = COIN_SHADOW_PAD
    shadow = Image.new("RGBA", face.size, (0, 0, 0, 0))
    shadow.putalpha(face.getchannel("A").point(lambda value: value * 150 // 255))
    lying = Image.new("RGBA", (face.width + 2 * pad, face.height + 2 * pad), (0, 0, 0, 0))
    lying.alpha_composite(shadow, (pad, pad + COIN_SHADOW_DROP))
    lying = lying.filter(ImageFilter.GaussianBlur(COIN_SHADOW_BLUR))
    lying.alpha_composite(face, (pad, pad))
    return lying


def folly_still() -> Image.Image:
    """Prophetic Folly's picture: `FOLLY_STILL`'s dice and coins,
    composed back to front on a transparent ground, which the card's
    panel shows through."""
    still = Image.new("RGBA", FOLLY_STILL_SIZE, (0, 0, 0, 0))
    for layer in FOLLY_STILL:
        if isinstance(layer[0], Die):
            die, size, corner = layer
            drawn = render_die(die, FOLLY_DIE_PIXELS)
            still.alpha_composite(drawn.resize((size, size), Image.Resampling.LANCZOS), corner)
        else:
            filename, (x, y), width, angle = layer
            piece = coin(filename, width, angle)
            still.alpha_composite(piece, (x - piece.width // 2, y - piece.height // 2))
    return still


def write_studio_pictures(out: Path) -> None:
    """The studio page's own pictures: Prophetic Folly's still, and the
    two coins at the foot of the box in the hero. The banner and the
    cover are the shared ones."""
    write_png(fit_width(folly_still(), FOLLY_STILL_WIDTH), out / "images" / "folly.png")
    for filename in HERO_COINS:
        write_png(Image.open(COIN_DIR / filename), out / "images" / "coins" / filename)


def write_species_icons(out: Path) -> None:
    """Each species' icon in its colour team's hex, which is the one
    `render.species_icon` is asked for everywhere else."""
    for species, team in SPECIES_TEAM.items():
        icon = species_icon(species, TEAM_COLORS[team], SPECIES_ICON_PIXELS)
        if icon is not None:
            write_png(icon, out / "images" / "species" / f"{species}.png")


# ------------------------------------------------------------ the styles

def colours_css() -> str:
    """The palette as custom properties, written from the renderer's own
    values so no hex is typed twice."""
    palette = {
        "ground": NIGHT_COVER.ground,
        "ink": NIGHT_COVER.ink,
        "muted": NIGHT_COVER.muted,
        "accent": NIGHT_COVER.accent,
        "edge": NIGHT_COVER.edge,
    }
    lines = [
        "/* Written by landing/build.py from box_art.NIGHT_COVER and",
        "   render.TEAM_COLORS. Do not edit; change those. */",
        ":root {",
    ]
    lines += [f"  --{name}: {value};" for name, value in palette.items()]
    lines += [
        f"  --team-{team.value.replace('_', '-')}: {TEAM_COLORS[team]};"
        for team in TEAM_COLORS
    ]
    lines.append("}")
    return "\n".join(lines) + "\n"


def copy_styles(site: str, out: Path) -> None:
    for stylesheet in sorted((LANDING_DIR / "shared").glob("*.css")):
        shutil.copyfile(stylesheet, out / stylesheet.name)
    shutil.copyfile(LANDING_DIR / site / "site.css", out / "site.css")
    (out / "colours.css").write_text(colours_css(), encoding="utf-8")
    # The display face is the bot's own, served as the TTF it is bundled
    # as: the OFL lets it be redistributed unmodified beside its
    # licence, and a converted woff2 would be a second file to keep in
    # step with the first. The text faces, IBM Plex, are the pages'
    # alone and live in landing/shared/fonts/ as IBM ships them.
    fonts = out / "fonts"
    fonts.mkdir(exist_ok=True)
    for name in (DISPLAY_FONT, DISPLAY_FONT_LICENCE):
        shutil.copyfile(FONT_DIR / name, fonts / name)
    for font in sorted((LANDING_DIR / "shared" / "fonts").iterdir()):
        shutil.copyfile(font, fonts / font.name)


# ------------------------------------------------------------ the pages

def chip_html(words: str, quiet: bool = False) -> str:
    kind = "chip chip-quiet" if quiet else "chip"
    return f'<span class="{kind}">{escape(words)}</span>'


def common_values(site: str) -> dict[str, str]:
    return {
        "origin": ORIGINS[site],
        "ground": NIGHT_COVER.ground,
        "publisher": escape(PUBLISHER),
        "contact": escape(CONTACT),
        "discord": escape(DISCORD_INVITE),
        "year": str(date.today().year),
    }


def redirect_target(site: str, source: str) -> str | None:
    return dict(REDIRECTS[site]).get(source)


def book_title(source: str, title: str) -> str:
    """A book's link text, which says "(PDF)" when the address is
    forwarded to one: a link says what it opens."""
    target = redirect_target("d12ball", source) or ""
    return f"{title} (PDF)" if target.endswith(".pdf") else title


# What the rulebooks card calls each book, by the address it links.
BOOK_TITLES = {
    "/learn": "Learn to Play",
    "/rules": "The Charter: Laws of the Game",
}


def book_links_html() -> str:
    """The rulebooks card's two covers, each a link to its book with
    only its title under it."""
    links = []
    for source, name, _ in BOOK_DOWNLOADS:
        title = escape(book_title(source, BOOK_TITLES[source]))
        links.append(
            f'<a class="book" href="{source}">\n'
            f'  <img src="images/books/{name}.png" width="{BOOK_COVER_PIXELS}" '
            f'alt="{escape(BOOKS[name].title)}, the cover">\n'
            f'  <span>{title}</span>\n'
            '</a>'
        )
    return "\n".join(links)


def turn_card_html(number: int, key: str, heading: str, words: str) -> str:
    name = escape(maneuvers().get(key).name)
    return (
        '<article class="card turn-card">\n'
        f'  <p class="turn-step">{number}. {escape(heading)}</p>\n'
        f'  <img src="images/cards/{key}.png" width="{CARD_PIXELS}" '
        f'alt="The {name} maneuver card">\n'
        f'  <p>{escape(words)}</p>\n'
        '</article>'
    )


def species_card_html(species: str, line: str) -> str:
    team = SPECIES_TEAM[species]
    player = species_face(species)
    team_name = escape(team_display_name(team))
    role = escape(player.role.value)
    return (
        '<article class="card species-card">\n'
        f'  <img class="player-card" src="images/players/{species}.png" '
        f'width="{CARD_PIXELS}" alt="{escape(player.name)}, {team_name} {role}">\n'
        '  <div class="species-row">\n'
        f'    <img src="images/species/{species}.png" width="32" height="32" alt="">\n'
        f'    <span>{team_name}</span>\n'
        f'    <span class="swatch" style="background: var(--team-{team.value.replace("_", "-")})"></span>\n'
        '  </div>\n'
        f'  <p>{escape(line)}</p>\n'
        '</article>'
    )


def team_names(teams: tuple[Team, ...]) -> str:
    return " and ".join(team_display_name(team) for team in teams)


def kit_link_text(teams: tuple[Team, ...]) -> str:
    if not teams:
        return "Boards and components (zip)"
    return f"Player cards: {team_names(teams)} (zip)"


def kit_card_html() -> str:
    """The print-and-play card, with a link to each of the kit's zips,
    each saying what is in it."""
    links = "".join(
        f'    <a class="way-link" href="{source}">{escape(kit_link_text(teams))}</a>\n'
        for source, _, teams in KIT_DOWNLOADS
    )
    return (
        '<div class="card way-card">\n'
        '  <span class="way-title">At the table</span>\n'
        '  <span class="way-words">Get the print-and-play kit. Meeples and '
        'd12s not included. 3D files for printing tokens are available on '
        'request.</span>\n'
        f'  <span class="way-links">\n{links}  </span>\n'
        '</div>'
    )


# The three beats, as the author wrote them on the canvas (2026-09-27).
TURN_BEATS = (
    ("The offense chooses its action",
     "When you're close enough to the opponent's goal you can try to "
     "score, but for most of the game players maneuver: choosing one of "
     "three possible actions to handle the ball."),
    ("The defense challenges",
     "The defending coach secretly picks a maneuver of their own. Both "
     "sides reveal their choice simultaneously."),
    ("Resolution",
     "The maneuvers relate to each other in a rock-paper-scissors cycle of "
     "priority: a low pass beats pressure, which beats a dribble, and "
     "so forth. In case of a tie in rank, players engage in an exhausting "
     "skill test, rolling d12s until one side gains the upper hand, or "
     "tentacle!"),
)


def d12ball_values() -> dict[str, str]:
    facts = game()[2]
    chip_row = [chip_html(words) for words in chips()]
    chip_row.append(chip_html(STAGE.upper(), quiet=True))
    turn_cards = [
        turn_card_html(number, key, heading, words)
        for number, (key, (heading, words)) in enumerate(
            zip(TURN_CARDS, TURN_BEATS), start=1,
        )
    ]
    return {
        **common_values("d12ball"),
        "title": escape(TITLE),
        "strapline": escape(STRAPLINE),
        "chips": "\n        ".join(chip_row),
        "stage": escape(STAGE),
        "playtest_headline": escape(PLAYTEST_HEADLINE, quote=False),
        "play": escape(PLAY_URL),
        "studio_origin": ORIGINS["studio"],
        "turn_cards": "\n".join(turn_cards),
        "species_count": number_word(facts.species).capitalize(),
        "species_word": number_word(facts.species),
        "teams_word": number_word(facts.teams),
        "colour_teams_count": number_word(len(COLOR_TEAMS)).capitalize(),
        "overview": escape(f"{TITLE} is {OVERVIEW}"),
        "players_count": number_word(facts.players_per_team).capitalize(),
        "fielded_word": number_word(facts.fielded),
        "bench_word": number_word(facts.players_per_team - facts.fielded),
        "species_cards": "\n".join(
            species_card_html(species, line) for species, line in SPECIES_LINES
        ),
        "kit_card": kit_card_html(),
        "books": book_links_html(),
        "hero_learn": book_title("/learn", "Learn to play"),
        "discord_mark": DISCORD_MARK,
    }


def emphasised(text: str, phrases: tuple[str, ...]) -> str:
    """`text` escaped, with each of `phrases` set in `<em>`. A phrase
    the text does not hold is an error: the paragraph is quoted, so a
    phrase that no longer matches means it was reworded."""
    html = escape(text)
    for phrase in phrases:
        if escape(phrase) not in html:
            raise ValueError(f"{phrase!r} is not in the paragraph")
        html = html.replace(escape(phrase), f"<em>{escape(phrase)}</em>", 1)
    return html


def site_address(origin: str) -> str:
    """How a link to another site reads: its bare domain."""
    return origin.split("://", 1)[1]


def studio_values() -> dict[str, str]:
    game_chips = [chip_html(words) for words in chips()]
    return {
        **common_values("studio"),
        "paragraph": emphasised(STUDIO_PARAGRAPH, STUDIO_EMPHASIS),
        "description": escape(STUDIO_PARAGRAPH.split(". ")[0] + "."),
        "title": escape(TITLE),
        "game_origin": ORIGINS["d12ball"],
        "game_address": escape(site_address(ORIGINS["d12ball"])),
        "game_stage": chip_html(STAGE.upper(), quiet=True),
        "game_overview": escape(OVERVIEW[0].upper() + OVERVIEW[1:]),
        "game_chips": "\n            ".join(game_chips),
        "folly_title": escape(FOLLY_TITLE),
        "folly_url": escape(FOLLY_URL),
        "folly_stage": chip_html(FOLLY_STAGE.upper(), quiet=True),
        "folly_callout": escape(FOLLY_CALLOUT),
        "folly_mechanic": escape(FOLLY_MECHANIC),
        "hero_coins": "\n      ".join(
            f'<img class="hero-coin hero-coin-{number}" src="images/coins/{filename}" alt="">'
            for number, filename in enumerate(HERO_COINS, start=1)
        ),
    }


VALUES = {"d12ball": d12ball_values, "studio": studio_values}


def redirects_file(site: str) -> str:
    return "".join(
        f"{source} {target} 302\n" for source, target in REDIRECTS[site]
    )


def unserved_printed_addresses() -> list[str]:
    """The printed addresses the d12ball site does not serve: off its
    origin, or a path that is neither the page nor a redirect."""
    origin = ORIGINS["d12ball"]
    unserved = []
    for address in PRINTED_ADDRESSES:
        path = address[len(origin):] if address.startswith(origin) else None
        if path is None or (path not in ("", "/") and redirect_target("d12ball", path) is None):
            unserved.append(address)
    return unserved


def build(site: str, out_dir: Path) -> Path:
    """Build one site into `out_dir`, which is created if it is missing.
    Returns the directory."""
    if site not in SITES:
        raise ValueError(f"no site {site!r}; the sites are {', '.join(SITES)}")
    if site == "d12ball" and (unserved := unserved_printed_addresses()):
        raise ValueError(
            f"the box art prints {', '.join(unserved)}, which {ORIGINS[site]} "
            "does not serve; add a redirect to REDIRECTS"
        )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    template = Template((LANDING_DIR / site / "index.html").read_text(encoding="utf-8"))
    (out / "index.html").write_text(
        template.substitute(VALUES[site]()), encoding="utf-8",
    )
    copy_styles(site, out)
    write_shared_pictures(out)
    write_png(die_mark(FAVICONS[site], FAVICON_PIXELS), out / "favicon.png")
    if site == "d12ball":
        write_d12ball_pictures(out)
        write_downloads(out)
    if site == "studio":
        write_studio_pictures(out)
    if REDIRECTS[site]:
        (out / "_redirects").write_text(redirects_file(site), encoding="utf-8")
    return out


def main(sites=SITES, out_root: Path = DIST_DIR) -> None:
    for site in sites:
        out = build(site, Path(out_root) / site)
        print(f"built {site} into {out}")

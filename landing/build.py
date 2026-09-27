"""
Build the two landing pages into static files.

    python3 scripts/build_landing.py
    python3 scripts/build_landing.py --only d12ball --out /tmp/site

`build(site, out_dir)` fills `landing/<site>/index.html`, a plain
`string.Template`, with values read from the game, copies the
stylesheets and the display face beside it, and renders the pictures
the page shows through the renderers the box and the bot already use.
Nothing is drawn here and nothing is typed that the game can answer:
the title, the publisher, the strapline and the chips are
`box_art`'s, the team colours `render.TEAM_COLORS`', the palette
`box_art.NIGHT_COVER`'s. See docs/design/landing-pages.md.
"""
from __future__ import annotations

import shutil
from datetime import date
from functools import lru_cache
from html import escape
from pathlib import Path
from string import Template

from PIL import Image

from d12ball.box_art import (
    DEFAULT_CLAIMS,
    NIGHT_COVER,
    PUBLISHER,
    SCREENTOP_BANNER_INCHES,
    STRAPLINE,
    SURVEY_URL,
    TITLE,
    BoxFacts,
    d12_art,
    render_banner,
    render_box_cover,
    retail_chips,
)
from d12ball.cards import render_maneuver_card
from d12ball.components import (
    MANEUVER_TIER_BASIC,
    PlayerRole,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import COLOR_TEAMS, Team, team_display_name
from d12ball.player_cards import render_player_card
from d12ball.render import FONT_DIR, TEAM_COLORS, species_icon
from d12ball.rulebooks import BOOKS, DEFAULT_PAPER, book_bytes
from d12ball.species_cards import SPECIES_TEAM
from landing.capture import BOARD_CAPTURE
from landing.covers import render_cover

LANDING_DIR = Path(__file__).resolve().parent
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

# The stage the game is at, in the author's word (2026-09-27). Not a
# fact the code can answer, so it is one constant with a date on it,
# as `DEFAULT_CLAIMS` is.
STAGE = "in playtesting"

# The studio's own paragraph, from its Notion page, as written -- the
# author's voice, which the page quotes rather than rewords.
STUDIO_PARAGRAPH = (
    "Prophetic Fools is a tabletop gaming studio creating meaningful and "
    "engaging play experiences. We make games that aim to capture a slice "
    "of the human experience, touching a wide array of topics that are "
    "often unusual, complex, or emotionally loaded. We design mechanics to "
    "match the theme to deliver compelling, immersive, and challenging "
    "interactions that invite repeat play."
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

# The addresses a site owns and forwards, Cloudflare Pages' `_redirects`
# format. `/learn` and `/rules` open the books' PDFs, which the build
# makes. The survey is a redirect so it can move without a card being
# reprinted. `/kit` is not here: the kit's zip is over the 25 MB a
# Pages file may be, and where it lives instead is the author's call
# (step 3 of docs/landing-pages.md); its card stands unlinked until then.
REDIRECTS: dict[str, tuple[tuple[str, str], ...]] = {
    "d12ball": (
        ("/play", PLAY_URL),
        *((source, f"/{DOWNLOADS_DIR}/{filename}") for source, _, filename in BOOK_DOWNLOADS),
        ("/survey", SURVEY_URL),
    ),
    "studio": (),
}

# The three beats of "How a turn goes", each over one maneuver's card.
# All three are basic cards -- the beats describe a basic turn, and a
# gambit is held only by a coach who is behind (the author, 2026-09-27);
# the build refuses one that is not. Pressure under the defence's beat
# is the card the Resolution beat names ("a low pass beats pressure").
TURN_CARDS = ("low_pass", "pressure", "high_pass")

# Whose card stands for each species under "The teams": a different
# role for each, so the four cards show four roles (the author,
# 2026-09-27 -- Flickerwing, Synapse, Dravox and Goopkeeper as the
# roster stood). Asked of the roster as the first player of that role in
# roster order, never by id or name, so a roster revision moves it.
SPECIES_FACE_ROLE: dict[Team, PlayerRole] = {
    Team.FIRE_DEMONS: PlayerRole.WINGER,
    Team.CYBORGS: PlayerRole.PLAYMAKER,
    Team.TELEKINETICS: PlayerRole.DEFENDER,
    Team.OOZES: PlayerRole.FULLBACK,
}

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
    """The player whose card stands for `species` (`SPECIES_FACE_ROLE`)."""
    team = SPECIES_TEAM[species]
    role = SPECIES_FACE_ROLE[team]
    return next(
        player for player in game()[0].teams[team].players
        if player.role == role
    )


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
    """What both sites show: the banner, the night cover, the preview
    card, and the d12 as the tab's icon."""
    for width in BANNER_WIDTHS:
        write_jpeg(night_banner(), out / "images" / f"banner-{width}.jpg", width)
    write_jpeg(night_cover(), out / "images" / "cover-night.jpg", COVER_WIDTH)
    write_jpeg(open_graph_banner(), out / "images" / "og.jpg")
    # The bot's own d12 is an application emoji fetched at runtime and
    # there is no d12 PNG among d12ball/images, so the icon is the
    # box's solid, drawn at the size a tab asks for.
    write_png(d12_art(FAVICON_PIXELS), out / "favicon.png")


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
    `scripts/build_rulebooks.py` runs."""
    for _, name, filename in BOOK_DOWNLOADS:
        path = out / DOWNLOADS_DIR / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(book_bytes(BOOKS[name], DEFAULT_PAPER))


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


def kit_card_html() -> str:
    """The print-and-play card, which links once the site forwards
    `/kit` to the kit (step 3) and stands unlinked until then."""
    words = (
        '<span class="way-title">At the table</span>\n'
        '  <span class="way-words">Get the print-and-play kit. Meeples and '
        'd12s not included. 3D files for printing tokens are available on '
        'request.</span>'
    )
    if redirect_target("d12ball", "/kit") is None:
        return f'<div class="card way-card">\n  {words}\n</div>'
    return (
        f'<a class="card way-card" href="/kit">\n  {words}\n'
        '  <span class="way-link">Download the kit (zip)</span>\n</a>'
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
     "priority: a low pass beats pressure, which beats dribble advance, and "
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
        "play": escape(PLAY_URL),
        "studio_origin": ORIGINS["studio"],
        "turn_cards": "\n".join(turn_cards),
        "species_count": number_word(facts.species).capitalize(),
        "species_word": number_word(facts.species),
        "teams_word": number_word(facts.teams),
        "colour_teams_count": number_word(len(COLOR_TEAMS)).capitalize(),
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


def studio_values() -> dict[str, str]:
    return {
        **common_values("studio"),
        "paragraph": escape(STUDIO_PARAGRAPH),
        "description": escape(STUDIO_PARAGRAPH.split(". ")[0] + "."),
        "game_title": escape(TITLE),
        "game_origin": ORIGINS["d12ball"],
    }


VALUES = {"d12ball": d12ball_values, "studio": studio_values}


def redirects_file(site: str) -> str:
    return "".join(
        f"{source} {target} 302\n" for source, target in REDIRECTS[site]
    )


def build(site: str, out_dir: Path) -> Path:
    """Build one site into `out_dir`, which is created if it is missing.
    Returns the directory."""
    if site not in SITES:
        raise ValueError(f"no site {site!r}; the sites are {', '.join(SITES)}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    template = Template((LANDING_DIR / site / "index.html").read_text(encoding="utf-8"))
    (out / "index.html").write_text(
        template.substitute(VALUES[site]()), encoding="utf-8",
    )
    copy_styles(site, out)
    write_shared_pictures(out)
    if site == "d12ball":
        write_d12ball_pictures(out)
        write_downloads(out)
    if REDIRECTS[site]:
        (out / "_redirects").write_text(redirects_file(site), encoding="utf-8")
    return out


def main(sites=SITES, out_root: Path = DIST_DIR) -> None:
    for site in sites:
        out = build(site, Path(out_root) / site)
        print(f"built {site} into {out}")

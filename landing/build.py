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
    TITLE,
    BoxFacts,
    d12_art,
    render_banner,
    render_box_cover,
    retail_chips,
)
from d12ball.components import load_basic_ruleset, load_player_catalog
from d12ball.render import FONT_DIR, TEAM_COLORS, species_icon
from d12ball.species_cards import SPECIES_TEAM

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

# The addresses a site owns and forwards, Cloudflare Pages' `_redirects`
# format. `/learn` goes to the web app's Reading Room, which carries the
# Learn to Play in the page, until step 3 of docs/landing-pages.md builds
# the PDF and points it there.
REDIRECTS: dict[str, tuple[tuple[str, str], ...]] = {
    "d12ball": (
        ("/play", PLAY_URL),
        ("/learn", f"{PLAY_URL}/rules"),
    ),
    "studio": (),
}

DISPLAY_FONT = "RacingSansOne-Regular.ttf"
DISPLAY_FONT_LICENCE = "RacingSansOne-OFL.txt"

BANNER_WIDTHS = (1500, 3000)
COVER_WIDTH = 1200
SPECIES_ICON_PIXELS = 96
FAVICON_PIXELS = 64
JPEG_QUALITY = 85


# ------------------------------------------------------------ the game

@lru_cache(maxsize=None)
def game() -> tuple:
    """The catalog, the ruleset and `BoxFacts`, read once per build."""
    catalog = load_player_catalog()
    rules = load_basic_ruleset()
    return catalog, rules, BoxFacts.read(catalog=catalog, rules=rules)


def chips() -> list[str]:
    """The box's own three chips: how many, how long, how old."""
    return retail_chips(game()[2], DEFAULT_CLAIMS)


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
    # Served as the TTF it is bundled as: the OFL lets it be
    # redistributed unmodified beside its licence, and a converted
    # woff2 would be a second file to keep in step with the first.
    fonts = out / "fonts"
    fonts.mkdir(exist_ok=True)
    for name in (DISPLAY_FONT, DISPLAY_FONT_LICENCE):
        shutil.copyfile(FONT_DIR / name, fonts / name)


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


def d12ball_values() -> dict[str, str]:
    chip_row = [chip_html(words) for words in chips()]
    chip_row.append(chip_html(STAGE.upper(), quiet=True))
    return {
        **common_values("d12ball"),
        "title": escape(TITLE),
        "strapline": escape(STRAPLINE),
        "chips": "\n        ".join(chip_row),
        "stage": escape(STAGE),
        "play": escape(PLAY_URL),
        "studio_origin": ORIGINS["studio"],
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
        write_species_icons(out)
    if REDIRECTS[site]:
        (out / "_redirects").write_text(redirects_file(site), encoding="utf-8")
    return out


def main(sites=SITES, out_root: Path = DIST_DIR) -> None:
    for site in sites:
        out = build(site, Path(out_root) / site)
        print(f"built {site} into {out}")

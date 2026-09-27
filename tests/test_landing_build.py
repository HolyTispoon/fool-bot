"""
The landing pages build, and nothing on them points at nothing
(docs/design/landing-pages.md).

Nothing printed or rendered is tested for how it looks (CLAUDE.md): the
pages are checked by building them and looking. What is watched here is
what a look would not catch --

- **both sites build** into a fresh directory, each with its page;
- **every local link resolves**: an `href` or `src` (and each `srcset`
  candidate, and a stylesheet's `url(...)`) that is not an outside
  address names a file in that site's output, or an address the site's
  `_redirects` forwards -- and a redirect whose target is local names a
  file too, and one to a `.pdf` or a `.zip` names one (the two books
  and the kit's zips the build makes);
- **a quoted rule is the Charter's own words**: every
  `<blockquote data-law>` on the d12ball page appears verbatim in
  docs/living-rules.md, the guarantee the box art is held to. The page
  carries none today (its copy is the author's); this is here for the
  day one is added.
"""
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from d12ball.box_art import plain
from landing.build import SITES, build

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIVING_RULES = PROJECT_ROOT / "docs" / "living-rules.md"

OUTSIDE = ("http:", "https:", "mailto:", "tel:", "data:", "#")
# How a download of each kind begins.
DOWNLOAD_MAGIC = {".pdf": b"%PDF-", ".zip": b"PK\x03\x04"}
CSS_URL = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)")


class PageReader(HTMLParser):
    """Every address a page names, and the text of each quoted rule."""

    def __init__(self):
        super().__init__()
        self.addresses: list[str] = []
        self.quotes: list[str] = []
        self._quote: list[str] | None = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        for name in ("href", "src"):
            if attributes.get(name):
                self.addresses.append(attributes[name])
        if attributes.get("srcset"):
            self.addresses += [
                candidate.split()[0]
                for candidate in attributes["srcset"].split(",")
                if candidate.strip()
            ]
        if tag == "blockquote":
            if self._quote is not None:
                self._depth += 1
            elif "data-law" in attributes:
                self._quote, self._depth = [], 0

    def handle_endtag(self, tag):
        if tag == "blockquote" and self._quote is not None:
            if self._depth:
                self._depth -= 1
            else:
                self.quotes.append(" ".join("".join(self._quote).split()))
                self._quote = None

    def handle_data(self, data):
        if self._quote is not None:
            self._quote.append(data)


def is_local(address: str) -> bool:
    return not address.startswith(OUTSIDE) and not address.startswith("//")


def redirect_sources(site_dir: Path) -> dict[str, str]:
    redirects = site_dir / "_redirects"
    if not redirects.exists():
        return {}
    rules = {}
    for line in redirects.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if fields and not fields[0].startswith("#"):
            rules[fields[0]] = fields[1]
    return rules


def resolves(address: str, relative_to: Path, site_dir: Path, redirects) -> bool:
    path = urlsplit(address).path
    if not path:
        return True
    if path in redirects:
        return True
    if path.startswith("/"):
        target = site_dir / path.lstrip("/")
    else:
        target = relative_to / path
    if path.endswith("/"):
        target = target / "index.html"
    target = target.resolve()
    return target.is_relative_to(site_dir.resolve()) and target.is_file()


class LandingBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name)
        cls.sites = {site: build(site, cls.out / site) for site in SITES}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def read_page(self, site: str) -> PageReader:
        reader = PageReader()
        reader.feed((self.sites[site] / "index.html").read_text(encoding="utf-8"))
        return reader

    def test_each_site_has_its_page(self):
        for site, site_dir in self.sites.items():
            with self.subTest(site=site):
                self.assertTrue((site_dir / "index.html").is_file())

    def test_the_templates_are_filled(self):
        for site, site_dir in self.sites.items():
            with self.subTest(site=site):
                page = (site_dir / "index.html").read_text(encoding="utf-8")
                self.assertNotRegex(page, r"\$\{?[A-Za-z_]")

    def test_every_local_link_resolves(self):
        for site, site_dir in self.sites.items():
            redirects = redirect_sources(site_dir)
            named = [
                (address, site_dir, "index.html")
                for address in self.read_page(site).addresses
            ]
            for stylesheet in site_dir.glob("*.css"):
                named += [
                    (address, stylesheet.parent, stylesheet.name)
                    for address in CSS_URL.findall(
                        stylesheet.read_text(encoding="utf-8")
                    )
                ]
            for address, relative_to, where in named:
                if not is_local(address):
                    continue
                with self.subTest(site=site, where=where, address=address):
                    self.assertTrue(
                        resolves(address, relative_to, site_dir, redirects),
                        f"{where} links {address!r}, which is not in the build",
                    )

    def test_every_local_redirect_lands_on_a_file(self):
        for site, site_dir in self.sites.items():
            for source, target in redirect_sources(site_dir).items():
                if not is_local(target):
                    continue
                with self.subTest(site=site, source=source):
                    self.assertTrue(
                        resolves(target, site_dir, site_dir, {}),
                        f"{source} forwards to {target!r}, which is not in the build",
                    )

    def test_a_forwarded_download_is_what_it_says(self):
        # The books and the kit are made by the build itself; a redirect
        # to one that came out empty or as something else would still
        # "resolve".
        for site, site_dir in self.sites.items():
            for source, target in redirect_sources(site_dir).items():
                suffix = Path(target).suffix
                if not (is_local(target) and suffix in DOWNLOAD_MAGIC):
                    continue
                with self.subTest(site=site, source=source):
                    with open(site_dir / target.lstrip("/"), "rb") as download:
                        head = download.read(8)
                    self.assertTrue(
                        head.startswith(DOWNLOAD_MAGIC[suffix]),
                        f"{target} is not a {suffix}",
                    )

    def test_a_quoted_rule_is_the_charters_own_words(self):
        charter = " ".join(plain(LIVING_RULES.read_text(encoding="utf-8")).split())
        for quote in self.read_page("d12ball").quotes:
            with self.subTest(quote=quote[:60]):
                self.assertIn(quote, charter)

    def test_the_quote_reader_reads_a_quote(self):
        # The page quotes nothing yet, so the check above passes on an
        # empty list; this holds the reader to reading one.
        reader = PageReader()
        reader.feed('<blockquote data-law="1.1">Two  <em>words</em>\n</blockquote>')
        self.assertEqual(reader.quotes, ["Two words"])


if __name__ == "__main__":
    unittest.main()

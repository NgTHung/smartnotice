"""Configure public university listings and bounded same-origin pagination."""

from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin

from bs4 import BeautifulSoup
from smartnotice.collectors import hcmus
from smartnotice.collectors.web import WebCollector


@dataclass(frozen=True)
class Source:
    """Hold verified listing and article selectors for a university source."""

    institution: str
    listing_url: str
    link_selector: str
    body_selector: str
    title_selector: str
    date_selector: str
    next_selector: str = "a[rel=next]"


SOURCES = {
    "hcmus-student": Source(
        "HCMUS",
        hcmus.LIST_URL,
        hcmus.LINK_SELECTOR,
        hcmus.BODY_SELECTOR,
        hcmus.TITLE_SELECTOR,
        hcmus.DATE_SELECTOR,
    ),
    "uit-student": Source(
        "UIT",
        "https://ctsv.uit.edu.vn/loai-bai-viet/thong-bao-0",
        '#content a[href*="/bai-viet/"], #content a[href*="/content/"]',
        ".field-name-body",
        "h1#page-title",
        "article .submitted",
        ".pager-next a",
    ),
    "ueh-training": Source(
        "UEH",
        "https://daotao.ueh.edu.vn/category/tin-tuc/",
        ".jet-listing-grid__item h2 a[href]",
        ".elementor-widget-theme-post-content",
        ".elementor-element-5906742 h2",
        "time.entry-date",
    ),
    "ueh-student": Source(
        "UEH",
        "https://dsa.ueh.edu.vn/hoc-bong/",
        "#content h3 a[href]",
        "article .bs-desc",
        "h1.page-title",
        ".bs-date span",
        "a.next.page-numbers",
    ),
}


def next_listing(raw: bytes, url: str, source: Source, page: int) -> str | None:
    """Return a same-origin next listing, or None when no next page is available."""
    soup = BeautifulSoup(raw, "html.parser")
    node = soup.select_one(source.next_selector)
    target = urljoin(url, node["href"]) if node else None
    # UEH renders its paging buttons in JavaScript; WordPress also serves archive URLs.
    if source.listing_url == SOURCES["ueh-training"].listing_url:
        target = source.listing_url + f"page/{page + 1}/"
    if target:
        target = urldefrag(target)[0]
        if WebCollector.origin(target) != WebCollector.origin(source.listing_url):
            raise ValueError("Pagination leaves the configured source origin")
    return target

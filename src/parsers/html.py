"""Turn HTML tables into header-value lines so dates retain their context."""

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from smartnotice.parsers.thread import QUOTE_CLOSE, QUOTE_OPEN


def parse_html(html: str, selector: str | None = None, *, email_quotes: bool = False) -> str:
    """Extract a selected body, preserving table rows as readable lines.

    Use a source-specific CSS selector to exclude navigation. Missing selectors
    raise ValueError rather than silently collecting a different page region.
    Absolute web/mail/telephone targets remain beside their anchor labels.
    Email quote markers are internal delimiters removed by the email parser.
    """
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(selector) if selector else soup.body or soup
    if root is None:
        raise ValueError(f"HTML selector did not match: {selector}")
    for tag in root.select("head, script, style, template, noscript, nav, footer, header"):
        tag.decompose()
    for tag in list(root.find_all(True)):
        if tag.attrs is None:
            continue
        style = re.sub(r"\s+", "", tag.get("style", "")).lower()
        if tag.has_attr("hidden") or "display:none" in style or "visibility:hidden" in style:
            tag.decompose()
    for anchor in root.find_all("a", href=True):
        href = anchor["href"].strip()
        try:
            scheme = urlsplit(href).scheme.lower()
        except ValueError:
            continue
        target = href[7:] if scheme == "mailto" else href
        if scheme in {"http", "https", "mailto", "tel"} and target not in anchor.get_text():
            anchor.append(soup.new_string(f" <{target}>"))
    if email_quotes:
        for tag in root.select("blockquote, .gmail_quote"):
            tag.insert_before(soup.new_string("\n" + QUOTE_OPEN + "\n"))
            tag.insert_after(soup.new_string("\n" + QUOTE_CLOSE + "\n"))
    for table in list(root.find_all("table")):
        lines = []
        headers = []
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"], recursive=False)
            values = [cell.get_text(" ", strip=True) for cell in cells]
            if not values:
                continue
            if all(cell.name == "th" for cell in cells):
                headers = values
                continue
            lines.append(
                "; ".join(
                    f"{headers[i] if i < len(headers) else f'Cột {i + 1}'}: {value}"
                    for i, value in enumerate(values)
                )
            )
        table.replace_with(soup.new_string("\n" + "\n".join(lines) + "\n"))
    for tag in root.find_all("br"):
        tag.replace_with("\n")
    for tag in root.find_all(["p", "div", "li", "h1", "h2", "h3", "h4", "section"]):
        tag.insert_before("\n")
        tag.insert_after("\n")
    return root.get_text("", strip=False).strip()

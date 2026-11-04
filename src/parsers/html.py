"""Turn HTML tables into header-value lines so dates retain their context."""

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from smartnotice.parsers.thread import split_thread


def parse_html(html: str, selector: str | None = None, *, email_quotes: bool = False) -> str:
    """Extract a selected body, preserving table rows as readable lines.

    Use a source-specific CSS selector to exclude navigation. Missing selectors
    raise ValueError rather than silently collecting a different page region.
    Absolute web/mail/telephone targets remain beside their anchor labels.
    With email_quotes=True, remove explicit gmail_quote/type=cite regions on
    the DOM before flattening tables. Ordinary blockquotes retain their text.
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
        for tag in list(root.find_all(True)):
            if tag.attrs is None:
                continue
            if "gmail_quote" in tag.get("class", []) or (
                tag.name == "blockquote" and tag.get("type", "").casefold() == "cite"
            ):
                previous = tag.previous_sibling
                while previous is not None and (
                    not previous.get_text().strip() or previous.name == "br"
                ):
                    previous = previous.previous_sibling
                if previous is not None:
                    # Remove the attribution belonging to this DOM quotation so
                    # it cannot consume an inline or bottom-posted reply later.
                    parts = split_thread(previous.get_text("\n"), "")
                    if len(parts) > 1 and all(not part.body for part in parts[1:]):
                        previous.replace_with(soup.new_string(parts[0].body))
                tag.decompose()
    for table in reversed(list(root.find_all("table"))):
        lines = []
        headers = []
        for row in table.find_all("tr"):
            if row.find_parent("table") is not table:
                continue
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
    for tag in root.find_all(["p", "div", "li", "h1", "h2", "h3", "h4", "section", "blockquote"]):
        tag.insert_before("\n")
        tag.insert_after("\n")
    return root.get_text("", strip=False).strip()

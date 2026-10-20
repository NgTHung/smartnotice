"""Turn HTML tables into header-value lines so dates retain their context."""

from bs4 import BeautifulSoup


def parse_html(html: str, selector: str | None = None) -> str:
    """Extract a selected body, preserving table rows as readable lines.

    Use a source-specific CSS selector to exclude navigation. Missing selectors
    raise ValueError rather than silently collecting a different page region.
    """
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(selector) if selector else soup.body or soup
    if root is None:
        raise ValueError(f"HTML selector did not match: {selector}")
    for tag in root.select("script, style, noscript, nav, footer, header"):
        tag.decompose()
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

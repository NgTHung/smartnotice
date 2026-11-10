"""Extract ordered web links; adapted from the supplied Data Email/content_processor.py."""

import re
from urllib.parse import urlsplit

WEB_LINK = re.compile(r"(?:https?://|www\.)[^\s<>\"“”‘’`]+", re.I)


def extract_links(text: str, *, keep_in_text: bool = False) -> tuple[str, list[str]]:
    """Return text and distinct HTTP(S)/www links in first-appearance order.

    Accept plain text or text already decoded by the HTML parser. Unfold URLs
    without HTML entity decoding, which belongs exclusively to that parser. With
    keep_in_text=True, retain normalized URLs as annotation evidence. Otherwise
    preserve the original cleaner's separation behavior. Labels always remain.
    This helper does not certify URL safety or fetch any link.
    """
    # Convert Markdown links to labels + angle-wrapped URLs before extraction.
    text = re.sub(
        r"\[([^\]\n]+)\]\(((?:https?://|www\.)[^\s]+)\)",
        lambda match: match[1] + " <" + match[2] + ">",
        text,
        flags=re.I,
    )

    def unfold(match: re.Match) -> str:
        candidate = re.sub(r"\n[ \t]*", "", match[1])
        return "<" + candidate + ">" if not re.search(r"\s", candidate) else match.group()

    text = re.sub(r"<((?:https?://|www\.)[^<>]+)>", unfold, text, flags=re.I)
    links: list[str] = []
    seen: set[str] = set()
    pieces: list[str] = []
    cursor = 0
    for match in WEB_LINK.finditer(text):
        raw = match.group().rstrip(".,;:!?'")
        # Keep parentheses in a URL such as /Function_(mathematics), while
        # excluding the closing delimiter in prose such as (https://example.org).
        while raw and raw[-1] in ")]}":
            closing = raw[-1]
            opening = {")": "(", "]": "[", "}": "{"}[closing]
            if raw.count(closing) <= raw.count(opening):
                break
            raw = raw[:-1]
        emphasis = re.search(r"([*_]+)$", text[: match.start()])
        if emphasis and raw.endswith(emphasis[1]):
            raw = raw[: -len(emphasis[1])]
        url = raw
        try:
            parsed = urlsplit("https://" + url if url.lower().startswith("www.") else url)
            if (
                not parsed.hostname
                or re.search(r"[()\[\]{}]", parsed.hostname)
                or any(char.isspace() for char in url)
            ):
                raise ValueError("invalid link host")
        except ValueError:
            # Privacy masking can expose an already malformed pseudo-link such
            # as http://([EMAIL]). Do not export it as a real URL.
            pieces.append(text[cursor : match.start()])
            pieces.append("[LIEN_KET_KHONG_HOP_LE]")
            cursor = match.end()
            continue
        start, stop = match.start(), match.start() + len(raw)
        while start > cursor and stop < len(text):
            if (text[start - 1], text[stop]) not in {
                ("<", ">"),
                ("(", ")"),
                ("`", "`"),
                ("*", "*"),
                ("_", "_"),
            }:
                break
            start -= 1
            stop += 1
        pieces.append(text[cursor:start])
        if keep_in_text:
            pieces.append(url)
        cursor = stop
        # Normalize case only for the scheme and host when comparing URLs.
        key = parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower()).geturl()
        if key not in seen:
            seen.add(key)
            links.append(url)
    pieces.append(text[cursor:])
    content = "".join(pieces)
    content = re.sub(r"(?m)^\[\d+\][ \t]*$", "", content)
    return content, links

"""Separate quotes; adapted from the supplied Data Email/content_processor.py."""

import re
from dataclasses import dataclass

from smartnotice.parsers.addresses import find_email_addresses

FROM_LINE = re.compile(r"^(?:From|Từ):\s*(.*)", re.I)


HEADER_LINE = re.compile(
    r"^(?:From|Từ|Sent|Date|Đã gửi|Ngày gửi|Ngày|To|Đến|Tới|Cc|Bcc|Subject|Chủ đề):", re.I
)


REPLY_END = re.compile(r"^.+\s+(?:wrote|đã viết|viết)\s*:\s*$", re.I)


FORWARD = re.compile(
    r"^(?:[-_‐‑‒–—―]*\s*(?:Forwarded message|Original Message|Thư được chuyển tiếp)"
    r"\s*[-_‐‑‒–—―]*|Begin forwarded message:)\s*$",
    re.I,
)


@dataclass
class ThreadPart:
    """One contribution; sender metadata is private and must not be persisted."""

    sender: str | None
    body: str
    kind: str = "message"
    depth: int = 0


def email_from_text(text: str) -> str | None:
    """Return the last NFC/case-folded address without prose wrappers, or None."""
    matches = find_email_addresses(text)
    if not matches:
        return None
    return matches[-1].address


def _header_block(lines: list[str], index: int) -> tuple[int, str | None, set[str]]:
    stop = index
    fields: dict[str, str] = {}
    current = ""
    while stop < min(len(lines), index + 40):
        item = lines[stop].strip()
        if not item:
            break
        if HEADER_LINE.match(item):
            current, value = item.split(":", 1)
            current = current.casefold()
            fields[current] = value.strip()
        elif current in {"from", "từ"} and not email_from_text(fields[current]):
            if not email_from_text(item):
                break
            fields[current] += " " + item
        else:
            break
        stop += 1
    sender = email_from_text(fields.get("from", fields.get("từ", "")))
    return stop, sender, set(fields)


def _attribution(lines: list[str], index: int) -> tuple[int, str | None] | None:
    line = lines[index].strip()
    if re.match(r"^(?:On|Vào)\s", line, re.I):
        # Gmail wraps the sender/email and 'wrote:' over multiple physical lines.
        for stop in range(index + 1, min(len(lines), index + 7) + 1):
            joined = " ".join(lines[index:stop]).strip()
            if REPLY_END.fullmatch(joined):
                sender = email_from_text(joined)
                dated = re.search(
                    r"\b(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\b|\b\d{1,4}[/.-]\d{1,2}",
                    joined,
                    re.I,
                )
                if sender or (dated and stop < len(lines) and lines[stop].lstrip().startswith(">")):
                    return stop, sender
                break
            if stop < len(lines) and (
                not lines[stop].strip() or lines[stop].lstrip().startswith(">")
            ):
                break
    if FROM_LINE.match(line):
        stop, sender, fields = _header_block(lines, index)
        if sender and len(fields) >= 3:
            return stop, sender
    if FORWARD.fullmatch(line):
        stop = index + 1
        while stop < len(lines) and not lines[stop].strip():
            stop += 1
        if stop < len(lines) and FROM_LINE.match(lines[stop].strip()):
            header_stop, sender, _ = _header_block(lines, stop)
            return header_stop, sender
        return stop, None
    return None


def split_thread(text: str, sender: str, parent_sender: str | None = None) -> list[ThreadPart]:
    """Separate line attributions and > quotations, preserving inline replies.

    Literal marker-like strings have no control meaning. HTML quote regions
    must be removed by the HTML parser before calling this plain-text function.
    """

    def quoted_region(lines: list[str], start: int) -> tuple[list[str], int] | None:
        if start >= len(lines):
            return None
        if lines[start].lstrip().startswith(">"):
            body = []
            stop = start
            while stop < len(lines):
                line = lines[stop]
                if line.lstrip().startswith(">"):
                    body.append(re.sub(r"^\s*> ?", "", line, count=1))
                elif not line.strip():
                    body.append("")
                else:
                    break
                stop += 1
            return body, stop
        return None

    def visit(
        lines: list[str], author: str | None, depth: int, fallback: str | None = None
    ) -> list[ThreadPart]:
        if depth > 30:
            # Do not attribute an unparsed tail to the wrong author.
            return [ThreadPart(None, "\n".join(lines), "quoted", depth)]
        own: list[str] = []
        children: list[ThreadPart] = []
        quote_author = fallback
        continuation: ThreadPart | None = None
        index = 0
        while index < len(lines):
            boundary = _attribution(lines, index)
            if boundary:
                stop, quoted_sender = boundary
                quote_author = quoted_sender or fallback
                while stop < len(lines) and not lines[stop].strip():
                    stop += 1
                region = quoted_region(lines, stop)
                if region:
                    child, index = region
                else:
                    child, index = lines[stop:], len(lines)
                while own and (not own[-1].strip() or re.fullmatch(r"[-_=]{3,}", own[-1].strip())):
                    own.pop()
                child_parts = visit(child, quote_author, depth + 1)
                continuation = child_parts[0]
                children.extend(child_parts)
                continue
            region = quoted_region(lines, index)
            if region:
                child, index = region
                child_parts = visit(child, quote_author, depth + 1)
                if continuation is not None and continuation.sender == quote_author:
                    continuation.body = (continuation.body + "\n\n" + child_parts[0].body).strip()
                    children.extend(child_parts[1:])
                else:
                    continuation = child_parts[0]
                    children.extend(child_parts)
                continue
            own.append(lines[index])
            index += 1
        part = ThreadPart(
            author, "\n".join(own).strip(), "message" if depth == 0 else "quoted", depth
        )
        return [part, *children]

    return visit(text.splitlines(), sender, 0, parent_sender)

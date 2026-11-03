"""Separate quotes; adapted from the supplied Data Email/content_processor.py."""

import re
from dataclasses import dataclass

QUOTE_OPEN = "[[EMAIL_QUOTE_START]]"


QUOTE_CLOSE = "[[EMAIL_QUOTE_END]]"


EMAIL = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)


FROM_LINE = re.compile(r"^(?:From|Từ):\s*(.*)", re.I)


HEADER_LINE = re.compile(
    r"^(?:From|Từ|Sent|Date|Đã gửi|Ngày gửi|Ngày|To|Đến|Tới|Cc|Bcc|Subject|Chủ đề):", re.I
)


REPLY_END = re.compile(r"(?:wrote|đã viết|viết)\s*:\s*$", re.I)


FORWARD = re.compile(
    r"^(?:[-_]{2,}\s*(?:Forwarded message|Original Message|Thư được chuyển tiếp)"
    r"|Begin forwarded message:)",
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
    """Return the last address in an attribution, or None if absent."""
    matches = list(EMAIL.finditer(text))
    if not matches:
        return None
    address = matches[-1].group().rstrip(".")
    local, domain = address.rsplit("@", 1)
    return local + "@" + domain.lower()


def _attribution(lines: list[str], index: int) -> tuple[int, str | None] | None:
    line = lines[index].strip()
    if re.match(r"^(?:On|Vào)\s", line, re.I):
        # Gmail wraps the sender/email and 'wrote:' over multiple physical lines.
        for stop in range(index + 1, min(len(lines), index + 7) + 1):
            joined = " ".join(lines[index:stop]).strip()
            if REPLY_END.search(joined):
                return stop, email_from_text(joined)
            if stop < len(lines) and (
                not lines[stop].strip() or lines[stop].lstrip().startswith(">")
            ):
                break
    if FROM_LINE.match(line):
        lookahead = lines[index + 1 : index + 12]
        if any(
            re.match(r"^(?:Sent|Date|Đã gửi|Ngày gửi|Subject|Chủ đề):", item, re.I)
            for item in lookahead
        ):
            stop = index + 1
            while stop < len(lines) and lines[stop].strip() and stop < index + 40:
                stop += 1
            header = []
            for item in lines[index:stop]:
                if header and HEADER_LINE.match(item):
                    break
                header.append(item)
            return stop, email_from_text(" ".join(header))
    if FORWARD.match(line):
        stop = index + 1
        while stop < len(lines) and not lines[stop].strip():
            stop += 1
        if stop < len(lines) and FROM_LINE.match(lines[stop].strip()):
            header_stop = stop + 1
            last_header = "from"
            while header_stop < len(lines) and lines[header_stop].strip():
                item = lines[header_stop]
                if HEADER_LINE.match(item):
                    last_header = item.split(":", 1)[0].casefold()
                elif last_header in {"from", "từ"} and email_from_text(
                    " ".join(lines[stop:header_stop])
                ):
                    break
                header_stop += 1
            sender_header = []
            for item in lines[stop:header_stop]:
                if sender_header and HEADER_LINE.match(item):
                    break
                sender_header.append(item)
            return header_stop, email_from_text(" ".join(sender_header))
        return stop, None
    return None


def split_thread(text: str, sender: str, parent_sender: str | None = None) -> list[ThreadPart]:
    """Separate authors; never assign unattributed quotations to the replier."""

    def quoted_region(lines: list[str], start: int) -> tuple[list[str], int] | None:
        if start >= len(lines):
            return None
        if lines[start].strip() == QUOTE_OPEN:
            depth = 1
            stop = start + 1
            while stop < len(lines):
                marker = lines[stop].strip()
                depth += marker == QUOTE_OPEN
                depth -= marker == QUOTE_CLOSE
                if not depth:
                    return lines[start + 1 : stop], stop + 1
                stop += 1
            return lines[start + 1 :], len(lines)
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
            if lines[index].strip() != QUOTE_CLOSE:
                own.append(lines[index])
            index += 1
        part = ThreadPart(
            author, "\n".join(own).strip(), "message" if depth == 0 else "quoted", depth
        )
        return [part, *children]

    return visit(text.splitlines(), sender, 0, parent_sender)

"""Decode MIME email bodies and remove common quoted-message boundaries."""

import re
from datetime import date
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

from smartnotice.parsers.html import parse_html

BOUNDARY = re.compile(
    r"^(?:On .+wrote:|Vào .+(?:đã viết|viết):|[- ]*(?:Original Message|Forwarded message)"
    r"[- :]*|_{5,}|--\s*$|(?:Trân trọng|Kính thư|Best regards|Regards)[,.!\s]*$)",
    re.IGNORECASE,
)


def parse_email(raw: bytes) -> tuple[str, date | None, str | None]:
    """Return body, local send date, and a thread key for later hashing.

    Attachments are excluded. HTML is used only when a plain body is absent.
    The thread key is sensitive metadata and must not be stored un-hashed.
    """
    message = BytesParser(policy=policy.default).parsebytes(raw)
    body = message.get_body(preferencelist=("plain", "html"))
    if body is None:
        raise ValueError("Email has no text body")
    text = body.get_content()
    if body.get_content_type() == "text/html":
        text = parse_html(text)
    lines = []
    for line in text.splitlines():
        if BOUNDARY.match(line.strip()):
            break
        if not line.lstrip().startswith(">"):
            lines.append(line)
    reference_date = None
    if message.get("Date"):
        try:
            reference_date = parsedate_to_datetime(str(message["Date"])).date()
        except (ValueError, TypeError, OverflowError):
            pass
    refs = str(message.get("References") or message.get("In-Reply-To") or "").split()
    thread_key = refs[0] if refs else str(message.get("Message-ID") or "") or None
    return "\n".join(lines), reference_date, thread_key

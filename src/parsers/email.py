"""Parse source dates and threads around the adapted Data Email MIME cleaner."""

import re
from dataclasses import dataclass, field
from datetime import date
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

from smartnotice.parsers.boilerplate import remove_boilerplate
from smartnotice.parsers.mime import extract_content
from smartnotice.parsers.thread import split_thread


@dataclass
class ParsedEmail:
    """Keep decoded content and private header identities local to preparation.

    Only warning codes may be persisted directly. Hash the thread key and redact
    text before export; identities must never be included in prepared records.
    """

    text: str = field(repr=False)
    reference_date: date | None
    thread_key: str | None = field(repr=False)
    identities: list[tuple[str, str]] = field(repr=False)
    warnings: list[str]


def parse_email(raw: bytes) -> tuple[str, date | None, str | None]:
    """Return body, local send date, and a thread key for later hashing.

    Attachments and quoted contributions are excluded. HTML is used when a
    plain body is absent or blank. Missing/invalid dates stay None.
    The thread key is sensitive metadata and must not be stored un-hashed.
    """
    parsed = parse_email_details(raw)
    return parsed.text, parsed.reference_date, parsed.thread_key


def parse_email_details(raw: bytes) -> ParsedEmail:
    """Decode one contribution plus private metadata and safe MIME warning codes.

    Missing From headers are accepted. No text MIME body raises ValueError;
    quote-only messages have an empty contribution for the caller to reject.
    """
    message = BytesParser(policy=policy.default).parsebytes(raw)
    warnings: list[str] = []
    text = extract_content(message, warnings)
    if not text:
        raise ValueError("Email has no text body")
    identities = []
    for key in ("From", "To", "Cc", "Bcc", "Reply-To"):
        for header in message.get_all(key, []):
            for address in getattr(header, "addresses", ()):
                if address.username and address.domain:
                    identities.append((address.addr_spec, address.display_name))
    # Attribution is used only to separate contributions; it is never exported.
    text = remove_boilerplate(split_thread(text, "")[0].body)
    warnings.extend(
        f"mime_defect:{name}"
        for name in sorted(
            {type(defect).__name__ for part in message.walk() for defect in part.defects}
        )
    )
    if "\ufffd" in text:
        warnings.append("replacement_character_in_content")
    reference_date = None
    if message.get("Date"):
        try:
            reference_date = parsedate_to_datetime(str(message["Date"])).date()
        except (ValueError, TypeError, OverflowError):
            pass
    refs = re.findall(
        r"<[^<>]+>", str(message.get("References") or message.get("In-Reply-To") or "")
    )
    thread_key = refs[0] if refs else str(message.get("Message-ID") or "") or None
    return ParsedEmail(text, reference_date, thread_key, identities, list(dict.fromkeys(warnings)))

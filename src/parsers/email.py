"""Parse source dates and threads around the adapted Data Email MIME cleaner."""

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

from smartnotice.parsers.addresses import normalize_email
from smartnotice.parsers.boilerplate import remove_boilerplate
from smartnotice.parsers.mime import extract_content
from smartnotice.parsers.thread import split_thread


class EmptyEmailBodyError(ValueError):
    """Report a source with no usable text MIME body, without exposing content."""


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


@dataclass(frozen=True, repr=False)
class EmailRouting:
    """Keep private source header fields in memory for source comparisons."""

    sent_at: datetime | None
    sender: str | None
    message_id: str | None
    parent_id: str | None
    subject: str | None = None


def parse_email_routing(raw: bytes) -> EmailRouting:
    """Read the outer email headers for an in-memory comparison.

    Require a timezone for minute comparisons and a single From mailbox.
    Prefer an unambiguous In-Reply-To, then the last References ID. Callers
    must export only derived pair facts, never these header fields or the subject.
    """
    message = BytesParser(policy=policy.default).parsebytes(raw, headersonly=True)
    date_headers = message.get_all("Date", [])
    sent_at = None
    if len(date_headers) == 1:
        try:
            observed = parsedate_to_datetime(str(date_headers[0]))
            if observed.utcoffset() is not None:
                sent_at = observed.astimezone(UTC)
        except (ValueError, TypeError, OverflowError):
            pass
    from_headers = message.get_all("From", [])
    addresses = getattr(from_headers[0], "addresses", ()) if len(from_headers) == 1 else ()
    sender = None
    if len(addresses) == 1 and addresses[0].username and addresses[0].domain:
        sender = normalize_email(addresses[0].addr_spec)

    def ids(name: str) -> list[str]:
        return re.findall(r"<[^<>\s]+@[^<>\s]+>", " ".join(map(str, message.get_all(name, []))))

    message_ids = ids("Message-ID")
    in_reply_to = ids("In-Reply-To")
    references = ids("References") if "In-Reply-To" not in message else []
    subjects = message.get_all("Subject", [])
    return EmailRouting(
        sent_at,
        sender,
        message_ids[0] if len(message_ids) == 1 else None,
        in_reply_to[0] if len(in_reply_to) == 1 else (references[-1] if references else None),
        str(subjects[0]) if len(subjects) == 1 else None,
    )


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
        raise EmptyEmailBodyError("Email has no text body")
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

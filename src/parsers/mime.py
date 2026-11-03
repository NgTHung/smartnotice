"""Decode MIME bodies; adapted from the supplied Data Email/clean_emails.py."""

from email.message import EmailMessage

from smartnotice.parsers.html import parse_html
from smartnotice.preprocessing.text import normalize_text


def decode_part(part: EmailMessage, warnings: list[str]) -> str:
    """Decode MIME bytes with fallback codecs, recording safe warning codes."""
    payload = part.get_payload(decode=True)
    if payload is None:
        value = part.get_payload()
        return value if isinstance(value, str) else ""
    declared = part.get_content_charset()
    encodings = list(dict.fromkeys(filter(None, [declared, "utf-8", "cp1258", "cp1252"])))
    for index, encoding in enumerate(encodings):
        try:
            text = payload.decode(encoding, errors="strict")
        except (LookupError, UnicodeError):
            continue
        if index or not declared:
            warnings.append("charset_fallback")
        return text
    warnings.append("charset_replacement")
    return payload.decode("utf-8", errors="replace")


def extract_content(
    part: EmailMessage, warnings: list[str], *, include_email_quotes: bool = False
) -> str:
    """Read one MIME body, excluding attachments and preferring nonempty plain text.

    HTML email quotations are excluded by default. Private policy audits may
    request include_email_quotes=True to inspect all body identities.
    """
    if part.get_content_disposition() == "attachment" or part.get_filename():
        return ""
    content_type = part.get_content_type()
    if part.get_content_maintype() == "message":
        return ""  # Do not turn an attached .eml into the sender's own message.
    if part.is_multipart():
        children = list(part.iter_parts())
        if content_type == "multipart/alternative":
            # Use one representation, so the plain and HTML copies never repeat.
            children.sort(
                key=lambda child: {"text/plain": 0, "text/html": 1}.get(child.get_content_type(), 2)
            )
            for child in children:
                text = extract_content(child, warnings, include_email_quotes=include_email_quotes)
                if text:
                    return text
            return ""
        if content_type == "multipart/related":
            start = part.get_param("start")
            if start:
                children = [
                    child for child in children if child.get("Content-ID") == start
                ] or children[:1]
            else:
                children = children[:1]
        return "\n\n".join(
            filter(
                None,
                (
                    extract_content(child, warnings, include_email_quotes=include_email_quotes)
                    for child in children
                ),
            )
        )
    if content_type not in {"text/plain", "text/html"}:
        return ""
    text = decode_part(part, warnings)
    if content_type == "text/html":
        text = parse_html(text, email_quotes=not include_email_quotes)
    # Split authors before removing signatures/footer, otherwise a signature
    # can hide an attribution or make an original message part of the reply.
    return normalize_text(text, preserve_images=True)

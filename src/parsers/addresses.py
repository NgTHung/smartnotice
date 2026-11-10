"""Locate email evidence without treating paired prose delimiters as addresses."""

import re
import unicodedata
from dataclasses import dataclass

EMAIL = re.compile(
    r"[\w.!#$%&'*+/=?^`{|}~-]+@[^\W_]+(?:[-][^\W_]+)*(?:\.[^\W_]+(?:[-][^\W_]+)*)+", re.UNICODE
)


@dataclass(frozen=True)
class EmailAddress:
    """An address and its end-exclusive Unicode offsets into the supplied text."""

    start: int
    end: int
    address: str


def normalize_email(address: str) -> str:
    """Return NFC with surrounding whitespace removed and both parts case-folded.

    Local-part case folding follows SmartNotice's existing policy comparison;
    it does not claim that differently cased mailboxes are universally equivalent.
    """
    return unicodedata.normalize("NFC", address.strip()).casefold()


def find_email_addresses(text: str) -> list[EmailAddress]:
    """Find normalized addresses while retaining exact replacement offsets.

    Matching pairs of Markdown emphasis, quotes, equals signs, or slashes are
    external delimiters. Unpaired special characters remain in the local part.
    The returned offsets always refer to the original, unnormalized input text.
    """
    addresses = []
    for match in EMAIL.finditer(text):
        start, end = match.span()
        opening = re.match(r"[*_'=/`]+", match.group())
        if opening:
            local_length = match.group().index("@")
            for length in range(min(len(opening[0]), local_length - 1), 0, -1):
                if text.startswith(opening[0][:length][::-1], end):
                    start += length
                    break
        addresses.append(EmailAddress(start, end, normalize_email(text[start:end])))
    return addresses

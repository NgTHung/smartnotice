"""Preserve Vietnamese diacritics and mask identifiers before segmentation."""

import re
import unicodedata

from smartnotice.schemas import Sentence


def normalize_and_redact(text: str, names: list[str] | None = None) -> tuple[str, int]:
    """Return NFC text and the number of automatic redactions.

    Name masking requires a supplied name list. Human privacy review remains
    necessary because unrestricted names and identifiers cannot be inferred.
    """
    text = unicodedata.normalize("NFC", text).replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    count = 0
    patterns = [
        (r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]"),
        (r"(?i)\b(?:MSSV|mã\s+sinh\s+viên)\s*[:#-]?\s*\d{6,12}\b", "[STUDENT_ID]"),
        (r"(?i)\b(?:điện thoại|sđt|tel|phone)\s*[:.]?\s*\+?\d[\d .()-]{7,}\d", "[PHONE]"),
    ]
    for pattern, replacement in patterns:
        text, n = re.subn(pattern, replacement, text)
        count += n
    for name in sorted(names or [], key=len, reverse=True):
        if name.strip():
            text, n = re.subn(
                re.escape(unicodedata.normalize("NFC", name)), "[NAME]", text, flags=re.IGNORECASE
            )
            count += n
    text = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip(), count


def segment_sentences(text: str) -> list[Sentence]:
    """Return exact offsets into normalized text using punctuation and lines.

    This deterministic segmentation is a review aid. Abbreviations may require
    annotators to select multiple evidence sentences.
    """
    sentences = []
    for match in re.finditer(r"[^\n]+", text):
        for part in re.finditer(r".+?(?:[.!?](?=\s|$)|$)", match.group()):
            raw = part.group()
            if not raw.strip():
                continue
            start = match.start() + part.start() + len(raw) - len(raw.lstrip())
            end = match.start() + part.end() - (len(raw) - len(raw.rstrip()))
            sentences.append(
                Sentence(
                    sentence_id=f"s{len(sentences) + 1}", start=start, end=end, text=text[start:end]
                )
            )
    return sentences

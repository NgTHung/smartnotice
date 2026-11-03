"""Preserve Vietnamese diacritics and mask identifiers before segmentation."""

import re
import unicodedata
from collections import Counter

from smartnotice.preprocessing.privacy import PrivacyRules
from smartnotice.schemas import Sentence


def normalize_text(text: str, preserve_images: bool = False) -> str:
    """Return NFC text with MIME whitespace/control noise removed, retaining diacritics."""
    text = re.sub(r"\r+\n", "\n", text).replace("\r", "\n")
    # MBOX exports escape a body line beginning with "From ", even when it is
    # ordinary prose (e.g. "From the Foundations"), not a reply quotation.
    text = re.sub(r"(?m)^>From ", "From ", text)
    text = unicodedata.normalize("NFC", text)
    text = "".join(
        character
        for character in text
        if character in "\n\t"
        or (
            unicodedata.category(character) not in {"Cc", "Co", "Cs"}
            and character
            not in "\u00ad\u200b\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2060\ufeff"
        )
    )
    if not preserve_images:
        text = re.sub(r"\[cid:[^\]\n]*\]|<cid:[^>\n]*>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\[image:\s*\ufffd+\s*\]", "", text, flags=re.IGNORECASE)
    text = "\n".join(re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Outlook often puts a bullet/number on a line by itself.
    text = re.sub(r"(?m)^(?:\*|•|·)\s*\n+(?=\S)", "- ", text)
    text = re.sub(r"(?m)^(\d+[.)])\s*\n+(?=\S)", r"\1 ", text)
    return text.strip()


def normalize_and_redact(
    text: str, names: list[str] | None = None, *, privacy: PrivacyRules | None = None
) -> tuple[str, int]:
    """Return NFC text and the number of automatic redactions.

    Optional rules support explicit public contacts and the legacy email policy.
    Names supplied here extend this local rules instance. Human privacy review
    remains necessary; regular expressions cannot infer all personal details.
    """
    privacy = privacy or PrivacyRules()
    privacy.student_names.update(
        unicodedata.normalize("NFC", name.strip()) for name in names or [] if name.strip()
    )
    stats: Counter = Counter()
    text = privacy.redact(normalize_text(text), stats)
    return normalize_text(text), sum(stats.values())


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

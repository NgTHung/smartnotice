"""Preserve Vietnamese diacritics and mask identifiers before segmentation."""

import re
import unicodedata
from collections import Counter

from smartnotice.preprocessing.privacy import PrivacyRules
from smartnotice.schemas import Sentence

# A period after these tokens continues the sentence ("TP. Hồ Chí Minh").
_TITLE_END = re.compile(r"(?:^|[\s(.,;:/-])(?:TS|ThS|Th\.S|PGS|GS|KS|BS|TP|Tp|Mr|Mrs|Ms|Dr|P|Q)$")
_LIST_MARKER = re.compile(r"[\s*_(\[]*(?:\d{1,2}|[A-Za-zĐđ]|[IVXivx]{1,4})")
# Runs include joiners so "❤️‍🔥" leaves its BMP symbol without a dangling ZWJ.
_ASTRAL_RUN = re.compile("[‍️]*[\U00010000-\U0010ffff](?:[‍️]*[\U00010000-\U0010ffff])*[‍️]*")


def _drop_astral_emoji(match: re.Match) -> str:
    """Remove symbols and their modifiers; a space keeps adjacent words separate."""
    kept = "".join(
        character
        for character in match.group()
        if ord(character) > 0xFFFF and unicodedata.category(character) not in {"So", "Sk", "Cf"}
    )
    if kept:
        return kept
    before = match.string[match.start() - 1 : match.start()]
    after = match.string[match.end() : match.end() + 1]
    return " " if before.isalnum() and after.isalnum() else ""


def normalize_text(text: str, preserve_images: bool = False) -> str:
    """Return NFC text with MIME whitespace/control noise removed, retaining diacritics.

    Emoji outside the Basic Multilingual Plane are removed because Python and
    browsers can index them differently, which would shift annotation offsets.
    BMP symbols and non-emoji astral letters remain; raw bytes keep the original.
    """
    text = re.sub(r"\r+\n", "\n", text).replace("\r", "\n")
    # MBOX exports escape a body line beginning with "From ", even when it is
    # ordinary prose (e.g. "From the Foundations"), not a reply quotation.
    text = re.sub(r"(?m)^>From ", "From ", text)
    text = unicodedata.normalize("NFC", text)
    text = _ASTRAL_RUN.sub(_drop_astral_emoji, text)
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

    This deterministic segmentation is a review aid. A period after a common
    title/place abbreviation or a line-leading list marker does not end a
    sentence, so one model quote can cover "TP. Hồ Chí Minh". Other abbreviations
    may still require annotators to select multiple evidence sentences.
    """
    sentences: list[Sentence] = []

    def add(start: int, end: int) -> None:
        raw = text[start:end]
        if not raw.strip():
            return
        start += len(raw) - len(raw.lstrip())
        end -= len(raw) - len(raw.rstrip())
        sentences.append(
            Sentence(
                sentence_id=f"s{len(sentences) + 1}", start=start, end=end, text=text[start:end]
            )
        )

    for line in re.finditer(r"[^\n]+", text):
        begin = 0
        for mark in re.finditer(r"[.!?](?=\s|$)", line.group()):
            head = line.group()[begin : mark.start()]
            if mark.group() == "." and (
                _TITLE_END.search(head) or (begin == 0 and _LIST_MARKER.fullmatch(head))
            ):
                continue
            add(line.start() + begin, line.start() + mark.end())
            begin = mark.end()
        add(line.start() + begin, line.end())
    return sentences

"""Describe surface language forms without assigning a document language."""

import re
import unicodedata
from collections import Counter

from smartnotice.preprocessing.links import find_link_occurrences
from smartnotice.schemas import LanguageFinding

ABBREVIATIONS = tuple(
    "SV HK ĐKHP DKHP ĐK DK HP GV CB CTĐT CTDT CNTT ĐH DH CĐ CD HSSV KTX PĐT PDT BGH THS TS".split()
)
ENGLISH_WORDS = tuple(
    sorted(
        set(
            (
                "deadline online offline email mail link form forms google microsoft teams "
                "zoom meeting workshop seminar webinar scholarship application apply "
                "submit registration register course courses student students credit "
                "credits semester academic university international office training "
                "internship research project program programme english test exam "
                "certificate download upload account password login feedback survey update "
                "schedule room website portal bachelor master education admission "
                "announcement please dear regards thank thanks"
            ).split()
        )
    )
)
UNACCENTED_PHRASES = (
    "sinh vien",
    "hoc ky",
    "dang ky hoc phan",
    "thong bao",
    "hoc phi",
    "nop ho so",
    "han chot",
    "phong dao tao",
    "lich thi",
    "xin chao",
    "cam on",
)
RULE_VERSION = "surface_v1"
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def has_vietnamese_mark(text: str) -> bool:
    """Detect Vietnamese letters/marks; this is a surface cue, not language ID."""
    return any(c in "ăâđêôơưĂÂĐÊÔƠƯ" for c in text) or any(
        c in "\u0300\u0301\u0303\u0309\u0323\u0306\u031b"
        for c in unicodedata.normalize("NFD", text)
    )


def _masked_text(text: str) -> str:
    masked = list(text)
    excluded = [(u.start, u.end) for u in find_link_occurrences(text)]
    excluded.extend((m.start(), m.end()) for m in re.finditer(r"\[[A-Z_]+\]", text))
    for start, end in excluded:
        masked[start:end] = [" " if c != "\n" else "\n" for c in text[start:end]]
    return "".join(masked)


def surface_words(text: str) -> list[str]:
    """Return alphabetic surface words excluding URLs and privacy placeholders."""
    return [m.group() for m in _WORD.finditer(_masked_text(text))]


def language_features(text: str) -> tuple[dict[str, int], list[LanguageFinding]]:
    """Count words/lines and return candidate offsets into the original text.

    URLs and bracketed privacy placeholders are excluded. ASCII words and
    dictionary hits do not establish unaccented Vietnamese or English language.
    """
    clean = _masked_text(text)
    words = list(_WORD.finditer(clean))
    counts = Counter(words=len(words), ascii_words=sum(m.group().isascii() for m in words))
    findings = []

    def add(rule: str, start: int, end: int, key: str | None = None) -> None:
        findings.append(LanguageFinding(rule=rule, start=start, end=end, lexicon_key=key))
        counts[rule] += 1

    for match in words:
        value = match.group()
        if value.upper() in ABBREVIATIONS:
            add("known_abbreviation", match.start(), match.end(), value.upper())
        if value.lower() in ENGLISH_WORDS:
            add("english_lexicon_hit", match.start(), match.end(), value.lower())
    for phrase in UNACCENTED_PHRASES:
        pattern = r"(?<!\w)" + r"\s+".join(map(re.escape, phrase.split())) + r"(?!\w)"
        for match in re.finditer(pattern, clean, re.I):
            add("unaccented_phrase_candidate", match.start(), match.end(), phrase)
    cursor = 0
    for line in clean.splitlines(keepends=True):
        letters = "".join(c for c in line if c.isalpha())
        if len(letters) >= 2:
            counts["eligible_lines"] += 1
            if letters.isupper():
                add("uppercase_line", cursor, cursor + len(line.rstrip("\r\n")))
            if letters.islower():
                add("lowercase_line", cursor, cursor + len(line.rstrip("\r\n")))
            if letters.isascii():
                add("ascii_only_line_candidate", cursor, cursor + len(line.rstrip("\r\n")))
            if has_vietnamese_mark(line) and any(
                m.group().lower() in ENGLISH_WORDS for m in _WORD.finditer(line)
            ):
                add("mixed_vietnamese_english_candidate", cursor, cursor + len(line.rstrip("\r\n")))
        cursor += len(line)
    return dict(counts), findings

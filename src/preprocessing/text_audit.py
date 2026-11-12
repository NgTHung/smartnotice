"""Find review-worthy characters and structure in prepared notice text."""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from smartnotice.preprocessing.links import find_link_occurrences

_HTML_TAG = re.compile(
    r"</?(?:html|body|div|span|p|br|table|thead|tbody|tr|td|th|a|img|meta|style|script)\b[^>]*>",
    re.I,
)
_HTML_ENTITY = re.compile(r"&(?:nbsp|amp|lt|gt|quot|#\d{2,6}|#x[0-9a-f]{2,6});", re.I)
_MIME_MARKER = re.compile(
    r"(?im)^\s*(?:content-type:|content-transfer-encoding:|mime-version:|boundary=|cid:|--[-_A-Za-z0-9]{6,})"
)
_MOJIBAKE = re.compile(r"(?:Ã.|Â.|áº[0-9A-Fa-f]|á»[0-9A-Fa-f]|Ä\x83|Æ\xA1)")
_LONG_WORD = re.compile(r"(?<!\S)[^\s]{80,}(?!\S)")
_DATE_LIKE = re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}|\d{1,2}\s+tháng\s+\d{1,2})\b", re.I)


@dataclass(frozen=True)
class TextFinding:
    """A text anomaly candidate without source snippets."""

    rule_id: str
    stage: str
    severity: str
    confidence: str
    start: int | None
    end: int | None
    codepoint: str | None
    unicode_name: str | None
    occurrence_count: int
    detail_code: str


def _finding(
    rule_id: str,
    start: int | None,
    end: int | None,
    *,
    severity: str = "review",
    confidence: str = "medium",
    codepoint: str | None = None,
    unicode_name: str | None = None,
    count: int = 1,
) -> TextFinding:
    return TextFinding(
        rule_id,
        "prepared_text",
        severity,
        confidence,
        start,
        end,
        codepoint,
        unicode_name,
        count,
        rule_id,
    )


def scan_prepared_text(text: str, parser_warnings: list[str] | None = None) -> list[TextFinding]:
    """Return deterministic heuristic findings with code-point offsets.

    Findings identify review candidates, not confirmed preprocessing defects.
    Vietnamese diacritics, combining marks, and ordinary non-ASCII characters
    are not flagged by themselves.
    """
    findings: list[TextFinding] = []
    if not unicodedata.is_normalized("NFC", text):
        findings.append(
            _finding("unicode.non_nfc", 0, len(text), severity="info", confidence="high")
        )
    for index, char in enumerate(text):
        category = unicodedata.category(char)
        name = unicodedata.name(char, "UNNAMED")
        if char == "\ufffd":
            findings.append(
                _finding(
                    "unicode.replacement_character",
                    index,
                    index + 1,
                    severity="critical",
                    confidence="high",
                    codepoint=f"U+{ord(char):04X}",
                    unicode_name=name,
                )
            )
        elif category in {"Cc", "Cf", "Co", "Cs"} and char not in "\n\r\t":
            severity = "critical" if char in {"\u200b", "\u200e", "\u200f", "\ufeff"} else "review"
            findings.append(
                _finding(
                    "unicode.invisible_or_control",
                    index,
                    index + 1,
                    severity=severity,
                    confidence="high",
                    codepoint=f"U+{ord(char):04X}",
                    unicode_name=name,
                )
            )
        elif ord(char) > 0xFFFF:
            findings.append(
                _finding(
                    "unicode.non_bmp_offset_review",
                    index,
                    index + 1,
                    severity="info",
                    confidence="high",
                    codepoint=f"U+{ord(char):04X}",
                    unicode_name=name,
                )
            )
    for rule, pattern, confidence in (
        ("encoding.mojibake_heuristic", _MOJIBAKE, "low"),
        ("structure.html_tag_residue", _HTML_TAG, "medium"),
        ("structure.html_entity_residue", _HTML_ENTITY, "medium"),
        ("structure.mime_marker_residue", _MIME_MARKER, "medium"),
        ("structure.long_unbroken_token", _LONG_WORD, "low"),
    ):
        for match in pattern.finditer(text):
            findings.append(_finding(rule, match.start(), match.end(), confidence=confidence))
    # Repeated exact long lines can indicate duplicated parser output. Keep only
    # line numbers/offsets; never copy the line itself into the finding.
    line_offsets = []
    cursor = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if len(stripped) >= 80:
            line_offsets.append(
                (cursor + len(line) - len(line.lstrip()), cursor + len(line.rstrip()))
            )
        cursor += len(line)
    line_keys = [text[start:end] for start, end in line_offsets]
    duplicate_counts = Counter(line_keys)
    for (start, end), key in zip(line_offsets, line_keys, strict=True):
        if duplicate_counts[key] > 1:
            findings.append(
                _finding(
                    "structure.repeated_long_line",
                    start,
                    end,
                    confidence="low",
                    count=duplicate_counts[key],
                )
            )
    # Flag line breaks inside a URL-like token only when a date or URL fragment
    # is split across the boundary; human review determines whether it is wrong.
    for match in re.finditer(r"(?i)(?:https?://|www\.)[^\s\n]{2,}\n[ \t]*[^\s\n]{2,}", text):
        findings.append(
            _finding(
                "structure.url_line_break_candidate", match.start(), match.end(), confidence="low"
            )
        )
    for match in re.finditer(
        r"(?i)\b(?:ngày|hạn|deadline)\s*[:：]?\s*\d{0,2}\s*\n\s*\d{1,2}[/-]\d{1,2}", text
    ):
        findings.append(
            _finding(
                "structure.date_line_break_candidate", match.start(), match.end(), confidence="low"
            )
        )
    for occurrence in find_link_occurrences(text):
        if re.search(r"\[(?:EMAIL|PHONE|ID|PERSON|STUDENT|REDACTED)\]", occurrence.value, re.I):
            findings.append(
                _finding(
                    "privacy.redaction_inside_url",
                    occurrence.start,
                    occurrence.end,
                    severity="critical",
                    confidence="high",
                )
            )
    for _warning in parser_warnings or []:
        findings.append(_finding("parser.warning_present", None, None, confidence="high"))
    return findings


def review_stratum(notice) -> list[str]:
    """Describe deterministic review strata without exposing source content."""
    size = len(notice.text)
    length = "short" if size < 1200 else "medium" if size < 5000 else "long"
    strata = [notice.source_type, f"length_{length}"]
    strata.append("has_url" if find_link_occurrences(notice.text) else "no_url")
    strata.append("parser_warning" if notice.parser_warnings else "no_parser_warning")
    strata.append("synthetic" if notice.synthetic else "research")
    return strata

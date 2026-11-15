"""Tracked copy of the TIME-span date rule used by the v3.1 curation recipe.

The v3.1 curated snapshot wrote every ``normalized_date`` and ``inferred`` value
with ``normalize_time_span`` from
``data/annotations/cleanup_curated_2026-11-10_v3_1/rules.py`` (SHA-256
``1eca99bc7f0eb8deaff1c56c5c2f1cde879adf9f8b44514b0d7676c27c4799c5``). That
recipe sits under the ignored research-data directory, so the report cannot
cite it. This module copies ``folded`` and ``normalize_time_span`` from that
file so the report can name tracked code. The code is unchanged; only the
``normalize_time_span`` docstring gained a sentence about its return value.

``gap_stats.py`` reruns this copy on every TIME argument and counts stored
values that it does not reproduce. A count of zero shows that this copy
matches the dates stored in the snapshot.
"""

import re
import unicodedata
from datetime import date

from smartnotice.preprocessing.dates import normalize_date


def folded(text: str) -> str:
    """Return NFC, case-folded text with whitespace and spelling variants normalized."""
    return (
        " ".join(unicodedata.normalize("NFC", text).casefold().split())
        .replace("khoá", "khóa")
        .replace("chính qui", "chính quy")
    )


def normalize_time_span(
    text: str, reference_date: date | None
) -> tuple[date | None, bool, str | None]:
    """Normalize one calendar date, accepting a clock range on that same day.

    Full hyphenated day-month-year dates are accepted. Multiple dates and
    compact day ranges stay null; a clock or duration alone is never a date.
    Returns ``(normalized_date, inferred, reason)``; ``reason`` names why the
    date stayed null and is ``None`` when a date was produced.
    """
    value = folded(re.sub(r"[*_]", "", text))
    pattern = (
        r"(?<![\d/:])(\d{1,2})\s*([/-])\s*(\d{1,2})"
        r"(?:\s*[/-]\s*(\d{4}))?(?![\d/:])"
    )
    matches = []
    for match in re.finditer(pattern, value):
        day, separator, month, year = match.groups()
        if separator == "-" and year is None:
            continue
        candidate = f"{day}/{month}" + (f"/{year}" if year else "")
        normalized, inferred = normalize_date(candidate, reference_date)
        plausible_without_reference = (
            year is None
            and reference_date is None
            and 1 <= int(month) <= 12
            and 1 <= int(day) <= 31
        )
        if normalized is not None or plausible_without_reference:
            matches.append((match, normalized, inferred))
    if len(matches) != 1:
        reason = "multiple_calendar_dates_require_split" if len(matches) > 1 else "no_calendar_date"
        return None, False, reason
    match, normalized, inferred = matches[0]
    prefix, suffix = value[: match.start()], value[match.end() :]
    before = re.search(
        r"(?<![\d/:h])(\d{1,2})\s*(?:[-–—]|đến|tới)\s*"
        r"(?:(?:hết\s+)?ngày\s*)?$",
        prefix,
    )
    after = re.match(
        r"\s*(?:[-–—]|đến|tới)\s*(?:ngày\s*)?\d{1,2}(?![\dh:])"
        r"(?!\s*(?:giờ|phút))",
        suffix,
    )
    if before or after:
        return None, False, "compact_calendar_range_requires_split"
    return normalized, inferred, None if normalized else "invalid_date_or_missing_reference"

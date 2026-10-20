"""Normalize explicit numeric dates without guessing relative expressions."""

import re
from datetime import date


def normalize_date(value: str, reference_date: date | None = None) -> tuple[date | None, bool]:
    """Return (date, inferred-year flag), or (None, False) when unresolved.

    Missing years use the reference year without rollover assumptions. Relative
    dates remain unresolved so annotation review controls their interpretation.
    """
    match = re.fullmatch(r"\s*(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}))?\s*", value)
    if not match:
        return None, False
    day, month, year = match.groups()
    if year is None and reference_date is None:
        return None, False
    try:
        return date(int(year) if year else reference_date.year, int(month), int(day)), year is None
    except ValueError:
        return None, False

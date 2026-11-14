"""Produce reproducible quality counts from prepared documents and split assignments."""

from collections import Counter

import pandas as pd
from smartnotice.schemas import Notice


def reference_date_counts(notices: list[Notice]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Count documents by calendar month and source, plus date coverage by source.

    Return integer monthly counts on a chronological monthly PeriodIndex and
    coverage columns ``total``, ``dated``, ``missing``. Include zero months between
    the earliest and latest reference dates and all observed source types. Null
    dates contribute only to coverage; publication candidates are never used.
    Empty input or entirely missing dates produce an empty monthly table.
    """
    sources = sorted({notice.source_type for notice in notices})
    total = Counter(notice.source_type for notice in notices)
    dated = Counter(notice.source_type for notice in notices if notice.reference_date is not None)
    coverage = pd.DataFrame(
        [[total[source], dated[source], total[source] - dated[source]] for source in sources],
        index=pd.Index(sources, name="source_type"),
        columns=["total", "dated", "missing"],
        dtype="int64",
    )
    counts = Counter(
        (pd.Period(notice.reference_date, freq="M"), notice.source_type)
        for notice in notices
        if notice.reference_date is not None
    )
    months = [month for month, _ in counts]
    index = (
        pd.period_range(min(months), max(months), freq="M", name="month")
        if months
        else pd.PeriodIndex([], freq="M", name="month")
    )
    monthly = pd.DataFrame(
        [[counts[month, source] for source in sources] for month in index],
        index=index,
        columns=pd.Index(sources, name="source_type"),
        dtype="int64",
    )
    return monthly, coverage


def quality_summary(notices: list[Notice], splits: list[dict]) -> dict:
    """Report corpus size, source balance, missing dates, and split leakage."""
    ids = [row["doc_id"] for row in splits]
    if len(ids) != len(set(ids)):
        raise ValueError("Split assignments must contain unique document IDs")
    if {notice.doc_id for notice in notices} != {row["doc_id"] for row in splits}:
        raise ValueError("Split assignments must cover exactly the prepared documents")
    groups: dict[str, set[str]] = {}
    for row in splits:
        groups.setdefault(row["group_id"], set()).add(row["split"])
    leaks = [
        key
        for key, values in groups.items()
        if len(values - {"domain_test", "excluded"}) > 1
        or (values & {"domain_test", "excluded"} and values - {"domain_test", "excluded"})
    ]
    return {
        "document_count": len(notices),
        "synthetic_count": sum(notice.synthetic for notice in notices),
        "source_counts": dict(Counter(notice.source_type for notice in notices)),
        "missing_reference_dates": sum(notice.reference_date is None for notice in notices),
        "redaction_count": sum(notice.redaction_count for notice in notices),
        "privacy_review_required": sum(notice.privacy_review_required for notice in notices),
        "sentence_count": sum(len(notice.sentences) for notice in notices),
        "empty_documents": sum(not notice.text.strip() for notice in notices),
        "split_counts": dict(Counter(row["split"] for row in splits)),
        "split_group_leaks": leaks,
    }

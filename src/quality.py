"""Produce reproducible quality counts from prepared documents and split assignments."""

from collections import Counter

from smartnotice.schemas import Notice


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

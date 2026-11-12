"""Measure token label membership on validated annotations."""

from collections import Counter

from smartnotice.schemas import Annotation


def token_label_counts(offsets: list[tuple[int, int]], annotation: Annotation) -> Counter:
    """Count exclusive label classes from code-point subword offsets.

    O means no overlap with the supplied spans, not independently verified
    negative gold. Tokens crossing span edges use BOUNDARY; multiple covering
    spans use MULTI. Empty offsets (special/zero-width tokens) are excluded.
    """
    counts = Counter()
    for start, end in offsets:
        if end <= start:
            continue
        hits = [s for s in annotation.spans if max(start, s.start) < min(end, s.end)]
        if not hits:
            counts["O"] += 1
        elif any(start < s.start or end > s.end for s in hits):
            counts["BOUNDARY"] += 1
        elif len(hits) > 1:
            counts["MULTI"] += 1
        else:
            counts[hits[0].label] += 1
    return counts

"""Measure label counts and exact agreement without treating silver labels as gold."""

from collections import Counter

from smartnotice.schemas import Annotation


def annotation_summary(annotations: list[Annotation]) -> dict:
    """Count spans, roles, and action-to-argument distances per annotation."""
    span_counts, role_counts, distances = Counter(), Counter(), []
    for annotation in annotations:
        spans = {span.span_id: span for span in annotation.spans}
        span_counts.update(span.label for span in annotation.spans)
        for event in annotation.events:
            action = spans[event.action_span_id]
            for argument in event.arguments:
                target = spans[argument.span_id]
                if argument.role:
                    role_counts[argument.role] += 1
                distances.append(abs(action.start - target.start))
    return {
        "annotation_count": len(annotations),
        "span_counts": dict(span_counts),
        "time_role_counts": dict(role_counts),
        "argument_distances_chars": distances,
    }


def span_f1(left: Annotation, right: Annotation) -> dict:
    """Compute exact typed-span agreement for two annotations of one document."""
    if left.doc_id != right.doc_id:
        raise ValueError("Agreement requires the same document")
    a = {(span.label, span.start, span.end) for span in left.spans}
    b = {(span.label, span.start, span.end) for span in right.spans}
    matched = len(a & b)
    return {
        "matched": matched,
        "left": len(a),
        "right": len(b),
        "f1": 2 * matched / (len(a) + len(b)) if a or b else 1.0,
    }


def cohens_kappa(left: list[str], right: list[str]) -> float | None:
    """Compute kappa over aligned categorical decisions; return None if undefined."""
    if len(left) != len(right) or not left:
        raise ValueError("Kappa requires equal nonempty aligned label lists")
    a, b = Counter(left), Counter(right)
    observed = sum(x == y for x, y in zip(left, right, strict=True)) / len(left)
    expected = sum(a[key] * b[key] for key in a.keys() | b.keys()) / len(left) ** 2
    return (observed - expected) / (1 - expected) if expected < 1 else None

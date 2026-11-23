"""Measure extraction and applicability using exact document evidence."""

from collections import Counter
from itertools import product

from sklearn.metrics import classification_report, confusion_matrix
from smartnotice.modeling.data import LINK_LABELS, SPAN_LABELS, TIME_ROLES, span_key
from smartnotice.schemas import Annotation


def prf(expected: set, predicted: set) -> dict:
    """Score exact items and expose matched, predicted, and expected denominators."""
    return prf_counts(len(expected & predicted), len(predicted), len(expected))


def prf_counts(tp: int, predicted: int, expected: int) -> dict:
    """Calculate exact-match precision, recall, and F1 from item counts."""
    if not 0 <= tp <= min(predicted, expected):
        raise ValueError("Matching count exceeds metric denominator")
    return {
        "precision": tp / predicted if predicted else 0.0,
        "recall": tp / expected if expected else 0.0,
        "f1": 2 * tp / (expected + predicted) if expected or predicted else 0.0,
        "matched": tp,
        "predicted": predicted,
        "expected": expected,
    }


def span_scores(expected: set, predicted: set) -> dict:
    """Score typed document offsets overall and separately by span type."""
    return {
        "micro": prf(expected, predicted),
        "by_type": {
            label: prf(
                {s for s in expected if s[-1] == label}, {s for s in predicted if s[-1] == label}
            )
            for label in SPAN_LABELS[1:]
        },
    }


def link_scores(expected: set, predicted: set) -> dict:
    """Score exact labeled links and average F1 over roles with gold support."""
    per_role = {
        label: prf(
            {s for s in expected if s[-1] == label}, {s for s in predicted if s[-1] == label}
        )
        for label in LINK_LABELS[1:]
    }
    result = {"micro": prf(expected, predicted), "by_role": per_role}
    for name, labels in (("macro_f1", LINK_LABELS[1:]), ("time_role_macro_f1", TIME_ROLES)):
        values = [per_role[label]["f1"] for label in labels if per_role[label]["expected"]]
        result[name] = sum(values) / len(values) if values else None
    return result


def event_keys(annotation: Annotation) -> dict:
    """Index event argument signatures by exact typed ACTION span."""
    spans = {span.span_id: span_key(span) for span in annotation.spans}
    return {
        spans[event.action_span_id]: frozenset(
            (spans[arg.span_id], arg.role, arg.normalized_date) for arg in event.arguments
        )
        for event in annotation.events
    }


def date_scores(expected: dict, predicted: dict) -> dict:
    """Score normalization per date subset, counting a missing role/link as a miss."""
    result = {}
    for subset in ("explicit", "inferred", "unresolved"):
        keys = [
            key
            for key, (value, inferred) in expected.items()
            if ("unresolved" if value is None else "inferred" if inferred else "explicit") == subset
        ]
        matched = [key for key in keys if key in predicted]
        dates = sum(expected[key][0] == predicted[key][0] for key in matched)
        flags = sum(expected[key][1] == predicted[key][1] for key in matched)
        result[subset] = {
            "expected_links": len(keys),
            "matched_links": len(matched),
            "correct_dates": dates,
            "matched_date_accuracy": dates / len(matched) if matched else None,
            "matched_inferred_flag_accuracy": flags / len(matched) if matched else None,
            "end_to_end_date_accuracy": dates / len(keys) if keys else None,
        }
    return result


def date_map(annotation: Annotation) -> dict:
    """Map a typed TIME link to its normalized date and inference flag."""
    spans = {span.span_id: span_key(span) for span in annotation.spans}
    return {
        (annotation.doc_id, spans[event.action_span_id], spans[arg.span_id], arg.role): (
            arg.normalized_date,
            arg.inferred,
        )
        for event in annotation.events
        for arg in event.arguments
        if spans[arg.span_id][-1] == "TIME"
    }


def classification(expected: list[str], predicted: list[str], labels: tuple[str, ...]) -> dict:
    """Report fixed-label classification metrics including unsupported classes."""
    if not expected:
        return {"examples": 0, "macro_f1": None}
    report = classification_report(
        expected, predicted, labels=list(labels), output_dict=True, zero_division=0
    )
    return {
        "examples": len(expected),
        "macro_f1": report["macro avg"]["f1-score"],
        "classes": {label: report[label] for label in labels},
        "labels": labels,
        "confusion": confusion_matrix(expected, predicted, labels=list(labels)).tolist(),
    }


def relation_confusion(
    endpoints: dict[str, set],
    expected: set,
    predicted: set,
) -> dict:
    """Report the relation confusion matrix over pairs with aligned annotated endpoints."""
    gold = {(doc, a, b): label for doc, a, b, label in expected}
    model = {(doc, a, b): label for doc, a, b, label in predicted}
    counts = Counter()
    for doc, spans in endpoints.items():
        actions = [span for span in spans if span[2] == "ACTION"]
        args = [span for span in spans if span[2] != "ACTION"]
        for a, b in product(actions, args):
            key = doc, a, b
            counts[gold.get(key, "NO_RELATION"), model.get(key, "NO_RELATION")] += 1
    return {
        "labels": LINK_LABELS,
        "confusion": [[counts[a, b] for b in LINK_LABELS] for a in LINK_LABELS],
    }

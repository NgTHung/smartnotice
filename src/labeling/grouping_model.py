"""Fit a source-feature baseline for event identity between two mentions."""

import hashlib
import math
import re
import unicodedata
from typing import Literal

from smartnotice.labeling.grouping_evidence import EVIDENCE_FEATURES
from smartnotice.schemas import GroupingLinearModel, GroupingModelMention, Notice

FEATURES = (
    "context_word_overlap",
    "action_word_overlap",
    "action_trigram_overlap",
    "shared_explicit_date",
    "disjoint_dates_same_role",
    "shared_visible_link",
)
MODEL_FEATURES = {
    "grouping-logistic-v1": FEATURES,
    "grouping-logistic-v2": FEATURES + EVIDENCE_FEATURES,
}
ModelKind = Literal["grouping-logistic-v1", "grouping-logistic-v2"]
LEXICAL_THRESHOLD = 0.5
URL = re.compile(r"https?://[^\s<>]+|www\.[^\s<>]+", re.IGNORECASE)
PLACEHOLDER = re.compile(r"\[[A-Z][A-Z_0-9]*\]")
WORD = re.compile(r"[^\W\d_]{2,}")


def validate_grouping_mention(mention: GroupingModelMention, notice: Notice) -> None:
    """Reject a stale mention, a missing ACTION, or offsets outside source evidence."""
    did = notice.doc_id
    version = mention.version
    if (
        mention.doc_id != did
        or version.event_ref != f"{did}:{mention.event.action_span_id}"
        or version.raw_sha256 != notice.raw_sha256
        or version.text_sha256 != hashlib.sha256(notice.text.encode("utf-8")).hexdigest()
    ):
        raise ValueError(f"Stale grouping mention for {did}")
    spans = {span.span_id: span for span in mention.spans}
    sentences = {sentence.sentence_id: sentence for sentence in mention.sentences}
    source_sentences = {sentence.sentence_id: sentence for sentence in notice.sentences}
    action = spans.get(mention.event.action_span_id)
    if (
        action is None
        or action.label != "ACTION"
        or len(spans) != len(mention.spans)
        or len(sentences) != len(mention.sentences)
        or sentences.keys() != set(mention.event.evidence_sentence_ids)
        or any(source_sentences.get(sid) != sent for sid, sent in sentences.items())
        or any(arg.span_id not in spans for arg in mention.event.arguments)
    ):
        raise ValueError(f"Invalid grouping mention references for {did}")
    if any(
        notice.text[span.start : span.end] != span.text
        or not any(s.start <= span.start < span.end <= s.end for s in sentences.values())
        for span in spans.values()
    ):
        raise ValueError(f"Invalid grouping mention offsets for {did}")


def _words(text: str) -> list[str]:
    clean = URL.sub(" ", PLACEHOLDER.sub(" ", text))
    return WORD.findall(unicodedata.normalize("NFC", clean).casefold())


def _trigrams(text: str) -> set[str]:
    value = " ".join(_words(text))
    return {value[i : i + 3] for i in range(len(value) - 2)}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _dates(mention: GroupingModelMention) -> dict[str, set[str]]:
    dates: dict[str, set[str]] = {}
    for arg in mention.event.arguments:
        if arg.role and arg.normalized_date and not arg.inferred:
            dates.setdefault(arg.role, set()).add(arg.normalized_date.isoformat())
    return dates


def pair_features(left: GroupingModelMention, right: GroupingModelMention) -> tuple[float, ...]:
    """Return symmetric overlap features from validated mention evidence."""
    a = {s.span_id: s.text for s in left.spans}[left.event.action_span_id]
    b = {s.span_id: s.text for s in right.spans}[right.event.action_span_id]
    left_text = "\n".join(s.text for s in left.sentences)
    right_text = "\n".join(s.text for s in right.sentences)
    x, y = _dates(left), _dates(right)
    return (
        _jaccard(set(_words(left_text)), set(_words(right_text))),
        _jaccard(set(_words(a)), set(_words(b))),
        _jaccard(_trigrams(a), _trigrams(b)),
        float(bool(set().union(*x.values()) & set().union(*y.values()))),
        float(any(not x[role] & y[role] for role in x.keys() & y.keys())),
        float(bool(set(URL.findall(left_text)) & set(URL.findall(right_text)))),
    )


def fit_grouping_classifier(
    features: list[tuple[float, ...]],
    labels: list[bool],
    *,
    seed: int,
    kind: ModelKind = "grouping-logistic-v1",
) -> GroupingLinearModel:
    """Fit scaling and L2 logistic regression on the supplied examples only."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    if len(features) != len(labels) or set(labels) != {True, False}:
        raise ValueError("Grouping training requires aligned features and both classes")
    feature_names = MODEL_FEATURES[kind]
    if any(len(row) != len(feature_names) for row in features):
        raise ValueError("Grouping training feature version mismatch")
    scaler = StandardScaler()
    scaled = scaler.fit_transform(features)
    classifier = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000, random_state=seed)
    classifier.fit(scaled, labels)
    return GroupingLinearModel(
        kind=kind,
        features=list(feature_names),
        mean=scaler.mean_.tolist(),
        scale=scaler.scale_.tolist(),
        weights=classifier.coef_[0].tolist(),
        intercept=float(classifier.intercept_[0]),
    )


def grouping_probability(model: GroupingLinearModel, features: tuple[float, ...]) -> float:
    """Return the fitted probability of shared event identity for one pair."""
    expected = MODEL_FEATURES[model.kind]
    if tuple(model.features) != expected or len(features) != len(expected):
        raise ValueError("Grouping model feature version mismatch")
    value = model.intercept + sum(
        weight * (feature - mean) / scale
        for feature, weight, mean, scale in zip(
            features, model.weights, model.mean, model.scale, strict=True
        )
    )
    return 1 / (1 + math.exp(-value)) if value >= 0 else math.exp(value) / (1 + math.exp(value))

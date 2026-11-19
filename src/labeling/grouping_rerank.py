"""Rank a verified reply against prepared source items with a fitted text scorer."""

import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, model_validator
from smartnotice.labeling.grouping_alignment import (
    FollowupAlignment,
    FollowupProfile,
    compatible_followup_items,
)
from smartnotice.labeling.grouping_followup import RoutingComparison
from smartnotice.labeling.grouping_model import PLACEHOLDER, URL, WORD
from smartnotice.schemas import Record

FEATURES = (
    "evidence_word_jaccard",
    "evidence_character_jaccard",
    "action_word_jaccard",
    "action_character_jaccard",
    "reply_action_in_parent_evidence",
    "parent_action_in_reply_evidence",
    "action_concept_jaccard",
    "evidence_concept_jaccard",
    "scoped_subject_jaccard",
    "shared_explicit_identity",
    "shared_scoped_item",
)

_STOP_WORDS = frozenset(
    "về cho em tôi chúng ta bạn anh chị các của những xin cảm ơn vui lòng kính chào "
    "trân trọng phải được vừa đang đã sẽ là một có không thể bằng theo lại đây "
    "này đó với qua hay hoặc và thêm thường ngày tháng năm học viên sinh viên "
    "ban phòng khoa trường thông báo thông tin nội dung liên hệ học vụ nhà trường".split()
)
_MAILBOX = re.compile(r"\b[^\s<>@]+@[^\s<>@]+")
_CONCEPTS = tuple(
    (name, re.compile(pattern))
    for name, pattern in (
        ("submission", r"\b(?:nộp|gửi|chuyển)\s+(?:bài|hồ sơ|tài liệu|biểu mẫu|phiếu)\b"),
        ("registration", r"\b(?:đăng k[ýí]|ghi danh|ghi tên|đăng danh)\b"),
        ("adjustment", r"\b(?:hiệu chỉnh|điều chỉnh|thay đổi)\b"),
        ("assessment", r"\b(?:bài thi|buổi thi|kiểm tra|đánh giá|thi giữa|thi cuối)\b"),
        ("schedule", r"\b(?:lịch|buổi|ca thi|thời khóa biểu)\b"),
        ("deadline", r"\b(?:hạn|hạn chót|thời hạn|hạn cuối|gia hạn)\b"),
        ("form", r"\b(?:mẫu đơn|đơn|biểu mẫu|phiếu|bản mềm)\b"),
        ("system", r"\b(?:hệ thống|cổng thông tin|cổng đăng ký|phần mềm|website)\b"),
        ("system_availability", r"\b(?:bị lỗi|sự cố|lỗi truy cập|truy cập|hoạt động|khôi phục)\b"),
        ("teaching", r"\b(?:học phần|môn học|lớp học|tiết học)\b"),
        ("supervision", r"\b(?:cố vấn|người hướng dẫn|giảng viên phụ trách)\b"),
        ("meeting", r"\b(?:hẹn|họp|tập trung|gặp mặt|sinh hoạt)\b"),
        ("payment", r"\b(?:đóng phí|nộp phí|thanh toán|chuyển khoản|học phí)\b"),
        ("room", r"\b(?:phòng học|phòng thi|phòng máy|phòng thí nghiệm|địa điểm)\b"),
        ("laboratory", r"\b(?:phòng thí nghiệm|thực hành|thí nghiệm|đo mẫu)\b"),
        ("survey", r"\b(?:khảo sát|lấy ý kiến|phản hồi|bảng hỏi)\b"),
        ("financial_aid", r"\b(?:học bổng|hỗ trợ tài chính|vay vốn|trợ cấp)\b"),
        ("return", r"\b(?:thu hồi|bàn giao|hoàn trả|trả lại)\b"),
    )
)


class FollowupRerankModel(Record):
    """Store scaled logistic coefficients, score threshold and runner-up margin."""

    kind: Literal["followup-rerank-logistic-v1"] = "followup-rerank-logistic-v1"
    features: list[str]
    mean: list[float]
    scale: list[float]
    weights: list[float]
    intercept: float
    threshold: float = Field(default=0.6, gt=0, lt=1)
    margin: float = Field(default=0.1, gt=0, lt=1)

    @model_validator(mode="after")
    def check_checkpoint(self):
        """Reject unknown feature versions, non-finite coefficients and malformed scaling."""
        validate_rerank_model(self)
        return self


def validate_rerank_model(model: FollowupRerankModel) -> None:
    """Reject invalid, mutated or incompatible follow-up checkpoints with ValueError."""
    vectors = (model.mean, model.scale, model.weights)
    if tuple(model.features) != FEATURES or any(len(v) != len(FEATURES) for v in vectors):
        raise ValueError("Follow-up model feature version mismatch")
    if (
        not math.isfinite(model.intercept)
        or not (0 < model.threshold < 1 and 0 < model.margin < 1)
        or not all(math.isfinite(number) for vector in vectors for number in vector)
        or any(scale <= 0 for scale in model.scale)
    ):
        raise ValueError("Follow-up model requires finite coefficients and positive scaling")


@dataclass(frozen=True, repr=False)
class _TextFeatures:
    action_words: frozenset[str]
    action_trigrams: frozenset[str]
    action_concepts: frozenset[str]
    evidence_words: frozenset[str]
    evidence_trigrams: frozenset[str]
    evidence_concepts: frozenset[str]


def _text_signals(text: str) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    cleaned = _MAILBOX.sub(" ", URL.sub(" ", PLACEHOLDER.sub(" ", text)))
    normalized = " ".join(unicodedata.normalize("NFC", cleaned).casefold().split())
    words = tuple(word for word in WORD.findall(normalized) if word not in _STOP_WORDS)
    joined = " ".join(words)
    return (
        frozenset(words),
        frozenset(joined[i : i + 3] for i in range(len(joined) - 2)),
        frozenset(name for name, pattern in _CONCEPTS if pattern.search(normalized)),
    )


def _encode(profile: FollowupProfile) -> _TextFeatures:
    action = _text_signals(profile.action_text)
    evidence = _text_signals("\n".join(profile.evidence_text))
    return _TextFeatures(*action, *evidence)


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    return len(left & right) / len(left | right) if left or right else 0.0


def _coverage(query: frozenset[str], evidence: frozenset[str]) -> float:
    return len(query & evidence) / len(query) if query else 0.0


def _compare(
    parent: FollowupProfile, reply: FollowupProfile, a: _TextFeatures, b: _TextFeatures
) -> tuple[tuple[float, ...], bool]:
    identity_shared = bool(
        parent.codes.keys() & reply.codes.keys() or parent.forms.keys() & reply.forms.keys()
    )
    scoped_item_shared = bool(
        parent.classes & reply.classes
        or (
            parent.scope.course
            and parent.scope.course == reply.scope.course
            and parent.scope.term
            and parent.scope.term == reply.scope.term
        )
    )
    topic_words = a.evidence_words & b.evidence_words
    action_support = bool(a.action_words & b.evidence_words or b.action_words & a.evidence_words)
    concept_support = len(a.evidence_concepts & b.evidence_concepts) >= 2
    supported = (
        identity_shared
        or scoped_item_shared
        or (action_support and len(topic_words) >= 2)
        or (concept_support and bool(topic_words))
    )
    features = (
        _jaccard(a.evidence_words, b.evidence_words),
        _jaccard(a.evidence_trigrams, b.evidence_trigrams),
        _jaccard(a.action_words, b.action_words),
        _jaccard(a.action_trigrams, b.action_trigrams),
        _coverage(b.action_words, a.evidence_words),
        _coverage(a.action_words, b.evidence_words),
        _jaccard(a.action_concepts, b.action_concepts),
        _jaccard(a.evidence_concepts, b.evidence_concepts),
        _jaccard(frozenset(parent.subject), frozenset(reply.subject)),
        float(identity_shared),
        float(scoped_item_shared),
    )
    return features, supported


def followup_rerank_features(parent: FollowupProfile, reply: FollowupProfile) -> tuple[float, ...]:
    """Return ordered numeric features for a source-bound parent and reply item."""
    return _compare(parent, reply, _encode(parent), _encode(reply))[0]


def fit_followup_reranker(
    features: Sequence[tuple[float, ...]], labels: Sequence[bool], *, seed: int
) -> FollowupRerankModel:
    """Fit L2 logistic regression on labelled train rows with both target classes."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    if len(features) != len(labels) or set(labels) != {True, False}:
        raise ValueError("Follow-up training requires aligned rows and both target classes")
    if any(len(row) != len(FEATURES) or not all(math.isfinite(x) for x in row) for row in features):
        raise ValueError("Invalid follow-up training features")
    scaler = StandardScaler()
    scaled = scaler.fit_transform(features)
    classifier = LogisticRegression(
        C=1.0, solver="lbfgs", max_iter=1000, random_state=seed, class_weight="balanced"
    )
    classifier.fit(scaled, labels)
    return FollowupRerankModel(
        features=list(FEATURES),
        mean=scaler.mean_.tolist(),
        scale=scaler.scale_.tolist(),
        weights=classifier.coef_[0].tolist(),
        intercept=float(classifier.intercept_[0]),
    )


def _score(model: FollowupRerankModel, features: tuple[float, ...]) -> float:
    value = model.intercept + sum(
        coefficient * ((feature - mean) / scale)
        for feature, mean, scale, coefficient in zip(
            features, model.mean, model.scale, model.weights, strict=True
        )
        if coefficient
    )
    if not math.isfinite(value):
        raise ValueError("Non-finite follow-up score")
    return 1 / (1 + math.exp(-value)) if value >= 0 else math.exp(value) / (1 + math.exp(value))


def followup_rerank_score(model: FollowupRerankModel, features: tuple[float, ...]) -> float:
    """Return the model's unit-interval score for finite features in checkpoint order."""
    validate_rerank_model(model)
    if len(features) != len(FEATURES) or not all(math.isfinite(x) for x in features):
        raise ValueError("Invalid follow-up scoring features")
    return _score(model, features)


def rerank_followup_mentions(
    left: Sequence[FollowupProfile],
    right: Sequence[FollowupProfile],
    routing: RoutingComparison,
    model: FollowupRerankModel,
    existing: Mapping[tuple[str, str], FollowupAlignment],
) -> dict[tuple[str, str], FollowupAlignment]:
    """Return new mutually best links above the cutoff for a verified directed reply.

    Compare every compatible prepared item. Each selected side must exceed its
    runner-up by the model margin. Require content support on both items and
    reserve mention endpoints already linked by the existing policy. Preserve
    input order and prepared sentence IDs. Return an empty result without a
    verified reply and raise ValueError for an invalid model.
    """
    validate_rerank_model(model)
    if not routing.direct_parent or routing.later not in (0, 1):
        return {}
    left_encoded = [(p, _encode(p)) for p in left]
    right_encoded = [(p, _encode(p)) for p in right]
    left_choices = defaultdict(list)
    right_choices = defaultdict(list)
    candidates = {}
    for a, a_features in left_encoded:
        for b, b_features in right_encoded:
            if not compatible_followup_items(a, b):
                continue
            features, supported = (
                _compare(a, b, a_features, b_features)
                if routing.later == 1
                else _compare(b, a, b_features, a_features)
            )
            key = (a.mention_id, b.mention_id)
            score = _score(model, features)
            left_choices[key[0]].append((score, key))
            right_choices[key[1]].append((score, key))
            if supported:
                candidates[key] = FollowupAlignment(
                    "reranked_reply_match", (a.sentences, b.sentences)
                )

    def winners(choices: Mapping[str, list[tuple[float, tuple[str, str]]]]) -> set:
        selected = set()
        for rows in choices.values():
            ranking = sorted(rows, reverse=True)
            score, key = ranking[0]
            if score >= model.threshold and (
                len(ranking) == 1 or score - ranking[1][0] >= model.margin
            ):
                selected.add(key)
        return selected

    reserved_left = {key[0] for key in existing}
    reserved_right = {key[1] for key in existing}
    return {
        key: candidates[key]
        for key in sorted(winners(left_choices) & winners(right_choices) & candidates.keys())
        if key[0] not in reserved_left and key[1] not in reserved_right
    }

"""Propose event groups conservatively while preserving every source mention."""

import hashlib
import re
from datetime import date
from itertools import combinations
from typing import Literal

from pydantic import Field
from smartnotice.labeling.llm import text_sha256
from smartnotice.labeling.validation import validate_annotation
from smartnotice.schemas import Annotation, Argument, Notice, Record, Sentence, Span

STOPWORDS = set(
    "và của các sinh viên trong được cho là có tại với để theo từ đến vào một những "
    "này sẽ đã khi hoặc phải thông báo thực hiện tham gia đăng ký liên hệ vui lòng "
    "ngày thời gian năm học nhà trường bạn em qua như sau lại xem nhận nộp".split()
)
DATE = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](20\d{2})\b")
PERIOD = re.compile(r"\bhk\s*[123]\s*/\s*\d{4}(?:\s*[-–]\s*\d{4})?|\b20\d{2}\s*[-–]\s*20\d{2}\b")
UPDATE = re.compile(r"gia hạn thời gian|thời hạn.{0,15}mới|dời lịch|thay đổi thời gian")


class GroupingConfig(Record):
    """Set candidate Jaccard similarity and minimum shared informative words."""

    similarity: float = Field(default=0.8, gt=0, le=1)
    min_shared_tokens: int = Field(default=3, ge=1)


class EventMention(Record):
    """Keep an event's exact spans, source hashes, and unreviewed origin."""

    event_ref: str
    doc_id: str
    event_id: str
    annotation_origin: str
    raw_sha256: str
    text_sha256: str
    action: Span
    arguments: list[Argument]
    argument_spans: list[Span]
    evidence: list[Sentence]
    review_required: bool = True


class PairDecision(Record):
    """Record a rule proposal; similarity is not a calibrated confidence."""

    left: str
    right: str
    similarity: float
    decision: Literal["SAME_EVENT", "UPDATE_CANDIDATE", "DIFFERENT_EVENT", "UNCLEAR"]
    reasons: list[str]
    grouped: bool = False


class EventGroup(Record):
    """Reference source mentions without discarding or resolving conflicting fields."""

    group_id: str
    members: list[str]
    review_required: bool = True


class GroupingResult(Record):
    """Contain tentative groups, candidate decisions, and comparison parameters."""

    rule_version: str = "event-grouping-prototype-v1"
    config: GroupingConfig
    mentions: list[EventMention]
    groups: list[EventGroup]
    decisions: list[PairDecision]
    compared_pairs: int


def _normalize(text: str) -> str:
    text = re.sub(r"https?://\S+|www\.\S+|\[[A-Z_]+\]", " ", text)
    return " ".join(re.findall(r"\w+", text.casefold()))


def _family(text: str) -> str | None:
    normalized = _normalize(text)
    for phrase, family in (
        ("đăng ký", "register"),
        ("đăng kí", "register"),
        ("tham dự", "attend"),
        ("tham gia", "attend"),
        ("nộp", "submit"),
        ("đóng học phí", "pay"),
        ("liên hệ", "contact"),
        ("khảo sát", "survey"),
    ):
        if phrase in normalized:
            return family
    return None


def _profile(mention: EventMention) -> dict:
    context = "\n".join(sentence.text for sentence in mention.evidence)
    normalized = _normalize(context)
    dates: dict[str, set[str]] = {}
    issues = []
    for argument, span in zip(mention.arguments, mention.argument_spans, strict=True):
        if span.label != "TIME":
            continue
        matches = list(DATE.finditer(span.text))
        if len(matches) > 1:
            issues.append("time_interval_not_split")
        for match in matches:
            try:
                value = date(int(match[3]), int(match[2]), int(match[1])).isoformat()
            except ValueError:
                issues.append("invalid_calendar_date")
                continue
            dates.setdefault(argument.role, set()).add(value)
    if any(len(values) > 1 for values in dates.values()):
        issues.append("multiple_dates_for_one_role")
    periods = {
        re.sub(r"\s+", "", m.group()).replace("–", "-") for m in PERIOD.finditer(context.casefold())
    }
    period_types = {
        ("semester_range" if "-" in value else "semester_code")
        if value.startswith("hk")
        else "year_range"
        for value in periods
    }
    return {
        "context": normalized,
        "tokens": set(normalized.split()) - STOPWORDS,
        "action": _normalize(mention.action.text),
        "family": _family(mention.action.text),
        "dates": dates,
        "periods": periods,
        "period_types": period_types,
        "issues": issues,
        "update": bool(UPDATE.search(context.casefold())),
    }


def _decision(left: EventMention, right: EventMention, a: dict, b: dict) -> tuple[str, str]:
    if a["family"] and b["family"] and a["family"] != b["family"]:
        return "DIFFERENT_EVENT", "different_action_families"
    if a["periods"] and b["periods"] and a["periods"].isdisjoint(b["periods"]):
        if a["period_types"] == b["period_types"]:
            return "DIFFERENT_EVENT", "different_explicit_periods"
        return "UNCLEAR", "period_encodings_require_review"
    if left.doc_id == right.doc_id:
        return "UNCLEAR", "same_document_mentions_require_review"
    if a["issues"] or b["issues"]:
        return "UNCLEAR", "invalid_or_unsplit_time_argument"
    common_roles = a["dates"].keys() & b["dates"].keys()
    conflicts = [role for role in common_roles if a["dates"][role] != b["dates"][role]]
    if conflicts:
        if a["update"] or b["update"]:
            return "UPDATE_CANDIDATE", "explicit_change_with_conflicting_dates_needs_review"
        return "UNCLEAR", "conflicting_dates_without_confirmed_update"
    if a["dates"] and b["dates"] and a["dates"] != b["dates"]:
        return "UNCLEAR", "time_roles_or_coverage_differ"
    if a["update"] or b["update"]:
        return "UPDATE_CANDIDATE", "explicit_change_needs_target_and_direction_review"
    has_anchor = bool(a["periods"] & b["periods"]) or bool(common_roles)
    informative_action = len(set(a["action"].split()) - STOPWORDS) >= 2
    if (
        a["context"] == b["context"]
        and a["action"] == b["action"]
        and has_anchor
        and informative_action
    ):
        return "SAME_EVENT", "identical_evidence_action_and_explicit_time_or_period"
    return "UNCLEAR", "similar_text_is_not_sufficient_identity_evidence"


def group_events(
    notices: list[Notice], annotations: list[Annotation], config: GroupingConfig | None = None
) -> GroupingResult:
    """Return deterministic tentative event groups and candidate explanations.

    Validate all input annotations against prepared text. Compare event evidence
    using token Jaccard, propose automatic groups only for identical evidence and
    informative actions with matching explicit time/period anchors. Abstain on
    ambiguous times, different roles, missing identity or updates. Updating dates
    never replaces source values. Every cross-pair in a merged group must have a
    SAME_EVENT decision; input order does not change membership. This baseline
    costs O(E²) for E event mentions and has no fitted parameters or quality claim.
    Raise ValueError for duplicate/unknown document IDs or invalid annotations.
    """
    config = config or GroupingConfig()
    documents = {n.doc_id: n for n in notices}
    if len(documents) != len(notices) or len({a.doc_id for a in annotations}) != len(annotations):
        raise ValueError("Grouping requires unique Notice and annotation document IDs")
    mentions = []
    for annotation in annotations:
        if annotation.doc_id not in documents:
            raise ValueError(f"Unknown grouping document: {annotation.doc_id}")
        notice = documents[annotation.doc_id]
        validate_annotation(annotation, notice)
        spans = {s.span_id: s for s in annotation.spans}
        actions = [e.action_span_id for e in annotation.events]
        if len(actions) != len(set(actions)):
            raise ValueError(f"Duplicate ACTION event: {annotation.doc_id}")
        for event in annotation.events:
            mentions.append(
                EventMention(
                    event_ref=f"{notice.doc_id}:{event.action_span_id}",
                    doc_id=notice.doc_id,
                    event_id=event.event_id,
                    annotation_origin=annotation.annotator_id,
                    raw_sha256=notice.raw_sha256,
                    text_sha256=text_sha256(notice),
                    action=spans[event.action_span_id],
                    arguments=event.arguments,
                    argument_spans=[spans[arg.span_id] for arg in event.arguments],
                    evidence=[
                        s for s in notice.sentences if s.sentence_id in event.evidence_sentence_ids
                    ],
                )
            )
    mentions.sort(key=lambda m: m.event_ref)
    profiles = [_profile(m) for m in mentions]
    decisions = []
    for i, j in combinations(range(len(mentions)), 2):
        a, b = profiles[i], profiles[j]
        shared = len(a["tokens"] & b["tokens"])
        if shared < config.min_shared_tokens:
            continue
        similarity = shared / len(a["tokens"] | b["tokens"])
        if similarity < config.similarity:
            continue
        decision, reason = _decision(mentions[i], mentions[j], a, b)
        decisions.append(
            PairDecision(
                left=mentions[i].event_ref,
                right=mentions[j].event_ref,
                similarity=similarity,
                decision=decision,
                reasons=[reason],
            )
        )
    approved = {(p.left, p.right) for p in decisions if p.decision == "SAME_EVENT"}
    clusters = {m.event_ref: {m.event_ref} for m in mentions}
    ownership = {m.event_ref: m.event_ref for m in mentions}
    for pair in sorted(decisions, key=lambda p: (-p.similarity, p.left, p.right)):
        if pair.decision != "SAME_EVENT":
            continue
        left, right = ownership[pair.left], ownership[pair.right]
        if left == right:
            continue
        if not all(
            tuple(sorted((a, b))) in approved for a in clusters[left] for b in clusters[right]
        ):
            pair.reasons.append("group_consistency_blocked")
            continue
        clusters[left].update(clusters.pop(right))
        for member in clusters[left]:
            ownership[member] = left
    groups = [
        EventGroup(
            group_id=hashlib.sha256("|".join(sorted(members)).encode()).hexdigest()[:20],
            members=sorted(members),
        )
        for members in clusters.values()
    ]
    for pair in decisions:
        pair.grouped = ownership[pair.left] == ownership[pair.right]
    return GroupingResult(
        config=config,
        mentions=mentions,
        groups=sorted(groups, key=lambda g: g.group_id),
        decisions=decisions,
        compared_pairs=len(mentions) * (len(mentions) - 1) // 2,
    )

"""Propose source-backed event identity, task relations and directed time changes."""

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from itertools import combinations
from math import isfinite
from pathlib import Path

from smartnotice.labeling.event_groups import assembly_fingerprint, build_event_groups
from smartnotice.labeling.grouping_academic import academic_scope, apply_academic_scope
from smartnotice.labeling.grouping_evidence import (
    compare_pair_evidence,
    evidence_decision,
    mention_context_sentences,
)
from smartnotice.labeling.grouping_followup import (
    FollowupRelation,
    compare_routing,
    followup_evidence,
    load_email_routing,
    resolve_followup,
)
from smartnotice.labeling.grouping_model import MODEL_FEATURES, grouping_probability, pair_features
from smartnotice.schemas import (
    Annotation,
    AssemblyMention,
    AutomaticGroupingComparison,
    AutomaticGroupingConfig,
    AutomaticGroupingResult,
    AutomaticPairProposal,
    EventGroupAssembly,
    EvidenceQuote,
    GroupedFact,
    GroupingChange,
    GroupingLinearModel,
    GroupingModelMention,
    GroupingPairComparison,
    GroupingReview,
    Notice,
    ReviewAuthor,
    Sentence,
    TimeBoundaryReview,
)

_STOP = set(
    "và của các sinh viên trong được cho là có tại với để theo từ đến vào một những "
    "này sẽ đã khi hoặc phải thông báo thực hiện tham gia đăng ký kí liên hệ vui lòng "
    "ngày thời gian năm học nhà trường bạn em qua như sau lại xem nhận nộp nhắc hạn "
    "gia dự hoan hoàn thành tất hướng dẫn check in bài vòng sơ loại buổi cuộc thi hội thảo "
    "chương trình chuyên đề đợt trước hết nay về xin kính mời dành đối tượng chưa kỹ năng".split()
)
_DATE = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d{2})\b")
_CODE = re.compile(
    r"(?:mã (?:sự kiện|cuộc thi|chương trình|đợt)|event code)\s*:\s*([\w-]{3,})", re.I
)
_PERIOD = re.compile(
    r"(?:năm học|học kỳ|học kì|hk|đợt|lần thứ|năm)\s*(?:[123]\s*[/:-]\s*)?"
    r"\d+(?:\s*[-–/]\s*\d+)?",
    re.I,
)
_SPECIALTY = re.compile(r"chuyên đề\s*(\d+)\s*:", re.I)
_SESSION = re.compile(r"\bca\s+(sáng|chiều|tối|\d+)\b", re.I)
_TITLE = re.compile(
    r'(?:hội thảo|cuộc thi|chương trình|học bổng|chiến dịch|tập huấn)\s*["“]([^"”\n]+)["”]'
    r"|(?:tên sự kiện|tên chương trình|chủ đề|chuyên đề\s*\d+)\s*:\s*([^\n.!?]+)",
    re.I,
)
_URL = re.compile(r"https?://[^\s<>\"\[\]]+", re.I)
_UPDATE = re.compile(
    r"gia hạn|đổi hạn|hạn mới|thời hạn mới|dời lịch|thay đổi (?:thời gian|địa điểm)|"
    r"chuyển (?:sang|đến) (?:phòng|hội trường)|tạm hoãn|hủy|mở lại",
    re.I,
)
_REMINDER = re.compile(r"\bnhắc\b|chưa (?:đăng ký|hoàn tất|hoàn thành)", re.I)
_UNSUPPORTED_UPDATE = re.compile(
    r"thay đổi địa điểm|chuyển (?:sang|đến) (?:phòng|hội trường)|tạm hoãn|hủy|mở lại", re.I
)
_FAMILIES = [
    ("check_in", r"check[ -]?in|điểm danh"),
    ("register", r"đăng k[ýí]"),
    ("survey", r"khảo sát|thực hiện phiếu"),
    ("submit", r"nộp|gửi bài"),
    ("pay", r"đóng học phí|thanh toán"),
    ("attend", r"tham dự|tham gia"),
    ("contact", r"liên hệ"),
]
_REASON_TEXT = {
    "ambiguous_multi_item_evidence": (
        "Bằng chứng chứa nhiều mã sự kiện hoặc chuyên đề; chưa xác định được phạm vi mục."
    ),
    "different_explicit_periods": "Hai nguồn nêu kỳ hoặc đợt độc lập.",
    "different_explicit_event_codes": "Hai nguồn nêu mã sự kiện khác nhau.",
    "different_numbered_specialty_titles": (
        "Hai tiêu đề chuyên đề có số riêng; đề xuất giữ nhóm riêng."
    ),
    "matching_explicit_event_code": "Trùng mã sự kiện được nêu rõ trong nguồn.",
    "distinctive_name_with_matching_period_or_date": (
        "Tên có từ nhận diện trùng nhau, kèm kỳ hoặc mốc ngày phù hợp."
    ),
    "insufficient_event_identity": (
        "Chưa đủ căn cứ nhận diện cùng sự kiện; nội dung hoặc đường dẫn giống nhau chưa đủ."
    ),
    "specialty_scope_missing_on_one_side": "Một bên thiếu căn cứ xác định đúng chuyên đề.",
    "location_or_status_change_requires_review": (
        "Có thay đổi địa điểm hoặc trạng thái cần người duyệt xác định trường và mục tiêu."
    ),
    "update_target_task_unresolved": (
        "Có dấu hiệu cập nhật nhưng chưa xác định được đầu việc bị sửa."
    ),
    "preserve_separate_tasks": (
        "Giữ riêng các đầu việc, ca hoặc quan hệ việc chưa chốt trong cùng nhóm."
    ),
    "unsplit_time_interval": "TIME chứa khoảng nhiều ngày chưa tách; chưa tự đối chiếu giá trị.",
    "invalid_calendar_date": "Có mốc ngày không hợp lệ cần kiểm tra nguồn hoặc trích xuất.",
    "ambiguous_time_change": (
        "Trường thời gian có nhiều giá trị; chưa xác định duy nhất phần thay đổi."
    ),
    "explicit_update_with_unique_old_new_time": (
        "Nguồn nêu thay đổi và có giá trị thời gian mới duy nhất; "
        "giữ giá trị cũ hoặc ghi chưa biết nếu thiếu."
    ),
    "explicit_update_without_resolved_changed_field": (
        "Có lời nêu thay đổi nhưng chưa tìm được trường và giá trị bị sửa."
    ),
    "conflicting_same_task_time_without_unique_update": (
        "Cùng đầu việc có mốc thời gian khác nhau nhưng chưa xác định được cập nhật."
    ),
    "update_direction_or_field_unresolved": "Chưa xác định được chiều hoặc trường của cập nhật.",
    "same_task_repetition": "Cùng đầu việc được nhắc lại; giữ tất cả nguồn thông báo.",
    "checkpoint_with_source_anchor": (
        "Mô hình vượt ngưỡng gộp và nguồn có dấu hiệu nhận diện cùng sự kiện."
    ),
    "source_backed_followup": "Nguồn có dấu hiệu thư tiếp nối cùng sự kiện.",
    "conflicting_contextual_identity": "Các đoạn nguồn lân cận nêu kỳ hoặc mã sự kiện khác nhau.",
    "explicit_deadline_extension": "Thư sau kéo dài đúng thời hạn của thư trước.",
    "unresolved_deadline_extension": "Cần xác định đầu việc đã được gia hạn và hai thời hạn.",
    "unresolved_non_deadline_change": "Thay đổi này cần người duyệt xác định trường được sửa.",
    "conflicting_deadline_without_extension": "Các thời hạn khác nhau và chưa có căn cứ gia hạn.",
    "separate_academic_scope": "Hai nguồn nêu kỳ học, môn học hoặc giai đoạn thi khác nhau.",
    "unclear_academic_scope": "Các mốc hoặc phạm vi học vụ cần được đối chiếu.",
    "different_insurance_operations": "Hai nguồn xác nhận riêng việc mua và gia hạn bảo hiểm y tế.",
    "referenced_insurance_operations": (
        "Hai nguồn xác nhận thao tác bảo hiểm khác nhau trong thư trả lời trực tiếp."
    ),
}


def _normal(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def _tokens(text: str) -> set[str]:
    return {w for w in _normal(_URL.sub(" ", text)).split() if w not in _STOP and not w.isdigit()}


def _similarity(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def _time_key(fact: GroupedFact) -> str:
    if fact.equivalence_key:
        return "reviewed:" + fact.equivalence_key
    text = fact.quote.text.casefold()
    dates = [(int(m[3]), int(m[2]), int(m[1])) for m in _DATE.finditer(text)]
    hours = re.findall(r"\b(\d{1,2})\s*(?:g|h|:)\s*(\d{2})?", text)
    if dates:
        qualifiers = re.findall(r"trước|đến hết|chậm nhất|sau", text)
        return repr((dates, hours, qualifiers))
    return _normal(text)


@dataclass
class _Profile:
    mention: AssemblyMention
    action: str
    tokens: set[str]
    identity: set[str]
    titles: set[str]
    codes: set[str]
    urls: set[str]
    periods: dict[str, set[str]]
    specialties: set[str]
    sessions: set[str]
    family: str | None
    times: dict[str, list[GroupedFact]]
    update: bool
    reminder: bool
    conditional: bool
    unsupported_update: bool


def _profile(mention: AssemblyMention, facts: list[GroupedFact]) -> _Profile:
    spans = {s.span_id: s for s in mention.spans}
    action = spans[mention.event.action_span_id].text
    context = "\n".join(s.text for s in mention.sentences)
    # Keep identity local to the annotated item; another bulletin item is not context.
    identity_action = re.split(
        r"\b(?:trước|vào|tại|qua|dành cho|đối với|sinh viên|đến hết)\b",
        action,
        maxsplit=1,
        flags=re.I,
    )[0]
    titles = {_normal(m[1] or m[2]) for m in _TITLE.finditer(context)}
    periods: dict[str, set[str]] = {}
    for m in _PERIOD.finditer(context):
        category = re.sub(r"\d.*", "", _normal(m[0])).strip()
        periods.setdefault(category, set()).add(_normal(m[0]))
    family = next((name for name, pattern in _FAMILIES if re.search(pattern, action, re.I)), None)
    times: dict[str, list[GroupedFact]] = {}
    for fact in facts:
        if fact.field in {"START", "END", "DEADLINE", "EVENT_TIME"}:
            times.setdefault(fact.field, []).append(fact)
    return _Profile(
        mention,
        _normal(action),
        _tokens(context),
        _tokens(identity_action),
        titles,
        {m[1].casefold() for m in _CODE.finditer(context)},
        {m[0].rstrip(".,;)") for m in _URL.finditer(context) if "/" in m[0].split("://", 1)[1]},
        periods,
        set(_SPECIALTY.findall(context)),
        set(_SESSION.findall(context.casefold())),
        family,
        times,
        bool(_UPDATE.search(context)),
        bool(_REMINDER.search(context)),
        any(s.label == "CONDITION" for s in mention.spans),
        bool(_UNSUPPORTED_UPDATE.search(context)),
    )


def _candidate(a: _Profile, b: _Profile, config: AutomaticGroupingConfig) -> list[str]:
    reasons = []
    if a.codes & b.codes:
        reasons.append("shared_explicit_event_code")
    if a.urls & b.urls:
        reasons.append("shared_source_url_support_only")
    if a.titles & b.titles:
        reasons.append("shared_explicit_title")
    if len(a.identity & b.identity) >= config.min_identity_tokens:
        reasons.append("shared_action_identity_tokens")
    if (
        len(a.tokens & b.tokens) >= config.min_shared_tokens
        and _similarity(a.tokens, b.tokens) >= config.candidate_similarity
    ):
        reasons.append("lexical_overlap")
    return reasons


def _decide(
    a: _Profile,
    b: _Profile,
    config: AutomaticGroupingConfig,
    identity_hint: str | None = None,
    followup: FollowupRelation | None = None,
) -> tuple:
    if any(len(p.codes) > 1 or len(p.specialties) > 1 for p in [a, b]):
        return a, b, "UNCLEAR", "UNRESOLVED", [], ["ambiguous_multi_item_evidence"]
    for category in a.periods.keys() & b.periods.keys():
        if a.periods[category].isdisjoint(b.periods[category]):
            return a, b, "DIFFERENT_EVENT", "UNRESOLVED", [], ["different_explicit_periods"]
    if a.codes and b.codes and a.codes.isdisjoint(b.codes):
        return a, b, "DIFFERENT_EVENT", "UNRESOLVED", [], ["different_explicit_event_codes"]
    if a.specialties and b.specialties and a.specialties.isdisjoint(b.specialties):
        return a, b, "DIFFERENT_EVENT", "UNRESOLVED", [], ["different_numbered_specialty_titles"]
    shared_dates = {
        _time_key(f) for values in a.times.values() for f in values if _DATE.search(f.quote.text)
    } & {_time_key(f) for values in b.times.values() for f in values if _DATE.search(f.quote.text)}
    shared_period = any(a.periods[k] & b.periods[k] for k in a.periods.keys() & b.periods.keys())
    name_match = (
        len(a.identity & b.identity) >= config.min_identity_tokens
        and _similarity(a.identity, b.identity) >= 0.8
    ) or any(len(_tokens(t)) >= config.min_identity_tokens for t in a.titles & b.titles)
    identity_reasons = []
    if a.codes & b.codes:
        identity_reasons.append("matching_explicit_event_code")
    if name_match and (shared_period or shared_dates):
        identity_reasons.append("distinctive_name_with_matching_period_or_date")
    if identity_hint:
        identity_reasons.append(identity_hint)
    if not identity_reasons:
        return a, b, "UNCLEAR", "UNRESOLVED", [], ["insufficient_event_identity"]
    if a.specialties != b.specialties and (a.specialties or b.specialties):
        return a, b, "UNCLEAR", "UNRESOLVED", [], ["specialty_scope_missing_on_one_side"]
    same_family = a.family is not None and a.family == b.family
    relation = "UNRESOLVED"
    if a.sessions and b.sessions and a.sessions.isdisjoint(b.sessions):
        relation = "DIFFERENT_SESSION"
    elif same_family and (
        _similarity(a.identity, b.identity) >= 0.8
        or (followup and followup.decision == "UPDATE_OF" and not (a.conditional or b.conditional))
    ):
        relation = "SAME_TASK"
    elif a.family and b.family:
        relation = "CONDITIONAL_TASK" if a.conditional or b.conditional else "DIFFERENT_TASK"
    if a.unsupported_update or b.unsupported_update:
        return a, b, "UNCLEAR", "UNRESOLVED", [], ["location_or_status_change_requires_review"]
    if relation != "SAME_TASK":
        if relation == "UNRESOLVED" and (a.update or b.update):
            return a, b, "UNCLEAR", "UNRESOLVED", [], ["update_target_task_unresolved"]
        return a, b, "SAME_EVENT", relation, [], identity_reasons + ["preserve_separate_tasks"]
    for p in [a, b]:
        for values in p.times.values():
            for fact in values:
                matches = list(_DATE.finditer(fact.quote.text))
                if len(matches) > 1:
                    return a, b, "UNCLEAR", "UNRESOLVED", [], ["unsplit_time_interval"]
                for match in matches:
                    try:
                        date(int(match[3]), int(match[2]), int(match[1]))
                    except ValueError:
                        return a, b, "UNCLEAR", "UNRESOLVED", [], ["invalid_calendar_date"]
    common = a.times.keys() & b.times.keys()
    conflicts = [
        k
        for k in common
        if {_time_key(f) for f in a.times[k]} != {_time_key(f) for f in b.times[k]}
    ]
    if followup and followup.decision == "UPDATE_OF":
        new, old = (a, b) if followup.update_side == 0 else (b, a)
        old_due, new_due = old.times.get("DEADLINE", []), new.times.get("DEADLINE", [])
        if (
            conflicts == ["DEADLINE"]
            and len(old_due) == len(new_due) == 1
            and old_due[0].span_id == followup.old_span_id
            and new_due[0].span_id == followup.new_span_id
        ):
            change = GroupingChange(field="DEADLINE", old=old_due[0].quote, new=new_due[0].quote)
            return (
                new,
                old,
                "UPDATE_OF",
                "SAME_TASK",
                [change],
                identity_reasons + [followup.reason],
            )
        return a, b, "UNCLEAR", "UNRESOLVED", [], ["unresolved_deadline_extension"]
    if a.update != b.update:
        new, old = (a, b) if a.update else (b, a)
        changes = []
        changed_fields = sorted(set(conflicts) | (new.times.keys() - old.times.keys()))
        for field in changed_fields:
            if len(new.times[field]) != 1 or (field in old.times and len(old.times[field]) != 1):
                return a, b, "UNCLEAR", "UNRESOLVED", [], ["ambiguous_time_change"]
            changes.append(
                GroupingChange(
                    field=field,
                    old=old.times[field][0].quote if field in old.times else None,
                    new=new.times[field][0].quote,
                )
            )
        if changes:
            return (
                new,
                old,
                "UPDATE_OF",
                "SAME_TASK",
                changes,
                identity_reasons + ["explicit_update_with_unique_old_new_time"],
            )
        return a, b, "UNCLEAR", "UNRESOLVED", [], ["explicit_update_without_resolved_changed_field"]
    if conflicts:
        return (
            a,
            b,
            "UNCLEAR",
            "UNRESOLVED",
            [],
            ["conflicting_same_task_time_without_unique_update"],
        )
    if (a.update or b.update) and (not common or a.action != b.action):
        return a, b, "UNCLEAR", "UNRESOLVED", [], ["update_direction_or_field_unresolved"]
    return a, b, "SAME_EVENT", "SAME_TASK", [], identity_reasons + ["same_task_repetition"]


def propose_event_groups(
    notices: list[Notice],
    annotations: list[Annotation],
    *,
    generated_at: datetime,
    config: AutomaticGroupingConfig | None = None,
    time_boundaries: list[TimeBoundaryReview] | None = None,
    checkpoint: GroupingLinearModel | None = None,
    raw_email_dir: Path | None = None,
) -> AutomaticGroupingResult:
    """Propose and assemble groups offline from validated per-item annotations.

    No supplied pair review, group approval or reference partition is an input.
    By default, require an explicit event code or a distinctive name with a
    matching period or date. An optional evidence checkpoint adds corroborated
    identity cues. With a checkpoint, local hash-verified emails can supply
    reply and close-send candidates. Compare dates inside their task. Updates
    require explicit language and source-bound time quotes.

    Check every cross-pair of a proposed positive component, including omitted
    candidates, before assembly. All outputs require review. Preserve input text,
    annotation offsets and source authorship. Raise ValueError for invalid
    inputs, incompatible checkpoints, corrupt email sources, or a naive time.
    Runtime is quadratic in the number of mentions.
    """
    config = config or AutomaticGroupingConfig()
    if checkpoint is not None and (
        checkpoint.kind != "grouping-logistic-v2"
        or tuple(checkpoint.features) != MODEL_FEATURES[checkpoint.kind]
        or not all(
            isfinite(value)
            for value in [
                checkpoint.intercept,
                *checkpoint.mean,
                *checkpoint.scale,
                *checkpoint.weights,
            ]
        )
    ):
        raise ValueError("Expected a finite evidence checkpoint with the v2 feature order")
    if raw_email_dir is not None and (checkpoint is None or not raw_email_dir.is_dir()):
        raise ValueError("A local raw email directory requires an evidence checkpoint")
    author = ReviewAuthor(
        reviewer_id="automatic_grouping_model_assisted_v1"
        if checkpoint is not None
        else "automatic_grouping_rules_v1",
        reviewer_kind="ai_assistant",
        reviewed_at=generated_at,
    )
    initial = build_event_groups(notices, annotations, [], time_boundaries)
    facts = {
        ref: task.facts for group in initial.groups for task in group.tasks for ref in task.members
    }
    profiles = {
        m.version.event_ref: _profile(m, facts[m.version.event_ref]) for m in initial.mentions
    }
    documents = {notice.doc_id: notice for notice in notices}
    model_mentions = {}
    headers = {}
    routing_candidates = {}
    academic_scopes = {}
    if checkpoint is not None:
        for ref, profile in profiles.items():
            mention = profile.mention
            doc_id = ref.partition(":")[0]
            model_mentions[ref] = GroupingModelMention(
                mention_id=ref,
                doc_id=doc_id,
                version=mention.version,
                event=mention.event,
                spans=mention.spans,
                sentences=mention.sentences,
            )
        if raw_email_dir is not None:
            for doc_id in sorted({mention.doc_id for mention in model_mentions.values()}):
                header = load_email_routing(documents[doc_id], raw_email_dir)
                if header is not None:
                    headers[doc_id] = header
            for left, right in combinations(headers, 2):
                routing = compare_routing(headers[left], headers[right])
                if routing.direct_parent:
                    routing_candidates[left, right] = "verified_direct_reply"
                elif routing.rapid:
                    routing_candidates[left, right] = "verified_close_same_sender"
        academic_scopes = {
            ref: academic_scope(mention, documents[mention.doc_id], headers.get(mention.doc_id))
            for ref, mention in model_mentions.items()
        }
    proposals: dict[tuple[str, str], AutomaticPairProposal] = {}

    def refine(
        left: str, right: str, result: tuple, model: GroupingLinearModel
    ) -> tuple[tuple, FollowupRelation | None, dict[str, list[Sentence]]]:
        a, b = profiles[left], profiles[right]
        pair_mentions = model_mentions[left], model_mentions[right]
        left_doc, right_doc = (mention.doc_id for mention in pair_mentions)
        if left_doc == right_doc or result[2] == "DIFFERENT_EVENT":
            return result, None, {}
        pair_headers = headers.get(left_doc), headers.get(right_doc)
        resolved = None
        extra_evidence = {}
        can_refine = result[2] == "SAME_EVENT" or result[-1][0] in {
            "insufficient_event_identity",
            "conflicting_same_task_time_without_unique_update",
            "update_target_task_unresolved",
            "update_direction_or_field_unresolved",
        }
        if can_refine:
            docs = documents[left_doc], documents[right_doc]
            pair_evidence = compare_pair_evidence(*pair_mentions, *docs)
            followup = followup_evidence(*pair_mentions, docs, pair_headers, pair_evidence)
            probability = grouping_probability(
                model, pair_features(*pair_mentions) + pair_evidence.features
            )
            status = evidence_decision(probability, model.threshold, pair_evidence)
            hint = None
            if status == "SAME_EVENT" and probability >= model.threshold:
                hint = "checkpoint_with_source_anchor"
            elif followup.joint:
                hint = "source_backed_followup"
            suggested = "SAME_EVENT" if hint or result[2] == "SAME_EVENT" else "UNCLEAR"
            resolved = resolve_followup(*pair_mentions, docs, pair_evidence, followup, suggested)
            if pair_evidence.conflict:
                result = (
                    a,
                    b,
                    "DIFFERENT_EVENT",
                    "UNRESOLVED",
                    [],
                    ["conflicting_contextual_identity"],
                )
            elif resolved.decision == "UNCLEAR" and resolved.reason != "base":
                result = a, b, "UNCLEAR", "UNRESOLVED", [], [resolved.reason]
            else:
                if resolved.reason != "base":
                    hint = hint or "source_backed_followup"
                if hint:
                    result = _decide(a, b, config, hint, resolved)
            for mention, doc, title_ids in zip(
                pair_mentions, docs, followup.title_sentences, strict=True
            ):
                ids = {s.sentence_id for s in mention_context_sentences(mention, doc)}
                ids.update(title_ids)
                extra_evidence[doc.doc_id] = [s for s in doc.sentences if s.sentence_id in ids]
        if result[2] != "DIFFERENT_EVENT":
            base = "SAME_EVENT" if result[2] == "UPDATE_OF" else result[2]
            scoped = apply_academic_scope(
                academic_scopes[left], academic_scopes[right], compare_routing(*pair_headers), base
            )
            if scoped.reason in (
                "different_insurance_operations",
                "referenced_insurance_operations",
            ):
                result = a, b, scoped.decision, "UNRESOLVED", [], [scoped.reason]
                for ref, mention in zip((left, right), pair_mentions, strict=True):
                    doc = documents[mention.doc_id]
                    ids = {s.sentence_id for s in extra_evidence.get(doc.doc_id, mention.sentences)}
                    ids.update(academic_scopes[ref].insurance_sentences)
                    extra_evidence[doc.doc_id] = [s for s in doc.sentences if s.sentence_id in ids]
            elif scoped.decision == "DIFFERENT_EVENT":
                result = a, b, "DIFFERENT_EVENT", "UNRESOLVED", [], ["separate_academic_scope"]
            elif (
                scoped.decision == "UNCLEAR"
                and scoped.reason != "base"
                and (
                    scoped.reason != "different_dates_same_role"
                    or (result[2] != "UPDATE_OF" and result[3] == "SAME_TASK")
                )
            ):
                result = a, b, "UNCLEAR", "UNRESOLVED", [], ["unclear_academic_scope"]
        return result, resolved, extra_evidence

    def add(left: str, right: str, reasons: list[str]) -> None:
        a, b = profiles[left], profiles[right]
        result, resolved, extra_evidence = _decide(a, b, config), None, {}
        if checkpoint is not None:
            result, resolved, extra_evidence = refine(left, right, result, checkpoint)
        new, old, decision, relation, changes, why = result
        evidence = [
            EvidenceQuote(
                doc_id=doc_id,
                sentence_id=s.sentence_id,
                start=s.start,
                end=s.end,
                text=s.text,
            )
            for p in [new, old]
            for doc_id in [p.mention.version.event_ref.partition(":")[0]]
            for s in extra_evidence.get(doc_id, p.mention.sentences)
        ]
        evidence = list({(q.doc_id, q.sentence_id): q for q in evidence}.values())
        rid = "auto-" + hashlib.sha256(f"{left}|{right}".encode()).hexdigest()[:20]
        pair = GroupingReview(
            review_id=rid,
            left=new.mention.version,
            right=old.mention.version,
            decision=decision,
            task_relation=relation,
            author=author,
            rationale=(
                "Đề xuất tự động với mô hình hỗ trợ. "
                if checkpoint is not None
                else "Đề xuất tự động bằng quy tắc. "
            )
            + " ".join(_REASON_TEXT[reason] for reason in why),
            evidence=evidence,
            changes=changes,
            notice_relation="UPDATE"
            if decision == "UPDATE_OF"
            else resolved.notice_relation
            if decision == "SAME_EVENT"
            and resolved
            and resolved.notice_relation in {"REMINDER", "REPEATED_NOTICE"}
            else "REMINDER"
            if decision == "SAME_EVENT" and (a.reminder or b.reminder)
            else "OTHER",
        )
        proposals[(left, right)] = AutomaticPairProposal(
            origin="model_assisted_rule_proposal" if checkpoint is not None else "rule_proposal",
            candidate_reasons=reasons,
            reasons=why,
            lexical_similarity=_similarity(a.tokens, b.tokens),
            pair=pair,
        )

    for left, right in combinations(sorted(profiles), 2):
        reasons = _candidate(profiles[left], profiles[right], config)
        if routing_candidates:
            routing_key = model_mentions[left].doc_id, model_mentions[right].doc_id
            if route := routing_candidates.get(tuple(sorted(routing_key))):
                reasons.append(route)
        if reasons:
            add(left, right, reasons)
    neighbors = {ref: set() for ref in profiles}
    for (left, right), proposal in proposals.items():
        if proposal.pair.decision in {"SAME_EVENT", "UPDATE_OF"}:
            neighbors[left].add(right)
            neighbors[right].add(left)
    remaining = set(profiles)
    while remaining:
        pending, component = [min(remaining)], set()
        while pending:
            ref = pending.pop()
            if ref not in component:
                component.add(ref)
                pending.extend(neighbors[ref] - component)
        remaining -= component
        for left, right in combinations(sorted(component), 2):
            if (left, right) not in proposals:
                add(left, right, ["positive_component_consistency_check"])
    ordered = [proposals[key] for key in sorted(proposals)]
    assembly = build_event_groups(notices, annotations, [p.pair for p in ordered], time_boundaries)
    return AutomaticGroupingResult(
        rule_version="automatic-event-grouping-model-assisted-v1"
        if checkpoint is not None
        else "automatic-event-grouping-v1",
        config=config,
        generated_at=generated_at,
        compared_pairs=len(profiles) * (len(profiles) - 1) // 2,
        proposals=ordered,
        assembly=assembly,
    )


def compare_grouping_reference(
    result: AutomaticGroupingResult,
    reference: EventGroupAssembly,
) -> AutomaticGroupingComparison:
    """Compare only explicit reference pairs after exact mention-version checks.

    Missing candidates remain missing, never predicted negatives. Reference group
    acceptance or singleton status does not supply independent pair labels.
    Report decision, task, direction and changed-field mismatches separately.
    Raise ValueError for a different source/annotation snapshot or mention set.
    """
    versions = {m.version.event_ref: m.version for m in result.assembly.mentions}
    if versions != {m.version.event_ref: m.version for m in reference.mentions}:
        raise ValueError("Reference requires the same mention set and annotation snapshots")
    proposals = {
        frozenset((p.pair.left.event_ref, p.pair.right.event_ref)): p.pair for p in result.proposals
    }
    groups = {ref: g.group_id for g in result.assembly.groups for ref in g.members}
    tasks = {ref: t.task_id for g in result.assembly.groups for t in g.tasks for ref in t.members}
    rows = []
    for pair in reference.reviews:
        left, right = pair.left.event_ref, pair.right.event_ref
        actual = proposals.get(frozenset((left, right)))
        issues = []
        if actual is None:
            issues.append("candidate_missing")
        else:
            if actual.decision != pair.decision:
                issues.append("decision_mismatch")
            if actual.task_relation != pair.task_relation:
                issues.append("task_relation_mismatch")
            if pair.decision == actual.decision == "UPDATE_OF":
                if actual.left.event_ref != pair.left.event_ref:
                    issues.append("update_direction_mismatch")
                if sorted(c.model_dump_json() for c in actual.changes) != sorted(
                    c.model_dump_json() for c in pair.changes
                ):
                    issues.append("update_fields_or_quotes_mismatch")
        expected_same = pair.decision in {"SAME_EVENT", "UPDATE_OF"}
        if pair.decision != "UNCLEAR" and (groups[left] == groups[right]) != expected_same:
            issues.append("resulting_group_mismatch")
        if expected_same and pair.task_relation != "UNRESOLVED":
            if (tasks[left] == tasks[right]) != (pair.task_relation == "SAME_TASK"):
                issues.append("resulting_task_mismatch")
        rows.append(
            GroupingPairComparison(
                reference_review_id=pair.review_id,
                left=left,
                right=right,
                reference_decision=pair.decision,
                proposed_decision=actual.decision if actual else None,
                reference_task_relation=pair.task_relation,
                proposed_task_relation=actual.task_relation if actual else None,
                same_resulting_group=groups[left] == groups[right],
                same_resulting_task=tasks[left] == tasks[right],
                issues=issues,
            )
        )
    return AutomaticGroupingComparison(
        reference_fingerprint=assembly_fingerprint(reference), pairs=rows
    )

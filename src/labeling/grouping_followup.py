"""Link an event mention to a named or referenced earlier notice."""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from smartnotice.labeling.grouping_evidence import (
    PairEvidence,
    event_form_keys,
    mention_context,
    single_calendar_date,
)
from smartnotice.parsers.email import EmailRouting, parse_email_routing
from smartnotice.schemas import GroupingModelMention, Notice

RAPID_SECONDS = 15 * 60
_EVENT = (
    r"hội nghị|hội thảo|seminar|workshop|giải thưởng|cuộc thi|chiến dịch|"
    r"talkshow|ngày hội|chương trình|học bổng"
)
_TITLE = re.compile(
    rf'(?:\b(?:{_EVENT})\s+)(?:["“]([^"”\r\n]{{5,160}})["”]|([^.!?;:\n]{{5,160}}))',
    re.I,
)
_TITLE_END = re.compile(
    r"\s+(?:với|như sau|do|thuộc|sẽ|được|vui lòng|và các mẫu|"
    r'tại đây|đăng ký tại|thông tin theo)\b|[,:(\[\]”"]',
    re.I,
)
_ITEM = re.compile(rf"^[\s*#-]*\d{{1,2}}[.)]\s+(?:{_EVENT})\b", re.I)
_UPDATE = re.compile(
    r"\b(?:xin\s+bổ sung|thông tin bổ sung|bổ sung thông tin|đính chính|gia hạn|"
    r"cập nhật|nhắc lại|nhắc nhở|sắp hết hạn|sẽ hết hạn|gửi lại|xin thông tin lại|"
    r"nhầm lẫn về|(?:thư|email|thông báo) (?:trước|vừa gửi)|"
    r"đăng k[ýí] lại|thay đổi lịch|điều chỉnh lịch)\b",
    re.I,
)
_ATTACHMENT = re.compile(r"\b(?:đính kèm|tệp kèm|file kèm|gửi lại)\b", re.I)
_ARTICLE = re.compile(
    r"\b(?:lịch thi|thời khóa biểu|lịch học|biểu mẫu|danh sách|đề cương|tài liệu)\b", re.I
)
_PRIOR_NOTICE = re.compile(
    r"\b(?:thư|email|thông báo|biểu mẫu|bản) (?:gốc|trước|cũ|vừa gửi|đã gửi)\b", re.I
)
_EXTEND = re.compile(r"\b(?:gia hạn|kéo dài (?:hạn|thời hạn))\b", re.I)
_EXTENSION_REQUEST = re.compile(
    r"\b(?:đề nghị|mong|xin|yêu cầu)\s+(?:(?:được|xem xét)\s+)*(?:gia hạn|kéo dài)\b", re.I
)
_FOLLOWUP_REMINDER = re.compile(
    r"\b(?:nhắc lại|nhắc nhở|nhắc (?:đăng k[ýí]|nộp|đóng|tham gia)|"
    r"(?:sắp|sẽ) hết hạn|lưu ý thời hạn)\b",
    re.I,
)
_FOLLOWUP_CONTINUATION = re.compile(
    r"\b(?:gửi lại|gửi bổ sung|xin bổ sung|bổ sung thông tin|thông tin bổ sung|"
    r"(?:xác nhận|chốt) (?:lịch|thời gian|địa điểm|kết quả))\b",
    re.I,
)
_OTHER_CHANGE = re.compile(r"\b(?:đính chính|thay đổi|hoãn|hủy|mở lại|dời lịch|đổi lịch)\b", re.I)
_NUMBERED_ITEM = re.compile(r"^[\s*#-]*(?:\d{1,2}|[IVX]+)[.)]\s+", re.I)
_TASK_SCOPE = re.compile(r"\b(?:phiên|ca|vòng|đợt|nhóm)\s+(?:\d+|[IVX]+)\b", re.I)
_TIME_INTERVAL = re.compile(r"\btừ\b[^.;\n]+\b(?:đến|tới)\b", re.I)
_TASK_OBJECT_END = re.compile(r"\b(?:trước|đến|từ|lúc|hạn|qua|tại|cho|bằng|vào)\b", re.I)
_TASK_ACTIONS = {
    "register": re.compile(r"\b(?:đăng k[ýí]|ghi danh)\b", re.I),
    "submit": re.compile(r"\b(?:nộp(?!\s+học phí)|gửi)\b", re.I),
    "pay": re.compile(r"\b(?:đóng|thanh toán|nộp\s+học phí)\b", re.I),
    "complete": re.compile(r"\bhoàn thành\b", re.I),
}
_STOP = frozenset(
    "và của các trong về được cho là tại với để theo từ đến vào một này "
    "sẽ đã khi thông tin nhắc hội thảo nghị thi giải thưởng trình chương ngày "
    "sinh viên tổ chức thực hiện đăng ký thông báo chi tiết các bạn năm học".split()
)


@dataclass(frozen=True)
class RoutingComparison:
    """Expose directional header facts without an address or header identifier."""

    later: int | None
    gap_seconds: int | None
    same_sender: bool
    direct_parent: bool

    @property
    def rapid(self) -> bool:
        """Return whether a known sender sent the second email within 15 minutes."""
        return (
            self.same_sender
            and self.gap_seconds is not None
            and 0 < self.gap_seconds <= RAPID_SECONDS
        )


@dataclass(frozen=True)
class FollowupEvidence:
    """Describe the active ways to link a follow-up and their source pointers."""

    title: bool
    reference: bool
    joint: bool
    routing: RoutingComparison
    title_sentences: tuple[tuple[str, ...], tuple[str, ...]]
    reason: str | None


@dataclass(frozen=True)
class FollowupRelation:
    """Carry a proposed pair decision and source span IDs for a deadline change."""

    decision: str
    reason: str
    notice_relation: Literal["REMINDER", "REPEATED_NOTICE", "UPDATE", "OTHER"] = "OTHER"
    update_side: int | None = None
    old_span_id: str | None = None
    new_span_id: str | None = None


def load_email_routing(notice: Notice, directory: Path) -> EmailRouting | None:
    """Verify local source bytes and parse private header facts in memory.

    Return None for an absent source or a web notice. Reject a raw hash mismatch.
    """
    if notice.source_type != "email" or not re.fullmatch(r"[a-f0-9]{64}", notice.raw_sha256):
        return None
    path = directory / f"{notice.raw_sha256}.eml"
    if not path.is_file():
        return None
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != notice.raw_sha256:
        raise ValueError(f"Email source hash differs for {notice.doc_id}")
    return parse_email_routing(raw)


def compare_routing(left: EmailRouting | None, right: EmailRouting | None) -> RoutingComparison:
    """Compare send times and one exact parent reference in a pair of emails."""
    if left is None or right is None:
        return RoutingComparison(None, None, False, False)
    later = None
    gap = None
    if left.sent_at is not None and right.sent_at is not None:
        delta = (right.sent_at - left.sent_at).total_seconds()
        later = (1 if delta > 0 else 0) if delta else None
        gap = int(abs(delta))
    right_replies = bool(left.message_id and left.message_id == right.parent_id)
    left_replies = bool(right.message_id and right.message_id == left.parent_id)
    child = (1 if right_replies else 0) if right_replies != left_replies else None
    direct = child is not None and later in (None, child)
    return RoutingComparison(
        child if direct and later is None else later,
        gap,
        bool(left.sender and left.sender == right.sender),
        direct,
    )


def _title_tokens(value: str) -> tuple[str, ...]:
    value = unicodedata.normalize("NFC", value).casefold()
    return tuple(w for w in re.findall(r"[^\W\d_]{2,}", value) if w not in _STOP)


def _titles(mention: GroupingModelMention, notice: Notice):
    scoped = any(_ITEM.match(s.text) for s in notice.sentences)
    index = {s.sentence_id: i for i, s in enumerate(notice.sentences)}
    selected = sorted(index[s.sentence_id] for s in mention.sentences)
    if not selected:
        return [], scoped
    if scoped:
        headings = [i for i, s in enumerate(notice.sentences) if _ITEM.match(s.text)]
        start = max((i for i in headings if i <= selected[0]), default=0)
        stop = min((i for i in headings if i > start), default=len(notice.sentences))
        if selected[-1] >= stop:
            return [], True
        candidates = notice.sentences[start : min(stop, start + 4)]
    else:
        chosen = set(range(min(6, len(notice.sentences))))
        chosen.update(i for j in selected for i in range(max(j - 2, 0), j + 1))
        candidates = [notice.sentences[i] for i in sorted(chosen)]
    results = {}
    for sentence in candidates:
        i = index[sentence.sentence_id]
        after = notice.sentences[i + 1 : i + 2]
        if after and (_ITEM.match(after[0].text) or scoped and i + 1 >= stop):
            after = []
        context = " ".join(s.text.replace("*", "") for s in [sentence, *after])
        for match in _TITLE.finditer(context):
            if match.start() >= len(sentence.text.replace("*", "")):
                continue
            text = match[1] or _TITLE_END.split(match[2], maxsplit=1)[0]
            words = _title_tokens(text)
            if len(set(words)) >= 3:
                ids = (sentence.sentence_id,)
                if match.end() > len(sentence.text.replace("*", "")) and after:
                    ids += (after[0].sentence_id,)
                results.setdefault(words, ids)
    return list(results.items()), scoped


def _title_similarity(left, right) -> tuple[bool, bool]:
    a, b = set(left), set(right)
    shared = a & b
    score = len(shared) / len(a | b)
    prefix = left[: min(len(left), len(right))] == right[: min(len(left), len(right))]
    return len(shared) >= 3 and (score >= 0.8 or prefix), len(shared) >= 4 and score >= 0.55


def followup_evidence(
    left: GroupingModelMention,
    right: GroupingModelMention,
    notices: tuple[Notice, Notice],
    headers: tuple[EmailRouting | None, EmailRouting | None],
    base: PairEvidence,
) -> FollowupEvidence:
    """Return separate title, reference, and joint cues for a possible follow-up.

    Use only validated prepared mentions for content. A recent send time or
    shared mailbox alone cannot identify an event. Keep feature provenance as
    sentence IDs and categorical routing facts.
    """
    a, b = notices
    routing = compare_routing(*headers)
    context = (mention_context(left, a), mention_context(right, b))
    titles_a, scoped_a = _titles(left, a)
    titles_b, scoped_b = _titles(right, b)
    marker = [bool(_UPDATE.search(x)) for x in context]
    for i, (notice, scoped) in enumerate(zip(notices, (scoped_a, scoped_b), strict=True)):
        if not scoped:
            lead = " ".join(s.text for s in notice.sentences[:6])
            marker[i] |= bool(_UPDATE.search(lead))
    later = routing.later
    if (
        later is None
        and a.reference_date
        and b.reference_date
        and a.reference_date != b.reference_date
    ):
        later = int(a.reference_date < b.reference_date)
    is_followup = marker[later] if later is not None else any(marker)
    date_close = bool(
        a.reference_date
        and b.reference_date
        and abs((a.reference_date - b.reference_date).days) <= 90
    )
    strong = weak = False
    pointers: tuple[tuple[str, ...], tuple[str, ...]] = ((), ())
    for words_a, ids_a in titles_a:
        for words_b, ids_b in titles_b:
            exact, fuzzy = _title_similarity(words_a, words_b)
            if exact or (fuzzy and not strong):
                pointers = (ids_a, ids_b)
            strong |= exact
            weak |= fuzzy or exact
    common_form = bool(event_form_keys(context[0]) & event_form_keys(context[1]))
    near_topic = base.features[0] >= 0.30 and base.features[1] > 0
    blocked = base.conflict or not is_followup
    title = not blocked and strong and date_close
    unambiguous = not (scoped_a or scoped_b)
    shared_article = {w.casefold() for w in _ARTICLE.findall(context[0])} & {
        w.casefold() for w in _ARTICLE.findall(context[1])
    }
    addendum = (
        later is not None and bool(_ATTACHMENT.search(context[later])) and bool(shared_article)
    )
    parent = routing.direct_parent and (common_form or near_topic or (addendum and unambiguous))
    rapid = routing.rapid and (common_form or near_topic or addendum) and unambiguous
    form_reference = (
        common_form and date_close and near_topic and any(_PRIOR_NOTICE.search(x) for x in context)
    )
    reference = not blocked and (parent or rapid or form_reference)
    corroborated = (routing.direct_parent or routing.rapid or common_form) and weak
    joint = title or reference or (not blocked and corroborated)
    if reference and not any(pointers) and later is not None:
        original = titles_a if later == 1 else titles_b
        if len(original) == 1:
            pointers = (original[0][1], ()) if later == 1 else ((), original[0][1])
    reason = None
    if joint:
        reason = (
            "direct_parent"
            if reference and parent
            else "rapid_same_sender_with_topic"
            if reference and rapid
            else "prior_notice_with_matching_form"
            if reference and form_reference
            else "recovered_title"
            if title
            else "title_with_corroborating_reference"
        )
    return FollowupEvidence(title, reference, joint, routing, pointers, reason)


def _deadline(mention: GroupingModelMention) -> tuple[str, date] | None:
    arguments = [arg for arg in mention.event.arguments if arg.role == "DEADLINE"]
    if len(arguments) != 1 or arguments[0].inferred:
        return None
    arg = arguments[0]
    span = next((s for s in mention.spans if s.span_id == arg.span_id and s.label == "TIME"), None)
    if span is None or _TIME_INTERVAL.search(span.text):
        return None
    value = single_calendar_date(span.text)
    if value is None or arg.normalized_date not in (None, value):
        return None
    return span.span_id, value


def _task_action(mention: GroupingModelMention) -> tuple[str, frozenset[str]] | None:
    action = next(s.text for s in mention.spans if s.span_id == mention.event.action_span_id)
    families = [(key, m) for key, pattern in _TASK_ACTIONS.items() if (m := pattern.search(action))]
    if len(families) != 1:
        return None
    family, verb = families[0]
    target = _TASK_OBJECT_END.split(action[verb.end() :], maxsplit=1)[0]
    return family, frozenset(_title_tokens(_TASK_SCOPE.sub("", target)))


def _same_task(left: GroupingModelMention, right: GroupingModelMention) -> bool:
    a = _task_action(left)
    b = _task_action(right)
    return (
        a is not None and b is not None and a[0] == b[0] and (not a[1] or not b[1] or a[1] == b[1])
    )


def _resolve_extension(
    old: tuple[str, date] | None,
    new: tuple[str, date] | None,
    later: int,
    same_task: bool,
    latest: str,
) -> FollowupRelation:
    if (
        old is None
        or new is None
        or new[1] <= old[1]
        or not same_task
        or _EXTENSION_REQUEST.search(latest)
    ):
        return FollowupRelation("UNCLEAR", "unresolved_deadline_extension")
    return FollowupRelation(
        "UPDATE_OF", "explicit_deadline_extension", "UPDATE", later, old[0], new[0]
    )


def resolve_followup(
    left: GroupingModelMention,
    right: GroupingModelMention,
    notices: tuple[Notice, Notice],
    evidence: PairEvidence,
    followup: FollowupEvidence,
    decision: str,
) -> FollowupRelation:
    """Refine a prior decision using a scoped follow-up marker and shared event cues.

    Supply validated mentions in the same order as their notices and evidence.
    Decide deadline extensions only for a matched task family with one explicit
    full deadline per side. An update returns its newer side (0 for left), plus
    the old and new span IDs. Competing dates, requests and unscoped changes
    remain for review. Apply independent scope checks before accepting a merge.
    """
    prior = FollowupRelation(decision, "base")
    if evidence.conflict:
        return FollowupRelation("DIFFERENT_EVENT", "explicit_event_conflict")
    if decision == "UPDATE_OF" or left.doc_id == right.doc_id:
        return prior
    later = followup.routing.later
    if later is None:
        a, b = (notice.reference_date for notice in notices)
        if a is None or b is None or a == b:
            return prior
        later = int(a < b)
    mentions = (left, right)
    contexts = tuple(mention_context(m, n) for m, n in zip(mentions, notices, strict=True))
    latest = contexts[later]
    extension = bool(_EXTEND.search(latest))
    reminder = bool(_FOLLOWUP_REMINDER.search(latest))
    continuation = _FOLLOWUP_CONTINUATION.search(latest)
    if not (extension or reminder or continuation):
        return prior

    numbered = any(_NUMBERED_ITEM.match(s.text) for n in notices for s in n.sentences)
    scoped_parent = (
        followup.routing.direct_parent
        and not numbered
        and evidence.features[0] >= 0.30
        and evidence.features[1] > 0
    )
    corroborated = followup.title or evidence.anchor == "explicit_event_code" or scoped_parent
    if not corroborated:
        return prior

    scopes = [{m[0].casefold() for m in _TASK_SCOPE.finditer(value)} for value in contexts]
    same_task = scopes[0] == scopes[1] and len(scopes[0]) <= 1 and _same_task(left, right)
    old, new = (_deadline(mentions[i]) for i in (1 - later, later))
    matching_deadlines = old is not None and new is not None and old[1] == new[1]
    if extension and not (reminder and matching_deadlines):
        return _resolve_extension(old, new, later, same_task, latest)
    if same_task and old is not None and new is not None and not matching_deadlines:
        return FollowupRelation("UNCLEAR", "conflicting_deadline_without_extension")
    if _OTHER_CHANGE.search(latest):
        return FollowupRelation("UNCLEAR", "unresolved_non_deadline_change")
    if reminder:
        return FollowupRelation("SAME_EVENT", "source_backed_reminder", "REMINDER")
    if continuation and continuation[0].casefold() == "gửi lại":
        return FollowupRelation("SAME_EVENT", "source_backed_continuation", "REPEATED_NOTICE")
    return FollowupRelation("SAME_EVENT", "source_backed_continuation")

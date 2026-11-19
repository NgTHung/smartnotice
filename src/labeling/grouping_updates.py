"""Resolve a directed field change after the source item has been linked."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, time
from typing import Literal

from smartnotice.labeling.grouping_evidence import single_calendar_date
from smartnotice.labeling.grouping_followup import RoutingComparison
from smartnotice.labeling.grouping_model import validate_grouping_mention
from smartnotice.schemas import EvidenceQuote, GroupingChange, GroupingModelMention, Notice

_DEADLINE_OBJECT = (
    r"(?:hạn(?:\s+(?:chót|cuối|nộp|đăng\s+k[ýí]|đóng))?|thời\s+hạn|"
    r"nộp|đăng\s+k[ýí]|đóng\s+học\s+phí)"
)
_EXTENSION = re.compile(rf"\b(?:gia\s+hạn|kéo\s+dài|lùi)\s+(?:việc\s+)?{_DEADLINE_OBJECT}\b", re.I)
_ADJUSTMENT = re.compile(
    rf"\b(?:điều\s+chỉnh|thay\s+đổi|đính\s+chính|dời|khôi\s+phục)\s+"
    rf"(?:mốc\s+)?{_DEADLINE_OBJECT}\b",
    re.I,
)
_UNCONFIRMED = re.compile(
    r"\b(?:nếu|giả\s+sử|dự\s+kiến|có\s+thể|đang\s+xem\s+xét|"
    r"đề\s+xuất|đề\s+nghị|mong|yêu\s+cầu|từ\s+chối|bác\s+bỏ|"
    r"xin\s+(?:(?:được|xem\s+xét)\s+)*(?=gia\s+hạn|điều\s+chỉnh)|"
    r"sẽ|chưa|không\s+(?:đồng\s+ý|chấp\s+thuận|"
    r"(?:thể\s+)?(?:gia\s+hạn|điều\s+chỉnh|thay\s+đổi|"
    r"đính\s+chính|được\s+khôi\s+phục)))\b",
    re.I,
)
_OLD_VALUE = re.compile(r"\b(?:hạn\s+cũ|thời\s+hạn\s+cũ|mốc\s+cũ|trước\s+khi\s+gia\s+hạn)\b", re.I)
_DATE_SHAPE = (
    r"\d{1,2}(?:\s*[./-]\s*|\s+tháng\s+)\d{1,2}"
    r"(?:\s*[./-]\s*|\s+năm\s+)(?:20\d{2})"
)
_CLOCK_SHAPE = r"\d{1,2}\s*(?::\s*\d{2}|h\s*\d{0,2}|giờ(?:\s+\d{1,2}(?:\s+phút)?)?)"
_DEADLINE_LITERAL = re.compile(
    rf"^(?:(?:đến\s+hết|đến|tới|trước|chậm\s+nhất|hết|vào)\s+)?"
    rf"(?:(?P<before>{_CLOCK_SHAPE})\s+)?(?:ngày\s+)?{_DATE_SHAPE}"
    rf"(?:\s*(?:,\s*|lúc\s+)?(?P<after>{_CLOCK_SHAPE}))?$",
    re.I,
)
_LITERAL_CLOCK = re.compile(r"^(\d{1,2})\s*(?::|h|giờ)\s*(\d{0,2})(?:\s+phút)?$", re.I)

_SERVICE = r"(?:hệ\s+thống|cổng|trang|ứng\s+dụng|nền\s+tảng)"
_SERVICE_WORD = re.compile(rf"\b{_SERVICE}\b", re.I)
_NAMED_SERVICE = rf"(?P<object>{_SERVICE}\s+[\wÀ-ỹ -]{{2,80}}?)\s+"
_FAULT = (
    r"(?:hiện\s+)?(?:(?:đang\s+|đã\s+)?"
    r"(?:gặp\s+lỗi|bị\s+lỗi|gặp\s+sự\s+cố|bị\s+gián\s+đoạn)"
    r"|không\s+(?:hoạt\s+động|(?:thể\s+)?truy\s+cập(?:\s+được)?))"
)
_RESTORED = (
    r"(?:đã|vừa)\s+(?:hoạt\s+động\s+(?:bình\s+thường\s+)?(?:trở\s+)?lại|"
    r"được\s+khôi\s+phục|khôi\s+phục\s+hoạt\s+động|truy\s+cập\s+được\s+trở\s+lại)"
)
_STATUS = re.compile(
    rf"\b{_NAMED_SERVICE}(?:(?P<fault>{_FAULT})|(?P<restored>{_RESTORED}))\b", re.I
)
_AMBIGUOUS_OBJECT = re.compile(r"\b(?:và|hoặc|cùng\s+với|không|chưa)\b|\s[-/]\s", re.I)
_QUALIFIED_STATUS = re.compile(
    r"\b(?:nhưng|tuy\s+nhiên|vẫn\s+chưa|thử\s+nghiệm|một\s+phần|"
    r"tạm\s+thời|không\s+ổn\s+định)\b",
    re.I,
)
_BAD_RESTORATION = re.compile(
    r"\b(?:không\s+(?:đã\s+)?(?:hoạt\s+động|khôi\s+phục|truy\s+cập)|"
    r"không\s+phải\s+là|chưa)\b",
    re.I,
)


@dataclass(frozen=True)
class FollowupUpdate:
    """Carry a supported change and the newer side of the input pair."""

    update_side: Literal[0, 1]
    change: GroupingChange
    reason: Literal["verified_deadline_change", "verified_status_restoration"]


def _clean(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def _deadline_value(
    mention: GroupingModelMention,
) -> tuple[date, time | None, EvidenceQuote] | None:
    due = [arg for arg in mention.event.arguments if arg.role == "DEADLINE"]
    if len(due) != 1 or due[0].inferred:
        return None
    span = next(
        (s for s in mention.spans if s.span_id == due[0].span_id and s.label == "TIME"), None
    )
    if span is None:
        return None
    literal = _DEADLINE_LITERAL.fullmatch(_clean(span.text).rstrip("."))
    day = single_calendar_date(span.text)
    if literal is None or day is None or due[0].normalized_date not in (None, day):
        return None
    if literal["before"] and literal["after"]:
        return None
    clock_text = literal["before"] or literal["after"]
    clock = None
    if clock_text:
        parsed = _LITERAL_CLOCK.fullmatch(clock_text)
        if parsed is None:
            return None
        hour, minute = int(parsed[1]), int(parsed[2] or 0)
        if hour > 23 or minute > 59:
            return None
        clock = time(hour, minute)
    sentence = next(s for s in mention.sentences if s.start <= span.start < span.end <= s.end)
    return (
        day,
        clock,
        EvidenceQuote(
            doc_id=mention.doc_id,
            sentence_id=sentence.sentence_id,
            start=span.start,
            end=span.end,
            text=span.text,
        ),
    )


def _other_times(mention: GroupingModelMention) -> dict[str, set[str]]:
    spans = {span.span_id: span for span in mention.spans}
    values: dict[str, set[str]] = {}
    for arg in mention.event.arguments:
        if arg.role and arg.role != "DEADLINE" and spans[arg.span_id].label == "TIME":
            values.setdefault(arg.role, set()).add(_clean(spans[arg.span_id].text))
    return values


def _deadline_change(
    previous: GroupingModelMention, newer: GroupingModelMention
) -> GroupingChange | None:
    old, new = _deadline_value(previous), _deadline_value(newer)
    if old is None or new is None:
        return None
    old_day, old_clock, old_quote = old
    new_day, new_clock, new_quote = new
    cue_sentences = [
        sentence.text
        for sentence in newer.sentences
        if _EXTENSION.search(sentence.text) or _ADJUSTMENT.search(sentence.text)
    ]
    if len(cue_sentences) != 1 or _UNCONFIRMED.search(cue_sentences[0]):
        return None
    due_sentence = next(s.text for s in newer.sentences if s.sentence_id == new_quote.sentence_id)
    if (
        single_calendar_date(due_sentence) != new_day
        or _OLD_VALUE.search(due_sentence)
        or _UNCONFIRMED.search(due_sentence)
    ):
        return None
    old_times, new_times = _other_times(previous), _other_times(newer)
    if any(old_times[role] != new_times[role] for role in old_times.keys() & new_times.keys()):
        return None
    if old_day != new_day:
        moves_later = new_day > old_day
    elif old_clock is not None and new_clock is not None and new_clock != old_clock:
        moves_later = new_clock > old_clock
    else:
        return None
    if _EXTENSION.search(cue_sentences[0]) and not moves_later:
        return None
    return GroupingChange(field="DEADLINE", old=old_quote, new=new_quote)


def _status_value(
    mention: GroupingModelMention,
) -> tuple[str, bool, EvidenceQuote] | None:
    values = []
    for sentence in mention.sentences:
        for match in _STATUS.finditer(sentence.text):
            restored = match["restored"] is not None
            if (
                len(_SERVICE_WORD.findall(sentence.text)) != 1
                or _AMBIGUOUS_OBJECT.search(match["object"])
                or _UNCONFIRMED.search(sentence.text)
                or _QUALIFIED_STATUS.search(sentence.text)
                or (restored and _BAD_RESTORATION.search(sentence.text))
            ):
                return None
            values.append(
                (
                    _clean(match["object"]),
                    restored,
                    EvidenceQuote(
                        doc_id=mention.doc_id,
                        sentence_id=sentence.sentence_id,
                        start=sentence.start + match.start(),
                        end=sentence.start + match.end(),
                        text=match[0],
                    ),
                )
            )
    return values[0] if len(values) == 1 else None


def resolve_followup_update(
    left: GroupingModelMention,
    right: GroupingModelMention,
    notices: tuple[Notice, Notice],
    routing: RoutingComparison,
    *,
    target_confirmed: bool,
    task_relation: str,
) -> FollowupUpdate | None:
    """Resolve one explicit deadline or service recovery in a verified reply.

    Pass the uniquely linked mentions and their prepared notices in matching
    order. A deadline requires an established shared task. An unresolved task
    can qualify for a status update with the same named service and explicit
    failure and recovery states. Quotes use end-exclusive prepared offsets.
    An unsupported or ambiguous change returns None. A stale eligible mention
    raises ValueError.
    """
    later = routing.later
    if (
        not target_confirmed
        or not routing.direct_parent
        or later not in (0, 1)
        or left.doc_id == right.doc_id
        or task_relation not in {"SAME_TASK", "UNRESOLVED"}
    ):
        return None
    mentions = (left, right)
    for mention, notice in zip(mentions, notices, strict=True):
        validate_grouping_mention(mention, notice)
    previous, newer = mentions[1 - later], mentions[later]
    deadline = _deadline_change(previous, newer) if task_relation == "SAME_TASK" else None
    old_status, new_status = _status_value(previous), _status_value(newer)
    restores = (
        old_status is not None
        and new_status is not None
        and old_status[0] == new_status[0]
        and not old_status[1]
        and new_status[1]
    )
    if restores:
        if deadline is not None:
            return None
        return FollowupUpdate(
            later,
            GroupingChange(field="STATUS", old=old_status[2], new=new_status[2]),
            "verified_status_restoration",
        )
    if deadline is not None:
        return FollowupUpdate(later, deadline, "verified_deadline_change")
    return None

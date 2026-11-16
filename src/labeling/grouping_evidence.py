"""Find corroborating event identity cues around a source-bound mention."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlsplit

from smartnotice.schemas import GroupingModelMention, Notice

_URL = re.compile(r"https?://[^\s<>\[\]]+", re.I)
_MASK = re.compile(r"\[[A-Z][A-Z_0-9]*\]")
_STOP = frozenset(
    "và của các sinh viên trong được cho là có tại với để theo từ đến vào một "
    "này sẽ đã khi phải thông báo những ngày thời gian bạn em phòng trường khoa "
    "lòng vui tham gia đăng ký kí xem qua link sau kính gửi chào thân đây".split()
)
_NUMBERED = re.compile(r"^[\s*]*(?:\d{1,2}|[IVX]+)[.)]\s+", re.I)
_TERM = re.compile(
    r"\b(?:hk|học\s*k[ỳì])\s*([1-3])\s*[/:-]\s*(?:20)?(\d{2})[-–/]?(?:20)?(\d{2})\b", re.I
)
_YEAR = re.compile(r"\bnăm\s+học\s+20(\d{2})\s*[-–/]\s*(?:20)?(\d{2})\b", re.I)
_DATE = re.compile(
    r"\b(\d{1,2})(?:\s*[./-]\s*|\s+tháng\s+)(\d{1,2})"
    r"(?:\s*[./-]\s*|\s+năm\s+)(20\d{2})\b",
    re.I,
)
_CODE = re.compile(
    r"\b(?:mã (?:sự kiện|cuộc thi|chương trình|đợt)|event code)\s*:\s*([\w-]{3,})", re.I
)
_REQUEST = re.compile(r"\b(?:nguyện vọng|mong .{0,45}(?:có thể|giúp)|xin phép|đề nghị)\b", re.I)
_REPLY = re.compile(r"\b(?:không (?:thể|giải quyết|đồng ý)|từ chối|chấp thuận|đã duyệt)\b", re.I)
_FORM_PATHS = {
    "forms.gle": "/",
    "forms.office.com": "/r/",
    "docs.google.com": "/forms/d/",
    "forms.cloud.microsoft": "/r/",
}

EVIDENCE_FEATURES = (
    "nearby_content_overlap",
    "nearby_phrase_overlap",
    "shared_literal_calendar_date",
    "shared_academic_period",
    "conflicting_academic_period",
    "shared_event_form_or_code",
    "close_repeated_context",
    "request_reply_overlap",
)


@dataclass(frozen=True)
class PairEvidence:
    """Carry numeric features and the source cues used by the merge policy."""

    features: tuple[float, ...]
    anchor: str | None
    conflict: bool


def mention_context(mention: GroupingModelMention, notice: Notice) -> str:
    """Return nearby prepared evidence without crossing a numbered item boundary."""
    ids = {s.sentence_id for s in mention.sentences}
    indices = [i for i, s in enumerate(notice.sentences) if s.sentence_id in ids]
    selected = set(indices)
    for i in indices:
        for j in range(i, max(-1, i - 3), -1):
            selected.add(j)
            if _NUMBERED.match(notice.sentences[j].text):
                break
        if i + 1 < len(notice.sentences) and not _NUMBERED.match(notice.sentences[i + 1].text):
            selected.add(i + 1)
    return unicodedata.normalize(
        "NFC", "\n".join(notice.sentences[i].text for i in sorted(selected))
    ).replace("*", "")


def _tokens(text: str) -> list[str]:
    text = _URL.sub(" ", _MASK.sub(" ", text.upper()))
    return [w for w in re.findall(r"[^\W\d_]{2,}", text.casefold()) if w not in _STOP]


def _overlap(left, right) -> float:
    return len(left & right) / max(1, len(left | right))


def _calendar(text: str) -> set[date]:
    result = set()
    for day, month, year in _DATE.findall(text):
        try:
            result.add(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    return result


def event_form_keys(text: str) -> set[str]:
    """Return visible form paths with an instance ID, without accessing the URLs."""
    result = set()
    for value in _URL.findall(text):
        try:
            parsed = urlsplit(value.rstrip(".,;)*"))
            host = parsed.hostname
        except ValueError:
            continue
        prefix = _FORM_PATHS.get(host or "")
        if prefix and parsed.path.startswith(prefix) and parsed.path[len(prefix) :].strip("/"):
            result.add(f"{host}{parsed.path.rstrip('/')}")
    return result


def compare_pair_evidence(
    left: GroupingModelMention, right: GroupingModelMention, a: Notice, b: Notice
) -> PairEvidence:
    """Compare validated mentions using local source sentences and publication dates."""
    x, y = mention_context(left, a), mention_context(right, b)
    tx, ty = _tokens(x), _tokens(y)
    wx, wy = set(tx), set(ty)
    shared_words = wx & wy
    px = set(zip(tx, tx[1:], tx[2:], strict=False))
    py = set(zip(ty, ty[1:], ty[2:], strict=False))
    dates_x, dates_y = _calendar(x), _calendar(y)
    same_day = bool(dates_x & dates_y)
    disjoint_dates = bool(dates_x and dates_y and dates_x.isdisjoint(dates_y))
    academic = [(set(p.findall(x)), set(p.findall(y))) for p in (_TERM, _YEAR)]
    same_period = any(left_periods & right_periods for left_periods, right_periods in academic)
    conflict = any(
        len(left_periods) == len(right_periods) == 1 and left_periods.isdisjoint(right_periods)
        for left_periods, right_periods in academic
    )
    codes_x, codes_y = set(_CODE.findall(x.casefold())), set(_CODE.findall(y.casefold()))
    conflict |= len(codes_x) == len(codes_y) == 1 and codes_x.isdisjoint(codes_y)
    same_code = len(codes_x) == len(codes_y) == 1 and codes_x == codes_y
    same_form = bool(event_form_keys(x) & event_form_keys(y))
    nearby = _overlap(wx, wy)
    phrase = _overlap(px, py)
    close = bool(
        a.reference_date
        and b.reference_date
        and abs((a.reference_date - b.reference_date).days) <= 3
    )
    repeat = (
        close and not disjoint_dates and nearby >= 0.8 and len(shared_words) >= 8 and phrase >= 0.55
    )
    reply = (
        close
        and not disjoint_dates
        and bool(px & py)
        and len(shared_words) >= 4
        and bool(
            (_REQUEST.search(x) and _REPLY.search(y)) or (_REQUEST.search(y) and _REPLY.search(x))
        )
    )
    topic = len(shared_words) >= 4 and (bool(px & py) or nearby >= 0.45)
    anchor = None
    if not conflict:
        if same_code:
            anchor = "explicit_event_code"
        elif topic and same_form:
            anchor = "same_form_and_topic"
        elif topic and same_day:
            anchor = "same_calendar_date_and_topic"
        elif topic and same_period and not disjoint_dates and phrase >= 0.25:
            anchor = "same_period_and_phrase"
        elif repeat:
            anchor = "close_repeated_context"
        elif reply:
            anchor = "request_reply_with_shared_phrase"
    return PairEvidence(
        (
            nearby,
            phrase,
            float(same_day),
            float(same_period),
            float(conflict),
            float(same_code or same_form),
            float(repeat),
            float(reply),
        ),
        anchor,
        conflict,
    )


def evidence_decision(probability: float, threshold: float, evidence: PairEvidence) -> str:
    """Return a merge, distinct event, or review decision for a scored pair."""
    if evidence.conflict:
        return "DIFFERENT_EVENT"
    if evidence.anchor == "request_reply_with_shared_phrase":
        return "SAME_EVENT"
    if evidence.anchor and probability >= threshold:
        return "SAME_EVENT"
    if not evidence.anchor and probability <= 0.25:
        return "DIFFERENT_EVENT"
    return "UNCLEAR"

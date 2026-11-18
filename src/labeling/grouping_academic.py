"""Resolve explicit academic scope before proposing an event merge."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from smartnotice.labeling.grouping_evidence import mention_context
from smartnotice.labeling.grouping_followup import RoutingComparison
from smartnotice.parsers.email import EmailRouting
from smartnotice.schemas import GroupingModelMention, Notice, Sentence

_YEAR_PAIR = r"(20\d{2}|\d{2})\s*[-/–]?\s*(20\d{2}|\d{2})(?!\d)"
_TERM = re.compile(r"\b(?:hk|học\s*k[ỳì])\s*(iii|ii|i|[123])\b", re.I)
_AFTER_TERM = re.compile(r"^\s*(?:[/:\-–]\s*|năm\s+học\s+)" + _YEAR_PAIR, re.I)
_YEAR = re.compile(r"\bnăm\s+học\s+" + _YEAR_PAIR, re.I)
_COURSE_PREFIX = re.compile(
    r"\b(?:CLC|TCTA|CTDA|VP)?" + _YEAR_PAIR + r"HK([123])_([A-Z]{2,6}\d{3,7})(?:_|\b)", re.I
)
_COURSE = re.compile(
    r"\b(?:mã\s*(?:môn|học phần)|môn|học phần)\s*[:#-]?\s*([A-Z]{2,6}\d{3,7})\b", re.I
)
_EXAM = re.compile(r"\blịch\s+thi\b|\b(?:kiểm tra|thi)\s+(?:giữa|cuối|lý thuyết|thực hành)", re.I)
_TUITION = re.compile(r"\b(?:đóng|nộp|thanh toán)\s+học\s+phí\b", re.I)
_MID = re.compile(r"\b(?:thi|kiểm tra|lịch thi)\s+giữa\s+k[ỳì]\b", re.I)
_FINAL = re.compile(r"\b(?:thi|kiểm tra|lịch thi)\s+cuối\s+k[ỳì]\b", re.I)
_INSURANCE_NAME = r"(?:bảo\s+hiểm\s+y\s+tế|bhyt)"
_INSURANCE = re.compile(rf"\b{_INSURANCE_NAME}\b", re.I)
_INSURANCE_OPERATION = re.compile(r"\b(?:mua|gia\s+hạn)\b", re.I)
_COMPLETED_INSURANCE = re.compile(
    rf"^(?:nhà trường|trường)\s+đã\s+(?:thực hiện\s+)?"
    rf"(mua|gia\s+hạn)\s+(?:thẻ\s+)?{_INSURANCE_NAME}\b",
    re.I | re.M,
)
_UPDATE = re.compile(
    r"\b(?:đính chính|đổi lịch|dời lịch|điều chỉnh lịch|thay đổi lịch|"
    r"gia hạn|nhầm lẫn về thời gian)\b",
    re.I,
)
_ITEM = re.compile(r"^[\s*#-]*\d{1,2}[.)]\s+", re.I)
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "1": 1, "2": 2, "3": 3}


@dataclass(frozen=True)
class AcademicScope:
    """Carry corroborated scope values and provenance for one prepared mention."""

    kind: str | None
    year: int | None
    term: int | None
    course: str | None
    phase: str | None
    ambiguous: bool
    sources: tuple[str, ...]
    explicit_change: bool
    times: tuple[tuple[str, date], ...]
    insurance_operation: str | None = None
    insurance_sentences: tuple[str, ...] = ()


@dataclass(frozen=True)
class AcademicDecision:
    """Return an event decision and the newer side for a confirmed update."""

    decision: str
    reason: str
    update_side: int | None = None


def _year_pair(first: str, second: str) -> int | None:
    start, end = (int(x) + (2000 if len(x) == 2 else 0) for x in (first, second))
    return start if end == start + 1 else None


def _values(text: str):
    years = {y for a, b in _YEAR.findall(text) if (y := _year_pair(a, b)) is not None}
    terms = set()
    courses = {val.upper() for val in _COURSE.findall(text)}
    for match in _TERM.finditer(text):
        terms.add(_ROMAN[match[1].casefold()])
        after = _AFTER_TERM.match(text[match.end() :])
        if after is not None and (year := _year_pair(*after.groups())) is not None:
            years.add(year)
    for first, second, term, course in _COURSE_PREFIX.findall(text):
        year = _year_pair(first, second)
        if year is not None:
            years.add(year)
            terms.add(int(term))
            courses.add(course.upper())
    return years, terms, courses


def _completed_insurance(local: str, lead: list[Sentence]) -> tuple[str | None, tuple[str, ...]]:
    if not lead or not _INSURANCE.search(local):
        return None, ()
    text = "\n".join(
        " ".join(unicodedata.normalize("NFKC", s.text).replace("*", "").split()) for s in lead
    )
    operations = {
        " ".join(m.group().casefold().split()) for m in _INSURANCE_OPERATION.finditer(text)
    }
    matches = list(_COMPLETED_INSURANCE.finditer(text))
    if len(operations) != 1 or len(matches) != 1:
        return None, ()
    match = matches[0]
    first = text.count("\n", 0, match.start())
    last = text.count("\n", 0, match.end())
    phase = " ".join(match[1].casefold().split())
    return phase, tuple(s.sentence_id for s in lead[first : last + 1])


def academic_scope(
    mention: GroupingModelMention, notice: Notice, headers: EmailRouting | None = None
) -> AcademicScope:
    """Extract explicit periods and completed operations for a prepared mention.

    Read the subject only for a single-item notice. Derive no event year from
    the send date. For a scoped health insurance mention, retain sentence IDs
    for an unambiguous completed purchase or renewal in the prepared lead.
    Return evidence categories and explicit TIME values without raw headers.
    """
    local = mention_context(mention, notice)
    texts = [("mention_context", local)]
    heading = []
    if not any(_ITEM.match(s.text) for s in notice.sentences):
        heading = notice.sentences[:4]
        lead = "\n".join(s.text for s in heading)
        texts.append(("prepared_heading", lead))
        if headers and headers.subject:
            texts.append(("email_subject", headers.subject))
    values = [set(), set(), set()]
    sources = []
    normalized = []
    for source, text in texts:
        value = unicodedata.normalize("NFKC", text).replace("*", "")
        normalized.append(value)
        derived = _values(value)
        if any(derived):
            sources.append(source)
            for union, candidates in zip(values, derived, strict=True):
                union.update(candidates)
    context = "\n".join(normalized)
    kinds = [
        name
        for name, pattern in (("exam", _EXAM), ("tuition", _TUITION))
        if pattern.search(context)
    ]
    phases = [
        name for name, pattern in (("midterm", _MID), ("final", _FINAL)) if pattern.search(context)
    ]
    year, term, course = (next(iter(items)) if len(items) == 1 else None for items in values)
    times = {
        (arg.role, arg.normalized_date)
        for arg in mention.event.arguments
        if arg.role and arg.normalized_date and not arg.inferred
    }
    insurance_operation, insurance_sentences = _completed_insurance(normalized[0], heading)
    return AcademicScope(
        kinds[0] if len(kinds) == 1 else None,
        year,
        term,
        course,
        phases[0] if len(phases) == 1 else None,
        any(len(items) > 1 for items in values),
        tuple(sources),
        bool(_UPDATE.search(context)),
        tuple(sorted(times)),
        insurance_operation,
        insurance_sentences,
    )


def apply_academic_scope(
    left: AcademicScope,
    right: AcademicScope,
    routing: RoutingComparison,
    base: str,
) -> AcademicDecision:
    """Refine a proposal with an explicit scope, operation, or comparable time role."""
    if left.insurance_operation and right.insurance_operation:
        if left.insurance_operation != right.insurance_operation:
            if routing.direct_parent:
                return AcademicDecision("UNCLEAR", "referenced_insurance_operations")
            return AcademicDecision("DIFFERENT_EVENT", "different_insurance_operations")
    # A direct reference resolves direction, but cannot by itself resolve a term mismatch.
    same_kind = left.kind is not None and left.kind == right.kind
    sides = (left, right)
    later = routing.later
    has_change = later is not None and sides[later].explicit_change
    if same_kind and (left.ambiguous or right.ambiguous):
        if base == "SAME_EVENT":
            return AcademicDecision("UNCLEAR", "ambiguous_academic_scope")
        return AcademicDecision(base, "base")
    if same_kind:
        for field in ("year", "term", "course", "phase"):
            a, b = getattr(left, field), getattr(right, field)
            if a is not None and b is not None and a != b:
                if has_change and routing.direct_parent:
                    return AcademicDecision("UNCLEAR", f"referenced_conflict_{field}")
                return AcademicDecision("DIFFERENT_EVENT", f"different_explicit_{field}")
    dates = [{role: {d for key, d in s.times if key == role} for role, _ in s.times} for s in sides]
    changed_role = any(
        len(dates[0][role]) == len(dates[1][role]) == 1
        and dates[0][role].isdisjoint(dates[1][role])
        for role in dates[0].keys() & dates[1].keys()
    )
    # A binary merge score alone cannot establish the direction or existence of an update.
    if base == "SAME_EVENT" and routing.direct_parent and has_change and changed_role:
        return AcademicDecision("UPDATE_OF", "direct_reference_with_explicit_time_change", later)
    if same_kind and changed_role and base == "SAME_EVENT":
        return AcademicDecision("UNCLEAR", "different_dates_same_role")
    return AcademicDecision(base, "base")

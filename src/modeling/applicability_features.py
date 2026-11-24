"""Build model inputs and comparison features for event/profile pairs."""

import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Literal
from unicodedata import normalize

from pydantic import ValidationError
from smartnotice.labeling.validation import validate_annotation
from smartnotice.modeling.lexicon import Lexicon, fold_text
from smartnotice.schemas import Annotation, DegreeLevel, Notice, Record, StudentStatus

AudienceSource = Literal["human", "predicted", "none"]
_PROFILE_FIELDS = ("cohort", "degree_level", "major", "program", "status")


class ApplicabilityInput(Record):
    """Expose the event text, optional span evidence, and profile attributes."""

    doc_id: str
    event_id: str
    profile_id: str
    event_text: str
    audience_texts: list[str] | None
    condition_texts: list[str] | None
    reference_date: date | None
    source_type: Literal["email", "web"]
    cohort: int | None = None
    degree_level: DegreeLevel | None = None
    major: str | None = None
    program: str | None = None
    status: StudentStatus | None = None


def _span_texts(annotation: Annotation, notice: Notice) -> dict[str, tuple[list[str], list[str]]]:
    validate_annotation(annotation, notice)
    spans = {span.span_id: span for span in annotation.spans}
    evidence = {}
    for event in annotation.events:
        linked = [spans[arg.span_id] for arg in event.arguments]
        evidence[event.event_id] = (
            [span.text for span in linked if span.label == "AUDIENCE"],
            [span.text for span in linked if span.label == "CONDITION"],
        )
    return evidence


def build_inputs(
    pairs: list[dict],
    notices: list[Notice],
    annotations: list[Annotation] | None,
    source: AudienceSource,
) -> list[ApplicabilityInput]:
    """Allowlist pair data and join event span text by document and event ID.

    Human and predicted modes require annotations aligned to the pair event
    IDs. Their span offsets refer to the prepared notice in Python code points.
    Event-text mode sets both span lists to None. Invalid joins raise ValueError
    with the one-based pair line.
    """
    if source not in {"human", "predicted", "none"}:
        raise ValueError("Audience source must be human, predicted, or none")
    if source != "none" and annotations is None:
        raise ValueError(f"{source} mode requires audience annotations")
    documents = {notice.doc_id: notice for notice in notices}
    if len(documents) != len(notices):
        raise ValueError("Notice document IDs must be unique")
    labels = {annotation.doc_id: annotation for annotation in annotations or []}
    if source != "none" and len(labels) != len(annotations or []):
        raise ValueError("Audience annotation document IDs must be unique")

    evidence: dict[str, dict[str, tuple[list[str], list[str]]]] = {}
    inputs = []
    for line, pair in enumerate(pairs, 1):
        location = f"pair line {line}"
        try:
            doc_id, event_id = pair["doc_id"], pair["event_id"]
            notice = documents[doc_id]
            if source == "none":
                audience, conditions = None, None
            else:
                if doc_id not in evidence:
                    evidence[doc_id] = _span_texts(labels[doc_id], notice)
                audience, conditions = evidence[doc_id][event_id]
            profile = pair["profile"]
            if not isinstance(profile, dict):
                raise ValueError("profile must be an object")
            item = ApplicabilityInput(
                doc_id=doc_id,
                event_id=event_id,
                profile_id=pair["profile_id"],
                event_text=pair["event_text"],
                audience_texts=audience,
                condition_texts=conditions,
                reference_date=notice.reference_date,
                source_type=notice.source_type,
                **{field: profile.get(field) for field in _PROFILE_FIELDS},
            )
        except KeyError as exc:
            raise ValueError(f"{location}: missing field or unknown reference {exc}") from None
        except ValidationError as exc:
            fields = ", ".join(
                ".".join(map(str, error["loc"])) for error in exc.errors(include_input=False)
            )
            raise ValueError(f"{location}: invalid applicability input fields: {fields}") from None
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{location}: {exc}") from None
        inputs.append(item)
    return inputs


_COHORT_YEAR = r"(?:19[0-9]{2}|20[0-9]{2}|1[5-9]|2[0-9]|3[0-5])"
_COHORT_PREFIX = r"(?:k\s*|kh(?:óa|oá)\s+)"
_BOUND = r"trở về trước|về trước|trở đi|trở lên"
_COHORT_CUE = re.compile(
    rf"\b{_COHORT_PREFIX}(?:từ\s+)?(?P<year>{_COHORT_YEAR})\b"
    rf"(?:\s*(?:đến|tới|[-–—])\s*(?:{_COHORT_PREFIX})?(?P<end>{_COHORT_YEAR})\b"
    rf"|\s+(?P<bound>{_BOUND})\b)?"
)
_STUDY_NUMBERS = {
    "nhất": 1,
    "một": 1,
    "hai": 2,
    "ba": 3,
    "tư": 4,
    "bốn": 4,
    "năm": 5,
    "sáu": 6,
    "bảy": 7,
    "tám": 8,
    "chín": 9,
}
_STUDY_CUE = re.compile(
    rf"\bnăm\s+(?:thứ\s+)?(?P<number>[1-9]|{'|'.join(_STUDY_NUMBERS)})\b"
    rf"(?:\s+(?P<bound>{_BOUND})\b)?"
)
_CLASS_CODE = re.compile(r"\blớp\s+(?=[a-z0-9]*[a-z])(?=[a-z0-9]*[0-9])[a-z0-9]+\b")
_CLAUSE_BREAK = re.compile(r"[,;.!?\n]|\b(?:nhưng|riêng)\b")


@dataclass
class AudienceCues:
    """Hold recognized audience cues, inclusive cohort bounds, and span counts."""

    cohorts: set[int] = field(default_factory=set)
    cohort_min: int | None = None
    cohort_max: int | None = None
    cohort_unresolved: bool = False
    degrees: set[str] = field(default_factory=set)
    majors: set[str] = field(default_factory=set)
    programs: set[str] = field(default_factory=set)
    statuses: set[str] = field(default_factory=set)
    excluded_statuses: set[str] = field(default_factory=set)
    all_students: bool = False
    outside_population: bool = False
    unrepresented: bool = False
    condition: bool = False
    absent: bool = False
    n_audience: int = 0
    n_condition: int = 0
    audience_chars: int = 0


def admission_year_for_study_year(year_of_study: int, reference_date: date | None) -> int | None:
    """Convert a positive year of study to an admission year.

    Return None without a reference date or between July 1 and October 15,
    inclusive. January through June uses the preceding academic-year start.
    """
    if year_of_study < 1:
        raise ValueError("Year of study must be positive")
    if reference_date is None or (7, 1) <= (reference_date.month, reference_date.day) <= (10, 15):
        return None
    academic_start = reference_date.year - int(reference_date.month <= 6)
    return academic_start - year_of_study + 1


def _cohort_year(text: str) -> int:
    return int(text) + (2000 if len(text) == 2 else 0)


def _read_cohorts(cues: AudienceCues, texts: list[str], reference_date: date | None) -> None:
    ranges = []
    for text in texts:
        for match in _COHORT_CUE.finditer(text):
            year = _cohort_year(match["year"])
            if end := match["end"]:
                ranges.append(tuple(sorted((year, _cohort_year(end)))))
            elif bound := match["bound"]:
                ranges.append((None, year) if bound.endswith("trước") else (year, None))
            else:
                cues.cohorts.add(year)
        for match in _STUDY_CUE.finditer(text):
            number = match["number"]
            study_year = int(number) if number.isdecimal() else _STUDY_NUMBERS[number]
            year = admission_year_for_study_year(study_year, reference_date)
            if year is None:
                cues.cohort_unresolved = True
            elif bound := match["bound"]:
                # Later years of study correspond to earlier admission years.
                ranges.append((year, None) if bound.endswith("trước") else (None, year))
            else:
                cues.cohorts.add(year)
    if ranges:
        lower, upper = zip(*ranges, strict=True)
        cues.cohort_min = None if None in lower else min(lower)
        cues.cohort_max = None if None in upper else max(upper)


@lru_cache
def _surface_pattern(forms: tuple[str, ...]) -> re.Pattern[str]:
    if not forms:
        return re.compile(r"(?!)")
    alternatives = "|".join(re.escape(form) for form in sorted(forms, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)")


def _has_form(forms: list[str], texts: list[str]) -> bool:
    pattern = _surface_pattern(tuple(forms))
    return any(pattern.search(text) for text in texts)


def _read_statuses(cues: AudienceCues, clauses: list[str], lexicon: Lexicon) -> None:
    exclusion = _surface_pattern(tuple(lexicon.exclusion))
    for clause in clauses:
        marker = exclusion.search(clause)
        included = clause if marker is None else clause[: marker.start()]
        excluded = "" if marker is None else clause[marker.end() :]
        for status, forms in lexicon.statuses.items():
            if _has_form(forms, [included]):
                cues.statuses.add(status)
            if _has_form(forms, [excluded]):
                cues.excluded_statuses.add(status)


def extract_audience_cues(item: ApplicabilityInput, lexicon: Lexicon) -> AudienceCues:
    """Recognize NFC Vietnamese cues in the supplied spans or event text.

    Counts and character length describe linked spans. Event-text-only mode
    has zero linked spans. Year-of-study cues keep missing dates unresolved.
    """
    audiences = item.audience_texts or []
    conditions = item.condition_texts or []
    texts = [item.event_text] if item.audience_texts is None else audiences
    condition_texts = [item.event_text] if item.condition_texts is None else conditions
    clauses = [
        fold_text(clause)
        for text in texts
        for clause in _CLAUSE_BREAK.split(normalize("NFC", text.casefold()))
    ]
    folded = [fold_text(text) for text in texts]
    cues = AudienceCues(
        n_audience=len(audiences),
        n_condition=len(conditions),
        audience_chars=sum(map(len, audiences)),
        condition=_has_form(lexicon.condition, [fold_text(text) for text in condition_texts]),
    )
    _read_cohorts(cues, folded, item.reference_date)
    _read_statuses(cues, clauses, lexicon)
    cues.degrees = {code for code, forms in lexicon.degrees.items() if _has_form(forms, folded)}
    if "graduate" in cues.degrees:
        cues.degrees.remove("graduate")
        cues.degrees.update(("master", "doctoral"))
    cues.majors = {code for code, forms in lexicon.majors.items() if _has_form(forms, folded)}
    cues.programs = {code for code, forms in lexicon.programs.items() if _has_form(forms, folded)}
    cues.outside_population = _has_form(lexicon.outside_population, folded) and not _has_form(
        lexicon.student_terms, folded
    )
    cues.all_students = not cues.outside_population and _has_form(lexicon.all_students, folded)
    cues.unrepresented = _has_form(lexicon.unrepresented, folded) or any(
        _CLASS_CODE.search(text) for text in folded
    )
    cues.absent = not (
        cues.cohorts
        or cues.cohort_min is not None
        or cues.cohort_max is not None
        or cues.cohort_unresolved
        or cues.degrees
        or cues.majors
        or cues.programs
        or cues.statuses
        or cues.excluded_statuses
        or cues.all_students
        or cues.outside_population
        or cues.unrepresented
    )
    return cues

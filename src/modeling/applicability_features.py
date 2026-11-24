"""Build model inputs and comparison features for event/profile pairs."""

from datetime import date
from typing import Literal

from pydantic import ValidationError
from smartnotice.labeling.validation import validate_annotation
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

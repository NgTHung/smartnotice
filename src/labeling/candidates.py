"""Validate candidate evidence and derive binary targets from reviewed spans."""

from smartnotice.labeling.llm import json_sha256, text_sha256
from smartnotice.schemas import CandidateTarget, Notice, Span, SpanCandidate, SpanReview


def project_annotation_spans(notice: Notice, row: dict) -> list[Span]:
    """Read typed spans from an annotation row and validate their prepared-text offsets.

    Only doc_id and spans are read. This projection does not validate event or
    audience metadata. Wrong document IDs, invalid spans and repeated span IDs
    raise ValueError without printing annotation content.
    """
    if row.get("doc_id") != notice.doc_id:
        raise ValueError(f"Annotation document mismatch: {notice.doc_id}")
    if not isinstance(row.get("spans"), list):
        raise ValueError(f"Expected a span list: {notice.doc_id}")
    try:
        spans = [Span.model_validate(span, strict=True) for span in row["spans"]]
    except ValueError:
        raise ValueError(f"Invalid annotation span structure: {notice.doc_id}") from None
    if len({span.span_id for span in spans}) != len(spans):
        raise ValueError(f"Duplicate span ID: {notice.doc_id}")
    for span in spans:
        _check_bounds(notice, span.start, span.end, span.text)
    return spans


def _check_bounds(notice: Notice, start: int, end: int, text: str) -> None:
    if not 0 <= start < end <= len(notice.text) or notice.text[start:end] != text:
        raise ValueError(f"Invalid span offsets: {notice.doc_id}")


def _match_status(candidate: SpanCandidate, keys: set[tuple[int, int, str]]):
    if (candidate.start, candidate.end, candidate.proposed_label) in keys:
        return "exact"
    if any((start, end) == (candidate.start, candidate.end) for start, end, _ in keys):
        return "wrong_label"
    overlapping = {
        label for start, end, label in keys if start < candidate.end and candidate.start < end
    }
    if candidate.proposed_label in overlapping:
        return "boundary"
    return "overlap_other_label" if overlapping else "no_overlap"


def build_candidate_targets(
    notice: Notice,
    candidates: list[SpanCandidate],
    annotation: dict | None = None,
    review: SpanReview | None = None,
) -> list[CandidateTarget]:
    """Return one target per distinct candidate from a single generator version.

    A supplied review must bind the exact prepared text and original annotation
    row. Without one, targets are None. Stale provenance, invalid offsets, a
    mixed generator batch or duplicate candidate keys raise ValueError.
    """
    digest = text_sha256(notice)
    annotation_hash = json_sha256(annotation) if annotation is not None else None
    spans = project_annotation_spans(notice, annotation) if annotation is not None else []
    if review is not None and (
        review.doc_id != notice.doc_id
        or review.text_sha256 != digest
        or review.annotation_sha256 != annotation_hash
    ):
        raise ValueError(f"Span review does not match current inputs: {notice.doc_id}")
    keys = {(span.start, span.end, span.label) for span in spans}
    if len({candidate.generator_version for candidate in candidates}) > 1:
        raise ValueError(f"Mixed candidate generator versions: {notice.doc_id}")
    seen = set()
    targets = []
    for candidate in candidates:
        if candidate.doc_id != notice.doc_id or candidate.text_sha256 != digest:
            raise ValueError(f"Candidate does not match prepared text: {notice.doc_id}")
        _check_bounds(notice, candidate.start, candidate.end, candidate.text)
        key = (candidate.start, candidate.end, candidate.proposed_label)
        if key in seen:
            raise ValueError(f"Duplicate candidate key: {notice.doc_id}")
        seen.add(key)
        status = _match_status(candidate, keys) if review is not None else "unverified"
        targets.append(
            CandidateTarget(
                doc_id=notice.doc_id,
                text_sha256=digest,
                start=candidate.start,
                end=candidate.end,
                proposed_label=candidate.proposed_label,
                generator_version=candidate.generator_version,
                annotation_sha256=annotation_hash,
                target=None if review is None else (1 if status == "exact" else 0),
                match_status=status,
            )
        )
    return targets

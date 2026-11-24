"""Check exact matching and review provenance with invented notices."""

from datetime import UTC, datetime

import pytest
from smartnotice.labeling.candidates import build_candidate_targets
from smartnotice.labeling.llm import json_sha256, text_sha256
from smartnotice.schemas import Notice, SpanCandidate, SpanReview


@pytest.fixture
def case():
    notice = Notice(
        doc_id="synthetic-test",
        source_type="web",
        source_ref="https://example.invalid",
        raw_sha256="0" * 64,
        reference_date_origin="missing",
        text="K24 nộp hồ sơ. K25 nộp hồ sơ.",
        sentences=[],
        group_id="synthetic",
        redaction_count=0,
        synthetic=True,
    )
    annotation = {
        "doc_id": notice.doc_id,
        "spans": [{"span_id": "a1", "start": 4, "end": 13, "text": "nộp hồ sơ", "label": "ACTION"}],
        "audience_constraints": [{"example_extension": True}],
    }
    review = SpanReview(
        doc_id=notice.doc_id,
        text_sha256=text_sha256(notice),
        annotation_sha256=json_sha256(annotation),
        reviewer_id="synthetic-fixture",
        reviewed_at=datetime(2026, 11, 24, tzinfo=UTC),
        annotation_origin="independent",
    )
    return notice, annotation, review


def _candidate(notice, start, end, label="ACTION"):
    return SpanCandidate(
        doc_id=notice.doc_id,
        text_sha256=text_sha256(notice),
        start=start,
        end=end,
        text=notice.text[start:end],
        proposed_label=label,
        rule_ids=["fixture"],
        generator_version="fixture",
    )


def test_targets_distinguish_label_boundary_and_repeated_text(case):
    notice, annotation, review = case
    candidates = [
        _candidate(notice, 4, 13),
        _candidate(notice, 4, 13, "DOCUMENT"),
        _candidate(notice, 4, 14),
        _candidate(notice, 4, 14, "DOCUMENT"),
        _candidate(notice, 19, 28),
    ]
    assert candidates[0].text == candidates[-1].text
    targets = build_candidate_targets(notice, candidates, annotation, review)
    assert [(row.target, row.match_status) for row in targets] == [
        (1, "exact"),
        (0, "wrong_label"),
        (0, "boundary"),
        (0, "overlap_other_label"),
        (0, "no_overlap"),
    ]


def test_reviewed_empty_annotation_and_unreviewed_annotation_are_distinct(case):
    notice, annotation, review = case
    candidates = [_candidate(notice, 4, 13)]
    assert build_candidate_targets(notice, candidates, annotation)[0].target is None
    empty = {**annotation, "spans": []}
    empty_review = review.model_copy(update={"annotation_sha256": json_sha256(empty)})
    assert build_candidate_targets(notice, candidates, empty, empty_review)[0].target == 0


def test_stale_review_and_stale_candidate_are_rejected(case):
    notice, annotation, review = case
    candidate = _candidate(notice, 4, 13)
    with pytest.raises(ValueError, match="review does not match"):
        build_candidate_targets(notice, [candidate], {**annotation, "version": 2}, review)
    revised = notice.model_copy(update={"text": notice.text + "!"})
    with pytest.raises(ValueError, match="Candidate does not match"):
        build_candidate_targets(revised, [candidate], annotation)


def test_out_of_bounds_and_duplicate_candidates_are_rejected(case):
    notice, annotation, review = case
    too_long = _candidate(notice, 19, len(notice.text) + 1)
    with pytest.raises(ValueError, match="Invalid span offsets"):
        build_candidate_targets(notice, [too_long], annotation, review)
    candidate = _candidate(notice, 4, 13)
    with pytest.raises(ValueError, match="Duplicate candidate"):
        build_candidate_targets(notice, [candidate, candidate], annotation, review)


def test_annotation_projection_rejects_an_invalid_label_or_offset(case):
    notice, annotation, _ = case
    span = annotation["spans"][0]
    for changes, message in [
        ({"label": "UNSUPPORTED"}, "Invalid annotation span structure"),
        ({"start": span["start"] + 1}, "Invalid span offsets"),
    ]:
        with pytest.raises(ValueError, match=message):
            build_candidate_targets(notice, [], {**annotation, "spans": [span | changes]})

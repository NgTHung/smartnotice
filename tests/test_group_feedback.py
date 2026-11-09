"""Check explicit application of user notes, not free-text label guessing."""

import hashlib
from datetime import UTC, datetime

import pytest
from smartnotice.labeling.event_groups import (
    annotation_sha256,
    assembly_fingerprint,
    build_event_groups,
)
from smartnotice.labeling.group_feedback import apply_group_feedback
from smartnotice.schemas import (
    Annotation,
    Event,
    EvidenceQuote,
    GroupFeedbackResolution,
    GroupingReview,
    GroupReviewNote,
    LocalGroupReviewNotes,
    MentionVersion,
    Notice,
    ReviewAuthor,
    Sentence,
    Span,
)


def fixture():
    notices, annotations, versions, quotes = [], [], [], []
    author = ReviewAuthor(
        reviewer_id="ai_assistant",
        reviewer_kind="ai_assistant",
        reviewed_at=datetime(2026, 11, 9, tzinfo=UTC),
    )
    for doc in ["a", "b", "c"]:
        text = f"Synthetic session {doc}."
        notice = Notice(
            doc_id=doc,
            source_type="email",
            source_ref="synthetic",
            raw_sha256=hashlib.sha256(text.encode()).hexdigest(),
            text=text,
            sentences=[Sentence(sentence_id="s1", start=0, end=len(text), text=text)],
            group_id=doc,
            reference_date_origin="missing",
            synthetic=True,
            redaction_count=0,
        )
        annotation = Annotation(
            doc_id=doc,
            annotator_id="ai_assistant",
            spans=[Span(span_id="a1", label="ACTION", start=0, end=len(text), text=text)],
            events=[
                Event(
                    event_id="e1", action_span_id="a1", arguments=[], evidence_sentence_ids=["s1"]
                )
            ],
        )
        notices.append(notice)
        annotations.append(annotation)
        versions.append(
            MentionVersion(
                event_ref=f"{doc}:a1",
                raw_sha256=notice.raw_sha256,
                text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                annotation_sha256=annotation_sha256(annotation),
            )
        )
        quotes.append(
            EvidenceQuote(doc_id=doc, sentence_id="s1", start=0, end=len(text), text=text)
        )
    reviews = [
        GroupingReview(
            review_id=f"r{i}",
            left=versions[0],
            right=versions[i],
            decision="SAME_EVENT",
            task_relation="DIFFERENT_SESSION",
            author=author,
            rationale="Initial broad program grouping.",
            evidence=[quotes[0], quotes[i]],
        )
        for i in [1, 2]
    ]
    assembly = build_event_groups(notices, annotations, reviews)
    return notices, annotations, assembly, author


def feedback(assembly, status="suggest_split"):
    return LocalGroupReviewNotes(
        kind="local_group_review_notes",
        draft=True,
        assembly_fingerprint=assembly_fingerprint(assembly),
        exported_at=datetime(2026, 11, 9, 2, tzinfo=UTC),
        entries=[
            GroupReviewNote(
                group_id=assembly.groups[0].group_id,
                status=status,
                text="User source review.",
                updated_at=datetime(2026, 11, 9, 1, tzinfo=UTC),
            )
        ],
    )


def test_split_replaces_crossing_edges_and_preserves_all_old_members():
    notices, annotations, assembly, author = fixture()
    notes = feedback(assembly)
    plan = GroupFeedbackResolution(
        group_id=assembly.groups[0].group_id,
        mode="PARTITION",
        partitions=[[r] for r in assembly.groups[0].members],
        rationale="User explicitly chose three separate sessions.",
    )
    original = assembly.model_dump()
    result = apply_group_feedback(
        assembly, notes, [plan], notes_sha256="a" * 64, application_author=author
    )
    updated = build_event_groups(notices, annotations, result.reviews)
    assert len(updated.groups) == 3 and not updated.conflicts
    assert len(result.reviews) == 3 and all(r.decision == "DIFFERENT_EVENT" for r in result.reviews)
    assert assembly.model_dump() == original
    assert result.applications[0].note == notes.entries[0]
    assert all(r.author.reviewer_kind == "ai_assistant" for r in result.reviews)


@pytest.mark.parametrize("partitions", [[["a:a1"], ["b:a1"]], [["a:a1"], ["b:a1", "b:a1", "c:a1"]]])
def test_incomplete_or_duplicate_partitions_are_rejected(partitions):
    _, _, assembly, author = fixture()
    plan = GroupFeedbackResolution(
        group_id=assembly.groups[0].group_id,
        mode="PARTITION",
        partitions=partitions,
        rationale="Split",
    )
    with pytest.raises(ValueError, match="exactly once"):
        apply_group_feedback(
            assembly, feedback(assembly), [plan], notes_sha256="a" * 64, application_author=author
        )


def test_unresolved_split_or_stale_export_cannot_be_applied():
    _, _, assembly, author = fixture()
    notes = feedback(assembly)
    with pytest.raises(ValueError, match="explicit resolution"):
        apply_group_feedback(assembly, notes, [], notes_sha256="a" * 64, application_author=author)
    notes.assembly_fingerprint = "0" * 64
    with pytest.raises(ValueError, match="fingerprint"):
        apply_group_feedback(assembly, notes, [], notes_sha256="a" * 64, application_author=author)


def test_acceptance_records_group_feedback_without_relabeling_pair_authorship():
    _, _, assembly, author = fixture()
    result = apply_group_feedback(
        assembly,
        feedback(assembly, "looks_ok"),
        [],
        notes_sha256="a" * 64,
        application_author=author,
    )
    assert result.reviews == assembly.reviews
    assert result.applications[0].outcome == "accepted"
    assert result.applications[0].affected_review_ids == ["r1", "r2"]


def test_separating_email_content_does_not_mislabel_its_repeated_schedule():
    _, _, assembly, author = fixture()
    plan = GroupFeedbackResolution(
        group_id=assembly.groups[0].group_id,
        mode="SEPARATE_CONTENT",
        additional_members=["a:promotion"],
        rationale="Separate promotion; keep repeated event schedule.",
    )
    result = apply_group_feedback(
        assembly, feedback(assembly), [plan], notes_sha256="a" * 64, application_author=author
    )
    assert result.reviews == assembly.reviews
    assert result.applications[0].outcome == "content_separated"


def test_duplicate_notes_and_naive_review_times_are_invalid():
    _, _, assembly, _ = fixture()
    notes = feedback(assembly)
    with pytest.raises(ValueError, match="Duplicate"):
        LocalGroupReviewNotes.model_validate({**notes.model_dump(), "entries": notes.entries * 2})
    with pytest.raises(ValueError, match="timezone"):
        GroupReviewNote(group_id="g", status="looks_ok", text="", updated_at=datetime(2026, 11, 9))

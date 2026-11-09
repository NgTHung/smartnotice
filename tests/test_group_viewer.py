"""Check source integrity and safe data embedding in the local review page."""

import hashlib
import json
from datetime import UTC, datetime

import pytest
from smartnotice.labeling.event_groups import build_event_groups
from smartnotice.labeling.group_viewer import render_group_review
from smartnotice.schemas import (
    Annotation,
    AppliedGroupFeedback,
    Event,
    GroupFeedbackResult,
    GroupReviewNote,
    Notice,
    ReviewAuthor,
    Sentence,
    Span,
)


def sample(text="Tham gia hội thảo 𝒜 ngày 10/11/2026."):
    notice = Notice(
        doc_id="synthetic-1",
        source_type="email",
        source_ref="private/source.eml",
        raw_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
        sentences=[Sentence(sentence_id="s1", start=0, end=len(text), text=text)],
        group_id="synthetic",
        reference_date_origin="missing",
        synthetic=True,
        redaction_count=0,
    )
    annotation = Annotation(
        doc_id=notice.doc_id,
        annotator_id="ai_assistant",
        spans=[Span(span_id="a1", label="ACTION", start=0, end=7, text=text[:7])],
        events=[
            Event(event_id="e1", action_span_id="a1", arguments=[], evidence_sentence_ids=["s1"])
        ],
    )
    return notice, build_event_groups([notice], [annotation], [])


def test_embedded_source_cannot_close_script_or_inject_html():
    text = "Tham gia </script><img src=x onerror=alert(1)> & 𝒜\u2028"
    notice, assembly = sample(text)
    html = render_group_review(
        assembly, [notice], '<script type="application/json">__SMARTNOTICE_REVIEW_DATA__</script>'
    )
    assert html.count("</script>") == 1
    encoded = html.split(">", 1)[1].rsplit("</script>", 1)[0]
    payload = json.loads(encoded)
    assert payload["notices"][0]["text"] == text
    assert "private/source.eml" not in html
    assert payload["assembly"]["groups"][0]["review_required"]


def test_changed_source_snapshot_is_rejected_before_rendering():
    notice, assembly = sample()
    notice.text += " Nguồn đã đổi."
    with pytest.raises(ValueError, match="snapshot"):
        render_group_review(assembly, [notice], "__SMARTNOTICE_REVIEW_DATA__")


def test_group_membership_and_fact_references_must_be_traceable():
    notice, assembly = sample()
    assembly.groups[0].members.append("missing:a1")
    with pytest.raises(ValueError, match="membership"):
        render_group_review(assembly, [notice], "__SMARTNOTICE_REVIEW_DATA__")


def test_template_has_exactly_one_data_placeholder():
    notice, assembly = sample()
    with pytest.raises(ValueError, match="placeholder"):
        render_group_review(assembly, [notice], "No data placeholder")


def test_applied_user_note_is_bound_to_the_resulting_partition():
    notice, assembly = sample()
    timestamp = datetime(2026, 11, 9, tzinfo=UTC)
    application = AppliedGroupFeedback(
        note=GroupReviewNote(
            group_id=assembly.groups[0].group_id,
            status="looks_ok",
            text="Đã đối chiếu nguồn.",
            updated_at=timestamp,
        ),
        outcome="accepted",
        partitions=[assembly.groups[0].members],
        rationale="Group accepted.",
        affected_review_ids=[],
        application_author=ReviewAuthor(
            reviewer_id="ai_assistant", reviewer_kind="ai_assistant", reviewed_at=timestamp
        ),
    )
    feedback = GroupFeedbackResult(
        notes_sha256="a" * 64,
        source_assembly_fingerprint="b" * 64,
        reviews=[],
        applications=[application],
        unreviewed_group_ids=[],
    )
    payload = json.loads(
        render_group_review(assembly, [notice], "__SMARTNOTICE_REVIEW_DATA__", feedback=feedback)
    )
    assert payload["applied_feedback"][0]["text"] == application.note.text
    newer = feedback.model_copy(deep=True)
    newer.applications[0].note.text = "Accepted by explicit user instruction."
    combined = json.loads(
        render_group_review(
            assembly, [notice], "__SMARTNOTICE_REVIEW_DATA__", feedback=[feedback, newer]
        )
    )
    assert len(combined["applied_feedback"]) == 1
    assert combined["applied_feedback"][0]["text"] == newer.applications[0].note.text
    assert feedback.applications[0].note.text == application.note.text
    application.partitions = [["missing:a1"]]
    with pytest.raises(ValueError, match="partition"):
        render_group_review(
            assembly, [notice], "__SMARTNOTICE_REVIEW_DATA__", feedback=[feedback, newer]
        )

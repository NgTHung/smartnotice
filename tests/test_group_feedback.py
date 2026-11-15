"""Check explicit application of user notes, not free-text label guessing."""

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

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
    GroupDisplayLabel,
    GroupFeedbackPlan,
    GroupFeedbackResolution,
    GroupingReview,
    GroupMergeResolution,
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


def merge_fixture():
    notices, annotations, initial, author = fixture()
    reviews = [r.model_copy(deep=True) for r in initial.reviews]
    for r in reviews:
        r.decision, r.task_relation = "UNCLEAR", "UNRESOLVED"
    assembly = build_event_groups(notices, annotations, reviews)
    group_ids = {ref: g.group_id for g in assembly.groups for ref in g.members}
    notes = LocalGroupReviewNotes(
        kind="local_group_review_notes",
        draft=True,
        assembly_fingerprint=assembly_fingerprint(assembly),
        exported_at=datetime(2026, 11, 9, 2, tzinfo=UTC),
        entries=[
            GroupReviewNote(
                group_id=group_ids[ref],
                status=status,
                text="Original user note.",
                updated_at=datetime(2026, 11, 9, 1, tzinfo=UTC),
            )
            for ref, status in [("a:a1", "looks_ok"), ("b:a1", "needs_check")]
        ],
    )
    merge = GroupMergeResolution(
        group_ids=[group_ids["a:a1"], group_ids["b:a1"]],
        rationale="Explicit user clarification: same event, separate steps.",
    )
    return notices, annotations, assembly, author, notes, merge


def test_explicit_merge_replaces_crossing_abstention_and_preserves_steps_and_notes():
    notices, annotations, assembly, author, notes, merge = merge_fixture()
    before = assembly.model_dump()
    result = apply_group_feedback(
        assembly, notes, [], notes_sha256="a" * 64, application_author=author, merges=[merge]
    )
    updated = build_event_groups(notices, annotations, result.reviews)
    combined = next(g for g in updated.groups if "a:a1" in g.members)
    assert combined.members == ["a:a1", "b:a1"]
    assert len(combined.tasks) == 2 and len(updated.groups) == 2
    assert not updated.conflicts
    assert assembly.model_dump() == before
    assert {a.outcome for a in result.applications} == {"merged"}
    assert {a.note.status for a in result.applications} == {"looks_ok", "needs_check"}
    assert all(a.partitions == [combined.members] for a in result.applications)
    assert all(a.application_author.reviewer_kind == "ai_assistant" for a in result.applications)
    assert len(result.unreviewed_group_ids) == 1


def test_explicit_merge_can_add_a_pair_omitted_by_candidate_retrieval():
    notices, annotations, assembly, author, notes, merge = merge_fixture()
    third = next(g for g in assembly.groups if "c:a1" in g.members)
    first = next(g for g in assembly.groups if "a:a1" in g.members)
    notes.entries[0].group_id = third.group_id
    merge.group_ids = [third.group_id if gid == first.group_id else gid for gid in merge.group_ids]
    result = apply_group_feedback(
        assembly, notes, [], notes_sha256="a" * 64, application_author=author, merges=[merge]
    )
    updated = build_event_groups(notices, annotations, result.reviews)
    combined = next(g for g in updated.groups if "b:a1" in g.members)
    assert combined.members == ["b:a1", "c:a1"] and len(combined.tasks) == 2
    assert len(result.reviews) == len(assembly.reviews) + 1
    assert not updated.conflicts


@pytest.mark.parametrize("case", ["unknown", "duplicate", "overlap", "unread", "split"])
def test_unsupported_merge_plans_are_rejected_without_changing_source(case):
    _, _, assembly, author, notes, merge = merge_fixture()
    before = assembly.model_dump()
    merges, plans = [merge], []
    if case == "unknown":
        merge.group_ids[1] = "unknown"
    elif case == "duplicate":
        merge.group_ids[1] = merge.group_ids[0]
    elif case == "overlap":
        merges.append(merge)
    elif case == "unread":
        notes.entries[0].status = "not_seen"
    else:
        plans.append(
            GroupFeedbackResolution(
                group_id=merge.group_ids[0], mode="PARTITION", partitions=[], rationale="Split too."
            )
        )
    with pytest.raises(ValueError):
        apply_group_feedback(
            assembly, notes, plans, notes_sha256="a" * 64, application_author=author, merges=merges
        )
    assert assembly.model_dump() == before


def test_review_runner_merges_steps_retains_original_notes_and_labels_without_new_tasks(tmp_path):
    notices, annotations, assembly, author, notes, merge = merge_fixture()
    third = next(g for g in assembly.groups if "c:a1" in g.members)
    title = notices[2].text
    plan = GroupFeedbackPlan(
        merges=[merge],
        display_labels=[
            GroupDisplayLabel(
                group_id=third.group_id,
                title=title,
                author=author,
                evidence=[
                    EvidenceQuote(doc_id="c", sentence_id="s1", start=0, end=len(title), text=title)
                ],
            )
        ],
    )
    inputs = {
        "assembly": assembly.model_dump_json(),
        "notes": notes.model_dump_json(),
        "plan": plan.model_dump_json(),
        "notices": "\n".join(n.model_dump_json() for n in notices),
        "annotations": "\n".join(a.model_dump_json() for a in annotations),
    }
    paths = {}
    for name, value in inputs.items():
        path = tmp_path / (name + ".json")
        path.write_text(value, encoding="utf-8")
        paths[name] = path
    original = {name: p.read_bytes() for name, p in paths.items()}
    root = Path(__file__).resolve().parents[1]
    private = root / "reports/generated"
    private.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="test-review-", dir=private) as local:
        output = Path(local) / "result"
        args = [sys.executable, "tools/apply_group_review.py"]
        for name, path in paths.items():
            args += ["--" + name, str(path)]
        args += ["--output-dir", str(output), "--applied-at", author.reviewed_at.isoformat()]
        completed = subprocess.run(args, cwd=root, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr
        updated = json.loads((output / "assembly.json").read_text(encoding="utf-8"))
        assert len(updated["groups"]) == 2
        assert sum(len(g["tasks"]) for g in updated["groups"]) == 3
        assert (output / "source_notes.json").read_bytes() == original["notes"]
        assert all(p.read_bytes() == original[name] for name, p in paths.items())
        html = (output / "index.html").read_text(encoding="utf-8")
        payload = json.loads(
            re.search(
                r'<script type="application/json" id="review-data">(.*?)</script>', html, re.S
            )[1]
        )
        applied = payload["applied_feedback"][0]
        assert len(applied["source_notes"]) == 2
        assert {n["status"] for n in applied["source_notes"]} == {"looks_ok", "needs_check"}
        assert applied["status"] == "needs_check" and applied["outcome"] == "merged"
        assert payload["display_labels"]["labels"][0]["title"] == title
        hashes = json.loads((output / "checksums.json").read_text(encoding="utf-8"))
        assert all(
            hashlib.sha256((output / name).read_bytes()).hexdigest() == sha
            for name, sha in hashes.items()
        )
        notes.assembly_fingerprint = "f" * 64
        paths["notes"].write_text(notes.model_dump_json(), encoding="utf-8")
        fresh = Path(local) / "stale"
        args[args.index("--output-dir") + 1] = str(fresh)
        stale = subprocess.run(args, cwd=root, capture_output=True, text=True)
        assert stale.returncode != 0 and "fingerprint" in stale.stderr
        assert not fresh.exists()

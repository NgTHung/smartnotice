"""Exercise checkpoint-assisted grouping with synthetic, source-backed notices."""

import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from smartnotice.labeling.automatic_grouping import propose_event_groups
from smartnotice.labeling.grouping_model import MODEL_FEATURES
from smartnotice.schemas import (
    Annotation,
    Argument,
    Event,
    GroupingLinearModel,
    Notice,
    Sentence,
    Span,
)

STAMP = datetime(2026, 11, 18, tzinfo=UTC)


def source(
    doc: str,
    action: str,
    context: str,
    *,
    received: date | None = None,
    deadline: str | None = None,
) -> tuple[Notice, Annotation]:
    """Return a synthetic email notice and an annotation of its first sentence."""
    text = f"{action}\n{context}"
    sentences = [
        Sentence(sentence_id="action", start=0, end=len(action), text=action),
        Sentence(sentence_id="context", start=len(action) + 1, end=len(text), text=context),
    ]
    spans = [Span(span_id="a1", label="ACTION", start=0, end=len(action), text=action)]
    argument_ids = []
    evidence_ids = ["action", "context"]
    if deadline is not None:
        start = len(text) + 1
        text += "\n" + deadline
        sentences.append(Sentence(sentence_id="due", start=start, end=len(text), text=deadline))
        spans.append(Span(span_id="d1", label="TIME", start=start, end=len(text), text=deadline))
        argument_ids.append(Argument(span_id="d1", role="DEADLINE"))
        evidence_ids = ["action", "due"]
    notice = Notice(
        doc_id=doc,
        raw_sha256=hashlib.sha256(text.encode()).hexdigest(),
        source_type="email",
        source_ref="synthetic",
        text=text,
        sentences=sentences,
        reference_date=received,
        reference_date_origin="email_header" if received else "missing",
        group_id=doc,
        synthetic=True,
        redaction_count=0,
    )
    annotation = Annotation(
        doc_id=doc,
        annotator_id="synthetic_fixture",
        spans=spans,
        events=[
            Event(
                event_id="e1",
                action_span_id="a1",
                arguments=argument_ids,
                evidence_sentence_ids=evidence_ids,
            )
        ],
    )
    return notice, annotation


def checkpoint(intercept: float) -> GroupingLinearModel:
    """Return a synthetic checkpoint whose constant score is controlled by its intercept."""
    features = list(MODEL_FEATURES["grouping-logistic-v2"])
    zeros = [0.0] * len(features)
    return GroupingLinearModel(
        kind="grouping-logistic-v2",
        features=features,
        mean=zeros,
        scale=[1.0] * len(features),
        weights=zeros,
        intercept=intercept,
    )


def test_checkpoint_contributes_event_identity_but_requires_source_anchor(tmp_path):
    items = [
        source(
            doc,
            "Đăng ký dự án thiết kế tàu điện",
            "Đội thi thiết kế tàu điện điền biểu mẫu https://forms.gle/synthetic",
        )
        for doc in ("email-a", "email-b")
    ]
    notices, annotations = (list(records) for records in zip(*items, strict=True))
    base = propose_event_groups(notices, annotations, generated_at=STAMP)
    low = propose_event_groups(notices, annotations, generated_at=STAMP, checkpoint=checkpoint(-10))
    assert base.proposals[0].pair.decision == low.proposals[0].pair.decision == "UNCLEAR"

    model_path, input_path, annotation_path = [
        tmp_path / name for name in ("model.json", "notices.jsonl", "annotations.jsonl")
    ]
    model_path.write_text(checkpoint(10).model_dump_json(), encoding="utf-8")
    for path, records in [(input_path, notices), (annotation_path, annotations)]:
        path.write_text("\n".join(record.model_dump_json() for record in records), encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    private = root / "reports/generated"
    private.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="test-grouping-checkpoint-", dir=private) as local:
        output = Path(local) / "result"
        completed = subprocess.run(
            [
                sys.executable,
                "tools/run_automatic_grouping.py",
                "--notices",
                str(input_path),
                "--annotations",
                str(annotation_path),
                "--checkpoint",
                str(model_path),
                "--generated-at",
                STAMP.isoformat(),
                "--output-dir",
                str(output),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        assert completed.returncode == 0
        result = json.loads((output / "result.json").read_text(encoding="utf-8"))
        assert result["proposals"][0]["pair"]["decision"] == "SAME_EVENT"
        assert result["proposals"][0]["origin"] == "model_assisted_rule_proposal"
        assert len(result["assembly"]["groups"]) == 1
        assert result["assembly"]["groups"][0]["review_required"]
        assert result["assembly"]["groups"][0]["privacy_review_required"]
        run = json.loads((output / "run.json").read_text(encoding="utf-8"))
        assert (
            run["source_sha256"][model_path.as_posix()]
            == hashlib.sha256(model_path.read_bytes()).hexdigest()
        )

    other_items = [
        source(doc, "Đăng ký dự án thiết kế tàu điện", "Đội thi thiết kế tàu điện điền biểu mẫu.")
        for doc in ("email-a", "email-b")
    ]
    other_notices, other_annotations = (list(records) for records in zip(*other_items, strict=True))
    unanchored = propose_event_groups(
        other_notices, other_annotations, generated_at=STAMP, checkpoint=checkpoint(10)
    )
    assert unanchored.proposals[0].pair.decision == "UNCLEAR"


def test_checkpoint_preserves_extension_direction_and_active_deadline():
    action = "Đăng ký dự án thiết kế tàu điện"
    old, old_label = source(
        "z",
        action,
        "Cuộc thi “Thiết kế tàu điện sinh viên”.",
        received=date(2026, 11, 1),
        deadline="10/11/2026",
    )
    new, new_label = source(
        "a",
        action,
        "Cuộc thi “Thiết kế tàu điện sinh viên”. Ban tổ chức quyết định gia hạn.",
        received=date(2026, 11, 9),
        deadline="12/11/2026",
    )
    base = propose_event_groups([old, new], [old_label, new_label], generated_at=STAMP)
    assert base.proposals[0].pair.decision == "UNCLEAR"
    with_model = propose_event_groups(
        [old, new], [old_label, new_label], generated_at=STAMP, checkpoint=checkpoint(10)
    )
    review = with_model.proposals[0].pair
    assert review.decision == "UPDATE_OF" and review.notice_relation == "UPDATE"
    assert review.left.event_ref == "a:a1" and review.right.event_ref == "z:a1"
    assert [change.field for change in review.changes] == ["DEADLINE"]
    [change] = review.changes
    assert (change.old.text, change.new.text) == ("10/11/2026", "12/11/2026")
    assert {q.sentence_id for q in review.evidence} == {"action", "context", "due"}
    [group] = with_model.assembly.groups
    [task] = group.tasks
    assert {
        fact.quote.text for fact in task.facts if fact.fact_id in task.active_values["DEADLINE"]
    } == {"12/11/2026"}


def test_reply_candidate_requires_a_verified_source_and_cannot_merge_on_headers(tmp_path):
    original, original_label = source("a", "Đăng ký tàu điện", "Xưởng thiết kế.")
    reply, reply_label = source("b", "Hoàn thành khảo sát", "Phòng thí nghiệm.")
    first = (
        b"Date: Mon, 16 Nov 2026 12:00:00 +0700\r\n"
        b"From: fixture@example.edu\r\nMessage-ID: <a@example.edu>\r\n\r\n"
    )
    second = (
        b"Date: Mon, 16 Nov 2026 12:02:00 +0700\r\n"
        b"From: fixture@example.edu\r\nMessage-ID: <b@example.edu>\r\n"
        b"In-Reply-To: <a@example.edu>\r\n\r\n"
    )
    notices = []
    for notice, raw in [(original, first), (reply, second)]:
        digest = hashlib.sha256(raw).hexdigest()
        (tmp_path / f"{digest}.eml").write_bytes(raw)
        notices.append(notice.model_copy(update={"raw_sha256": digest}))

    labels = [original_label, reply_label]
    model = checkpoint(10)
    no_headers = propose_event_groups(notices, labels, generated_at=STAMP, checkpoint=model)
    assert not no_headers.proposals
    with_headers = propose_event_groups(
        notices, labels, generated_at=STAMP, checkpoint=model, raw_email_dir=tmp_path
    )
    [proposal] = with_headers.proposals
    assert proposal.candidate_reasons == ["verified_direct_reply"]
    assert proposal.pair.decision == "UNCLEAR"
    aligned = propose_event_groups(
        notices,
        labels,
        generated_at=STAMP,
        checkpoint=model,
        raw_email_dir=tmp_path,
        align_followup=True,
    )
    assert aligned.proposals[0].pair.decision == "UNCLEAR"
    (tmp_path / f"{notices[0].raw_sha256}.eml").write_bytes(b"unexpected fixture bytes")
    with pytest.raises(ValueError, match="source hash differs"):
        propose_event_groups(
            notices, labels, generated_at=STAMP, checkpoint=model, raw_email_dir=tmp_path
        )


def _verified_reply_sources(folder: Path, parent: Notice, reply: Notice) -> list[Notice]:
    notices = []
    for notice, letter_id, parent_line in (
        (parent, "design-a", ""),
        (reply, "design-b", "In-Reply-To: <design-a@example.edu>\r\n"),
    ):
        raw = f"Message-ID: <{letter_id}@example.edu>\r\n{parent_line}\r\n".encode()
        digest = hashlib.sha256(raw).hexdigest()
        (folder / f"{digest}.eml").write_bytes(raw)
        notices.append(notice.model_copy(update={"raw_sha256": digest}))
    return notices


def test_align_verified_reply_with_one_source_item(tmp_path):
    parent, parent_label = source(
        "parent",
        "Nộp bản vẽ thiết kế cầu gỗ",
        "Cuộc thi “Thiết kế cầu gỗ chịu tải”.",
    )
    reply, reply_label = source(
        "reply",
        "Hỏi về cách gửi bản vẽ",
        "Cuộc thi “Thiết kế cầu gỗ chịu tải”.",
    )
    notices = _verified_reply_sources(tmp_path, parent, reply)
    labels = [parent_label, reply_label]
    options = {"generated_at": STAMP, "checkpoint": checkpoint(-10), "raw_email_dir": tmp_path}
    baseline = propose_event_groups(notices, labels, **options)
    assert baseline.proposals[0].pair.decision == "UNCLEAR"
    aligned = propose_event_groups(notices, labels, align_followup=True, **options)

    [proposal] = aligned.proposals
    assert aligned.rule_version == "automatic-event-grouping-model-assisted-alignment-v1"
    assert proposal.pair.decision == "SAME_EVENT"
    assert {"source_aligned_followup", "direct_reply_shared_phrase"} <= set(proposal.reasons)
    assert proposal.pair.task_relation == "UNRESOLVED"
    assert not proposal.pair.changes
    [group] = aligned.assembly.groups
    assert len(group.tasks) == 2
    assert group.review_required and group.privacy_review_required
    original = {notice.doc_id: notice.text for notice in notices}
    assert all(original[q.doc_id][q.start : q.end] == q.text for q in proposal.pair.evidence)
    assert {q.sentence_id for q in proposal.pair.evidence} == {"action", "context"}


def test_direct_reply_with_two_compatible_parent_items_stays_separate(tmp_path):
    parent, parent_label = source(
        "parent",
        "Đăng ký bản vẽ thiết kế cầu gỗ chịu tải.",
        "Chuẩn bị bản vẽ thiết kế cầu gỗ chịu tải.",
    )
    second = "Nộp bản vẽ thiết kế cầu gỗ chịu tải."
    start = len(parent.text) + 1
    end = start + len(second)
    parent = parent.model_copy(
        update={
            "text": parent.text + "\n" + second,
            "sentences": [
                *parent.sentences,
                Sentence(sentence_id="second", start=start, end=end, text=second),
            ],
        }
    )
    parent_label.spans.append(Span(span_id="a2", label="ACTION", start=start, end=end, text=second))
    parent_label.events.append(
        Event(event_id="e2", action_span_id="a2", arguments=[], evidence_sentence_ids=["second"])
    )
    reply, reply_label = source(
        "reply",
        "Liên hệ về bản vẽ thiết kế cầu gỗ chịu tải.",
        "Nhắc lại thủ tục bản vẽ thiết kế cầu gỗ chịu tải.",
    )
    notices = _verified_reply_sources(tmp_path, parent, reply)
    labels = [parent_label, reply_label]
    options = {"generated_at": STAMP, "checkpoint": checkpoint(-10), "raw_email_dir": tmp_path}
    baseline = propose_event_groups(notices, labels, **options)
    assert any(p.pair.decision == "SAME_EVENT" for p in baseline.proposals)

    aligned = propose_event_groups(notices, labels, align_followup=True, **options)
    replies = [p for p in aligned.proposals if "verified_direct_reply" in p.candidate_reasons]
    assert len(replies) == 2
    assert all(
        p.pair.decision == "UNCLEAR" and p.reasons == ["ambiguous_followup_target"] for p in replies
    )
    assert len(aligned.assembly.groups) == 3


def test_alignment_mode_requires_checkpoint_and_existing_email_directory(tmp_path):
    with pytest.raises(ValueError, match="Alignment requires"):
        propose_event_groups([], [], generated_at=STAMP, align_followup=True)
    with pytest.raises(ValueError, match="Alignment requires"):
        propose_event_groups(
            [],
            [],
            generated_at=STAMP,
            align_followup=True,
            checkpoint=checkpoint(0),
            raw_email_dir=tmp_path / "missing",
        )


def test_checkpoint_keeps_distinct_academic_terms_separate(tmp_path):
    items = [
        source(
            doc,
            "Tham gia lịch thi điều khiển tự động",
            f"Lịch thi học kỳ {term} năm học 2025–2026.",
            deadline="10/11/2026",
        )
        for doc, term in (("a", "I"), ("b", "II"))
    ]
    notices, annotations = (list(records) for records in zip(*items, strict=True))
    baseline = propose_event_groups(notices, annotations, generated_at=STAMP)
    assert baseline.proposals[0].pair.decision == "SAME_EVENT"
    assisted = propose_event_groups(
        notices, annotations, generated_at=STAMP, checkpoint=checkpoint(10)
    )
    assert assisted.proposals[0].pair.decision == "DIFFERENT_EVENT"
    assert assisted.proposals[0].reasons == ["separate_academic_scope"]
    assert len(assisted.assembly.groups) == 2

    aligned = propose_event_groups(
        notices,
        annotations,
        generated_at=STAMP,
        checkpoint=checkpoint(10),
        raw_email_dir=tmp_path,
        align_followup=True,
    )
    assert aligned.proposals[0].pair.decision == "DIFFERENT_EVENT"
    assert len(aligned.assembly.groups) == 2


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        (
            "Nhà trường đã mua bảo hiểm y tế cho sinh viên.",
            "Nhà trường đã thực hiện gia hạn bảo hiểm y tế năm 2026.",
            "DIFFERENT_EVENT",
        ),
        (
            "Nhà trường đã mua bảo hiểm y tế cho sinh viên.",
            "Nhà trường hướng dẫn mua hoặc gia hạn bảo hiểm y tế.",
            "UNCLEAR",
        ),
        (
            "Nhà trường đã mua bảo hiểm y tế cho sinh viên.",
            "Nhà trường chưa thực hiện gia hạn bảo hiểm y tế.",
            "UNCLEAR",
        ),
        (
            "Nhà trường đã mua bảo hiểm y tế cho sinh viên.",
            "Nhà trường đã mua bảo hiểm y tế và gia hạn thẻ theo danh sách.",
            "UNCLEAR",
        ),
    ],
)
def test_checkpoint_distinguishes_completed_insurance_operations(first, second, expected):
    action = "Cài ứng dụng để tra cứu thông tin bảo hiểm y tế."
    items = [source(doc, action, lead) for doc, lead in (("a", first), ("b", second))]
    notices, annotations = (list(records) for records in zip(*items, strict=True))
    baseline = propose_event_groups(notices, annotations, generated_at=STAMP)
    assert baseline.proposals[0].pair.decision == "UNCLEAR"

    assisted = propose_event_groups(
        notices, annotations, generated_at=STAMP, checkpoint=checkpoint(0)
    )
    [proposal] = assisted.proposals
    assert proposal.pair.decision == expected
    if expected == "DIFFERENT_EVENT":
        assert proposal.reasons == ["different_insurance_operations"]
        assert {quote.text for quote in proposal.pair.evidence} >= {first, second}


def test_insurance_operations_in_a_direct_reply_go_to_review(tmp_path):
    action = "Cài ứng dụng để tra cứu thông tin bảo hiểm y tế."
    old, old_label = source("a", action, "Nhà trường đã mua bảo hiểm y tế cho sinh viên.")
    new, new_label = source("b", action, "Nhà trường đã thực hiện gia hạn bảo hiểm y tế.")
    first = (
        b"Date: Mon, 16 Nov 2026 12:00:00 +0700\r\nMessage-ID: <insurance-a@example.edu>\r\n\r\n"
    )
    second = (
        b"Date: Mon, 16 Nov 2026 12:02:00 +0700\r\n"
        b"Message-ID: <insurance-b@example.edu>\r\n"
        b"In-Reply-To: <insurance-a@example.edu>\r\n\r\n"
    )
    notices = []
    for notice, raw in ((old, first), (new, second)):
        digest = hashlib.sha256(raw).hexdigest()
        (tmp_path / f"{digest}.eml").write_bytes(raw)
        notices.append(notice.model_copy(update={"raw_sha256": digest}))

    assisted = propose_event_groups(
        notices,
        [old_label, new_label],
        generated_at=STAMP,
        checkpoint=checkpoint(0),
        raw_email_dir=tmp_path,
    )
    [proposal] = assisted.proposals
    assert proposal.pair.decision == "UNCLEAR"
    assert proposal.reasons == ["referenced_insurance_operations"]


def test_checkpoint_sends_reminder_with_conflicting_deadline_to_review():
    old, old_label = source(
        "z",
        "Đăng ký dự án thiết kế tàu điện",
        "Cuộc thi “Thiết kế tàu điện sinh viên”.",
        received=date(2026, 11, 1),
        deadline="10/11/2026",
    )
    reminder, reminder_label = source(
        "a",
        "Đăng ký dự án thiết kế tàu điện",
        "Cuộc thi “Thiết kế tàu điện sinh viên”. Nhắc lại thời hạn đăng ký.",
        received=date(2026, 11, 9),
        deadline="12/11/2026",
    )
    result = propose_event_groups(
        [old, reminder],
        [old_label, reminder_label],
        generated_at=STAMP,
        checkpoint=checkpoint(10),
    )
    [proposal] = result.proposals
    assert proposal.pair.decision == "UNCLEAR"
    assert proposal.reasons == ["conflicting_deadline_without_extension"]
    assert not result.assembly.updates

"""Verify reranked targets and directed updates through normal group assembly."""

import hashlib
from pathlib import Path

import pytest
from smartnotice.labeling.automatic_grouping import propose_event_groups
from smartnotice.labeling.grouping_rerank import FEATURES, FollowupRerankModel
from smartnotice.schemas import Argument, Notice, Span
from test_automatic_checkpoint import STAMP, checkpoint, source


def _reply_sources(path: Path, original: Notice, reply: Notice) -> list[Notice]:
    raw = (
        b"Date: Thu, 19 Nov 2026 09:00:00 +0700\r\nMessage-ID: <source@example.edu>\r\n\r\n",
        b"Date: Thu, 19 Nov 2026 10:00:00 +0700\r\n"
        b"Message-ID: <reply@example.edu>\r\n"
        b"In-Reply-To: <source@example.edu>\r\n\r\n",
    )
    notices = []
    for message, notice in zip(raw, (original, reply), strict=True):
        digest = hashlib.sha256(message).hexdigest()
        (path / f"{digest}.eml").write_bytes(message)
        notices.append(notice.model_copy(update={"raw_sha256": digest}))
    return notices


def test_unique_reranked_item_reaches_group_assembly(tmp_path):
    old, old_label = source(
        "a", "Nộp hồ sơ gia nhập câu lạc bộ thiên văn.", "Ban tổ chức nhận bản giấy."
    )
    new, new_label = source(
        "z", "Gửi giấy tờ đăng ký CLB thiên văn.", "Người tham gia điền thông tin."
    )
    notices = _reply_sources(tmp_path, old, new)
    common = {
        "generated_at": STAMP,
        "checkpoint": checkpoint(-10),
        "raw_email_dir": tmp_path,
        "align_followup": True,
    }
    a = propose_event_groups(notices, [old_label, new_label], **common)
    assert a.proposals[0].pair.decision == "UNCLEAR"
    ranker = FollowupRerankModel(
        features=list(FEATURES),
        mean=[0.0] * len(FEATURES),
        scale=[1.0] * len(FEATURES),
        weights=[0.0] * len(FEATURES),
        intercept=4.0,
    )
    d = propose_event_groups(notices, [old_label, new_label], followup_reranker=ranker, **common)
    assert d.proposals[0].pair.decision == "SAME_EVENT"
    assert "reranked_reply_match" in d.proposals[0].reasons
    assert len(d.assembly.groups) == 1
    assert len(d.assembly.groups[0].tasks) == 2


@pytest.mark.parametrize("conditional", [False, True])
def test_verified_status_is_applied_in_reply_direction(tmp_path, conditional):
    condition = "khi dùng thẻ khách"
    action = f"Xử lý thông báo dịch vụ {condition}." if conditional else "Xử lý thông báo dịch vụ."
    old, old_label = source("z", action, "Mã sự kiện: WX-140. Cổng thư viện đang gặp lỗi.")
    if conditional:
        offset = action.index(condition)
        old_label.spans.append(
            Span(
                span_id="condition",
                label="CONDITION",
                start=offset,
                end=offset + len(condition),
                text=condition,
            )
        )
        old_label.events[0].arguments.append(Argument(span_id="condition"))
    new, new_label = source(
        "a", "Theo dõi thông báo dịch vụ.", "Mã sự kiện: WX-140. Cổng thư viện đã hoạt động lại."
    )
    notices = _reply_sources(tmp_path, old, new)
    common = {
        "generated_at": STAMP,
        "checkpoint": checkpoint(-10),
        "raw_email_dir": tmp_path,
        "align_followup": True,
    }
    a = propose_event_groups(notices, [old_label, new_label], **common)
    assert a.proposals[0].pair.decision == "SAME_EVENT"
    b = propose_event_groups(
        notices, [old_label, new_label], **common, resolve_followup_updates=True
    )
    review = b.proposals[0].pair
    if conditional:
        assert review.decision == "SAME_EVENT"
        assert not b.assembly.updates
        return
    assert review.decision == "UPDATE_OF"
    assert review.left.event_ref == "a:a1"
    assert review.right.event_ref == "z:a1"
    assert review.changes[0].field == "STATUS"
    assert review.changes[0].old.text == "Cổng thư viện đang gặp lỗi"
    assert review.changes[0].new.text == "Cổng thư viện đã hoạt động lại"
    [task] = b.assembly.groups[0].tasks
    active = set(task.active_values["STATUS"])
    assert [f.quote.text for f in task.facts if f.fact_id in active] == [
        "Cổng thư viện đã hoạt động lại"
    ]


def test_verified_deadline_supersedes_the_old_value_for_the_linked_task(tmp_path):
    action = "Nộp bài luận tuyển nhóm mô hình."
    old, old_label = source("a", action, "Mã sự kiện: MD-010.", deadline="18/11/2026")
    new, new_label = source(
        "z",
        action,
        "Mã sự kiện: MD-010. Ban tổ chức lùi thời hạn nộp bài.",
        deadline="20/11/2026",
    )
    for label in (old_label, new_label):
        label.events[0].evidence_sentence_ids.append("context")
    notices = _reply_sources(tmp_path, old, new)
    result = propose_event_groups(
        notices,
        [old_label, new_label],
        generated_at=STAMP,
        checkpoint=checkpoint(-10),
        raw_email_dir=tmp_path,
        align_followup=True,
        resolve_followup_updates=True,
    )
    [review] = result.assembly.reviews
    assert review.decision == "UPDATE_OF"
    assert review.left.event_ref == "z:a1"
    [update] = result.assembly.updates
    assert update.applied and update.field == "DEADLINE"
    [task] = result.assembly.groups[0].tasks
    facts = {fact.quote.text: fact for fact in task.facts if fact.field == "DEADLINE"}
    assert task.active_values["DEADLINE"] == [facts["20/11/2026"].fact_id]
    assert facts["18/11/2026"].superseded_by == [facts["20/11/2026"].fact_id]

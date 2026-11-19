"""Exercise source-backed follow-up changes with synthetic notices."""

from typing import Literal

import pytest
from smartnotice.labeling.event_groups import build_event_groups
from smartnotice.labeling.grouping_followup import RoutingComparison
from smartnotice.labeling.grouping_updates import resolve_followup_update
from smartnotice.schemas import GroupingModelMention, GroupingReview, ReviewAuthor
from test_automatic_checkpoint import STAMP, source

_DIRECT = RoutingComparison(1, 60, True, True)
_FAULT = "Phòng kỹ thuật xác nhận cổng đăng ký đề tài đang gặp sự cố."
_RECOVERY = "Phòng kỹ thuật xác nhận cổng đăng ký đề tài đã hoạt động trở lại."


def _case(
    old_text: str,
    new_text: str,
    old_due: str | None = None,
    new_due: str | None = None,
    old_role: Literal["DEADLINE", "EVENT_TIME"] = "DEADLINE",
):
    old = source("previous", "Nộp hồ sơ ứng tuyển", old_text, deadline=old_due)
    new = source("newer", "Nộp hồ sơ ứng tuyển", new_text, deadline=new_due)
    notices, annotations = (list(items) for items in zip(old, new, strict=True))
    for annotation in annotations:
        event = annotation.events[0]
        if "context" not in event.evidence_sentence_ids:
            event.evidence_sentence_ids.append("context")
    if old_due:
        annotations[0].events[0].arguments[0].role = old_role
    assembly = build_event_groups(notices, annotations, [])
    mentions = {
        mention.version.event_ref: GroupingModelMention(
            mention_id=mention.version.event_ref,
            doc_id=mention.version.event_ref.split(":")[0],
            **mention.model_dump(exclude={"annotation_origin"}),
        )
        for mention in assembly.mentions
    }
    return tuple(notices), annotations, mentions["previous:a1"], mentions["newer:a1"]


def test_status_restoration_keeps_both_verbatim_states_and_supports_assembly():
    notices, annotations, previous, newer = _case(_FAULT, _RECOVERY)
    update = resolve_followup_update(
        newer,
        previous,
        notices[::-1],
        RoutingComparison(0, 60, True, True),
        target_confirmed=True,
        task_relation="UNRESOLVED",
    )
    assert update is not None
    assert update.update_side == 0
    assert update.reason == "verified_status_restoration"
    change = update.change
    assert change.field == "STATUS"
    assert change.old is not None
    assert change.old.text == "cổng đăng ký đề tài đang gặp sự cố"
    assert change.new.text == "cổng đăng ký đề tài đã hoạt động trở lại"
    for notice, quote in zip(notices, (change.old, change.new), strict=True):
        assert notice.doc_id == quote.doc_id
        assert notice.text[quote.start : quote.end] == quote.text
    assembly = build_event_groups(
        list(notices),
        annotations,
        [
            GroupingReview(
                review_id="synthetic-status",
                left=newer.version,
                right=previous.version,
                decision="UPDATE_OF",
                notice_relation="UPDATE",
                task_relation="SAME_TASK",
                rationale="Both notices confirm a status for the same named service.",
                author=ReviewAuthor(
                    reviewer_id="synthetic_test",
                    reviewer_kind="ai_assistant",
                    reviewed_at=STAMP,
                ),
                evidence=[change.old, change.new],
                changes=[change],
            )
        ],
    )
    assert assembly.updates[0].applied
    task = assembly.groups[0].tasks[0]
    active = task.active_values["STATUS"][0]
    assert next(fact for fact in task.facts if fact.fact_id == active).quote == change.new
    assert any(fact.quote == change.old and fact.superseded_by == [active] for fact in task.facts)


@pytest.mark.parametrize(
    "reply",
    [
        "Cổng đăng ký đề tài dự kiến sẽ hoạt động trở lại.",
        "Nếu cổng đăng ký đề tài đã hoạt động trở lại, vui lòng thử đăng nhập.",
        "Cổng đăng ký đề tài chưa được khôi phục.",
        "Cổng học phí đã hoạt động trở lại.",
        "Cổng đăng ký đề tài và hệ thống học phí đã hoạt động trở lại.",
        "Cổng đăng ký đề tài đã hoạt động trở lại nhưng vẫn chưa ổn định.",
        "Cổng đăng ký đề tài đã khôi phục dữ liệu sao lưu.",
        "Cổng đăng ký đề tài bị lỗi rồi lại bị gián đoạn.",
    ],
)
def test_status_requires_a_confirmed_restoration_of_the_same_service(reply):
    notices, _, previous, newer = _case(_FAULT, reply)
    assert (
        resolve_followup_update(
            previous, newer, notices, _DIRECT, target_confirmed=True, task_relation="UNRESOLVED"
        )
        is None
    )


@pytest.mark.parametrize(
    ("confirmed", "routing", "relation"),
    [
        (False, _DIRECT, "SAME_TASK"),
        (True, RoutingComparison(1, 60, True, False), "SAME_TASK"),
        (True, RoutingComparison(None, None, True, True), "SAME_TASK"),
        (True, _DIRECT, "DIFFERENT_TASK"),
        (True, _DIRECT, "CONDITIONAL_TASK"),
    ],
)
def test_status_requires_a_verified_target_and_compatible_task(confirmed, routing, relation):
    notices, _, previous, newer = _case(_FAULT, _RECOVERY)
    assert (
        resolve_followup_update(
            previous, newer, notices, routing, target_confirmed=confirmed, task_relation=relation
        )
        is None
    )


@pytest.mark.parametrize(
    ("message", "old_due", "new_due"),
    [
        ("Gia hạn thời hạn nộp hồ sơ.", "trước 17h00 ngày 20/11/2026", "đến hết ngày 22/11/2026"),
        ("Điều chỉnh hạn nộp hồ sơ về mốc ban đầu.", "ngày 22/11/2026", "ngày 20/11/2026"),
        ("Gia hạn thời hạn nộp hồ sơ.", "20/11/2026 lúc 17:00", "23h59 ngày 20/11/2026"),
    ],
)
def test_deadline_supports_literals_clock_changes_and_explicit_reversals(message, old_due, new_due):
    notices, _, previous, newer = _case("Thời hạn nộp hồ sơ.", message, old_due, new_due)
    update = resolve_followup_update(
        previous, newer, notices, _DIRECT, target_confirmed=True, task_relation="SAME_TASK"
    )
    assert update is not None
    assert update.update_side == 1
    assert update.reason == "verified_deadline_change"
    assert update.change.field == "DEADLINE"
    assert update.change.old is not None and update.change.old.text == old_due
    assert update.change.new.text == new_due


@pytest.mark.parametrize(
    ("message", "new_due", "old_role", "relation"),
    [
        ("Đề nghị gia hạn thời hạn nộp hồ sơ.", "21/11/2026", "DEADLINE", "SAME_TASK"),
        ("Đã từ chối gia hạn thời hạn nộp hồ sơ.", "21/11/2026", "DEADLINE", "SAME_TASK"),
        ("Yêu cầu gia hạn thời hạn nộp hồ sơ.", "21/11/2026", "DEADLINE", "SAME_TASK"),
        ("Dự kiến điều chỉnh hạn nộp hồ sơ.", "21/11/2026", "DEADLINE", "SAME_TASK"),
        ("Thông báo lịch báo cáo.", "21/11/2026", "DEADLINE", "SAME_TASK"),
        ("Gia hạn thời hạn nộp hồ sơ.", "19/11/2026", "DEADLINE", "SAME_TASK"),
        ("Lùi thời hạn nộp hồ sơ.", "19/11/2026", "DEADLINE", "SAME_TASK"),
        ("Gia hạn thời hạn nộp hồ sơ.", "22/11", "DEADLINE", "SAME_TASK"),
        ("Gia hạn thời hạn nộp hồ sơ.", "20-22/11/2026", "DEADLINE", "SAME_TASK"),
        ("Gia hạn thời hạn nộp hồ sơ.", "23/13/2026", "DEADLINE", "SAME_TASK"),
        ("Gia hạn thời hạn nộp hồ sơ.", "22/11/2026", "EVENT_TIME", "SAME_TASK"),
        ("Gia hạn thời hạn nộp hồ sơ.", "22/11/2026", "DEADLINE", "UNRESOLVED"),
    ],
)
def test_deadline_abstains_for_unsupported_or_unconfirmed_changes(
    message, new_due, old_role, relation
):
    notices, _, previous, newer = _case(
        "Thời hạn nộp hồ sơ.", message, "20/11/2026", new_due, old_role
    )
    assert (
        resolve_followup_update(
            previous, newer, notices, _DIRECT, target_confirmed=True, task_relation=relation
        )
        is None
    )

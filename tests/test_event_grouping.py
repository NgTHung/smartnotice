import copy
import hashlib
import json

import pytest
from smartnotice.labeling.grouping import GroupingConfig, group_events
from smartnotice.labeling.llm import parse_proposal
from smartnotice.labeling.studio import (
    annotation_results,
    export_prediction_task,
    import_prediction_tasks,
)
from smartnotice.schemas import Argument, Notice, Sentence, Span


def make_event(doc_id, text, action, time, role="DEADLINE"):
    notice = Notice(
        doc_id=doc_id,
        raw_sha256=hashlib.sha256(doc_id.encode()).hexdigest(),
        source_type="email",
        source_ref="synthetic",
        reference_date_origin="missing",
        text=text,
        sentences=[Sentence(sentence_id="s1", start=0, end=len(text), text=text)],
        group_id=doc_id,
        synthetic=True,
        redaction_count=0,
    )
    annotation = parse_proposal(
        notice,
        json.dumps(
            {
                "spans": [
                    {"span_id": "a1", "label": "ACTION", "sentence_id": "s1", "text": action},
                    {"span_id": "t1", "label": "TIME", "sentence_id": "s1", "text": time},
                ],
                "events": [
                    {
                        "event_id": "e1",
                        "action_span_id": "a1",
                        "arguments": [{"span_id": "t1", "role": role}],
                    }
                ],
            }
        ),
    )
    return notice, annotation


def test_identical_event_evidence_groups_and_preserves_sources():
    text = "Sinh viên nộp hồ sơ học bổng Sao Mai trước 20/11/2026."
    items = [
        make_event(doc, text, "nộp hồ sơ học bổng Sao Mai", "20/11/2026") for doc in ("d1", "d2")
    ]
    notices, annotations = map(list, zip(*items, strict=True))
    result = group_events(notices, annotations)
    assert len(result.groups) == 1
    assert result.groups[0].members == ["d1:a1", "d2:a1"]
    assert result.decisions[0].decision == "SAME_EVENT"
    assert result.decisions[0].grouped
    assert {m.raw_sha256 for m in result.mentions} == {n.raw_sha256 for n in notices}
    assert group_events(notices[::-1], annotations[::-1]) == result


@pytest.mark.parametrize(
    ("left", "right", "left_action", "right_action", "left_time", "right_time", "expected"),
    [
        (
            "Nộp hồ sơ học bổng Sao Mai HK2/2425 đến 20/11/2025.",
            "Nộp hồ sơ học bổng Sao Mai HK2/2526 đến 20/11/2026.",
            "Nộp hồ sơ học bổng Sao Mai",
            "Nộp hồ sơ học bổng Sao Mai",
            "20/11/2025",
            "20/11/2026",
            "DIFFERENT_EVENT",
        ),
        (
            "Nộp hồ sơ học bổng Sao Mai đến 20/11/2026.",
            "Nộp hồ sơ học bổng Sao Mai đến 21/11/2026.",
            "Nộp hồ sơ học bổng Sao Mai",
            "Nộp hồ sơ học bổng Sao Mai",
            "20/11/2026",
            "21/11/2026",
            "UNCLEAR",
        ),
        (
            "Nộp hồ sơ học bổng Sao Mai đến 20/11/2026.",
            "Gia hạn thời gian nộp hồ sơ học bổng Sao Mai đến 21/11/2026.",
            "Nộp hồ sơ học bổng Sao Mai",
            "nộp hồ sơ học bổng Sao Mai",
            "20/11/2026",
            "21/11/2026",
            "UPDATE_CANDIDATE",
        ),
        (
            "Nộp hồ sơ học bổng Sao Mai từ 20/11/2026 đến 21/11/2026.",
            "Nộp hồ sơ học bổng Sao Mai từ 20/11/2026 đến 21/11/2026.",
            "Nộp hồ sơ học bổng Sao Mai",
            "Nộp hồ sơ học bổng Sao Mai",
            "20/11/2026 đến 21/11/2026",
            "20/11/2026 đến 21/11/2026",
            "UNCLEAR",
        ),
    ],
)
def test_conflicts_and_updates_remain_separate(
    left, right, left_action, right_action, left_time, right_time, expected
):
    a = make_event("d1", left, left_action, left_time)
    b = make_event("d2", right, right_action, right_time)
    result = group_events([a[0], b[0]], [a[1], b[1]], GroupingConfig(similarity=0.5))
    assert result.decisions[0].decision == expected
    assert len(result.groups) == 2
    assert not result.decisions[0].grouped


def test_generic_boilerplate_placeholders_and_missing_year_are_not_identity():
    text = "Sinh viên liên hệ [NAME] qua [EMAIL] nếu có thắc mắc trước 20/11."
    items = [make_event(doc, text, "liên hệ", "20/11") for doc in ("d1", "d2")]
    notices, annotations = map(list, zip(*items, strict=True))
    assert len(group_events(notices, annotations).groups) == 2


def test_role_conflict_and_broken_offsets_are_rejected_or_abstained():
    text = "Nộp hồ sơ học bổng Sao Mai ngày 20/11/2026."
    a = make_event("d1", text, "Nộp hồ sơ học bổng Sao Mai", "20/11/2026")
    b = make_event("d2", text, "Nộp hồ sơ học bổng Sao Mai", "20/11/2026", "EVENT_TIME")
    result = group_events([a[0], b[0]], [a[1], b[1]])
    assert result.decisions[0].decision == "UNCLEAR"
    b[1].spans[0].start += 1
    with pytest.raises(ValueError, match="offsets"):
        group_events([a[0], b[0]], [a[1], b[1]])


def test_saved_predictions_round_trip_without_human_review():
    notice, annotation = make_event(
        "d1",
        "Nộp hồ sơ học bổng Sao Mai trước 20/11/2026.",
        "Nộp hồ sơ học bổng Sao Mai",
        "20/11/2026",
    )
    task = export_prediction_task(notice, annotation, provider="featherless", model="synthetic")
    original = copy.deepcopy(task)
    converted = import_prediction_tasks([task], [notice])
    assert converted[0].annotator_id == "model_prediction"
    assert annotation_results(converted[0]) == task["predictions"][0]["result"]
    assert task == original and "annotations" not in task
    with pytest.raises(ValueError, match="Duplicate"):
        import_prediction_tasks([task, task], [notice])
    task["predictions"][0]["result"][0]["value"]["text"] += " changed"
    with pytest.raises(ValueError, match="provenance"):
        import_prediction_tasks([task], [notice])


def test_academic_year_dash_variants_do_not_create_a_false_difference():
    a = make_event(
        "d1",
        "Nộp hồ sơ học bổng Sao Mai năm học 2025-2026 đến 20/11/2026.",
        "Nộp hồ sơ học bổng Sao Mai",
        "20/11/2026",
    )
    b = make_event(
        "d2",
        "Nộp hồ sơ học bổng Sao Mai năm học 2025–2026 đến 20/11/2026.",
        "Nộp hồ sơ học bổng Sao Mai",
        "20/11/2026",
    )
    result = group_events([a[0], b[0]], [a[1], b[1]])
    assert result.decisions[0].decision == "SAME_EVENT"


def test_unconfirmed_year_code_equivalence_abstains():
    a = make_event(
        "d1",
        "Nộp hồ sơ học bổng Sao Mai HK2/2526 đến 20/11/2026.",
        "Nộp hồ sơ học bổng Sao Mai",
        "20/11/2026",
    )
    b = make_event(
        "d2",
        "Nộp hồ sơ học bổng Sao Mai HK2/2025-2026 đến 20/11/2026.",
        "Nộp hồ sơ học bổng Sao Mai",
        "20/11/2026",
    )
    result = group_events([a[0], b[0]], [a[1], b[1]], GroupingConfig(similarity=0.5))
    assert result.decisions[0].decision == "UNCLEAR"


def test_same_program_different_actions_and_empty_input():
    text = "Đăng ký hội thảo Sao Mai và tham dự hội thảo Sao Mai ngày 20/11/2026."
    a = make_event("d1", text, "Đăng ký hội thảo Sao Mai", "20/11/2026")
    b = make_event("d2", text, "tham dự hội thảo Sao Mai", "20/11/2026")
    assert group_events([a[0], b[0]], [a[1], b[1]]).decisions[0].decision == "DIFFERENT_EVENT"
    assert group_events([], []).groups == []
    with pytest.raises(ValueError, match="unique"):
        group_events([a[0], a[0]], [a[1]])


def test_prediction_converter_refuses_completions_and_preserves_empty_predictions():
    notice, annotation = make_event(
        "d1",
        "Nộp hồ sơ học bổng Sao Mai trước 20/11/2026.",
        "Nộp hồ sơ học bổng Sao Mai",
        "20/11/2026",
    )
    task = export_prediction_task(notice, annotation, provider="featherless", model="synthetic")
    task["annotations"] = [{"completed_by": 1, "result": []}]
    with pytest.raises(ValueError, match="without completions"):
        import_prediction_tasks([task], [notice])
    annotation.spans = []
    annotation.events = []
    task = export_prediction_task(notice, annotation, provider="featherless", model="synthetic")
    assert import_prediction_tasks([task], [notice])[0].events == []


def test_multiple_dates_for_one_role_stay_unresolved():
    text = "Hội thảo học bổng Sao Mai ngày 01/10/2014 hoặc 01/10/2024."
    items = [
        make_event(doc, text, "Hội thảo học bổng Sao Mai", "01/10/2014", "EVENT_TIME")
        for doc in ("d1", "d2")
    ]
    for _notice, annotation in items:
        start = text.index("01/10/2024")
        annotation.spans.append(
            Span(span_id="t2", label="TIME", start=start, end=start + 10, text="01/10/2024")
        )
        annotation.events[0].arguments.append(Argument(span_id="t2", role="EVENT_TIME"))
    result = group_events([i[0] for i in items], [i[1] for i in items])
    assert result.decisions[0].decision == "UNCLEAR"

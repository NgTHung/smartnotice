"""Check automatic decisions against hand-checkable synthetic source items."""

import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from smartnotice.labeling.automatic_grouping import (
    compare_grouping_reference,
    propose_event_groups,
)
from smartnotice.labeling.event_groups import build_event_groups
from smartnotice.schemas import (
    Annotation,
    Argument,
    AutomaticGroupingConfig,
    AutomaticGroupingResult,
    AutomaticPairProposal,
    Event,
    Notice,
    Sentence,
    Span,
)

STAMP = datetime(2026, 11, 9, tzinfo=UTC)


def item(
    doc,
    action="Đăng ký cuộc thi Sao Bắc năm 2026",
    *,
    code="SB-26",
    deadline="10/11/2026",
    event_time=None,
    context="",
):
    lines = ([f"Mã sự kiện: {code}."] if code else []) + [action + "."]
    if context:
        lines.append(context)
    fields = []
    if deadline:
        fields.append(("DEADLINE", deadline))
    if event_time:
        fields.append(("EVENT_TIME", event_time))
    lines += [f"{role}: {value}." for role, value in fields]
    text = "\n".join(lines)
    sentences, start = [], 0
    for i, line in enumerate(lines):
        sentences.append(
            Sentence(sentence_id=f"s{i}", start=start, end=start + len(line), text=line)
        )
        start += len(line) + 1
    spans = [
        Span(
            span_id="a1",
            label="ACTION",
            start=text.index(action),
            end=text.index(action) + len(action),
            text=action,
        )
    ]
    arguments = []
    for index, (role, value) in enumerate(fields):
        start = text.index(f"{role}: {value}") + len(role) + 2
        sid = f"t{index}"
        spans.append(
            Span(span_id=sid, label="TIME", start=start, end=start + len(value), text=value)
        )
        arguments.append(Argument(span_id=sid, role=role))
    notice = Notice(
        doc_id=doc,
        raw_sha256=hashlib.sha256(text.encode()).hexdigest(),
        source_type="email",
        source_ref="synthetic",
        text=text,
        sentences=sentences,
        reference_date_origin="missing",
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
                arguments=arguments,
                evidence_sentence_ids=[s.sentence_id for s in sentences],
            )
        ],
    )
    return notice, annotation


def run(items):
    return propose_event_groups([n for n, _ in items], [a for _, a in items], generated_at=STAMP)


def test_open_remind_extend_then_check_in_preserves_one_group_two_tasks():
    items = [
        item("a"),
        item("b", "Nhắc đăng ký cuộc thi Sao Bắc năm 2026"),
        item("c", "Gia hạn đăng ký cuộc thi Sao Bắc năm 2026", deadline="12/11/2026"),
    ]
    original = [a.model_dump() for _, a in items]
    result = run(items)
    assert len(result.assembly.groups) == 1
    assert len(result.assembly.groups[0].tasks) == 1
    assert len(result.assembly.groups[0].members) == 3
    assert sum(u.applied for u in result.assembly.updates) == 2
    facts = result.assembly.groups[0].tasks[0]
    assert {f.quote.text for f in facts.facts if f.fact_id in facts.active_values["DEADLINE"]} == {
        "12/11/2026"
    }
    assert [a.model_dump() for _, a in items] == original
    items.append(
        item("d", "Check-in cuộc thi Sao Bắc năm 2026", deadline=None, event_time="15/11/2026")
    )
    final = run(items)
    assert len(final.assembly.groups) == 1
    assert len(final.assembly.groups[0].tasks) == 2
    assert not final.assembly.conflicts
    assert final == run(items[::-1])
    assert all(
        p.origin == "rule_proposal" and p.pair.author.reviewer_kind == "ai_assistant"
        for p in final.proposals
    )


def test_different_steps_and_time_roles_do_not_split_event():
    result = run([item("a"), item("b", "Nộp bài cuộc thi Sao Bắc năm 2026", deadline="15/11/2026")])
    assert result.proposals[0].pair.decision == "SAME_EVENT"
    assert result.proposals[0].pair.task_relation == "DIFFERENT_TASK"
    assert len(result.assembly.groups) == 1
    assert len(result.assembly.groups[0].tasks) == 2


def test_narrowed_recipient_context_remains_a_reminder():
    result = run([item("a"), item("b", context="Nhắc sinh viên chưa hoàn tất đăng ký.")])
    pair = result.proposals[0].pair
    assert pair.decision == "SAME_EVENT" and pair.task_relation == "SAME_TASK"
    assert pair.notice_relation == "REMINDER"


def test_explicit_code_links_aliases_and_different_source_wording():
    result = run(
        [
            item("a", "Đăng ký chương trình North Star"),
            item("b", "Tham dự chương trình Sao Bắc", deadline=None),
        ]
    )
    assert result.proposals[0].pair.decision == "SAME_EVENT"
    assert result.proposals[0].pair.task_relation == "DIFFERENT_TASK"


@pytest.mark.parametrize("context", ["CHUYÊN ĐỀ 6: Hành trang nghiên cứu.", "Năm học 2027-2028."])
def test_explicit_independent_specialty_or_period_stays_separate(context):
    result = run(
        [
            item("a", context="CHUYÊN ĐỀ 4: Kỹ năng diễn thuyết.\nNăm học 2026-2027."),
            item("b", context=context),
        ]
    )
    assert result.proposals[0].pair.decision == "DIFFERENT_EVENT"
    assert len(result.assembly.groups) == 2


def test_sessions_of_same_activity_remain_distinct_obligations():
    result = run(
        [
            item(
                "a", "Tham dự cuộc thi Sao Bắc năm 2026", context="Ca sáng", event_time="15/11/2026"
            ),
            item(
                "b",
                "Tham dự cuộc thi Sao Bắc năm 2026",
                context="Ca chiều",
                event_time="16/11/2026",
            ),
        ]
    )
    assert result.proposals[0].pair.task_relation == "DIFFERENT_SESSION"
    assert len(result.assembly.groups) == 1


def test_conflicting_deadline_without_change_language_abstains():
    result = run([item("a"), item("b", deadline="12/11/2026")])
    assert result.proposals[0].pair.decision == "UNCLEAR"
    assert not result.assembly.updates
    assert len(result.assembly.groups) == 2


def test_shared_reused_form_and_generic_name_cannot_establish_identity():
    result = run(
        [
            item(
                "a",
                "Đăng ký hội thảo kỹ năng",
                code=None,
                context="https://example.test/form/register",
            ),
            item(
                "b",
                "Tham dự hội thảo kỹ năng",
                code=None,
                context="https://example.test/form/register",
            ),
        ]
    )
    assert result.proposals[0].pair.decision == "UNCLEAR"


def test_distinctive_action_name_and_matching_date_can_anchor_without_code():
    result = run([item("a", code=None), item("b", code=None)])
    assert result.proposals[0].pair.decision == "SAME_EVENT"


def test_update_without_old_value_preserves_unknown_old_quote():
    result = run(
        [
            item("a", deadline=None),
            item("b", "Gia hạn đăng ký cuộc thi Sao Bắc năm 2026", deadline="12/11/2026"),
        ]
    )
    pair = result.proposals[0].pair
    assert pair.decision == "UPDATE_OF"
    assert pair.left.event_ref == "b:a1"
    assert pair.changes[0].old is None


def test_location_change_with_no_resolved_field_abstains():
    result = run([item("a"), item("b", context="Thay đổi địa điểm sang phòng B203.")])
    assert result.proposals[0].pair.decision == "UNCLEAR"


def test_bulletin_is_compared_per_item_including_same_email_items():
    one, two = item("mail", code="EVENT-A"), item("mail", "Nhận vé xem phim", code="EVENT-B")
    notice, ann = one
    offset = len(notice.text) + 1
    notice.text += "\n" + two[0].text
    notice.raw_sha256 = hashlib.sha256(notice.text.encode()).hexdigest()
    notice.sentences += [
        s.model_copy(
            update={
                "sentence_id": "b" + s.sentence_id,
                "start": s.start + offset,
                "end": s.end + offset,
            }
        )
        for s in two[0].sentences
    ]
    ann.spans += [
        s.model_copy(
            update={"span_id": "b" + s.span_id, "start": s.start + offset, "end": s.end + offset}
        )
        for s in two[1].spans
    ]
    event = two[1].events[0].model_copy(deep=True)
    event.event_id = "e2"
    event.action_span_id = "ba1"
    event.arguments = [a.model_copy(update={"span_id": "b" + a.span_id}) for a in event.arguments]
    event.evidence_sentence_ids = ["b" + s for s in event.evidence_sentence_ids]
    ann.events.append(event)
    result = run([(notice, ann), item("followup", code="EVENT-A")])
    membership = {ref: g.group_id for g in result.assembly.groups for ref in g.members}
    assert membership["mail:a1"] == membership["followup:a1"]
    assert membership["mail:ba1"] != membership["mail:a1"]


def test_comparison_reports_missing_candidate_without_inventing_negative_labels():
    result = run([item("a"), item("b")])
    reference = result.assembly.model_copy(deep=True)
    assert compare_grouping_reference(result, reference).pairs[0].issues == []
    result.proposals = []
    row = compare_grouping_reference(result, reference).pairs[0]
    assert row.proposed_decision is None
    assert row.issues == ["candidate_missing"]
    reference.mentions[0].version.annotation_sha256 = "f" * 64
    with pytest.raises(ValueError, match="snapshot"):
        compare_grouping_reference(result, reference)


def test_invalid_offsets_and_naive_timestamp_are_rejected():
    notice, ann = item("a")
    ann.spans[0].text = "Unsupported action"
    with pytest.raises(ValueError):
        run([(notice, ann)])
    with pytest.raises(ValueError, match="timezone"):
        propose_event_groups([], [], generated_at=datetime(2026, 11, 9))


@pytest.mark.parametrize("deadline", ["31/02/2026", "10/11/2026 đến 15/11/2026"])
def test_invalid_or_unsplit_dates_do_not_merge(deadline):
    result = run([item("a", deadline=deadline), item("b", deadline=deadline)])
    assert result.proposals[0].pair.decision == "UNCLEAR"


def test_deadline_qualifiers_are_not_discarded_as_equivalent():
    result = run([item("a", deadline="trước 10/11/2026"), item("b", deadline="đến hết 10/11/2026")])
    assert result.proposals[0].pair.decision == "UNCLEAR"


def test_ambiguous_context_with_multiple_event_codes_abstains():
    result = run([item("a"), item("b", context="Mã sự kiện: OTHER-26.")])
    assert result.proposals[0].pair.decision == "UNCLEAR"


def test_missing_cross_pair_in_positive_component_is_checked_before_merging():
    items = [
        item("a", "Đăng ký Quỹ Sông Xanh", code="CODE-A"),
        item("b", "Tham dự Sao Bắc", code="CODE-A"),
        item("c", "Nộp bài Sao Bắc", code=None),
    ]
    result = propose_event_groups(
        [n for n, _ in items],
        [a for _, a in items],
        generated_at=STAMP,
        config=AutomaticGroupingConfig(candidate_similarity=1, min_shared_tokens=100),
    )
    assert any(
        p.candidate_reasons == ["positive_component_consistency_check"] for p in result.proposals
    )
    assert len(result.assembly.groups) == 3
    assert result.assembly.conflicts[0].kind == "group_contradiction"


def test_cli_exports_reproducible_page_and_keeps_reference_out_of_predictions(tmp_path):
    items = [item("a"), item("b")]
    expected = run(items)
    reference = expected.assembly.model_copy(deep=True)
    reference.reviews[0].decision = "DIFFERENT_EVENT"
    reference.reviews[0].task_relation = "UNRESOLVED"
    reference = build_event_groups([n for n, _ in items], [a for _, a in items], reference.reviews)
    notices, annotations, source = [
        tmp_path / name for name in ["notices.jsonl", "annotations.jsonl", "reference.json"]
    ]
    notices.write_text("\n".join(n.model_dump_json() for n, _ in items), encoding="utf-8")
    annotations.write_text("\n".join(a.model_dump_json() for _, a in items), encoding="utf-8")
    source.write_text(reference.model_dump_json(), encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    private = root / "reports/generated"
    private.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="test-automatic-", dir=private) as local:
        output = Path(local) / "result"
        args = [
            sys.executable,
            "tools/run_automatic_grouping.py",
            "--notices",
            str(notices),
            "--annotations",
            str(annotations),
            "--reference-assembly",
            str(source),
            "--output-dir",
            str(output),
            "--generated-at",
            STAMP.isoformat(),
        ]
        completed = subprocess.run(args, cwd=root, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr
        saved = json.loads((output / "result.json").read_text(encoding="utf-8"))
        assert saved == expected.model_dump(mode="json")
        diagnostics = json.loads((output / "comparison.json").read_text(encoding="utf-8"))
        assert "decision_mismatch" in diagnostics["pairs"][0]["issues"]
        assert not diagnostics["independent_evaluation"]
        hashes = json.loads((output / "checksums.json").read_text(encoding="utf-8"))
        assert all(
            hashlib.sha256((output / name).read_bytes()).hexdigest() == sha
            for name, sha in hashes.items()
        )
        html = (output / "index.html").read_text(encoding="utf-8")
        assert "__SMARTNOTICE_REVIEW_DATA__" not in html
        assert "</html>" in html
        assert (
            json.loads((output / "run.json").read_text(encoding="utf-8"))[
                "reference_used_for_prediction"
            ]
            is False
        )
        before = (output / "index.html").read_bytes()
        repeated = subprocess.run(args, cwd=root, capture_output=True, text=True)
        assert repeated.returncode != 0 and "already exists" in repeated.stderr
        assert (output / "index.html").read_bytes() == before


def test_conditional_extra_task_keeps_its_annotated_condition():
    first = item("a")
    notice, annotation = item(
        "b", "Nộp giấy xác nhận cuộc thi Sao Bắc năm 2026", context="Chỉ thực hiện nếu thiếu hồ sơ."
    )
    value = "nếu thiếu hồ sơ"
    start = notice.text.index(value)
    annotation.spans.append(
        Span(span_id="c1", label="CONDITION", start=start, end=start + len(value), text=value)
    )
    annotation.events[0].arguments.append(Argument(span_id="c1"))
    result = run([first, (notice, annotation)])
    assert result.proposals[0].pair.task_relation == "CONDITIONAL_TASK"
    assert len(result.assembly.groups[0].tasks) == 2
    assert any(
        f.field == "CONDITION" and f.quote.text == value
        for task in result.assembly.groups[0].tasks
        for f in task.facts
    )


def test_persisted_rule_origin_cannot_claim_human_review_or_naive_generation_time():
    result = run([item("a"), item("b")])
    proposal = result.proposals[0].model_dump()
    proposal["pair"]["author"]["reviewer_id"] = "synthetic-human"
    proposal["pair"]["author"]["reviewer_kind"] = "human"
    with pytest.raises(ValueError, match="nonhuman"):
        AutomaticPairProposal.model_validate(proposal)
    record = result.model_dump()
    record["generated_at"] = datetime(2026, 11, 9)
    with pytest.raises(ValueError, match="timezone"):
        AutomaticGroupingResult.model_validate(record)

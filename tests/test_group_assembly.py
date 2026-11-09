"""Exercise reviewed grouping with synthetic, source-checkable notices."""

import hashlib
from datetime import UTC, datetime

import pytest
from smartnotice.labeling.event_groups import annotation_sha256, build_event_groups
from smartnotice.schemas import (
    Annotation,
    Argument,
    Event,
    EvidenceQuote,
    GroupingChange,
    GroupingReview,
    MentionVersion,
    Notice,
    ReviewAuthor,
    Sentence,
    Span,
    TimeBoundaryReview,
)


def make_notice(doc, deadline="10/11/2026", action="Đăng ký cuộc thi"):
    text = f"{action} trước {deadline}."
    notice = Notice(
        doc_id=doc,
        raw_sha256=hashlib.sha256(text.encode()).hexdigest(),
        source_type="email",
        source_ref="synthetic",
        text=text,
        sentences=[Sentence(sentence_id="s1", start=0, end=len(text), text=text)],
        group_id=doc,
        reference_date_origin="missing",
        synthetic=True,
        redaction_count=0,
    )
    start = text.index(deadline)
    annotation = Annotation(
        doc_id=doc,
        annotator_id="ai_assistant",
        spans=[
            Span(span_id="a1", label="ACTION", start=0, end=len(action), text=action),
            Span(span_id="t1", label="TIME", start=start, end=start + len(deadline), text=deadline),
        ],
        events=[
            Event(
                event_id="e1",
                action_span_id="a1",
                arguments=[Argument(span_id="t1", role="DEADLINE")],
                evidence_sentence_ids=["s1"],
            )
        ],
    )
    return notice, annotation


def version(item):
    notice, annotation = item
    return MentionVersion(
        event_ref=f"{notice.doc_id}:a1",
        raw_sha256=notice.raw_sha256,
        text_sha256=hashlib.sha256(notice.text.encode()).hexdigest(),
        annotation_sha256=annotation_sha256(annotation),
    )


def quote(item, text=None):
    notice, _ = item
    value = notice.text if text is None else text
    start = notice.text.index(value)
    return EvidenceQuote(
        doc_id=notice.doc_id, sentence_id="s1", start=start, end=start + len(value), text=value
    )


def review(left, right, decision="SAME_EVENT", relation="SAME_TASK", changes=None, rid="r1"):
    return GroupingReview(
        review_id=rid,
        left=version(left),
        right=version(right),
        decision=decision,
        task_relation=relation,
        author=ReviewAuthor(
            reviewer_id="ai_assistant",
            reviewer_kind="ai_assistant",
            reviewed_at=datetime(2026, 11, 6, tzinfo=UTC),
        ),
        rationale="Synthetic source comparison.",
        evidence=[quote(left), quote(right)],
        changes=changes or [],
    )


def assemble(items, reviews, boundaries=None):
    return build_event_groups(
        [i[0] for i in items], [i[1] for i in items], reviews, boundaries or []
    )


def test_registration_reminder_extension_and_check_in_keep_counts_and_history():
    a, b = make_notice("a"), make_notice("b")
    c = make_notice("c", "12/11/2026")
    d = make_notice("d", "15/11/2026", "Check-in cuộc thi")
    reviews = [
        review(a, b),
        review(
            c,
            a,
            "UPDATE_OF",
            changes=[
                GroupingChange(
                    field="DEADLINE", old=quote(a, "10/11/2026"), new=quote(c, "12/11/2026")
                )
            ],
            rid="r2",
        ),
    ]
    first = assemble([a, b, c], reviews)
    assert len(first.groups) == len(first.groups[0].tasks) == 1
    task = first.groups[0].tasks[0]
    assert len(task.members) == 3
    assert [f.quote.text for f in task.facts if f.fact_id in task.active_values["DEADLINE"]] == [
        "12/11/2026"
    ]
    assert sum(bool(f.superseded_by) for f in task.facts) == 2
    reviews.append(review(d, a, relation="DIFFERENT_TASK", rid="r3"))
    result = assemble([a, b, c, d], reviews)
    assert len(result.groups) == 1 and len(result.groups[0].tasks) == 2
    assert len(result.groups[0].document_ids) == 4
    assert all(g.review_required and g.privacy_review_required for g in result.groups)
    assert result == assemble([d, c, b, a], reviews[::-1])


@pytest.mark.parametrize("relation", ["DIFFERENT_TASK", "DIFFERENT_SESSION", "CONDITIONAL_TASK"])
def test_other_steps_sessions_and_conditional_obligations_stay_separate(relation):
    a, b = make_notice("a"), make_notice("b", "15/11/2026", "Nộp bài cuộc thi")
    result = assemble([a, b], [review(a, b, relation=relation)])
    assert len(result.groups) == 1 and len(result.groups[0].tasks) == 2
    assert not result.conflicts


def test_conflicting_transitive_group_does_not_merge_a_negative_pair():
    a, b, c = [make_notice(doc) for doc in "abc"]
    result = assemble(
        [a, b, c],
        [
            review(a, b),
            review(b, c, rid="r2"),
            review(a, c, "DIFFERENT_EVENT", "UNRESOLVED", rid="r3"),
        ],
    )
    assert len(result.groups) == 3
    assert result.conflicts[0].kind == "group_contradiction"


def test_transitive_same_task_does_not_swallow_a_separate_session():
    a, b, c = [make_notice(doc) for doc in "abc"]
    result = assemble(
        [a, b, c],
        [
            review(a, b),
            review(b, c, rid="r2"),
            review(a, c, relation="DIFFERENT_SESSION", rid="r3"),
        ],
    )
    assert len(result.groups) == 1 and len(result.groups[0].tasks) == 3
    assert result.conflicts[0].kind == "task_contradiction"


def test_different_dates_without_update_remain_an_unresolved_conflict():
    a, b = make_notice("a"), make_notice("b", "12/11/2026")
    result = assemble([a, b], [review(a, b)])
    assert result.conflicts[0].kind == "competing_values"
    assert len(result.groups[0].tasks[0].active_values["DEADLINE"]) == 2


def test_two_extensions_of_the_same_old_value_do_not_choose_latest_deadline():
    a, b, c = make_notice("a"), make_notice("b", "12/11/2026"), make_notice("c", "15/11/2026")
    reviews = [
        review(
            item,
            a,
            "UPDATE_OF",
            changes=[
                GroupingChange(field="DEADLINE", old=quote(a, "10/11/2026"), new=quote(item, date))
            ],
            rid=rid,
        )
        for item, date, rid in [(b, "12/11/2026", "r1"), (c, "15/11/2026", "r2")]
    ]
    result = assemble([a, b, c], reviews)
    assert len(result.groups[0].tasks[0].active_values["DEADLINE"]) == 2
    assert any(c.kind == "competing_values" for c in result.conflicts)


def test_update_cycle_is_rejected():
    items = [
        make_notice(doc, date)
        for doc, date in [("a", "10/11/2026"), ("b", "12/11/2026"), ("c", "15/11/2026")]
    ]
    reviews = [
        review(
            items[i],
            items[(i + 1) % 3],
            "UPDATE_OF",
            changes=[
                GroupingChange(
                    field="DEADLINE",
                    old=quote(items[(i + 1) % 3], items[(i + 1) % 3][1].spans[1].text),
                    new=quote(items[i], items[i][1].spans[1].text),
                )
            ],
            rid=f"r{i}",
        )
        for i in range(3)
    ]
    with pytest.raises(ValueError, match="cycle"):
        assemble(items, reviews)


@pytest.mark.parametrize("broken", ["snapshot", "quote", "reference", "direction"])
def test_stale_sources_and_unsupported_update_evidence_fail(broken):
    a, b = make_notice("a"), make_notice("b", "12/11/2026")
    r = review(
        b,
        a,
        "UPDATE_OF",
        changes=[
            GroupingChange(field="DEADLINE", old=quote(a, "10/11/2026"), new=quote(b, "12/11/2026"))
        ],
    )
    if broken == "snapshot":
        r.left.annotation_sha256 = "0" * 64
    elif broken == "quote":
        r.evidence[0].start += 1
    elif broken == "reference":
        r.left.event_ref = "unknown:a1"
    else:
        r.changes[0].new = quote(a, "10/11/2026")
    with pytest.raises(ValueError):
        assemble([a, b], [r])


def test_time_boundary_is_explicit_without_changing_annotation_roles():
    a = make_notice("a", "11:00 ngày 20/12/2025", "Chuyên đề")
    a[1].events[0].arguments[0].role = "EVENT_TIME"
    boundary = TimeBoundaryReview(
        mention=version(a),
        span_id="t1",
        boundary="END",
        author=ReviewAuthor(
            reviewer_id="ai_assistant",
            reviewer_kind="ai_assistant",
            reviewed_at=datetime(2026, 11, 6, tzinfo=UTC),
        ),
        rationale="The source specifies the end of the session.",
    )
    result = assemble([a], [], [boundary])
    fact = result.groups[0].tasks[0].facts[0]
    assert fact.field == "END" and fact.quote.text == "11:00 ngày 20/12/2025"
    assert a[1].events[0].arguments[0].role == "EVENT_TIME"


def test_two_events_in_one_document_can_belong_to_separate_groups():
    a, b = make_notice("a"), make_notice("b")
    b[1].doc_id = a[0].doc_id
    b[1].events[0].action_span_id = "a2"
    b[1].spans[0].span_id = "a2"
    a[1].spans.append(b[1].spans[0])
    b[1].events[0].event_id = "e2"
    a[1].events.append(b[1].events[0])
    result = assemble([a], [])
    assert len(result.groups) == 2


def test_duplicate_reviews_invalid_roles_and_false_human_attribution_fail():
    a, b = make_notice("a"), make_notice("b")
    r = review(a, b)
    with pytest.raises(ValueError, match="Duplicate"):
        assemble([a, b], [r, r])
    with pytest.raises(ValueError):
        ReviewAuthor(
            reviewer_id="ai_assistant", reviewer_kind="human", reviewed_at=datetime.now(UTC)
        )
    with pytest.raises(ValueError):
        GroupingReview.model_validate({**r.model_dump(), "decision": "GUESS"})
    assert not assemble([], []).groups


def test_update_reverting_to_an_earlier_value_keeps_the_latest_graph_version():
    a, b, c = make_notice("a"), make_notice("b", "12/11/2026"), make_notice("c")
    reviews = [
        review(
            b,
            a,
            "UPDATE_OF",
            changes=[
                GroupingChange(
                    field="DEADLINE", old=quote(a, "10/11/2026"), new=quote(b, "12/11/2026")
                )
            ],
        ),
        review(
            c,
            b,
            "UPDATE_OF",
            changes=[
                GroupingChange(
                    field="DEADLINE", old=quote(b, "12/11/2026"), new=quote(c, "10/11/2026")
                )
            ],
            rid="r2",
        ),
    ]
    task = assemble([a, b, c], reviews).groups[0].tasks[0]
    active = [f for f in task.facts if f.fact_id in task.active_values["DEADLINE"]]
    assert len(active) == 1 and active[0].mention_ref == "c:a1"


def test_a_literal_action_quote_cannot_be_asserted_as_a_deadline():
    a, b = make_notice("a"), make_notice("b", "12/11/2026")
    r = review(
        b,
        a,
        "UPDATE_OF",
        changes=[
            GroupingChange(
                field="DEADLINE", old=quote(a, "10/11/2026"), new=quote(b, "Đăng ký cuộc thi")
            )
        ],
    )
    with pytest.raises(ValueError, match="TIME"):
        assemble([a, b], [r])


def test_reviewed_complementary_time_spans_keep_all_evidence_without_false_conflict():
    a, b = make_notice("a", "20:00 22/10/2026"), make_notice("b", "22/10/2026")
    for item in [a, b]:
        item[1].events[0].arguments[0].role = "EVENT_TIME"
    author = review(a, b).author
    boundaries = [
        TimeBoundaryReview(
            mention=version(item),
            span_id="t1",
            boundary="POINT",
            value_key="same-source-reviewed-meeting",
            author=author,
            rationale="The shared date and hour have been compared against source context.",
        )
        for item in [a, b]
    ]
    result = assemble([a, b], [review(a, b)], boundaries)
    assert not result.conflicts
    assert len(result.groups[0].tasks[0].facts) == 2


@pytest.mark.parametrize("field", ["LOCATION", "STATUS"])
def test_reviewed_location_and_status_updates_keep_old_and_new_quotes(field):
    a = make_notice("a", action="Hội thảo phòng A đang mở")
    b = make_notice("b", action="Hội thảo phòng B tạm hoãn")
    old, new = ("phòng A", "phòng B") if field == "LOCATION" else ("đang mở", "tạm hoãn")
    r = review(
        b,
        a,
        "UPDATE_OF",
        changes=[GroupingChange(field=field, old=quote(a, old), new=quote(b, new))],
    )
    result = assemble([a, b], [r])
    task = result.groups[0].tasks[0]
    assert [f.quote.text for f in task.facts if f.fact_id in task.active_values[field]] == [new]
    assert any(f.quote.text == old and f.superseded_by for f in task.facts)

"""Exercise source alignment with local synthetic mentions."""

import hashlib

from smartnotice.labeling.grouping_alignment import align_followup_mentions, build_followup_profiles
from smartnotice.labeling.grouping_followup import RoutingComparison
from smartnotice.parsers.email import EmailRouting
from smartnotice.schemas import Event, GroupingModelMention, MentionVersion, Notice, Sentence, Span

DIRECT = RoutingComparison(1, 3600, False, True)
SEPARATE = RoutingComparison(1, 86400, False, False)


def _profiles(doc_id: str, lines: list[str], actions: list[int], subject: str | None = None):
    text = "\n".join(lines)
    sentences = []
    start = 0
    for i, line in enumerate(lines):
        end = start + len(line)
        sentences.append(Sentence(sentence_id=f"s{i}", start=start, end=end, text=line))
        start = end + 1
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    notice = Notice(
        doc_id=doc_id,
        source_type="email",
        source_ref="synthetic",
        raw_sha256=digest,
        text=text,
        sentences=sentences,
        reference_date_origin="missing",
        group_id=doc_id,
        redaction_count=0,
        synthetic=True,
    )
    mentions = []
    for i in actions:
        sentence = sentences[i]
        span = Span(
            span_id=f"a{i}",
            label="ACTION",
            start=sentence.start,
            end=sentence.end,
            text=sentence.text,
        )
        ref = f"{doc_id}:{span.span_id}"
        mentions.append(
            GroupingModelMention(
                mention_id=ref,
                doc_id=doc_id,
                version=MentionVersion(
                    event_ref=ref, raw_sha256=digest, text_sha256=digest, annotation_sha256=digest
                ),
                event=Event(
                    event_id=f"e{i}",
                    action_span_id=span.span_id,
                    arguments=[],
                    evidence_sentence_ids=[sentence.sentence_id],
                ),
                spans=[span],
                sentences=[sentence],
            )
        )
    header = EmailRouting(None, None, None, None, subject) if subject else None
    return build_followup_profiles(notice, mentions, header)


def test_direct_reply_selects_exact_code_from_its_section():
    earlier = _profiles(
        "earlier",
        [
            "1. Nộp mô hình cầu treo.",
            "Mã cuộc thi: BRG25.",
            "2. Gửi bản thiết kế xưởng.",
            "Mã cuộc thi: SHOP25.",
        ],
        [0, 2],
    )
    later = _profiles("later", ["Cho em hỏi có bản điện tử không?", "Mã cuộc thi: BRG25."], [0])
    alignments = align_followup_mentions(earlier, later, DIRECT)
    assert set(alignments) == {("earlier:a0", "later:a0")}
    evidence = alignments["earlier:a0", "later:a0"]
    assert evidence.reason == "direct_reply_event_code"
    assert evidence.sentence_ids == (("s1",), ("s1",))


def test_reply_header_and_generic_template_are_insufficient():
    subject = "Thông báo thử nghiệm tại cơ sở"
    earlier = _profiles(
        "earlier", ["Thông báo thử nghiệm tại cơ sở.", "Nộp mô hình cầu treo."], [1], subject
    )
    later = _profiles(
        "later",
        ["Thông báo thử nghiệm tại cơ sở.", "Bàn giao máy khoan cầm tay."],
        [1],
        f"Re: {subject}",
    )
    assert not align_followup_mentions(earlier, later, DIRECT)


def test_reply_with_two_equally_supported_sections_abstains():
    earlier = _profiles(
        "earlier",
        [
            "1. Gửi mẫu giấy.",
            "Mã chương trình: CAMP25.",
            "2. Mang đồ bảo hộ.",
            "Mã chương trình: CAMP25.",
        ],
        [0, 2],
    )
    later = _profiles("later", ["Có nhận bản mềm không?", "Mã chương trình: CAMP25."], [0])
    assert not align_followup_mentions(earlier, later, DIRECT)


def test_direct_reply_reuses_one_fully_stated_exam_scope():
    earlier = _profiles("earlier", ["Lịch thi giữa kỳ, mã môn CSC102, học kỳ 1/2526."], [0])
    later = _profiles("later", ["Thi giữa kỳ môn CSC102 học kỳ I năm học 2025-2026."], [0])
    [match] = align_followup_mentions(earlier, later, DIRECT).values()
    assert match.reason == "direct_reply_exam_scope"
    assert match.sentence_ids == (("s0",), ("s0",))
    other_term = _profiles("other", ["Thi giữa kỳ môn CSC102 học kỳ 2/2526."], [0])
    assert not align_followup_mentions(earlier, other_term, DIRECT)


def test_disjoint_class_codes_veto_otherwise_identical_exam_scope():
    template = "Lịch thi giữa kỳ, mã môn CSC102, học kỳ 1/2526, lớp học phần {}."
    a = _profiles("a", [template.format("CSC102A")], [0])
    b = _profiles("b", [template.format("CSC102B")], [0])
    assert not align_followup_mentions(a, b, DIRECT)


def test_headline_exam_scope_is_not_inherited_by_an_unrelated_item():
    official = "Lịch thi giữa kỳ, mã môn CSC102, học kỳ 1/2526."
    earlier = _profiles("earlier", [official, "Nộp phiếu mượn phòng máy."], [0, 1])
    later = _profiles("later", ["Thi giữa kỳ môn CSC102 học kỳ 1/2526."], [0])
    assert set(align_followup_mentions(earlier, later, DIRECT)) == {("earlier:a0", "later:a0")}


def test_later_title_and_form_can_corroborate_a_scoped_continuation():
    topic = "Đo cường độ ánh sáng"
    text = [f"{topic}.", "Điền phiếu phản hồi.", "Phiếu: https://forms.gle/fixture"]
    earlier = _profiles("earlier", text, [1], topic)
    later = _profiles("later", text, [1], f"Gia hạn {topic}")
    [match] = align_followup_mentions(earlier, later, SEPARATE).values()
    assert match.reason == "continuation_form_and_phrase"
    assert match.sentence_ids == (("s0", "s2"), ("s0", "s2"))

    recurring = _profiles("recurring", [*text, "Đợt 2."], [1], f"Gia hạn {topic}")
    first = _profiles("first", [*text, "Đợt 1."], [1], topic)
    assert not align_followup_mentions(first, recurring, SEPARATE)


def test_verified_reply_can_follow_a_distinctive_phrase_in_prepared_evidence():
    a = _profiles("a", ["Nộp nhật ký đo cường độ bức xạ."], [0])
    b = _profiles("b", ["Nhật ký đo cường độ bức xạ có cần chữ ký?"], [0])
    [match] = align_followup_mentions(a, b, DIRECT).values()
    assert match.reason == "direct_reply_shared_phrase"
    assert not align_followup_mentions(a, b, SEPARATE)

"""Align a follow-up mention with one corroborated item in an earlier notice."""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from smartnotice.labeling.grouping_academic import AcademicScope, academic_scope
from smartnotice.labeling.grouping_evidence import event_form_keys
from smartnotice.labeling.grouping_followup import RoutingComparison
from smartnotice.labeling.grouping_model import PLACEHOLDER, URL, validate_grouping_mention
from smartnotice.parsers.email import EmailRouting
from smartnotice.schemas import GroupingModelMention, Notice, Sentence

_SECTION = re.compile(r"^[\s*#-]*(?:\d{1,2}[.)]|[IVX]{1,4}[.)]|chuyên đề\s+\d+\s*:)\s*", re.I)
_CODE = re.compile(
    r"\b(?:mã (?:sự kiện|cuộc thi|chương trình|đợt)|event code)\s*:\s*([\w-]{3,})\b", re.I
)
_EDITION = re.compile(r"\b(đợt|vòng|phiên|ca|lần thứ)\s+(\d{1,2})\b", re.I)
_CLASS_CODE = re.compile(r"\b(?:mã lớp|lớp học phần)\s*:?\s*([a-z]{1,8}\d{1,8}[a-z0-9-]*)\b", re.I)
_WORD = re.compile(r"[^\W\d_]{2,}")
_REPLY_PREFIX = re.compile(r"^\s*(?:(?:re|fw|fwd)\s*:\s*|\[[^]\n]+\]\s*)+", re.I)
_CONTINUATION = re.compile(
    r"\b(?:gia hạn|nhắc lại|nhắc nhở|đính chính|cập nhật|bổ sung|gửi lại)\b", re.I
)
_STOP = frozenset(
    "của các trong được cho là có tại với để theo từ đến vào một này sẽ đã khi những "
    "thời gian ngày tháng năm mời kính chào thưa vui lòng sinh viên phòng khoa trường "
    "thông báo tham gia đăng ký kí học phần hướng dẫn liên hệ biểu mẫu báo cáo xem "
    "lại trước sau trên dưới bạn em anh chị mọi người mới tiếp nhận gửi".split()
)
_NON_REPLY_WINDOW_SECONDS = 30 * 86400


@dataclass(frozen=True, repr=False)
class FollowupProfile:
    """Keep provisional match cues and prepared sentence references in memory."""

    mention_id: str
    doc_id: str
    sentences: tuple[str, ...]
    codes: dict[str, str]
    forms: dict[str, str]
    phrases: dict[tuple[str, ...], str]
    local_phrases: dict[tuple[str, ...], str]
    editions: frozenset[tuple[str, str]]
    classes: frozenset[str]
    scope: AcademicScope
    subject: tuple[str, ...]
    continuation: bool
    ambiguous: bool
    action_text: str
    evidence_text: tuple[str, ...]


@dataclass(frozen=True)
class FollowupAlignment:
    """Give a categorical reason and ordered prepared sentence IDs for both sides."""

    reason: str
    sentence_ids: tuple[tuple[str, ...], tuple[str, ...]]


def _words(text: str) -> tuple[str, ...]:
    clean = URL.sub(" ", PLACEHOLDER.sub(" ", text))
    return tuple(w for w in _WORD.findall(clean.casefold()) if w not in _STOP)


def _profile(
    mention: GroupingModelMention,
    notice: Notice,
    sentences: Sequence[Sentence],
    subject: str,
    crosses_sections: bool,
) -> FollowupProfile:
    codes, forms, phrases, local_phrases = {}, {}, {}, {}
    editions = set()
    classes = set()
    source_words = set()
    mention_ids = set(mention.event.evidence_sentence_ids)
    continuation = bool(_CONTINUATION.search(subject))
    for sentence in sentences:
        text = unicodedata.normalize("NFC", sentence.text)
        for code in _CODE.findall(text):
            codes.setdefault(code.casefold(), sentence.sentence_id)
        for form in event_form_keys(text):
            forms.setdefault(form, sentence.sentence_id)
        editions.update(_EDITION.findall(text.casefold()))
        classes.update(_CLASS_CODE.findall(text.casefold()))
        words = _words(text)
        source_words.update(words)
        for phrase in zip(words, words[1:], words[2:], strict=False):
            if len(set(phrase)) == 3:
                phrases.setdefault(phrase, sentence.sentence_id)
        if sentence.sentence_id in mention_ids:
            for phrase in zip(words, words[1:], words[2:], words[3:], strict=False):
                if len(set(phrase)) == 4:
                    local_phrases.setdefault(phrase, sentence.sentence_id)
        continuation |= bool(_CONTINUATION.search(text))
    title = _words(_CONTINUATION.sub(" ", _REPLY_PREFIX.sub("", subject)))
    title = title if len(set(title) & source_words) >= 3 else ()
    # Limit the academic parser's heading lookup to this item's prepared sentences.
    scoped_notice = notice.model_copy(update={"sentences": list(sentences)})
    return FollowupProfile(
        mention.mention_id,
        notice.doc_id,
        tuple(s.sentence_id for s in sentences),
        codes,
        forms,
        phrases,
        local_phrases,
        frozenset(editions),
        frozenset(classes),
        academic_scope(mention, scoped_notice),
        title,
        continuation,
        crosses_sections
        or len(codes) > 1
        or len(classes) > 1
        or len({kind for kind, _ in editions}) < len(editions),
        next(s.text for s in mention.spans if s.span_id == mention.event.action_span_id),
        tuple(s.text for s in sentences),
    )


def build_followup_profiles(
    notice: Notice,
    mentions: Sequence[GroupingModelMention],
    header: EmailRouting | None = None,
) -> tuple[FollowupProfile, ...]:
    """Profile all ACTION mentions of one document with validated source offsets.

    A single mention in a numbered section can draw on that whole section.
    Mentions sharing a section only use their annotated evidence. An optional
    verified subject supports unnumbered, single-mention notices in memory.
    Reject stale or duplicate mention references with ValueError.
    """
    sentence_indices = {s.sentence_id: i for i, s in enumerate(notice.sentences)}
    boundaries = [0]
    boundaries.extend(i for i, s in enumerate(notice.sentences) if i and _SECTION.match(s.text))
    sections = {}
    for start, end in zip(boundaries, [*boundaries[1:], len(notice.sentences)], strict=True):
        sections.update(dict.fromkeys(range(start, end), (start, end)))
    entries = defaultdict(list)
    seen = set()
    for mention in mentions:
        validate_grouping_mention(mention, notice)
        if mention.mention_id in seen or mention.version.event_ref in seen:
            raise ValueError(f"Duplicate follow-up mention for {notice.doc_id}")
        seen.update((mention.mention_id, mention.version.event_ref))
        action = next(s for s in mention.spans if s.span_id == mention.event.action_span_id)
        sentence = next(s for s in mention.sentences if s.start <= action.start < s.end)
        start, end = sections[sentence_indices[sentence.sentence_id]]
        entries[start, end].append(mention)
    numbered = len(boundaries) > 1 or any(_SECTION.match(s.text) for s in notice.sentences[:1])
    subject = ""
    if header and header.subject and len(mentions) == 1 and not numbered:
        subject = header.subject
    profiles = []
    for (start, end), items in entries.items():
        section = notice.sentences[start:end]
        section_ids = {s.sentence_id for s in section}
        for mention in items:
            known_ids = set(mention.event.evidence_sentence_ids)
            crosses_sections = not known_ids <= section_ids
            sentences = (
                section if len(items) == 1 else [s for s in section if s.sentence_id in known_ids]
            )
            profiles.append(_profile(mention, notice, sentences, subject, crosses_sections))
    return tuple(profiles)


def _scope_conflict(left: FollowupProfile, right: FollowupProfile) -> bool:
    if left.codes and right.codes and left.codes.keys().isdisjoint(right.codes):
        return True
    left_editions, right_editions = dict(left.editions), dict(right.editions)
    if any(
        left_editions[k] != right_editions[k] for k in left_editions.keys() & right_editions.keys()
    ):
        return True
    if left.classes and right.classes and left.classes.isdisjoint(right.classes):
        return True
    a, b = left.scope, right.scope
    return (
        a.ambiguous
        or b.ambiguous
        or any(
            x is not None and y is not None and x != y
            for x, y in zip(
                (a.kind, a.year, a.term, a.course, a.phase),
                (b.kind, b.year, b.term, b.course, b.phase),
                strict=True,
            )
        )
    )


def compatible_followup_items(left: FollowupProfile, right: FollowupProfile) -> bool:
    """Return whether two distinct documents have no ambiguous or conflicting scope."""
    return (
        left.doc_id != right.doc_id
        and not (left.ambiguous or right.ambiguous)
        and not _scope_conflict(left, right)
    )


def _anchor(
    left: FollowupProfile, right: FollowupProfile, routing: RoutingComparison
) -> tuple[int, FollowupAlignment] | None:
    if not compatible_followup_items(left, right):
        return None
    codes = left.codes.keys() & right.codes.keys()
    forms = left.forms.keys() & right.forms.keys()
    phrases = left.phrases.keys() & right.phrases.keys()
    if routing.direct_parent:
        if codes:
            code = min(codes)
            return 3, FollowupAlignment(
                "direct_reply_event_code", ((left.codes[code],), (right.codes[code],))
            )
        a, b = left.scope, right.scope
        values = (a.year, a.term, a.course, a.phase)
        if (
            a.kind == b.kind == "exam"
            and all(value is not None for value in values)
            and values == (b.year, b.term, b.course, b.phase)
        ):
            return 2, FollowupAlignment(
                "direct_reply_exam_scope", (left.sentences, right.sentences)
            )
    else:
        later = (left, right)[routing.later] if routing.later is not None else None
        if not (
            later
            and later.continuation
            and routing.gap_seconds is not None
            and 0 < routing.gap_seconds <= _NON_REPLY_WINDOW_SECONDS
            and left.subject
            and left.subject == right.subject
            and len(forms) == 1
        ):
            return None
    if forms and phrases:
        form, phrase = min(forms), min(phrases)
        ordered_ids = tuple(
            tuple(
                sid
                for sid in profile.sentences
                if sid in (profile.forms[form], profile.phrases[phrase])
            )
            for profile in (left, right)
        )
        return 2, FollowupAlignment(
            "continuation_form_and_phrase",
            (ordered_ids[0], ordered_ids[1]),
        )
    local_phrases = left.local_phrases.keys() & right.local_phrases.keys()
    if routing.direct_parent and local_phrases:
        phrase = min(local_phrases)
        return 1, FollowupAlignment(
            "direct_reply_shared_phrase",
            ((left.local_phrases[phrase],), (right.local_phrases[phrase],)),
        )
    return None


def align_followup_mentions(
    left: Sequence[FollowupProfile],
    right: Sequence[FollowupProfile],
    routing: RoutingComparison,
) -> dict[tuple[str, str], FollowupAlignment]:
    """Return mutually unique, strongest links across both documents' mentions.

    Keys follow the input document order. Repeated cues, mismatched explicit
    scope, or tie scores keep affected mentions out of the result. Links provide
    candidate event identity and source locations for the downstream policy.
    """
    supported = {}
    left_ranks, right_ranks = defaultdict(list), defaultdict(list)
    for a in left:
        for b in right:
            if a.doc_id == b.doc_id or not (match := _anchor(a, b, routing)):
                continue
            key = (a.mention_id, b.mention_id)
            rank, evidence = match
            supported[key] = evidence
            left_ranks[a.mention_id].append((rank, key))
            right_ranks[b.mention_id].append((rank, key))

    def winners(ranks):
        result = set()
        for choices in ranks.values():
            top = max(rank for rank, _ in choices)
            best = [key for rank, key in choices if rank == top]
            if len(best) == 1:
                result.add(best[0])
        return result

    return {key: supported[key] for key in sorted(winners(left_ranks) & winners(right_ranks))}

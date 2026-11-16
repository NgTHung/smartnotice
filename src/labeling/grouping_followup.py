"""Link an event mention to a named or referenced earlier notice."""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from smartnotice.labeling.grouping_evidence import PairEvidence, event_form_keys, mention_context
from smartnotice.parsers.email import EmailRouting, parse_email_routing
from smartnotice.schemas import GroupingModelMention, Notice

RAPID_SECONDS = 15 * 60
_EVENT = (
    r"hội nghị|hội thảo|seminar|workshop|giải thưởng|cuộc thi|chiến dịch|"
    r"talkshow|ngày hội|chương trình|học bổng"
)
_TITLE = re.compile(
    rf'(?:\b(?:{_EVENT})\s+)(?:["“]([^"”\r\n]{{5,160}})["”]|([^.!?;:\n]{{5,160}}))',
    re.I,
)
_TITLE_END = re.compile(
    r"\s+(?:với|như sau|do|thuộc|sẽ|được|vui lòng|và các mẫu|"
    r'tại đây|đăng ký tại|thông tin theo)\b|[,:(\[\]”"]',
    re.I,
)
_ITEM = re.compile(rf"^[\s*#-]*\d{{1,2}}[.)]\s+(?:{_EVENT})\b", re.I)
_UPDATE = re.compile(
    r"\b(?:xin\s+bổ sung|thông tin bổ sung|bổ sung thông tin|đính chính|gia hạn|"
    r"cập nhật|nhắc lại|nhắc nhở|sắp hết hạn|sẽ hết hạn|gửi lại|xin thông tin lại|"
    r"nhầm lẫn về|(?:thư|email|thông báo) (?:trước|vừa gửi)|"
    r"đăng k[ýí] lại|thay đổi lịch|điều chỉnh lịch)\b",
    re.I,
)
_ATTACHMENT = re.compile(r"\b(?:đính kèm|tệp kèm|file kèm|gửi lại)\b", re.I)
_ARTICLE = re.compile(
    r"\b(?:lịch thi|thời khóa biểu|lịch học|biểu mẫu|danh sách|đề cương|tài liệu)\b", re.I
)
_PRIOR_NOTICE = re.compile(
    r"\b(?:thư|email|thông báo|biểu mẫu|bản) (?:gốc|trước|cũ|vừa gửi|đã gửi)\b", re.I
)
_STOP = frozenset(
    "và của các trong về được cho là tại với để theo từ đến vào một này "
    "sẽ đã khi thông tin nhắc hội thảo nghị thi giải thưởng trình chương ngày "
    "sinh viên tổ chức thực hiện đăng ký thông báo chi tiết các bạn năm học".split()
)


@dataclass(frozen=True)
class RoutingComparison:
    """Expose directional header facts without an address or header identifier."""

    later: int | None
    gap_seconds: int | None
    same_sender: bool
    direct_parent: bool

    @property
    def rapid(self) -> bool:
        """Return whether a known sender sent the second email within 15 minutes."""
        return (
            self.same_sender
            and self.gap_seconds is not None
            and 0 < self.gap_seconds <= RAPID_SECONDS
        )


@dataclass(frozen=True)
class FollowupEvidence:
    """Describe the active ways to link a follow-up and their source pointers."""

    title: bool
    reference: bool
    joint: bool
    routing: RoutingComparison
    title_sentences: tuple[tuple[str, ...], tuple[str, ...]]
    reason: str | None


def load_email_routing(notice: Notice, directory: Path) -> EmailRouting | None:
    """Verify local source bytes and parse private header facts in memory.

    Return None for an absent source or a web notice. Reject a raw hash mismatch.
    """
    if notice.source_type != "email" or not re.fullmatch(r"[a-f0-9]{64}", notice.raw_sha256):
        return None
    path = directory / f"{notice.raw_sha256}.eml"
    if not path.is_file():
        return None
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != notice.raw_sha256:
        raise ValueError(f"Email source hash differs for {notice.doc_id}")
    return parse_email_routing(raw)


def compare_routing(left: EmailRouting | None, right: EmailRouting | None) -> RoutingComparison:
    """Compare send times and one exact parent reference in a pair of emails."""
    if left is None or right is None:
        return RoutingComparison(None, None, False, False)
    later = None
    gap = None
    if left.sent_at is not None and right.sent_at is not None:
        delta = (right.sent_at - left.sent_at).total_seconds()
        later = (1 if delta > 0 else 0) if delta else None
        gap = int(abs(delta))
    right_replies = bool(left.message_id and left.message_id == right.parent_id)
    left_replies = bool(right.message_id and right.message_id == left.parent_id)
    child = (1 if right_replies else 0) if right_replies != left_replies else None
    direct = child is not None and later in (None, child)
    return RoutingComparison(
        child if direct and later is None else later,
        gap,
        bool(left.sender and left.sender == right.sender),
        direct,
    )


def _title_tokens(value: str) -> tuple[str, ...]:
    value = unicodedata.normalize("NFC", value).casefold()
    return tuple(w for w in re.findall(r"[^\W\d_]{2,}", value) if w not in _STOP)


def _titles(mention: GroupingModelMention, notice: Notice):
    scoped = any(_ITEM.match(s.text) for s in notice.sentences)
    index = {s.sentence_id: i for i, s in enumerate(notice.sentences)}
    selected = sorted(index[s.sentence_id] for s in mention.sentences)
    if not selected:
        return [], scoped
    if scoped:
        headings = [i for i, s in enumerate(notice.sentences) if _ITEM.match(s.text)]
        start = max((i for i in headings if i <= selected[0]), default=0)
        stop = min((i for i in headings if i > start), default=len(notice.sentences))
        if selected[-1] >= stop:
            return [], True
        candidates = notice.sentences[start : min(stop, start + 4)]
    else:
        chosen = set(range(min(6, len(notice.sentences))))
        chosen.update(i for j in selected for i in range(max(j - 2, 0), j + 1))
        candidates = [notice.sentences[i] for i in sorted(chosen)]
    results = {}
    for sentence in candidates:
        i = index[sentence.sentence_id]
        after = notice.sentences[i + 1 : i + 2]
        if after and (_ITEM.match(after[0].text) or scoped and i + 1 >= stop):
            after = []
        context = " ".join(s.text.replace("*", "") for s in [sentence, *after])
        for match in _TITLE.finditer(context):
            if match.start() >= len(sentence.text.replace("*", "")):
                continue
            text = match[1] or _TITLE_END.split(match[2], maxsplit=1)[0]
            words = _title_tokens(text)
            if len(set(words)) >= 3:
                ids = (sentence.sentence_id,)
                if match.end() > len(sentence.text.replace("*", "")) and after:
                    ids += (after[0].sentence_id,)
                results.setdefault(words, ids)
    return list(results.items()), scoped


def _title_similarity(left, right) -> tuple[bool, bool]:
    a, b = set(left), set(right)
    shared = a & b
    score = len(shared) / len(a | b)
    prefix = left[: min(len(left), len(right))] == right[: min(len(left), len(right))]
    return len(shared) >= 3 and (score >= 0.8 or prefix), len(shared) >= 4 and score >= 0.55


def followup_evidence(
    left: GroupingModelMention,
    right: GroupingModelMention,
    notices: tuple[Notice, Notice],
    headers: tuple[EmailRouting | None, EmailRouting | None],
    base: PairEvidence,
) -> FollowupEvidence:
    """Return separate title, reference, and joint cues for a possible follow-up.

    Use only validated prepared mentions for content. A recent send time or
    shared mailbox alone cannot identify an event. Keep feature provenance as
    sentence IDs and categorical routing facts.
    """
    a, b = notices
    routing = compare_routing(*headers)
    context = (mention_context(left, a), mention_context(right, b))
    titles_a, scoped_a = _titles(left, a)
    titles_b, scoped_b = _titles(right, b)
    marker = [bool(_UPDATE.search(x)) for x in context]
    for i, (notice, scoped) in enumerate(zip(notices, (scoped_a, scoped_b), strict=True)):
        if not scoped:
            lead = " ".join(s.text for s in notice.sentences[:6])
            marker[i] |= bool(_UPDATE.search(lead))
    later = routing.later
    if (
        later is None
        and a.reference_date
        and b.reference_date
        and a.reference_date != b.reference_date
    ):
        later = int(a.reference_date < b.reference_date)
    is_followup = marker[later] if later is not None else any(marker)
    date_close = bool(
        a.reference_date
        and b.reference_date
        and abs((a.reference_date - b.reference_date).days) <= 90
    )
    strong = weak = False
    pointers: tuple[tuple[str, ...], tuple[str, ...]] = ((), ())
    for words_a, ids_a in titles_a:
        for words_b, ids_b in titles_b:
            exact, fuzzy = _title_similarity(words_a, words_b)
            if exact or (fuzzy and not strong):
                pointers = (ids_a, ids_b)
            strong |= exact
            weak |= fuzzy or exact
    common_form = bool(event_form_keys(context[0]) & event_form_keys(context[1]))
    near_topic = base.features[0] >= 0.30 and base.features[1] > 0
    blocked = base.conflict or not is_followup
    title = not blocked and strong and date_close
    unambiguous = not (scoped_a or scoped_b)
    shared_article = {w.casefold() for w in _ARTICLE.findall(context[0])} & {
        w.casefold() for w in _ARTICLE.findall(context[1])
    }
    addendum = (
        later is not None and bool(_ATTACHMENT.search(context[later])) and bool(shared_article)
    )
    parent = routing.direct_parent and (common_form or near_topic or (addendum and unambiguous))
    rapid = routing.rapid and (common_form or near_topic or addendum) and unambiguous
    form_reference = (
        common_form and date_close and near_topic and any(_PRIOR_NOTICE.search(x) for x in context)
    )
    reference = not blocked and (parent or rapid or form_reference)
    corroborated = (routing.direct_parent or routing.rapid or common_form) and weak
    joint = title or reference or (not blocked and corroborated)
    if reference and not any(pointers) and later is not None:
        original = titles_a if later == 1 else titles_b
        if len(original) == 1:
            pointers = (original[0][1], ()) if later == 1 else ((), original[0][1])
    reason = None
    if joint:
        reason = (
            "direct_parent"
            if reference and parent
            else "rapid_same_sender_with_topic"
            if reference and rapid
            else "prior_notice_with_matching_form"
            if reference and form_reference
            else "recovered_title"
            if title
            else "title_with_corroborating_reference"
        )
    return FollowupEvidence(title, reference, joint, routing, pointers, reason)

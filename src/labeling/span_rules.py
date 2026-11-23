"""Propose sentence-bounded evidence spans using Vietnamese cues and a training phrase list."""

import re
from collections import Counter, defaultdict
from collections.abc import Iterable

from smartnotice.schemas import Annotation, Notice

_TOKEN = re.compile(r"\w+|[^\w\s]")
_ACTION = (
    r"đăng ký|đăng kí|nộp|gửi|đóng|thanh toán|hoàn thành|cập nhật|xác nhận|tham gia|"
    r"tham dự|điền|bổ sung|kiểm tra|liên hệ|nhận|tra cứu|phản hồi"
)
_AUDIENCE = r"sinh viên|học viên|nghiên cứu sinh|thí sinh|tân sinh viên"
_DOCUMENT = (
    r"hồ sơ|biểu mẫu|minh chứng|giấy chứng nhận|giấy xác nhận|bản sao|đơn đề nghị|phiếu đăng ký"
)
_CONDITION = r"nếu|trường hợp|với điều kiện|ngoại trừ"
_BOUNDARY = re.compile(
    r"[,;:.!?\n]|\s+(?:trước|chậm nhất|từ ngày|đến ngày|qua|tại|theo đường dẫn|để|nhằm|và (?:"
    + _ACTION
    + r"))\b",
    re.I,
)
_CUES = {
    label: re.compile(r"\b(?:" + cue + r")\b", re.I)
    for label, cue in [
        ("ACTION", _ACTION),
        ("AUDIENCE", _AUDIENCE),
        ("DOCUMENT", _DOCUMENT),
        ("CONDITION", _CONDITION),
    ]
}
_AUDIENCE_END = re.compile(r"\s+(?:(?:phải|cần|được|vui lòng)\b|(?:" + _ACTION + r")\b)", re.I)
_DATE = re.compile(
    r"(?<!\d)\d{1,2}([/-])\d{1,2}(?:\1\d{4})?(?![\d/-])|\b\d{1,2}\s*(?:giờ|h)\s*\d{0,2}\b", re.I
)
_CHANNEL = re.compile(
    r"https?://[^\s<>]+|\[(?:REDACTED_URL|URL)\]|"
    r"\b(?:email|moodle|google form|cổng thông tin sinh viên)\b",
    re.I,
)


def _key(word):
    return re.sub(r"\d", "0", word.casefold())


class SpanRules:
    """Combine hand-written patterns with optional token phrases recurring in training documents."""

    def __init__(self):
        self.phrases = defaultdict(dict)

    def fit_phrases(self, annotations: Iterable[Annotation], min_documents: int = 2) -> None:
        """Index typed token sequences found in at least min_documents distinct training notices."""
        support = Counter()
        seen = set()
        for annotation in annotations:
            if annotation.doc_id in seen:
                raise ValueError("Duplicate training notice")
            seen.add(annotation.doc_id)
            support.update(
                {
                    (tuple(_key(t) for t in _TOKEN.findall(s.text)), s.label)
                    for s in annotation.spans
                }
            )
        self.phrases.clear()
        for (words, label), count in support.items():
            if words and count >= min_documents:
                self.phrases[words[0]].setdefault(words, set()).add(label)

    def predict(self, notice: Notice, *, phrases: bool = False) -> set[tuple[int, int, str]]:
        """Return sentence-bounded offsets, keeping the longest match per start and type."""
        spans = {}
        for sent in notice.sentences:
            text = notice.text[sent.start : sent.end]

            def add(a, b, label, offset=sent.start):
                bounds = (offset + a, label)
                spans[bounds] = max(spans.get(bounds, 0), offset + b)

            for label, pattern in (("TIME", _DATE), ("CHANNEL", _CHANNEL)):
                for match in pattern.finditer(text):
                    end = match.start() + len(match.group().rstrip(".,;:!?) "))
                    add(match.start(), end, label)
            for label, cue in _CUES.items():
                for match in cue.finditer(text):
                    end = min(
                        [
                            m.start()
                            for p in (
                                (_BOUNDARY, _AUDIENCE_END) if label == "AUDIENCE" else (_BOUNDARY,)
                            )
                            if (m := p.search(text, match.end()))
                        ]
                        or [len(text)]
                    )
                    tail = list(re.finditer(r"\S+", text[match.end() : end]))
                    limit = 12 if label == "CONDITION" else 7
                    end = match.end() + (tail[min(len(tail), limit) - 1].end() if tail else 0)
                    add(match.start(), end, label)
            if phrases:
                tokens = list(_TOKEN.finditer(text))
                words = [_key(t.group()) for t in tokens]
                for i, word in enumerate(words):
                    for phrase, labels in self.phrases.get(word, {}).items():
                        if tuple(words[i : i + len(phrase)]) == phrase:
                            for label in labels:
                                add(tokens[i].start(), tokens[i + len(phrase) - 1].end(), label)
        return {(a, b, label) for (a, label), b in spans.items()}

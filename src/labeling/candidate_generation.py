"""Generate typed span candidates from rules on the exact prepared text."""

import re
from collections import defaultdict
from typing import get_args

from smartnotice.labeling.llm import text_sha256
from smartnotice.preprocessing.links import WEB_LINK, extract_links
from smartnotice.preprocessing.text import segment_sentences
from smartnotice.schemas import Notice, SpanCandidate, SpanLabel

GENERATOR_VERSION = "span-rules-v1"
LABELS = get_args(SpanLabel)
_TRIM = " \t.,;:!?–—"
_DATE = r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{4})?"
_CLOCK = r"(?:\d{1,2}h(?:\d{2})?|\d{1,2}:\d{2})(?:\s*phút)?"
_TIME = rf"(?:ngày\s+\d{{1,2}}\s+tháng\s+\d{{1,2}}(?:\s+năm\s+\d{{4}})?|{_DATE}|{_CLOCK})"
_STRUCTURES = {
    "time.expression": (
        "TIME",
        re.compile(rf"(?<![\w/-]){_TIME}(?![\w/-])", re.I),
    ),
    "time.leadin": (
        "TIME",
        re.compile(rf"\b(?:trước|đến|từ|lúc)\s+(?:ngày\s+)?{_TIME}(?![\w/-])", re.I),
    ),
    "time.relative": (
        "TIME",
        re.compile(r"\b(?:hôm nay|ngày mai|tuần sau|cuối tuần|cuối tháng)\b", re.I),
    ),
}
_ANCHORS = {
    "ACTION": r"nộp|đăng ký|hoàn thành|bổ sung|xác nhận|tham gia|gửi|thanh toán|cập nhật",
    "AUDIENCE": r"sinh viên|học viên|nghiên cứu sinh|khóa|ngành|lớp|đối tượng",
    "DOCUMENT": r"đơn|hồ sơ|giấy xác nhận|bản sao|minh chứng|biểu mẫu",
    "CHANNEL": r"qua|tại|trực tiếp|trực tuyến|cổng thông tin|phòng",
    "CONDITION": r"nếu|đáp ứng|với điều kiện|không thuộc|trừ|đã|chưa|yêu cầu",
}
_ANCHOR_PATTERNS = {
    label: re.compile(rf"\b(?:{pattern})\b", re.I) for label, pattern in _ANCHORS.items()
}
_FIELD = re.compile(
    r"^\s*(?:[-•*]\s*)?(đối tượng|hạn nộp|thời gian|hồ sơ gồm|kênh thực hiện|"
    r"hình thức|điều kiện|công việc)\s*:\s*",
    re.I,
)
_FIELD_LABEL = {
    "đối tượng": "AUDIENCE",
    "hạn nộp": "TIME",
    "thời gian": "TIME",
    "hồ sơ gồm": "DOCUMENT",
    "kênh thực hiện": "CHANNEL",
    "hình thức": "CHANNEL",
    "điều kiện": "CONDITION",
    "công việc": "ACTION",
}
_CLAUSE_END = re.compile(r"[,;]|\s+(?:trước ngày|đến ngày|thông qua|qua|tại)\b", re.I)
_PREFIX = re.compile(r"\b(?:không cần|không được|đã|chưa|ngoại trừ)\s+$", re.I)


def generate_span_candidates(
    notice: Notice, max_units: dict[SpanLabel, int]
) -> list[SpanCandidate]:
    """Return unique typed spans in offset order with sorted rule provenance.

    Phrase limits count whitespace-delimited units. Atomic time and URL
    expressions use their own structural boundaries. Input is never rewritten.
    """
    if set(max_units) != set(LABELS) or any(
        type(limit) is not int or limit < 1 for limit in max_units.values()
    ):
        raise ValueError("Provide a positive integer phrase limit for each span label")
    text = notice.text
    found = defaultdict(set)

    def emit(label, start, end, rule, *, atomic=False):
        raw = text[start:end]
        start += len(raw) - len(raw.lstrip(_TRIM))
        end -= len(raw) - len(raw.rstrip(_TRIM))
        if start < end and (atomic or len(text[start:end].split()) <= max_units[label]):
            found[start, end, label].add(rule)

    for match in WEB_LINK.finditer(text):
        # Parse the matched slice, then keep only links that retain exact offsets.
        _, urls = extract_links(match.group())
        for url in urls:
            if match.group().startswith(url):
                found[match.start(), match.start() + len(url), "CHANNEL"].add("channel.url")

    # Use the owning segmenter so sentence boundaries keep the offset convention.
    sentences = notice.sentences or segment_sentences(text)
    for sentence in sentences:
        base = sentence.start
        line = sentence.text
        for rule, (label, pattern) in _STRUCTURES.items():
            for match in pattern.finditer(line):
                emit(label, base + match.start(), base + match.end(), rule, atomic=True)
        field = _FIELD.match(line)
        if field:
            label = _FIELD_LABEL[field[1].casefold()]
            parts = re.finditer(r"[^;]+", line[field.end() :])
            for part in parts:
                start = base + field.end() + part.start()
                emit(label, start, start + len(part.group()), "field.value")
        for label, pattern in _ANCHOR_PATTERNS.items():
            for anchor in pattern.finditer(line):
                prefix = _PREFIX.search(line[: anchor.start()])
                start = base + anchor.start()
                stops = [anchor.end(), len(line)]
                clause = _CLAUSE_END.search(line, anchor.end())
                if clause is not None:
                    stops.append(clause.start())
                words = list(re.finditer(r"\S+", line[anchor.end() :]))
                stops.extend(anchor.end() + word.end() for word in words[:4])
                available = max_units[label] - len(anchor.group().split())
                if 0 < available <= len(words):
                    stops.append(anchor.end() + words[available - 1].end())
                for stop in stops:
                    emit(label, start, base + stop, "anchor." + label.lower())
                    if prefix is not None:
                        emit(label, base + prefix.start(), base + stop, "anchor.qualifier")

    digest = text_sha256(notice)
    return [
        SpanCandidate(
            doc_id=notice.doc_id,
            text_sha256=digest,
            start=start,
            end=end,
            text=text[start:end],
            proposed_label=label,
            rule_ids=sorted(rules),
            generator_version=GENERATOR_VERSION,
        )
        for (start, end, label), rules in sorted(found.items())
    ]

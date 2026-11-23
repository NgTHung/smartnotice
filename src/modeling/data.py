"""Read the frozen development split and align evidence with tokenizer offsets."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from smartnotice.io import read_jsonl
from smartnotice.labeling.validation import validate_annotation
from smartnotice.schemas import Annotation, Notice, Span

SPAN_LABELS = ("NONE", "ACTION", "TIME", "AUDIENCE", "CONDITION", "CHANNEL", "DOCUMENT")
TIME_ROLES = ("START", "DEADLINE", "EVENT_TIME")
LINK_LABELS = ("NO_RELATION", *TIME_ROLES, *SPAN_LABELS[3:])
type SpanKey = tuple[int, int, str]
type LinkKey = tuple[SpanKey, SpanKey, str]


@dataclass(frozen=True)
class Document:
    """Bind canonical labeled evidence to a prepared notice and its frozen group."""

    notice: Notice
    annotation: Annotation
    group_id: str


@dataclass(frozen=True)
class Location:
    """Store the window index and inclusive token endpoints for a character interval."""

    window: int
    first: int
    last: int
    margin: int

    @property
    def width(self) -> int:
        """Return the number of tokens in the interval."""
        return self.last - self.first + 1


@dataclass
class TokenDocument:
    """Keep overflow windows and a canonical token location for each span candidate."""

    document: Document
    windows: list[list[int]]
    candidates: dict[tuple[int, int], Location]


def sha256(path: Path) -> str:
    """Return a SHA-256 digest of the original file bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_development(root: Path) -> tuple[dict[str, list[Document]], dict]:
    """Load verified train and validation files while leaving reserved notices unopened."""
    manifest = json.loads((root / "checksums.json").read_text(encoding="utf-8"))
    files = ["record.json", "assignments.jsonl"]
    files += [
        f"{part}/{name}.jsonl"
        for part in ("train", "validation")
        for name in ("notices", "annotations")
    ]
    hashes = {name: sha256(root / name) for name in files}
    if hashes != {name: manifest[name] for name in files}:
        raise ValueError("Drive release checksum mismatch")
    record = json.loads((root / "record.json").read_text(encoding="utf-8"))
    assignments = {}
    group_splits = {}
    for row in read_jsonl(root / "assignments.jsonl"):
        if row["doc_id"] in assignments:
            raise ValueError("Duplicate split assignment")
        assignments[row["doc_id"]] = row
        split = "reserved" if row["split"] in {"domain_test", "excluded"} else row["split"]
        if group_splits.setdefault(row["group_id"], split) != split:
            raise ValueError("Frozen group crosses split boundaries")

    result = {}
    for part in ("train", "validation"):
        notices = [Notice.model_validate(row) for row in read_jsonl(root / part / "notices.jsonl")]
        annotations = [
            Annotation.model_validate(row) for row in read_jsonl(root / part / "annotations.jsonl")
        ]
        by_id = {n.doc_id: n for n in notices}
        expected = {key for key, row in assignments.items() if row["split"] == part}
        if (
            len(annotations) != len(notices)
            or len(by_id) != len(notices)
            or set(by_id) != expected
            or {a.doc_id for a in annotations} != expected
        ):
            raise ValueError(f"Incomplete or duplicate development records in {part}")
        documents = []
        for annotation in annotations:
            notice = by_id[annotation.doc_id]
            assignment = assignments[notice.doc_id]
            text_hash = hashlib.sha256(notice.text.encode("utf-8")).hexdigest()
            if text_hash != assignment["text_sha256"] or notice.synthetic:
                raise ValueError(f"Unexpected prepared text or synthetic source: {notice.doc_id}")
            validate_annotation(annotation, notice)
            documents.append(Document(notice, annotation, assignment["group_id"]))
        result[part] = documents
    return result, {
        "hashes": hashes,
        "split_counts": record["split_counts"],
        "annotation_origin": record["annotation_origin"],
        "gold_ready": record["gold_ready"],
        "manual_group_review_completed": record["manual_group_review_completed"],
    }


def span_key(span: Span) -> SpanKey:
    """Identify a span by typed document character offsets."""
    return span.start, span.end, span.label


def labeled_links(annotation: Annotation) -> set[LinkKey]:
    """Return positive directed links with exact typed endpoints and relation labels."""
    spans = {s.span_id: span_key(s) for s in annotation.spans}
    return {
        (spans[event.action_span_id], spans[arg.span_id], arg.role or spans[arg.span_id][2])
        for event in annotation.events
        for arg in event.arguments
    }


def _trim_offsets(text: str, offsets: list[tuple[int, int]]) -> list[tuple[int, int]]:
    # BamiBERT can include the preceding space in a word's first subword.
    trimmed = []
    for start, end in offsets:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        trimmed.append((start, end))
    return trimmed


def tokenize(document: Document, tokenizer, length: int, overlap: int, width: int) -> TokenDocument:
    """Enumerate bounded spans inside source sentences, retaining one window per interval."""
    text = document.notice.text
    encoded = tokenizer(
        text,
        max_length=length,
        truncation=True,
        stride=overlap,
        return_overflowing_tokens=True,
        return_offsets_mapping=True,
    )
    candidates: dict[tuple[int, int], Location] = {}
    sentences = document.notice.sentences
    for window, raw_offsets in enumerate(encoded["offset_mapping"]):
        offsets = _trim_offsets(text, raw_offsets)
        valid = [i for i, (a, b) in enumerate(offsets) if a < b]
        if not valid:
            continue
        sentence_index = 0
        for first in valid:
            start = offsets[first][0]
            while sentence_index < len(sentences) and sentences[sentence_index].end <= start:
                sentence_index += 1
            if sentence_index == len(sentences) or start < sentences[sentence_index].start:
                continue
            for last in range(first, min(first + width, valid[-1] + 1)):
                last_start, end = offsets[last]
                if end <= last_start:
                    continue
                if end > sentences[sentence_index].end:
                    break
                if end <= start:
                    continue
                key = (start, end)
                margin = min(first - valid[0], valid[-1] - last)
                hit = Location(window, first, last, margin)
                current = candidates.get(key)
                if current is None or (hit.margin, -hit.width) > (current.margin, -current.width):
                    candidates[key] = hit
    return TokenDocument(document, encoded["input_ids"], candidates)


def choose_width(documents: list[Document], tokenizer, length: int, overlap: int) -> int:
    """Estimate the 99th percentile of exactly alignable training span widths."""
    widths = []
    for doc in documents:
        windows = tokenizer(
            doc.notice.text,
            max_length=length,
            truncation=True,
            stride=overlap,
            return_overflowing_tokens=True,
            return_offsets_mapping=True,
        )
        boundaries = [
            (
                dict((a, i) for i, (a, b) in enumerate(w) if a < b),
                {b: i for i in reversed(range(len(w))) if (b := w[i][1]) > w[i][0]},
            )
            for w in (_trim_offsets(doc.notice.text, raw) for raw in windows["offset_mapping"])
        ]
        for span in doc.annotation.spans:
            matches = [
                ends[span.end] - starts[span.start] + 1
                for starts, ends in boundaries
                if span.start in starts
                and span.end in ends
                and ends[span.end] >= starts[span.start]
            ]
            if matches:
                widths.append(min(matches))
    if not widths:
        raise ValueError("No training spans align to the tokenizer")
    return max(1, sorted(widths)[(99 * len(widths) + 99) // 100 - 1])

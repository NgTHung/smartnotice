"""Record train/validation span and relation diagnostics without reading test labels.

Run from the repository root:

    uv run python reports/data-report/span_window_stats.py

The script reads the train and validation exports of the frozen split v3.1 of
2026-11-12, validates every annotation, and measures span widths and
action--argument distances in Unicode letter/number runs. It writes
``reports/generated/data-report/span_window_split_v3_1.json``. It checks the
existing 36-unit span-width and two-sentence window candidates; it does not
select a policy. The test and domain_test exports are never opened.
"""

import hashlib
import json
import platform
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from smartnotice.io import read_jsonl
from smartnotice.labeling.validation import validate_annotation
from smartnotice.schemas import Annotation, Notice

ROOT = Path(__file__).resolve().parents[2]
SPLIT = ROOT / "data/annotations/split_65_15_20_v3_1_2026-11-12"
OUT = ROOT / "reports/generated/data-report"
TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def digest(path: Path) -> str:
    """Return the SHA-256 of the exact input bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(values: list[int], threshold: int) -> dict:
    """Count coverage and linear quantiles; empty populations have null quantiles."""
    series = pd.Series(values, dtype="float64")
    return {
        "n": len(values),
        "p50": float(series.quantile(0.5)) if values else None,
        "p90": float(series.quantile(0.9)) if values else None,
        "p99": float(series.quantile(0.99)) if values else None,
        "kept": sum(value <= threshold for value in values),
        "threshold": threshold,
    }


def sentence_index(notice: Notice, start: int, end: int) -> int:
    """Find the sole sentence containing the complete span or reject the record."""
    matches = [
        i
        for i, sentence in enumerate(notice.sentences)
        if sentence.start <= start and end <= sentence.end
    ]
    if len(matches) != 1:
        raise ValueError(f"Ambiguous span sentence: {notice.doc_id}")
    return matches[0]


def main() -> None:
    """Validate inputs and save only aggregate diagnostics and measurement provenance."""
    result = {
        "created_at": datetime.now(UTC).isoformat(),
        "snapshot": "baseline-preserving-cleanup-audience-v3.1",
        "split": SPLIT.name,
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "seed": None,
        "method": {
            "sampling": "none; all train and validation records, separately",
            "token_regex": TOKEN.pattern,
            "token_unit": "Unicode letter/number runs, not model subwords",
            "quantile": "linear interpolation",
            "span_width_candidate": 36,
            "sentence_window_candidate": 2,
            "distance": "absolute index difference of sentences containing full spans",
            "relation_denominator": "each event argument, including shared arguments",
            "status": "diagnostics of existing candidates; no policy selected",
        },
        "sha256": {},
        "splits": {},
    }
    seen = set()
    for split in ("train", "validation"):
        paths = [SPLIT / split / f"{name}.jsonl" for name in ("notices", "annotations")]
        for path in paths:
            result["sha256"][path.relative_to(ROOT).as_posix()] = digest(path)
        notices = {row["doc_id"]: Notice.model_validate(row) for row in read_jsonl(paths[0])}
        annotations = [Annotation.model_validate(row) for row in read_jsonl(paths[1])]
        assert len(annotations) == len(notices)
        assert {ann.doc_id for ann in annotations} == set(notices)
        assert not seen.intersection(notices)
        seen.update(notices)
        widths, distances, gaps = defaultdict(list), defaultdict(list), defaultdict(list)
        docs = Counter(notice.source_type for notice in notices.values())
        for annotation in annotations:
            notice = notices[annotation.doc_id]
            validate_annotation(annotation, notice)
            spans = {span.span_id: span for span in annotation.spans}
            for span in annotation.spans:
                widths[notice.source_type, span.label].append(len(TOKEN.findall(span.text)))
            for event in annotation.events:
                action = spans[event.action_span_id]
                action_sentence = sentence_index(notice, action.start, action.end)
                for argument in event.arguments:
                    target = spans[argument.span_id]
                    key = notice.source_type, target.label
                    distances[key].append(
                        abs(action_sentence - sentence_index(notice, target.start, target.end))
                    )
                    left, right = sorted((action, target), key=lambda span: span.start)
                    gap = notice.text[left.end : right.start] if left.end <= right.start else ""
                    gaps[key].append(len(TOKEN.findall(gap)))
        result["splits"][split] = {
            "documents": dict(docs),
            "span_widths": {
                f"{source}/{label}": summarize(values, 36)
                for (source, label), values in sorted(widths.items())
            },
            "relation_distances": {
                f"{source}/{label}": {
                    "sentences": summarize(values, 2),
                    "gap_tokens": summarize(gaps[source, label], 36),
                }
                for (source, label), values in sorted(distances.items())
            },
        }
    for path in (SPLIT / "assignments.jsonl", ROOT / "uv.lock", Path(__file__).resolve()):
        result["sha256"][path.relative_to(ROOT).as_posix()] = digest(path)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "span_window_split_v3_1.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result["splits"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

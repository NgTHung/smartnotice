"""Compute the date, event-count, and grouping-threshold figures for the EDA report.

Run from the repository root:

    uv run python reports/data-report/gap_stats.py

The script reads the v3.1 curated snapshot and the frozen split v3.1 of
2026-11-12, checks that the split was built from the same snapshot hashes, and
writes ``reports/generated/data-report/gap_stats_split_v3_1.json``. It reports
counts over the development set (train + validation) and, where useful, the full
snapshot. All event labels are machine-assisted curation, not gold labels.
Date outcomes are rechecked with the tracked copy of the curation rule in
``curation_dates.py``.

The grouping-threshold comparison repeats the frozen split's grouping rule
(source thread/template group plus SequenceMatcher similarity, merged
transitively) at several thresholds. It does not review whether a merged group
is correct; that remains a human task.
"""

import hashlib
import json
import re
import sys
from collections import Counter
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd
from curation_dates import normalize_time_span
from smartnotice.io import read_jsonl
from smartnotice.schemas import Annotation, Notice

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "data/annotations/cleanup_curated_2026-11-10_v3_1/artifacts"
SPLIT_DIR = ROOT / "data/annotations/split_65_15_20_v3_1_2026-11-12"
OUT = ROOT / "reports/generated/data-report"
THRESHOLDS = [0.80, 0.85, 0.90, 0.95]
DEVELOPMENT = {"train", "validation"}

YEAR_DATE = re.compile(r"\d{1,2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*\d{4}")
NO_YEAR_DATE = re.compile(r"(?<![\d/.-])\d{1,2}\s*/\s*\d{1,2}(?![\d/]|\s*/\s*\d)")
WRITTEN_DATE = re.compile(r"ngày\s*\d{1,2}\s+tháng\s+\d{1,2}|tháng\s+\d{1,2}\s+năm\s+\d{4}")
RELATIVE = re.compile(
    r"\b(?:hôm nay|ngày mai|mai|tuần (?:này|sau|tới)|tháng (?:này|sau|tới)|sắp tới|"
    r"từ nay|ngay sau|sau khi|trong vòng|thứ \w+ (?:này|tới))\b",
    re.IGNORECASE,
)
# Slash or hyphen dates only; a dot would also match decimal scores such as 8.5.
TEXT_DATE = re.compile(r"(?<![\d/-])(\d{1,2})([/-])(\d{1,2})(?:\2(\d{4}))?(?![\d/-])")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def describe(values: list[float]) -> dict:
    """Match the report's Table 3: sample variance (n-1), inclusive interpolated IQR."""
    series = pd.Series(values, dtype="float64")
    if series.empty:
        return {"n": 0}
    q1, q3 = series.quantile(0.25), series.quantile(0.75)
    return {
        "n": int(series.size),
        "mean": round(float(series.mean()), 2),
        "median": round(float(series.median()), 2),
        "var": round(float(series.var()), 2),
        "min": float(series.min()),
        "max": float(series.max()),
        "iqr": round(float(q3 - q1), 2),
    }


def date_form(span_text: str) -> str:
    """Classify a TIME span by its most resolvable date expression.

    Priority: numeric date with year, numeric day/month without year, written
    date, relative expression, then ``other`` (time of day only, month/year,
    named periods, or non-Vietnamese wording).
    """
    text = span_text.replace("*", "")
    if YEAR_DATE.search(text):
        return "numeric_with_year"
    if NO_YEAR_DATE.search(text):
        return "numeric_without_year"
    if WRITTEN_DATE.search(text.casefold()):
        return "written"
    if RELATIVE.search(text.casefold()):
        return "relative"
    return "other"


def date_styles(text: str) -> set[tuple]:
    """Return the separator, zero-padding, and year-presence styles of numeric dates."""
    styles = set()
    for day, separator, month, year in TEXT_DATE.findall(text):
        if not (1 <= int(day) <= 31 and 1 <= int(month) <= 12):
            continue
        styles.add((separator, len(day) == 2, len(month) == 2, bool(year)))
    return styles


def load() -> tuple[list[Notice], dict[str, Annotation], dict[str, str], dict]:
    notices_path, annotations_path = ARTIFACTS / "notices.jsonl", ARTIFACTS / "annotations.jsonl"
    hashes = {"notices.jsonl": sha256(notices_path), "annotations.jsonl": sha256(annotations_path)}
    record = json.loads((SPLIT_DIR / "record.json").read_text(encoding="utf-8"))
    checksums = json.loads((SPLIT_DIR / "checksums.json").read_text(encoding="utf-8"))
    for name in ["assignments.jsonl", "record.json", "verification.json"]:
        if sha256(SPLIT_DIR / name) != checksums[name]:
            raise ValueError(f"{name} does not match {SPLIT_DIR.name}/checksums.json")
    expected = record["source_files_sha256"]
    if (expected["notices.jsonl"], expected["annotations.jsonl"]) != (
        hashes["notices.jsonl"],
        hashes["annotations.jsonl"],
    ):
        raise ValueError("The frozen split was built from a different snapshot")
    notices = [Notice.model_validate(r) for r in read_jsonl(notices_path)]
    annotations = {
        a.doc_id: a for a in (Annotation.model_validate(r) for r in read_jsonl(annotations_path))
    }
    split = {r["doc_id"]: r["split"] for r in read_jsonl(SPLIT_DIR / "assignments.jsonl")}
    if set(split) != {n.doc_id for n in notices} or set(annotations) != set(split):
        raise ValueError("Assignments, notices, and annotations cover different documents")
    return notices, annotations, split, {"inputs_sha256": hashes, "record": record}


def time_arguments(notices: list[Notice], annotations: dict[str, Annotation]):
    """Yield (notice, span, argument) for every TIME argument of every event."""
    for notice in notices:
        annotation = annotations[notice.doc_id]
        spans = {s.span_id: s for s in annotation.spans}
        for event in annotation.events:
            for argument in event.arguments:
                span = spans[argument.span_id]
                if span.label == "TIME":
                    yield notice, span, argument


def date_statistics(
    notices: list[Notice], annotations: dict[str, Annotation], normalize_time_span
) -> dict:
    forms: dict[str, Counter] = {}
    resolved: dict[str, Counter] = {}
    unresolved_ranges = Counter()
    reasons: dict[str, Counter] = {}
    recipe_mismatches = 0
    earlier_inferred, earlier_any = [], Counter()
    deadline_days: dict[str, list[int]] = {"email": [], "web": []}
    for notice, span, argument in time_arguments(notices, annotations):
        form = date_form(span.text)
        forms.setdefault(form, Counter())[notice.source_type] += 1
        recomputed, inferred, reason = normalize_time_span(span.text, notice.reference_date)
        if (recomputed, inferred) != (argument.normalized_date, argument.inferred):
            recipe_mismatches += 1
        if argument.normalized_date is None:
            outcome = "unresolved"
            if len(YEAR_DATE.findall(span.text.replace("*", ""))) >= 2:
                unresolved_ranges[notice.source_type] += 1
            reasons.setdefault(form, Counter())[f"{notice.source_type}:{reason}"] += 1
        else:
            outcome = "inferred" if argument.inferred else "explicit"
        resolved.setdefault(form, Counter())[outcome] += 1
        reference = notice.reference_date
        if argument.normalized_date and reference:
            if argument.normalized_date < reference:
                earlier_any[notice.source_type] += 1
                if argument.inferred:
                    earlier_inferred.append(
                        {
                            "doc_id": notice.doc_id,
                            "reference_month": reference.month,
                            "normalized_month": argument.normalized_date.month,
                            "days": (argument.normalized_date - reference).days,
                        }
                    )
            if argument.role == "DEADLINE":
                deadline_days[notice.source_type].append(
                    (argument.normalized_date - reference).days
                )
    total = sum(sum(c.values()) for c in forms.values())
    return {
        "time_arguments": total,
        "by_source": dict(sum(forms.values(), Counter())),
        "forms_by_source": {k: dict(v) for k, v in forms.items()},
        "forms_by_outcome": {k: dict(v) for k, v in resolved.items()},
        "outcome_totals": dict(sum(resolved.values(), Counter())),
        "unresolved_with_two_dated_endpoints": dict(unresolved_ranges),
        "unresolved_reasons_by_form": {k: dict(sorted(v.items())) for k, v in reasons.items()},
        "stored_values_not_reproduced_by_recipe": recipe_mismatches,
        "inferred_and_earlier_than_reference": earlier_inferred,
        "any_normalized_earlier_than_reference": dict(earlier_any),
        "reference_to_deadline_days": {k: describe(v) for k, v in deadline_days.items()},
        "deadlines_more_than_7_days_before_reference": {
            k: sum(d < -7 for d in v) for k, v in deadline_days.items()
        },
    }


def document_statistics(notices: list[Notice], annotations: dict[str, Annotation]) -> dict:
    events = {"email": [], "web": []}
    mixed_dates, dated = Counter(), Counter()
    for notice in notices:
        events[notice.source_type].append(len(annotations[notice.doc_id].events))
        styles = date_styles(notice.text)
        if styles:
            dated[notice.source_type] += 1
        if len(styles) >= 2:
            mixed_dates[notice.source_type] += 1
    documents = Counter(n.source_type for n in notices)
    return {
        "documents": dict(documents),
        "events_per_document": {k: describe(v) for k, v in events.items()},
        "documents_with_numeric_dates": dict(dated),
        "documents_with_two_or_more_date_styles": dict(mixed_dates),
    }


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def similar_pairs(notices: list[Notice], floor: float) -> list[tuple[int, int, float]]:
    """Return every document pair whose SequenceMatcher ratio is at least ``floor``."""
    texts = [normalized(n.text) for n in notices]
    pairs = []
    for i in range(len(texts)):
        for j in range(i):
            matcher = SequenceMatcher(None, texts[i], texts[j], autojunk=False)
            if matcher.real_quick_ratio() < floor or matcher.quick_ratio() < floor:
                continue
            ratio = matcher.ratio()
            if ratio >= floor:
                pairs.append((i, j, ratio))
    return pairs


def groups_at(notices: list[Notice], pairs: list[tuple[int, int, float]], threshold: float):
    parents = list(range(len(notices)))

    def find(i: int) -> int:
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    def union(i: int, j: int) -> None:
        parents[find(i)] = find(j)

    first_by_source_group: dict[str, int] = {}
    for i, notice in enumerate(notices):
        union(i, first_by_source_group.setdefault(notice.group_id, i))
    for i, j, ratio in pairs:
        if ratio >= threshold:
            union(i, j)
    members: dict[int, list[int]] = {}
    for i in range(len(notices)):
        members.setdefault(find(i), []).append(i)
    return list(members.values())


def threshold_statistics(notices: list[Notice], split: dict[str, str]) -> dict:
    floor = min(THRESHOLDS)
    pairs = similar_pairs(notices, floor)
    frozen_groups = {
        r["doc_id"]: r["group_id"] for r in read_jsonl(SPLIT_DIR / "assignments.jsonl")
    }
    result = {"pairs_at_or_above_floor": len(pairs), "floor": floor, "thresholds": {}}
    for threshold in THRESHOLDS:
        groups = groups_at(notices, pairs, threshold)
        largest = max(len(g) for g in groups)
        cross_split = sum(len({split[notices[i].doc_id] for i in g}) > 1 for g in groups)
        result["thresholds"][f"{threshold:.2f}"] = {
            "groups": len(groups),
            "multi_document_groups": sum(len(g) > 1 for g in groups),
            "documents_in_multi_document_groups": sum(len(g) for g in groups if len(g) > 1),
            "largest_group": largest,
            "largest_group_pct": round(100 * largest / len(notices), 2),
            "similar_pairs_below_threshold": sum(floor <= r < threshold for *_, r in pairs),
            "groups_spanning_frozen_splits": cross_split,
        }
    reproduced = groups_at(notices, pairs, 0.80)
    canonical = {frozenset(notices[i].doc_id for i in g) for g in reproduced}
    frozen: dict[str, set] = {}
    for doc_id, group_id in frozen_groups.items():
        frozen.setdefault(group_id, set()).add(doc_id)
    frozen_sets = {frozenset(v) for v in frozen.values()}
    result["reproduces_frozen_groups_at_0_80"] = canonical == frozen_sets
    return result


def main() -> None:
    notices, annotations, split, provenance = load()
    development = [n for n in notices if split[n.doc_id] in DEVELOPMENT]
    stats = {
        "snapshot": "baseline-preserving-cleanup-audience-v3.1",
        "split": SPLIT_DIR.name,
        "label_origin": sorted({a.annotator_id for a in annotations.values()}),
        "inputs_sha256": provenance["inputs_sha256"],
        "assignments_sha256": sha256(SPLIT_DIR / "assignments.jsonl"),
        "python": sys.version.split()[0],
        "development": {
            "scope": "train + validation",
            **document_statistics(development, annotations),
            "dates": date_statistics(development, annotations, normalize_time_span),
        },
        "full_snapshot": {
            **document_statistics(notices, annotations),
            "dates": date_statistics(notices, annotations, normalize_time_span),
        },
        "grouping_thresholds": threshold_statistics(notices, split),
        "computed_on": date.today().isoformat(),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "gap_stats_split_v3_1.json"
    path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

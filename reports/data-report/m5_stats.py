"""Compute the applicability and source statistics for the data report (role M5).

Run from the repository root:

    uv run python reports/data-report/m5_stats.py

The script reads the v3.1 curated snapshot, regenerates the seeded diagnostic
profiles, derives silver event/profile labels with ``build_pairs``, and joins
every document to the frozen split v3.1 of 2026-11-12 through
``assignments.jsonl``. It checks that the split was built from the same
snapshot hashes before counting anything. It writes counts to
``reports/generated/data-report/m5_stats_split_v3_1.json`` and saves the
Spearman figure under ``reports/data-report/figures/``.

All labels are machine-assisted curation and rule-derived silver labels. The
frozen split has no completed human group review and no gold test labels;
test and domain_test labels counted here are the source curation, not gold.
"""

import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from smartnotice.io import read_jsonl
from smartnotice.labeling.pairs import build_pairs
from smartnotice.labeling.profiles import generate_profiles
from smartnotice.preprocessing.split import DEFAULT_SEED
from smartnotice.schemas import Annotation, Notice, Profile

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "data/annotations/cleanup_curated_2026-11-10_v3_1"
ARTIFACTS = SNAPSHOT / "artifacts"
SPLIT_DIR = ROOT / "data/annotations/split_65_15_20_v3_1_2026-11-12"
OUT = ROOT / "reports/generated/data-report"
FIGURES = ROOT / "reports/data-report/figures"
LABELS = ["APPLIES", "NOT_APPLIES", "UNCLEAR"]
SPLITS = ["train", "validation", "test", "domain_test"]
FIELDS = ["cohort", "degree_level", "major", "program", "status"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 2) if whole else None


def describe(values: list[float]) -> dict:
    series = pd.Series(values, dtype="float64")
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


def cramers_v(table: pd.DataFrame) -> float:
    observed = table.to_numpy(dtype="float64")
    total = observed.sum()
    expected = observed.sum(1, keepdims=True) * observed.sum(0, keepdims=True) / total
    chi2 = float(((observed - expected) ** 2 / expected).sum())
    return math.sqrt(chi2 / (total * (min(observed.shape) - 1)))


def vif(frame: pd.DataFrame) -> dict:
    result = {}
    for column in frame:
        target = frame[column].to_numpy(dtype="float64")
        others = frame.drop(columns=column).to_numpy(dtype="float64")
        design = np.column_stack([np.ones(len(frame)), others])
        coef, *_ = np.linalg.lstsq(design, target, rcond=None)
        residual = target - design @ coef
        r2 = 1 - residual.var() / target.var()
        result[column] = round(float(1 / (1 - r2)), 2) if r2 < 1 else None
    return result


def event_only_oracle(event_labels: dict[tuple, Counter]) -> dict:
    """Score a profile-blind predictor that gives every pair its event's majority label.

    The predictor reads the silver labels themselves, so its score is an upper
    bound for any model that ignores the profile, not a model result.
    """
    gold, confusion = Counter(), Counter()
    for counter in event_labels.values():
        majority = counter.most_common(1)[0][0]
        for label, n in counter.items():
            gold[label] += n
            confusion[(label, majority)] += n
    total = sum(gold.values())
    constant = Counter(next(iter(c)) for c in event_labels.values() if len(c) == 1)
    return {
        "events": len(event_labels),
        "pairs": total,
        "constant_label_events": dict(constant),
        "constant_label_events_total": sum(constant.values()),
        "constant_label_events_pct": pct(sum(constant.values()), len(event_labels)),
        "profile_dependent_events": len(event_labels) - sum(constant.values()),
        "accuracy": round(sum(v for (g, p), v in confusion.items() if g == p) / total, 4),
        "macro_f1": macro_f1(gold, confusion),
    }


def load_frozen_split(notices_sha256: str, annotations_sha256: str) -> tuple[dict, list[dict]]:
    """Return the frozen split record and assignment rows after checking provenance.

    Raises:
        ValueError: if a split file fails its checksum or the split was built
            from a different notices/annotations snapshot.
    """
    record = json.loads((SPLIT_DIR / "record.json").read_text(encoding="utf-8"))
    checksums = json.loads((SPLIT_DIR / "checksums.json").read_text(encoding="utf-8"))
    for name in ["assignments.jsonl", "holdout_manifest.jsonl", "record.json", "verification.json"]:
        if sha256(SPLIT_DIR / name) != checksums[name]:
            raise ValueError(f"{name} does not match {SPLIT_DIR.name}/checksums.json")
    expected = record["source_files_sha256"]
    if (expected["notices.jsonl"], expected["annotations.jsonl"]) != (
        notices_sha256,
        annotations_sha256,
    ):
        raise ValueError("The frozen split was built from a different snapshot")
    rows = list(read_jsonl(SPLIT_DIR / "assignments.jsonl"))
    if {r["data_sha256"] for r in rows} != {notices_sha256}:
        raise ValueError("An assignment row names a different notices.jsonl hash")
    return record, rows


def macro_f1(gold: Counter, confusion: Counter) -> float:
    scores = []
    for label in LABELS:
        tp = confusion[(label, label)]
        predicted = sum(v for (g, p), v in confusion.items() if p == label)
        support = gold[label]
        precision = tp / predicted if predicted else 0.0
        recall = tp / support if support else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return round(sum(scores) / len(scores), 4)


ATTRIBUTE_ABBREVIATION = re.compile(
    r"^(?:K\d{2,4}|\d{2}[A-ZĐ][A-ZĐ0-9]*|CLC|TCTA|CNTT|ĐHCQ|HVCH|NCS)$"
)


def abbreviation_tokens(text: str) -> list[str]:
    """Return attribute codes written as abbreviations, such as K24, 24KHMT, CLC, or NCS.

    Institution acronyms, ``SV`` and redaction placeholders do not count because
    they never encode a cohort, major, program, or degree level.
    """
    return [t for t in re.findall(r"\w+", text) if ATTRIBUTE_ABBREVIATION.match(t)]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    inputs = {
        name: ARTIFACTS / name
        for name in [
            "notices.jsonl",
            "annotations.jsonl",
            "email_notices.jsonl",
            "email_annotations.jsonl",
            "diagnostic_profiles.jsonl",
            "annotation_log.json",
            "summary.json",
        ]
    }
    notices = [Notice.model_validate(r) for r in read_jsonl(inputs["notices.jsonl"])]
    annotations = [Annotation.model_validate(r) for r in read_jsonl(inputs["annotations.jsonl"])]
    by_doc = {n.doc_id: n for n in notices}
    ann_by_doc = {a.doc_id: a for a in annotations}
    email_ann = [
        Annotation.model_validate(r) for r in read_jsonl(inputs["email_annotations.jsonl"])
    ]
    stored_profiles = [
        Profile.model_validate(r) for r in read_jsonl(inputs["diagnostic_profiles.jsonl"])
    ]
    summary = json.loads(inputs["summary.json"].read_text(encoding="utf-8"))
    code_log = json.loads(inputs["annotation_log.json"].read_text(encoding="utf-8"))
    input_hashes = {name: sha256(path) for name, path in inputs.items()}
    record, assignment_rows = load_frozen_split(
        input_hashes["notices.jsonl"], input_hashes["annotations.jsonl"]
    )
    stats: dict = {
        "snapshot": "baseline-preserving-cleanup-audience-v3.1",
        "label_origin": "machine-assisted curation (annotator_id "
        + ", ".join(sorted({a.annotator_id for a in annotations}))
        + "); applicability labels are constraint_rule silver labels",
        "inputs_sha256": input_hashes,
        "split_dir": SPLIT_DIR.relative_to(ROOT).as_posix(),
        "assignments_sha256": sha256(SPLIT_DIR / "assignments.jsonl"),
        "python": sys.version.split()[0],
        "seed": DEFAULT_SEED,
        "split_seed": record["selected_seed"],
        "similarity": record["similarity"],
    }

    # Profiles: regenerate from email constraints and compare with the stored set.
    constraints = [c for a in email_ann for c in a.audience_constraints]
    profiles = generate_profiles(constraints, DEFAULT_SEED)
    assert [p.model_dump() for p in profiles] == [p.model_dump() for p in stored_profiles]
    pframe = pd.DataFrame([p.model_dump() for p in profiles])
    stats["profiles"] = {
        "count": len(profiles),
        "reproduced_from_email_constraints": True,
        "email_constraints": len(constraints),
        "missing": {f: int(pframe[f].isna().sum()) for f in FIELDS},
        "missing_pct": {f: pct(int(pframe[f].isna().sum()), len(pframe)) for f in FIELDS},
        "distinct": {f: int(pframe[f].nunique()) for f in FIELDS},
        "cohort_range": [int(pframe.cohort.min()), int(pframe.cohort.max())],
        "value_counts": {
            f: {str(k): int(v) for k, v in pframe[f].value_counts(dropna=False).items()}
            for f in ["degree_level", "status"]
        },
        "constraint_scopes": dict(Counter(c.scope for c in constraints)),
    }

    # Frozen grouped split: every notice must have exactly one assignment.
    split_rows = assignment_rows
    split_of = {r["doc_id"]: r["split"] for r in split_rows}
    if len(split_of) != len(split_rows) or set(split_of) != set(by_doc):
        raise ValueError("Frozen assignments do not cover each notice exactly once")

    # The stored profile set was designed from all email constraints, test included.
    # Record which attribute values a train+validation-only design would lack.
    # Profile-by-profile overlap is not reported: a different value pool changes
    # the seeded mismatch choices, so most profiles differ even for shared values.
    dev_constraints = [
        c
        for a in email_ann
        if split_of[a.doc_id] in {"train", "validation"}
        for c in a.audience_constraints
    ]
    dev_profiles = generate_profiles(dev_constraints, DEFAULT_SEED)
    stats["profiles"]["development_only"] = {
        "constraints": len(dev_constraints),
        "profiles": len(dev_profiles),
        "cohorts": sorted({p.cohort for p in dev_profiles if p.cohort is not None}),
        "programs": sorted({p.program for p in dev_profiles if p.program is not None}),
    }
    group_sizes = Counter(r["group_id"] for r in split_rows)
    split_table = defaultdict(lambda: {"groups": set(), "email": 0, "web": 0})
    for row in split_rows:
        cell = split_table[row["split"]]
        cell["groups"].add(row["group_id"])
        cell[by_doc[row["doc_id"]].source_type] += 1
    stats["split"] = {
        "status": "frozen; manual_group_review_completed="
        + str(record["manual_group_review_completed"]).lower()
        + "; gold_ready="
        + str(record["gold_ready"]).lower(),
        "domain_holdout_documents": sum(r["split"] == "domain_test" for r in split_rows),
        "holdout_sites": record["holdout_sites"],
        "groups": len(group_sizes),
        "largest_group": max(group_sizes.values()),
        "multi_document_groups": sum(v > 1 for v in group_sizes.values()),
        "by_split": {
            s: {
                "groups": len(split_table[s]["groups"]),
                "email": split_table[s]["email"],
                "web": split_table[s]["web"],
            }
            for s in SPLITS
        },
    }

    # Audience coverage per email event and constraint codes.
    coverage = Counter()
    abbreviations = Counter()
    code_events: dict[tuple[str, str], set] = defaultdict(set)
    code_forms: dict[tuple[str, str], set] = defaultdict(set)
    patterns = {
        (field, code): [re.compile(p, re.IGNORECASE) for p in pats]
        for field, table in [("major", code_log["majors"]), ("program", code_log["programs"])]
        for code, pats in table.items()
    }
    email_events = 0
    for annotation in email_ann:
        spans = {s.span_id: s for s in annotation.spans}
        mapping = {c.audience_span_id: c for c in annotation.audience_constraints}
        for event in annotation.events:
            email_events += 1
            key = (annotation.doc_id, event.event_id)
            audience_ids = [
                a.span_id for a in event.arguments if spans[a.span_id].label == "AUDIENCE"
            ]
            branches = [mapping[sid] for sid in audience_ids if sid in mapping]
            if not audience_ids:
                coverage["no_audience"] += 1
            else:
                coverage["has_audience"] += 1
                if len(branches) == len(audience_ids):
                    coverage["reviewed_constraint"] += 1
            if any(c.scope in {"listed", "all_students"} for c in branches):
                coverage["explicit"] += 1
            if any(c.scope == "listed" for c in branches):
                coverage["listed"] += 1
            if any(c.scope == "all_students" for c in branches):
                coverage["all_students"] += 1
            if any(c.scope == "implicit" for c in branches):
                coverage["implicit"] += 1
            if any(c.scope == "outside_population" for c in branches):
                coverage["outside_population"] += 1
            if any(c.excluded_statuses for c in branches):
                coverage["excluded_statuses"] += 1
            if len(audience_ids) >= 2:
                coverage["multiple_branches"] += 1
            if any(c.unrepresented for c in branches):
                coverage["unrepresented"] += 1
            if any(spans[a.span_id].label == "CONDITION" for a in event.arguments):
                coverage["condition"] += 1
            tokens = [t for sid in audience_ids for t in abbreviation_tokens(spans[sid].text)]
            if tokens:
                coverage["abbreviation"] += 1
                abbreviations.update(tokens)
            audience_text = " ".join(spans[sid].text for sid in audience_ids)
            for c in branches:
                years = set(c.cohorts)
                if c.cohort_min is not None or c.cohort_max is not None:
                    years.add(f"{c.cohort_min}..{c.cohort_max}")
                for year in years:
                    code_events[("cohort", str(year))].add(key)
                for field, values in [("major", c.majors), ("program", c.programs)]:
                    for code in values:
                        code_events[(field, code)].add(key)
                        for pattern in patterns.get((field, code), []):
                            for match in pattern.finditer(audience_text):
                                code_forms[(field, code)].add(" ".join(match.group(0).split()))
    profile_values = {
        f: Counter(str(getattr(p, f)) for p in profiles if getattr(p, f) is not None)
        for f in FIELDS
    }
    codes = []
    dev_values = stats["profiles"]["development_only"]
    for (field, code), events in sorted(code_events.items()):
        if field == "cohort" and ".." in code:
            low, high = code.split("..")
            low_i = None if low == "None" else int(low)
            high_i = None if high == "None" else int(high)
            matching = sum(
                n
                for value, n in profile_values["cohort"].items()
                if (low_i is None or int(value) >= low_i)
                and (high_i is None or int(value) <= high_i)
            )
        else:
            matching = profile_values[field].get(code, 0)
        codes.append(
            {
                "field": field,
                "code": code,
                "events": len(events),
                "events_by_split": dict(Counter(split_of[doc_id] for doc_id, _ in events)),
                "surface_forms": sorted(code_forms[(field, code)]) if field != "cohort" else None,
                "profiles_with_value": matching,
                "value_in_development_profiles": (
                    int(code) in dev_values["cohorts"]
                    if field == "cohort" and ".." not in code
                    else code in dev_values["programs"]
                    if field == "program"
                    else None
                ),
            }
        )
    logged = {
        (f, c)
        for f, t in [("major", code_log["majors"]), ("program", code_log["programs"])]
        for c in t
    }
    stats["audience_coverage"] = {
        "email_events": email_events,
        "counts": dict(coverage),
        "pct": {k: pct(v, email_events) for k, v in coverage.items()},
        "abbreviation_rule": ATTRIBUTE_ABBREVIATION.pattern,
        "top_abbreviations": abbreviations.most_common(25),
        "codes": codes,
        "logged_codes_unused_in_email": sorted(
            f"{f}:{c}" for f, c in logged if (f, c) not in code_events
        ),
    }

    # Silver pairs under the run policy and under the contract default.
    pair_stats = {}
    email_notices = [by_doc[a.doc_id] for a in email_ann]
    for policy in [True, False]:
        labels, reasons_raw, components = Counter(), Counter(), Counter()
        split_labels = Counter()
        event_components: dict[str, set] = defaultdict(set)
        event_label_sets: dict[tuple, Counter] = {}
        multi_reason_pairs = 0
        events_seen_in_splits: dict[tuple, set] = defaultdict(set)
        for annotation, notice in zip(email_ann, email_notices, strict=True):
            rows = build_pairs(
                [notice], [annotation], profiles, assume_all_students_without_audience=policy
            )
            for row in rows:
                key = (row["doc_id"], row["event_id"])
                label = row["label"]
                labels[label] += 1
                reasons_raw[row["rule_reason"]] += 1
                parts = set(row["rule_reason"].split(";"))
                multi_reason_pairs += len(row["rule_reason"].split(";")) > 1
                for part in parts:
                    components[(part, label)] += 1
                    event_components[(part, label)].add(key)
                split_labels[(split_of[row["doc_id"]], label)] += 1
                events_seen_in_splits[key].add(split_of[row["doc_id"]])
                event_label_sets.setdefault(key, Counter())[label] += 1
        pairs_total = sum(labels.values())
        n_events = len(event_label_sets)
        oracle_all = event_only_oracle(event_label_sets)
        oracle_by_split = {
            s: event_only_oracle({k: v for k, v in event_label_sets.items() if split_of[k[0]] == s})
            for s in ["train", "validation", "test"]
        }
        unmodeled = components[("unmodeled_condition", "UNCLEAR")]
        events_per_split = Counter()
        docs_per_split = Counter(split_of[a.doc_id] for a in email_ann)
        for splits in events_seen_in_splits.values():
            events_per_split[next(iter(splits))] += 1
        pair_stats["assume_all_students" if policy else "contract_default"] = {
            "pairs": pairs_total,
            "events": n_events,
            "documents": len(email_ann),
            "profiles": len(profiles),
            "labels": dict(labels),
            "labels_pct": {k: pct(v, pairs_total) for k, v in labels.items()},
            "by_split": {s: {label: split_labels[(s, label)] for label in LABELS} for s in SPLITS},
            "events_per_split": dict(events_per_split),
            "documents_per_split": dict(docs_per_split),
            "events_in_multiple_splits": sum(len(s) > 1 for s in events_seen_in_splits.values()),
            "reason_components": [
                {
                    "reason": reason,
                    "label": label,
                    "pairs": n,
                    "pairs_pct": pct(n, pairs_total),
                    "events": len(event_components[(reason, label)]),
                    "events_pct": pct(len(event_components[(reason, label)]), n_events),
                }
                for (reason, label), n in sorted(components.items(), key=lambda x: -x[1])
            ],
            "multi_reason_pairs": multi_reason_pairs,
            "unmodeled_condition": {
                "pairs": unmodeled,
                "share_of_applies_plus_unmodeled_pct": pct(
                    unmodeled, labels["APPLIES"] + unmodeled
                ),
                "events": len(event_components[("unmodeled_condition", "UNCLEAR")]),
            },
            "event_only_oracle": {
                "all_email": oracle_all,
                "by_split": oracle_by_split,
                "note": "upper bound of a profile-blind predictor; reads the silver labels",
            },
        }
        if policy:
            assert labels == Counter(summary["diagnostics"]["labels"]), "summary mismatch"
            assert reasons_raw == Counter(summary["diagnostics"]["reasons"]), "summary mismatch"
    stats["pairs"] = pair_stats

    # Document-level features for EDA on the frozen development pool.
    doc_rows = []
    for notice in notices:
        annotation = ann_by_doc[notice.doc_id]
        labels = Counter(s.label for s in annotation.spans)
        time_args = [
            a
            for e in annotation.events
            for a in e.arguments
            if next(s for s in annotation.spans if s.span_id == a.span_id).label == "TIME"
        ]
        syllables = len(notice.text.split())
        doc_rows.append(
            {
                "doc_id": notice.doc_id,
                "source": notice.source_type,
                "split": split_of[notice.doc_id],
                "chars": len(notice.text),
                "sentences": len(notice.sentences),
                "syllables": syllables,
                "redactions": notice.redaction_count,
                "events": len(annotation.events),
                "TIME": labels["TIME"],
                "AUDIENCE": labels["AUDIENCE"],
                "CONDITION": labels["CONDITION"],
                "CHANNEL": labels["CHANNEL"],
                "DOCUMENT": labels["DOCUMENT"],
                "time_args": len(time_args),
                "time_unresolved": sum(a.normalized_date is None for a in time_args),
                "reference_missing": notice.reference_date is None,
            }
        )
    docs = pd.DataFrame(doc_rows)
    dev = docs[docs.split.isin(["train", "validation"])]
    train = docs[docs.split == "train"]
    features = [
        "chars",
        "sentences",
        "syllables",
        "redactions",
        "events",
        "TIME",
        "AUDIENCE",
        "CONDITION",
        "CHANNEL",
        "DOCUMENT",
    ]
    spearman = train[features].corr(method="spearman")
    stats["relations"] = {
        "subset": "frozen train",
        "documents": int(len(train)),
        "by_source": train.source.value_counts().to_dict(),
        "spearman": spearman.round(3).to_dict(),
        "vif_length": vif(train[["chars", "sentences", "syllables"]]),
        "vif_length_log": vif(np.log1p(train[["chars", "sentences", "syllables"]])),
    }
    span_table = pd.DataFrame(
        [
            {"source": by_doc[a.doc_id].source_type, "label": s.label}
            for a in annotations
            if split_of[a.doc_id] == "train"
            for s in a.spans
        ]
    )
    role_table = pd.DataFrame(
        [
            {"source": by_doc[a.doc_id].source_type, "role": arg.role}
            for a in annotations
            if split_of[a.doc_id] == "train"
            for e in a.events
            for arg in e.arguments
            if arg.role is not None
        ]
    )
    stats["relations"]["cramers_v_source_span_label"] = round(
        cramers_v(pd.crosstab(span_table.source, span_table.label)), 3
    )
    stats["relations"]["cramers_v_source_time_role"] = round(
        cramers_v(pd.crosstab(role_table.source, role_table.role)), 3
    )
    stats["relations"]["span_label_by_source"] = pd.crosstab(
        span_table.label, span_table.source
    ).to_dict()
    stats["relations"]["time_role_by_source"] = pd.crosstab(
        role_table.role, role_table.source
    ).to_dict()

    compare = {}
    for source, part in dev.groupby("source"):
        compare[source] = {
            "documents": int(len(part)),
            "reference_missing_pct": pct(int(part.reference_missing.sum()), len(part)),
            "time_unresolved_pct": pct(int(part.time_unresolved.sum()), int(part.time_args.sum())),
            "time_args": int(part.time_args.sum()),
            "syllables_median": float(part.syllables.median()),
            "events_median": float(part.events.median()),
            "redactions_per_1000_syllables": round(
                1000 * part.redactions.sum() / part.syllables.sum(), 2
            ),
            "syllables": describe(part.syllables.tolist()),
            "events": describe(part.events.tolist()),
        }
    stats["source_compare"] = {"subset": "frozen train+validation", "by_source": compare}

    # Spearman heatmap: diverging blue/red with a neutral gray midpoint.
    cmap = LinearSegmentedColormap.from_list("div", ["#2a78d6", "#f0efec", "#e34948"])
    fig, axis = plt.subplots(figsize=(7.2, 6))
    image = axis.imshow(spearman.to_numpy(), cmap=cmap, vmin=-1, vmax=1)
    names = [
        "Ký tự",
        "Câu",
        "Âm tiết",
        "Token che",
        "Sự kiện",
        "TIME",
        "AUDIENCE",
        "CONDITION",
        "CHANNEL",
        "DOCUMENT",
    ]
    axis.set_xticks(range(len(names)), names, rotation=45, ha="right")
    axis.set_yticks(range(len(names)), names)
    for i in range(len(names)):
        for j in range(len(names)):
            value = spearman.iat[i, j]
            axis.text(
                j,
                i,
                f"{value:.2f}",
                ha="center",
                va="center",
                fontsize=7,
                color="#1a1a19" if abs(value) < 0.7 else "#fcfcfb",
            )
    fig.colorbar(image, ax=axis, fraction=0.046, pad=0.04, label="Spearman ρ")
    axis.set_title(f"Tương quan Spearman, tập train (n = {len(train)} tài liệu)")
    fig.tight_layout()
    fig.savefig(FIGURES / "m5_spearman_train.png", dpi=200)
    plt.close(fig)

    (OUT / "m5_stats_split_v3_1.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"Wrote {(OUT / 'm5_stats_split_v3_1.json').relative_to(ROOT)}")


if __name__ == "__main__":
    main()

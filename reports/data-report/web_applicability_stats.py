"""Audit web applicability feasibility on v3.1 development data only.

Run from the repository root:

    uv run python reports/data-report/web_applicability_stats.py

The script regenerates 722 diagnostic profiles from train constraints only
(seed 42), derives silver event/profile labels with ``build_pairs`` with the
population policy on and off, and writes ``summary.json``,
``event_diagnostics.json`` and ``profiles_train_only.json`` under
``reports/generated/data-report/web-applicability/``. Outputs contain aggregate
counts and safe IDs, never notice text. Labels are rule-derived diagnostics,
not human correctness judgments or estimates of real prevalence.

The 722-profile count predates constraint deduplication in
``generate_profiles``. Run the script at commit ``4f5b8b1`` to reproduce the
reported figures; later code generates fewer profiles.
"""

import hashlib
import json
import platform
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from smartnotice.io import read_jsonl
from smartnotice.labeling.applicability import constraint_requirements
from smartnotice.labeling.pairs import build_pairs
from smartnotice.labeling.profiles import generate_profiles
from smartnotice.labeling.validation import validate_annotation
from smartnotice.schemas import Annotation, Notice

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/generated/data-report/web-applicability"
ART = ROOT / "data/annotations/cleanup_curated_2026-11-10_v3_1/artifacts"
SPLIT = ROOT / "data/annotations/split_65_15_20_v3_1_2026-11-12"
FIELDS = ["cohort", "degree_level", "major", "program", "status"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def aggregate(events, document_rows):
    """Count documents, independent split groups, events, and diagnostic labels."""
    flags = [
        "has_audience",
        "has_condition",
        "unrepresented",
        "no_audience",
        "listed",
        "listed_representable",
        "all_students",
        "excluded_statuses",
    ]
    result = {
        "documents": len(document_rows),
        "documents_with_events": len({e["doc_id"] for e in events}),
        "groups": len({r["group_id"] for r in document_rows}),
        "events": len(events),
    }
    result["flags"] = {
        f: {
            "events": sum(e[f] for e in events),
            "documents": len({e["doc_id"] for e in events if e[f]}),
            "groups": len({e["group_id"] for e in events if e[f]}),
        }
        for f in flags
    }
    result["fields"] = {
        f: {
            "events": sum(f in e["required_fields"] for e in events),
            "documents": len({e["doc_id"] for e in events if f in e["required_fields"]}),
        }
        for f in FIELDS
    }
    for mode in ["default_on", "default_off"]:
        totals, reasons = Counter(), Counter()
        for e in events:
            totals.update(e[mode]["labels"])
            reasons.update(e[mode]["reasons"])
        dependent = [e for e in events if len(e[mode]["labels"]) > 1]
        contrasting = [e for e in events if {"APPLIES", "NOT_APPLIES"} <= set(e[mode]["labels"])]
        result[mode] = {
            "pair_labels": dict(totals),
            "pair_reasons": dict(reasons),
            "dependent_events": len(dependent),
            "dependent_documents": len({e["doc_id"] for e in dependent}),
            "dependent_groups": len({e["group_id"] for e in dependent}),
            "applies_not_applies_events": len(contrasting),
            "applies_not_applies_documents": len({e["doc_id"] for e in contrasting}),
            "applies_not_applies_groups": len({e["group_id"] for e in contrasting}),
            "label_sets": dict(Counter("+".join(sorted(e[mode]["labels"])) for e in events)),
        }
    return result


def main():
    """Verify snapshot identity, compute diagnostics, and save reproducible evidence."""
    OUT.mkdir(parents=True, exist_ok=True)
    record = json.loads((SPLIT / "record.json").read_text(encoding="utf-8"))
    checksums = json.loads((SPLIT / "checksums.json").read_text(encoding="utf-8"))
    for name in ["record.json", "assignments.jsonl", "holdout_manifest.jsonl", "verification.json"]:
        assert digest(SPLIT / name) == checksums[name], name
    for name in ["notices.jsonl", "annotations.jsonl"]:
        assert digest(ART / name) == record["source_files_sha256"][name], name
    notices = {r["doc_id"]: Notice.model_validate(r) for r in read_jsonl(ART / "notices.jsonl")}
    annotations = {
        r["doc_id"]: Annotation.model_validate(r) for r in read_jsonl(ART / "annotations.jsonl")
    }
    assignments = {r["doc_id"]: r for r in read_jsonl(SPLIT / "assignments.jsonl")}
    assert len(notices) == len(annotations) == len(assignments) == 534
    assert notices.keys() == annotations.keys() == assignments.keys()
    dev_ids = [d for d in notices if assignments[d]["split"] in {"train", "validation"}]
    for d in dev_ids:
        validate_annotation(annotations[d], notices[d])
    train_constraints = [
        c
        for d in dev_ids
        if assignments[d]["split"] == "train"
        for c in annotations[d].audience_constraints
    ]
    profiles = generate_profiles(train_constraints, seed=42)
    assert profiles == generate_profiles(train_constraints, seed=42)
    profile_json = [p.model_dump(mode="json") for p in profiles]
    (OUT / "profiles_train_only.json").write_text(
        json.dumps(profile_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    events = []
    for d in dev_ids:
        notice, ann = notices[d], annotations[d]
        spans = {s.span_id: s for s in ann.spans}
        constraints = {c.audience_span_id: c for c in ann.audience_constraints}
        rows_by_mode = {}
        for mode, default in [("default_on", True), ("default_off", False)]:
            by_event = defaultdict(list)
            for row in build_pairs(
                [notice], [ann], profiles, assume_all_students_without_audience=default
            ):
                by_event[row["event_id"]].append(row)
            rows_by_mode[mode] = by_event
        for ev in ann.events:
            audiences = [
                constraints[a.span_id]
                for a in ev.arguments
                if spans[a.span_id].label == "AUDIENCE" and a.span_id in constraints
            ]
            labels = [spans[a.span_id].label for a in ev.arguments]
            item = {
                "doc_id": d,
                "event_id": ev.event_id,
                "source": notice.source_type,
                "site": urlparse(notice.source_ref).hostname
                if notice.source_type == "web"
                else "email",
                "split": assignments[d]["split"],
                "group_id": assignments[d]["group_id"],
                "has_audience": "AUDIENCE" in labels,
                "no_audience": "AUDIENCE" not in labels,
                "has_condition": "CONDITION" in labels,
                "listed": any(c.scope == "listed" for c in audiences),
                "listed_representable": any(
                    c.scope == "listed" and not c.unrepresented for c in audiences
                ),
                "all_students": any(c.scope == "all_students" for c in audiences),
                "unrepresented": any(c.unrepresented for c in audiences),
                "excluded_statuses": any(c.excluded_statuses for c in audiences),
                "required_fields": sorted(
                    {f for c in audiences for f, _ in constraint_requirements(c)}
                ),
            }
            for mode in rows_by_mode:
                rows = rows_by_mode[mode][ev.event_id]
                assert len(rows) == len(profiles)
                witnesses = {}
                for row in rows:
                    witnesses.setdefault(row["label"], row["profile_id"])
                item[mode] = {
                    "labels": dict(Counter(r["label"] for r in rows)),
                    "reasons": dict(Counter(r["rule_reason"] for r in rows)),
                    "witness_profiles": witnesses,
                }
            events.append(item)
    groups = {
        "web_development": [e for e in events if e["source"] == "web"],
        "email_development": [e for e in events if e["source"] == "email"],
    }
    for site in sorted({e["site"] for e in events if e["source"] == "web"}):
        groups[site] = [e for e in events if e["site"] == site]
    for source in ["email", "web"]:
        for split in ["train", "validation"]:
            groups[source + "_" + split] = [
                e for e in events if e["source"] == source and e["split"] == split
            ]
    field_values = {
        f: sorted({getattr(p, f) for p in profiles if getattr(p, f) is not None}) for f in FIELDS
    }
    document_groups = {}
    for key in groups:
        if key.endswith("_development"):
            ids = [d for d in dev_ids if notices[d].source_type == key.split("_")[0]]
        elif key.startswith(("email_", "web_")):
            source, split = key.split("_")
            ids = [
                d
                for d in dev_ids
                if notices[d].source_type == source and assignments[d]["split"] == split
            ]
        else:
            ids = [d for d in dev_ids if urlparse(notices[d].source_ref).hostname == key]
        document_groups[key] = [assignments[d] for d in ids]
    results = {
        "created_at": datetime.now(UTC).isoformat(),
        "snapshot": ART.parent.name,
        "python": platform.python_version(),
        "seed": 42,
        "label_origin": "machine-assisted curation; constraint-rule silver diagnostic",
        "scope": "train+validation only; test/domain_test inventory only; no human adjudication",
        "profiles": {
            "count": len(profiles),
            "origin": "pooled email+web TRAIN constraints only",
            "sha256": digest(OUT / "profiles_train_only.json"),
            "field_values": field_values,
        },
        "input_sha256": {
            p.relative_to(ROOT).as_posix(): digest(p)
            for p in [
                ART / "notices.jsonl",
                ART / "annotations.jsonl",
                SPLIT / "assignments.jsonl",
                SPLIT / "record.json",
                ROOT / "uv.lock",
                Path(__file__).resolve(),
                ROOT / "src/labeling/pairs.py",
                ROOT / "src/labeling/profiles.py",
                ROOT / "src/labeling/applicability.py",
            ]
        },
        "inventory": {
            split: dict(
                Counter(
                    n.source_type for d, n in notices.items() if assignments[d]["split"] == split
                )
            )
            for split in ["train", "validation", "test", "domain_test"]
        },
        "summaries": {key: aggregate(value, document_groups[key]) for key, value in groups.items()},
    }
    assert len(events) == sum(len(annotations[d].events) for d in dev_ids)
    assert all(assignments[e["doc_id"]]["split"] in {"train", "validation"} for e in events)
    (OUT / "event_diagnostics.json").write_text(
        json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "profiles": len(profiles),
                "inventory": results["inventory"],
                "summaries": {
                    k: {f: v[f] for f in ["documents", "groups", "events"]}
                    for k, v in results["summaries"].items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

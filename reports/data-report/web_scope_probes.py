"""Record two synthetic profile probes against existing development annotations.

Run from the repository root:

    uv run python reports/data-report/web_scope_probes.py

Each probe keeps every profile attribute fixed except the admission year and
labels one development web event with ``build_pairs``. The script writes
``reports/generated/data-report/web-applicability/scope_probes.json``.
These probes diagnose missing context in v3.1; they do not edit annotations or
constitute independent human adjudication. No notice text is exported.
"""

import json
from pathlib import Path

from smartnotice.io import read_jsonl
from smartnotice.labeling.pairs import build_pairs
from smartnotice.schemas import Annotation, Notice, Profile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/generated/data-report/web-applicability"
ART = ROOT / "data/annotations/cleanup_curated_2026-11-10_v3_1/artifacts"
notices = {r["doc_id"]: Notice.model_validate(r) for r in read_jsonl(ART / "notices.jsonl")}
annotations = {
    r["doc_id"]: Annotation.model_validate(r) for r in read_jsonl(ART / "annotations.jsonl")
}
cases = [
    ("9a198b5379e7f5568237", "e2", "HOA_HOC", 2024),
    ("e54c4db60ab87c156e2a", "e7", "KTMT", 2026),
]
result = []
for doc_id, event_id, major, other_year in cases:
    profiles = [
        Profile(
            profile_id=f"probe_{year}",
            cohort=year,
            degree_level="undergraduate",
            major=major,
            program="CLC",
            status="active",
        )
        for year in [2023, other_year]
    ]
    rows = build_pairs(
        [notices[doc_id]],
        [annotations[doc_id]],
        profiles,
        assume_all_students_without_audience=True,
    )
    result.extend(
        {
            k: row[k]
            for k in ["doc_id", "event_id", "profile", "label", "rule_reason", "annotation_sha256"]
        }
        for row in rows
        if row["event_id"] == event_id
    )
assert len(result) == 4
assert all(r["label"] == "APPLIES" for r in result)
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "scope_probes.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(result, ensure_ascii=False, indent=2))

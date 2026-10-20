"""Exercise the data milestone using explicitly synthetic source documents."""

import json
from pathlib import Path

from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.labeling.analysis import annotation_summary
from smartnotice.labeling.pairs import build_pairs
from smartnotice.labeling.studio import export_tasks
from smartnotice.labeling.validation import validate_annotation
from smartnotice.preprocessing.pipeline import prepare
from smartnotice.preprocessing.split import split_documents
from smartnotice.quality import quality_summary
from smartnotice.schemas import Annotation, Profile


def run_demo(root: Path) -> dict:
    """Prepare fixtures, validate annotations, derive pairs, and save quality evidence."""
    notices = prepare(
        root / "data/raw/examples/manifest.jsonl", root / "data/interim/demo/notices.jsonl"
    )
    splits = split_documents(notices)
    write_jsonl(root / "data/processed/demo/splits.jsonl", splits)
    annotations = [
        Annotation.model_validate(row)
        for row in read_jsonl(root / "data/annotations/examples/events.jsonl")
    ]
    documents = {notice.doc_id: notice for notice in notices}
    for annotation in annotations:
        validate_annotation(annotation, documents[annotation.doc_id])
    profiles = [
        Profile.model_validate(row)
        for row in read_jsonl(root / "data/annotations/examples/profiles.jsonl")
    ]
    pairs = build_pairs(notices, annotations, profiles)
    write_jsonl(root / "data/processed/demo/applicability.jsonl", pairs)
    report_dir = root / "reports/generated/demo"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "label_studio_tasks.json").write_text(
        json.dumps(export_tasks(notices), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = quality_summary(notices, splits)
    summary["annotations"] = annotation_summary(annotations)
    summary["applicability_pair_count"] = len(pairs)
    (report_dir / "quality.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary

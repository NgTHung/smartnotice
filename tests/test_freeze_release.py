import hashlib
import json
import subprocess
import sys
from pathlib import Path

from smartnotice.io import read_jsonl, write_jsonl


def test_release_keeps_test_unlabeled_and_extends_assignments(tmp_path, notices):
    source = tmp_path / "input"
    source.mkdir()
    docs = [
        notices[0]
        .model_copy(
            update={
                "doc_id": f"synthetic-{i}",
                "group_id": f"group-{i}",
                "source_type": "web" if i < 60 else "email",
                "source_ref": f"https://site{i % 3}.invalid/notice/{i}",
                "text": f"Synthetic notice {i}.",
                "sentences": [],
                "domain_holdout": False,
            }
        )
        .model_dump(mode="json")
        for i in range(100)
    ]

    def snapshot():
        write_jsonl(source / "notices.jsonl", docs)
        write_jsonl(
            source / "annotations.jsonl",
            [
                {
                    "doc_id": n["doc_id"],
                    "annotator_id": "synthetic-fixture",
                    "spans": [],
                    "events": [],
                    "audience_constraints": [],
                }
                for n in docs
            ],
        )
        checks = {
            name: hashlib.sha256((source / name).read_bytes()).hexdigest()
            for name in ("notices.jsonl", "annotations.jsonl")
        }
        (source / "checksums.json").write_text(json.dumps(checks), encoding="utf-8")
        (source / "human_review.json").write_text(
            json.dumps(
                {
                    "privacy_review_completed": True,
                    "human_review_completed": True,
                    "snapshot": {"files_sha256": checks},
                    "annotation_origin": "synthetic fixture",
                    "privacy_review_basis": "synthetic fixture",
                }
            ),
            encoding="utf-8",
        )

    def run(output, *extra):
        return subprocess.run(
            [
                sys.executable,
                "tools/freeze_curated_split.py",
                "--input",
                str(source),
                "--output",
                str(output),
                "--similarity",
                "1.0",
                "--seed-count",
                "2",
                *extra,
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=True,
        )

    snapshot()
    first = tmp_path / "first"
    run(first)
    rows = read_jsonl(first / "assignments.jsonl")
    assert len(rows) == 100
    record = json.loads((first / "record.json").read_text(encoding="utf-8"))
    assert record["split_counts"]["domain_test"] == 45
    assert len(record["holdout_sites"]) == 3
    assert not record["gold_ready"]
    assert not (first / "test/annotations.jsonl").exists()
    tasks = json.loads((first / "test/independent_annotation_tasks.json").read_text())
    assert tasks and all("predictions" not in task and "annotations" not in task for task in tasks)
    assert len(read_jsonl(first / "reference_only_do_not_train_on_test/annotations.jsonl")) == 100
    target = next(row for row in rows if row["split"] == "test")
    duplicate = next(n for n in docs if n["doc_id"] == target["doc_id"]).copy()
    duplicate["doc_id"] = "new-duplicate"
    docs.append(duplicate)
    snapshot()
    second = tmp_path / "second"
    run(second, "--previous", str(first))
    updated = {row["doc_id"]: row["split"] for row in read_jsonl(second / "assignments.jsonl")}
    assert all(updated[row["doc_id"]] == row["split"] for row in rows)
    assert updated["new-duplicate"] == "test"

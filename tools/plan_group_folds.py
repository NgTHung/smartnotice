"""Audit event links against a frozen split and create a train-only CV plan."""

import argparse
import hashlib
import json
import platform
from collections import Counter, defaultdict
from pathlib import Path

from pydantic import ValidationError
from smartnotice.io import write_jsonl
from smartnotice.preprocessing.group_cv import event_group_documents, plan_group_folds
from smartnotice.preprocessing.split import DEFAULT_SEED
from smartnotice.schemas import EventGroupAssembly, FrozenGroupAssignment, LocalGroupReviewNotes


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    """Write IDs, fold membership and provenance under a new private directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assignments", type=Path, required=True)
    parser.add_argument("--reviewed-assembly", type=Path, required=True)
    parser.add_argument("--notes", type=Path, required=True)
    parser.add_argument("--proposed-assembly", type=Path)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    private_root = Path("reports/generated").resolve()
    if output == private_root or not output.is_relative_to(private_root) or output.exists():
        parser.error("Choose a new output directory under reports/generated")
    inputs = {name: getattr(args, name) for name in ("assignments", "reviewed_assembly", "notes")}
    if args.proposed_assembly:
        inputs["proposed_assembly"] = args.proposed_assembly
    data = {name: path.read_bytes() for name, path in inputs.items()}
    try:
        assignments = []
        for number, line in enumerate(data["assignments"].decode("utf-8-sig").splitlines(), 1):
            if line.strip():
                try:
                    assignments.append(FrozenGroupAssignment.model_validate_json(line))
                except ValidationError:
                    parser.error(f"Invalid frozen assignment on line {number}")
        assembly = EventGroupAssembly.model_validate_json(data["reviewed_assembly"])
        notes = LocalGroupReviewNotes.model_validate_json(data["notes"])
        rows, links = plan_group_folds(
            assignments, assembly, notes, n_splits=args.folds, seed=args.seed
        )
        proposals = (
            event_group_documents(
                EventGroupAssembly.model_validate_json(data["proposed_assembly"]), assignments
            )
            if args.proposed_assembly
            else {}
        )
    except ValidationError:
        parser.error("Invalid assembly or local review notes schema")
    except ValueError as exc:
        parser.error(str(exc))

    by_doc = {row.doc_id: row for row in rows}
    by_component = defaultdict(list)
    for row in rows:
        by_component[row.fold_group_id].append(row)
    review_queue = []
    for event_group_id, docs in sorted(proposals.items()):
        if len(docs) < 2:
            continue
        review_queue.append(
            {
                "event_group_id": event_group_id,
                "doc_ids": docs,
                "frozen_splits": sorted({by_doc[d].split for d in docs}),
                "cv_folds": sorted({by_doc[d].fold for d in docs if by_doc[d].fold is not None}),
            }
        )
    conflicts = [
        {
            "fold_group_id": key,
            "documents_by_split": {
                split: [row.doc_id for row in members if row.split == split] for split in splits
            },
        }
        for key, members in sorted(by_component.items())
        if len(splits := sorted({row.split for row in members})) > 1
    ]
    counts = {
        "documents_by_split": dict(sorted(Counter(row.split for row in rows).items())),
        "review_notes_by_status": dict(sorted(Counter(n.status for n in notes.entries).items())),
        "reviewed_event_links": len(links),
        "cross_split_components": len(conflicts),
        "train_documents_quarantined": sum(
            r.exclusion_reason == "linked_to_outside_train" for r in rows
        ),
        "folds": [
            {
                "fold": i,
                "documents": sum(r.fold == i for r in rows),
                "groups": len({r.fold_group_id for r in rows if r.fold == i}),
            }
            for i in range(args.folds)
        ],
        "proposed_multi_document_groups": len(review_queue),
        "proposed_groups_crossing_frozen_splits": sum(
            len(r["frozen_splits"]) > 1 for r in review_queue
        ),
        "proposed_groups_crossing_cv_folds": sum(len(r["cv_folds"]) > 1 for r in review_queue),
    }
    run = {
        "algorithm": "smartnotice-group-kfold-v1",
        "seed": args.seed,
        "n_splits": args.folds,
        "reviewed_assembly_fingerprint": notes.assembly_fingerprint,
        "python_version": platform.python_version(),
        "source_files": {
            name: {"path": path.as_posix(), "sha256": _digest(data[name])}
            for name, path in inputs.items()
        },
        "code_and_lock_sha256": {
            p: _digest(Path(p).read_bytes())
            for p in (
                "src/preprocessing/group_cv.py",
                "src/preprocessing/split.py",
                "src/schemas.py",
                "src/labeling/event_groups.py",
                "tools/plan_group_folds.py",
                "uv.lock",
            )
        },
        **counts,
    }
    output.mkdir(parents=True, exist_ok=False)
    write_jsonl(output / "fold_assignments.jsonl", [row.model_dump() for row in rows])
    write_jsonl(output / "reviewed_event_links.jsonl", [row.model_dump() for row in links])
    write_jsonl(output / "split_conflicts.jsonl", conflicts)
    if args.proposed_assembly:
        write_jsonl(output / "provisional_review_queue.jsonl", review_queue)
    _write_json(output / "run.json", run)
    _write_json(
        output / "checksums.json",
        {p.name: _digest(p.read_bytes()) for p in sorted(output.iterdir()) if p.is_file()},
    )
    print(json.dumps(counts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Freeze a privacy-reviewed curated corpus for annotation and later evaluation."""

import argparse
import hashlib
import json
import platform
import random
import shutil
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.labeling.studio import export_tasks
from smartnotice.labeling.validation import validate_annotation
from smartnotice.preprocessing.frozen_split import RATIOS, allocate_frozen_groups
from smartnotice.preprocessing.split import DEFAULT_SEED, group_documents
from smartnotice.schemas import Annotation, Notice


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    """Validate a reviewed snapshot and write a new, non-overwriting split release.

    Required input files are notices.jsonl, annotations.jsonl, checksums.json and
    human_review.json. Only the first release samples a web holdout. Extensions
    require --previous pointing to the previous release and keep all old splits.
    New snapshots need their own matching privacy and annotation review record.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--group-map", type=Path)
    parser.add_argument("--similarity", type=float, default=0.8)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--seed-count", type=int, default=100)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Output already exists; use a new release directory")
    if args.seed_count < 1:
        raise ValueError("seed-count must be positive")
    review = json.loads((args.input / "human_review.json").read_text(encoding="utf-8"))
    if not review.get("privacy_review_completed") or not review.get("human_review_completed"):
        raise ValueError("A recorded privacy and annotation review is required")
    for name in ("notices.jsonl", "annotations.jsonl"):
        if _hash(args.input / name) != review["snapshot"]["files_sha256"][name]:
            raise ValueError(f"Reviewed snapshot hash mismatch: {name}")
    notice_rows = read_jsonl(args.input / "notices.jsonl")
    annotation_rows = read_jsonl(args.input / "annotations.jsonl")
    notices = sorted([Notice.model_validate(row) for row in notice_rows], key=lambda n: n.doc_id)
    annotations = {row["doc_id"]: Annotation.model_validate(row) for row in annotation_rows}
    if len(annotations) != len(annotation_rows) or set(annotations) != {n.doc_id for n in notices}:
        raise ValueError("Expected exactly one annotation per document")
    for notice in notices:
        validate_annotation(annotations[notice.doc_id], notice)
    print(f"Validated {len(notices)} reviewed documents; grouping at {args.similarity}", flush=True)
    if args.group_map:
        cache_record = json.loads(args.group_map.with_suffix(".record.json").read_text())
        if (
            cache_record["data_sha256"] != _hash(args.input / "notices.jsonl")
            or cache_record["similarity"] != args.similarity
            or cache_record["groups_sha256"] != _hash(args.group_map)
        ):
            raise ValueError("Grouping cache does not match data, threshold and mapping hash")
        groups = json.loads(args.group_map.read_text(encoding="utf-8"))
    else:
        groups = group_documents(notices, args.similarity)
    members = defaultdict(list)
    for notice in notices:
        members[groups[notice.doc_id]].append(notice)
    previous = None
    if args.previous:
        previous_record = json.loads((args.previous / "record.json").read_text(encoding="utf-8"))
        if previous_record["similarity"] != args.similarity:
            raise ValueError("Cannot change grouping threshold while extending a frozen release")
        previous = read_jsonl(args.previous / "assignments.jsonl")
        if not {row["doc_id"] for row in previous} <= set(groups):
            raise ValueError("Cumulative snapshot is missing previously frozen documents")
        selected_groups = {
            groups[row["doc_id"]] for row in previous if row["split"] == "domain_test"
        }
    else:
        web_counts = Counter(
            urlsplit(n.source_ref).hostname for n in notices if n.source_type == "web"
        )
        if sum(web_counts.values()) < 50:
            raise ValueError("At least 50 web notices are required for this holdout procedure")
        targets = {
            site: 45 * count / sum(web_counts.values()) for site, count in web_counts.items()
        }
        candidates = sorted(
            key for key, items in members.items() if all(n.source_type == "web" for n in items)
        )
        random.Random(args.seed).shuffle(candidates)
        selected_groups, current = set(), Counter()
        while candidates:

            def delta(key):
                addition = Counter(urlsplit(n.source_ref).hostname for n in members[key])
                return sum(
                    ((current[s] + addition[s] - target) ** 2 - (current[s] - target) ** 2)
                    / max(target, 1) ** 2
                    for s, target in targets.items()
                )

            key = min(candidates, key=delta)
            if delta(key) > 0 or (delta(key) == 0 and sum(current.values()) >= 45):
                break
            selected_groups.add(key)
            current.update(urlsplit(n.source_ref).hostname for n in members[key])
            candidates.remove(key)
        if not 40 <= sum(current.values()) <= 50 or set(current) != set(targets):
            raise ValueError("Grouped holdout cannot meet site coverage and 40–50 document target")
    selected_groups.update(groups[n.doc_id] for n in notices if n.domain_holdout)
    allocation_notices = [
        n.model_copy(update={"domain_holdout": groups[n.doc_id] in selected_groups})
        for n in notices
    ]
    features = {}
    for notice in notices:
        annotation = annotations[notice.doc_id]
        row = Counter(span.label for span in annotation.spans)
        row[f"source:{notice.source_type}"] = 1
        row["has_condition"] = int(row["CONDITION"] > 0)
        row["outside_population"] = int(
            any(c.scope == "outside_population" for c in annotation.audience_constraints)
        )
        row["restricted_representable"] = int(
            any(
                c.scope == "listed" and not c.unrepresented for c in annotation.audience_constraints
            )
        )
        features[notice.doc_id] = dict(row)

    def balance(rows):
        counts = {name: Counter() for name in RATIOS}
        for row in rows:
            if row["split"] in counts:
                counts[row["split"]].update(features[row["doc_id"]])
                counts[row["split"]]["documents"] += 1
        totals = sum(counts.values(), Counter())
        score = sum(
            (counts[name][f] / total - ratio) ** 2
            for name, ratio in RATIOS.items()
            for f, total in totals.items()
            if total
        )
        return score, counts

    trials = []
    for seed in range(args.seed, args.seed + args.seed_count):
        rows = allocate_frozen_groups(
            allocation_notices, groups, features, seed=seed, previous=previous
        )
        score, counts = balance(rows)
        trials.append({"seed": seed, "score": score})
    selected = min(trials, key=lambda row: (row["score"], row["seed"]))
    assignments = allocate_frozen_groups(
        allocation_notices, groups, features, seed=selected["seed"], previous=previous
    )
    _, counts = balance(assignments)
    data_hash = _hash(args.input / "notices.jsonl")
    for row in assignments:
        row.update(seed=selected["seed"], similarity=args.similarity, data_sha256=data_hash)
    args.output.mkdir(parents=True)
    write_jsonl(args.output / "assignments.jsonl", assignments)
    _json(args.output / "seed_search.json", trials)
    write_jsonl(
        args.output / "group_review.jsonl",
        [
            {
                "group_id": key,
                "doc_ids": [n.doc_id for n in items],
                "sources": dict(Counter(n.source_type for n in items)),
                "manual_group_review_completed": False,
            }
            for key, items in sorted(members.items())
            if len(items) > 1
        ],
    )
    by_id = {row["doc_id"]: row["split"] for row in assignments}
    raw_notices = {row["doc_id"]: row for row in notice_rows}
    raw_annotations = {row["doc_id"]: row for row in annotation_rows}
    for split in ("train", "validation", "test", "domain_test", "excluded"):
        subset = [n for n in notices if by_id[n.doc_id] == split]
        directory = args.output / split
        directory.mkdir()
        write_jsonl(directory / "notices.jsonl", [raw_notices[n.doc_id] for n in subset])
        if split in {"train", "validation"}:
            write_jsonl(
                directory / "annotations.jsonl", [raw_annotations[n.doc_id] for n in subset]
            )
        elif split in {"test", "domain_test"}:
            tasks = export_tasks(subset)
            for task in tasks:
                task["data"]["privacy_review_required"] = False
                task["data"]["privacy_review_basis"] = (
                    "bound human_review.json; requesting_user confirmation"
                )
            _json(directory / "independent_annotation_tasks.json", tasks)
            write_jsonl(
                directory / "gold_review_queue.jsonl",
                [
                    {
                        "doc_id": n.doc_id,
                        "annotator_a_completed": False,
                        "annotator_b_completed": False,
                        "adjudication_completed": False,
                        "gold_ready": False,
                    }
                    for n in subset
                ],
            )
    reference = args.output / "reference_only_do_not_train_on_test"
    reference.mkdir()
    write_jsonl(reference / "annotations.jsonl", annotation_rows)
    for name in ("human_review.json", "checksums.json"):
        shutil.copyfile(args.input / name, reference / name)
    site_counts = Counter(
        urlsplit(n.source_ref).hostname for n in notices if by_id[n.doc_id] == "domain_test"
    )
    record = {
        "created_at": datetime.now(UTC).isoformat(),
        "ratios": RATIOS,
        "similarity": args.similarity,
        "selected_seed": selected["seed"],
        "holdout_sampling_seed": args.seed,
        "holdout_sites": dict(site_counts),
        "source_files_sha256": {
            name: _hash(args.input / name)
            for name in ("notices.jsonl", "annotations.jsonl", "human_review.json")
        },
        "split_counts": dict(Counter(row["split"] for row in assignments)),
        "balance_counts": {name: dict(row) for name, row in counts.items()},
        "group_count": len(members),
        "seed_selection": (
            "minimum normalized squared size/source/span/rare-document count deviation; "
            "no model results"
        ),
        "gold_ready": False,
        "manual_group_review_completed": False,
        "annotation_origin": review["annotation_origin"],
        "privacy_review_basis": review["privacy_review_basis"],
        "previous_assignments_sha256": _hash(args.previous / "assignments.jsonl")
        if args.previous
        else None,
        "python_version": platform.python_version(),
        "uv_lock_sha256": _hash(Path("uv.lock")),
        "code_sha256": {
            name: _hash(Path(name))
            for name in (
                "tools/freeze_curated_split.py",
                "src/preprocessing/frozen_split.py",
                "src/preprocessing/split.py",
            )
        },
    }
    _json(args.output / "record.json", record)
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

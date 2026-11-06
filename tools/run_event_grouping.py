"""Run the offline event grouping prototype on saved model predictions."""

import argparse
import hashlib
import json
import platform
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from smartnotice.io import read_jsonl, write_jsonl
from smartnotice.labeling.grouping import GroupingConfig, group_events
from smartnotice.labeling.studio import import_prediction_tasks
from smartnotice.schemas import Notice


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    """Validate predictions, write new private outputs, and print aggregate counts.

    Run from the repository root. Existing output directories are refused. Every
    output is a rule proposal requiring review; no source, split assignment,
    privacy approval, or human annotation is modified. Thresholds are recorded,
    not tuned against the assistant's labels or the pilot pair proposals.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    batch = Path("data/annotations/drive-auto-label-2026-11-04")
    parser.add_argument("--notices", type=Path, default=batch / "notices.compat.jsonl")
    parser.add_argument("--predictions", type=Path, default=batch / "tasks.json")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed/event-grouping-prototype-2026-11-05"),
    )
    parser.add_argument("--similarity", type=float, default=0.8)
    parser.add_argument("--min-shared-tokens", type=int, default=3)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    output = args.output_dir.resolve()
    if not any(output.is_relative_to(root / p) for p in ("data/processed", "reports/generated")):
        raise ValueError("Output must stay in data/processed or reports/generated")
    if output.exists():
        raise ValueError("Output directory already exists; choose a new path")
    config = GroupingConfig(similarity=args.similarity, min_shared_tokens=args.min_shared_tokens)
    before = {str(p): _sha(p) for p in (args.notices, args.predictions)}
    start = perf_counter()
    notices = []
    for number, row in enumerate(read_jsonl(args.notices), 1):
        try:
            notices.append(Notice.model_validate(row))
        except ValueError:
            raise ValueError(f"Invalid Notice on line {number}") from None
    tasks = json.loads(args.predictions.read_text(encoding="utf-8-sig"))
    if {t["data"]["doc_id"] for t in tasks} != {n.doc_id for n in notices}:
        raise ValueError("The prototype requires matching Notice and prediction document sets")
    try:
        annotations = import_prediction_tasks(tasks, notices)
    except (ValueError, KeyError, TypeError):
        raise ValueError(
            "Invalid prediction structure/provenance; inspect sources privately"
        ) from None
    validation_seconds = perf_counter() - start
    start = perf_counter()
    result = group_events(notices, annotations, config)
    grouping_seconds = perf_counter() - start
    for path in (args.notices, args.predictions):
        if _sha(path) != before[str(path)]:
            raise ValueError("Source changed during the run")
    groups = [g for g in result.groups if len(g.members) > 1]
    stats = {
        "documents": len(notices),
        "event_mentions": len(result.mentions),
        "groups_including_singletons": len(result.groups),
        "multi_member_groups": len(groups),
        "mentions_in_multi_member_groups": sum(len(g.members) for g in groups),
        "candidate_pairs": len(result.decisions),
        "compared_pairs": result.compared_pairs,
        "pair_proposals": dict(Counter(p.decision for p in result.decisions)),
    }
    code_paths = [
        Path("src/labeling/grouping.py"),
        Path("src/labeling/studio.py"),
        Path("src/labeling/validation.py"),
        Path("src/schemas.py"),
        Path("src/labeling/llm.py"),
        Path("uv.lock"),
        Path(__file__),
    ]
    run = {
        "created_at": datetime.now(UTC).isoformat(),
        "rule_version": result.rule_version,
        "config": config.model_dump(),
        "source_sha256": before,
        "code_sha256": {str(p): _sha(p) for p in code_paths},
        "environment": {"python": platform.python_version(), "platform": platform.system()},
        "validation_seconds": validation_seconds,
        "grouping_seconds": grouping_seconds,
        "workflow_counts": stats,
        "label_origin": "rule_proposals_over_model_predictions",
        "human_review_completed": False,
        "privacy_review_completed": False,
        "quality_measured": False,
        "split_assignments_changed": False,
        "parameters_fitted": False,
        "sampling_or_randomness": None,
    }
    by_ref = {m.event_ref: m for m in result.mentions}
    worksheet = [
        "# Kết quả thử nghiệm gộp sự kiện",
        "",
        "Đề xuất bằng quy tắc trên dự đoán mô hình; chưa được con người duyệt.",
        "",
        "Mọi lần nhắc và giá trị thời gian vẫn được giữ trong events.jsonl.",
        "",
        "UPDATE_CANDIDATE chưa được gộp hoặc xác định chiều cập nhật.",
        "",
    ]
    for group in groups:
        worksheet += [f"## Nhóm `{group.group_id}`", ""]
        for ref in group.members:
            mention = by_ref[ref]
            worksheet += [f"### `{ref}`", "", mention.action.text, ""]
            for sentence in mention.evidence:
                worksheet += [
                    f"Câu `{sentence.sentence_id}` [{sentence.start}:{sentence.end}]:",
                    "",
                    *["> " + line for line in sentence.text.splitlines()],
                    "",
                ]
    worksheet += [
        "## Các cặp cần xem thêm",
        "",
        "Xem toàn bộ pair_decisions.jsonl để đọc lý do UNCLEAR và UPDATE_CANDIDATE.",
        "",
    ]
    output.mkdir(parents=True)
    write_jsonl(output / "events.jsonl", [m.model_dump(mode="json") for m in result.mentions])
    write_jsonl(output / "groups.jsonl", [g.model_dump() for g in result.groups])
    write_jsonl(output / "pair_decisions.jsonl", [p.model_dump() for p in result.decisions])
    _json(output / "run.json", run)
    (output / "review_groups.md").write_text("\n".join(worksheet), encoding="utf-8")
    _json(output / "checksums.json", {p.name: _sha(p) for p in sorted(output.iterdir())})
    print(json.dumps({**stats, "grouping_seconds": round(grouping_seconds, 3)}))


if __name__ == "__main__":
    main()
